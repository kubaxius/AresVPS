# BearWorks deployment workshop

This workshop builds a release pipeline for `bearworks.pl` without adding a
runtime application server. Astro produces static files; Nginx serves them.
GitHub Actions builds and packages each release, Tailscale gives the temporary
CI runner narrowly scoped network access, and a server-side helper installs and
activates the artifact.

The intended reader already knows Git, Ansible, and SSH. GitHub Actions,
Tailscale, and artifact-based releases are introduced as they are used.

> This is an implementation guide, not the implementation. Run every command
> yourself, inspect the result, and commit only after its checkpoint passes.
> Values in angle brackets, such as `<TAILNET>`, are placeholders.

## 1. Starting point and destination

At the time this guide was written:

- the website has no Git remote, GitHub workflows, or tags;
- its branch is named `master`;
- `npm run build` creates `dist/`, but the combination of the required
  `src/pages/index.astro` route and Astro's automatic i18n root redirect
  reports a prerender conflict for `/`;
- the Pantheon repository at `/home/kubaxius/Projects/VPS` installs Nginx and
  configures UFW;
- `ansible/roles/static_site/tasks/main.yml` is empty;
- the production inventory still contains `example.server.net`; and
- neither `gh` nor `tailscale` is installed on the workstation.

The finished path is:

```text
signed Git tag
    -> GitHub Actions validation and build
    -> versioned archive, manifest, and checksum
    -> ephemeral Tailscale CI node
    -> SSH upload to a restricted deploy account
    -> server-side validation
    -> atomic current symlink switch
    -> Nginx health check
    -> GitHub Release publication
```

### Release invariants

Keep these rules true throughout the workshop:

1. Build once in GitHub Actions. Never install Node or build the site on the
   VPS.
2. Deploy an artifact, not a working tree.
3. Let Ansible own accounts, directories, permissions, Nginx, Tailscale, and
   helper programs.
4. Let the website workflow upload and activate releases, but never run
   Ansible or provision infrastructure.
5. Make completed release directories root-owned and immutable to the deploy
   account.
6. Never replace `current` until a new release is fully installed and checked.
7. Retain enough releases to roll back without rebuilding or downloading.
8. Deploy production only from an annotated, SSH-signed
   `vMAJOR.MINOR.PATCH` tag whose commit is contained in `main`.

### What "build once" means

The build job creates one byte-for-byte artifact. Deployment jobs download that
artifact; they do not repeat `npm run build`. This prevents the VM, production,
and GitHub Release from accidentally receiving different output for the same
tag.

### Security boundary

There are four independent identities:

- your Git release-signing key proves who authorized a release;
- the GitHub OIDC identity lets one workflow temporarily join the tailnet;
- the VM deploy key authenticates to OpenSSH on `ares-local`;
- the production deploy key authenticates to OpenSSH on `ares`.

Do not reuse any of these keys.

## 2. Prepare the website repository

### What you are building

The repository must build deterministically from a clean checkout before CI can
be useful. Astro's default static output is `dist/`; Nginx needs only that
directory.

### Do this

Create a public, empty repository named `kubaxius/bw-website` in GitHub. Do not
initialize it with a README or license. Then, from this repository:

```console
git branch -m master main
git remote add origin git@github.com:kubaxius/bw-website.git
git push -u origin main
```

In GitHub, open **Settings -> Rules -> Rulesets** and create a branch ruleset:

- target the default branch;
- block force pushes and deletion;
- require pull requests once CI exists;
- require the `ci / validate` status check;
- require the branch to be up to date before merging.

Create a second ruleset targeting tags matching `v*`:

- restrict tag creation to repository administrators;
- block tag updates and deletion.

The signed-tag check remains necessary: a ruleset controls who can mutate the
reference, while a signature proves which key authorized it.

Pin the LTS major used locally and by CI:

```console
printf '24\n' > .nvmrc
npm pkg set engines.node='>=24 <25'
npm install --save-dev @astrojs/check typescript
npm pkg set scripts.check='astro check'
```

These commands intentionally modify project files when _you_ execute them.
Review `package.json` and `package-lock.json` afterward.

Resolve the root-route conflict without deleting the root route. Astro requires
a physical `src/pages/index.astro` when all locales use prefixes. If you
already deleted it, restore it first:

```console
git restore src/pages/index.astro
```

Then make the redirect explicit:

1. Replace `src/pages/index.astro` with:

   ```astro
   ---
   return Astro.redirect("/pl/", 308);
   ---
   ```

2. In `astro.config.mjs`, set `defaultLocale` to `"pl"`.
3. Keep `prefixDefaultLocale: true`, but set
   `redirectToDefaultLocale: false`. The explicit index route now owns
   `/`, so Astro does not create a second prerendered route at the same path.

This keeps development routing valid, produces `dist/index.html` for static
hosting, and avoids the duplicate-route build warning. Nginx will later return
the same permanent redirect directly, before reading that static file.

Perform a clean build:

```console
rm -rf node_modules dist .astro
npm ci
npm run check
npm run build
test -f dist/index.html
test -f dist/pl/index.html
test -f dist/en/index.html
grep -q '/pl/' dist/index.html
```

The build must finish without the current "conflicts with higher priority
route" warning.

### Checkpoint

```console
node --version
npm --version
npm ls --depth=0
find dist -maxdepth 3 -type f -printf '%P\n' | sort
git diff --check
git status --short
```

Expected:

- Node reports `v24.x`;
- `npm ci`, `npm run check`, and `npm run build` succeed;
- the three locale/root entrypoints exist;
- the root page points to `/pl/`.

### Break it deliberately

Temporarily add a nonexistent property to an Astro expression. Confirm
`npm run check` fails even if `npm run build` transpiles the page. Revert the
change. This demonstrates why build and type-check are separate gates.

### Commit boundary

```console
git add .nvmrc package.json package-lock.json astro.config.mjs src/pages/index.astro
git commit -m "build: make static site checks reproducible"
```

## 3. Learn GitHub Actions by adding CI

### Vocabulary used below

- **event**: the repository activity that starts a workflow;
- **workflow**: one YAML file in `.github/workflows/`;
- **job**: a group of steps running on one fresh runner;
- **step**: an action or shell command;
- **runner**: the temporary VM executing a job;
- **context**: GitHub-provided data such as `github.sha`;
- **expression**: a `${{ ... }}` value evaluated by GitHub;
- **permission**: a capability of the temporary `GITHUB_TOKEN`;
- **artifact**: files retained by GitHub and passed between jobs;
- **environment**: a deployment target with scoped variables, secrets, and
  protection rules;
- **concurrency**: a lock preventing overlapping runs.

CI answers, "Can this commit become a release?" Deployment answers, "Can this
already-built artifact become active on this target?" Release publication
answers, "Which permanent files and metadata represent this tag?"

### Pin actions before using them

A tag such as `actions/checkout@v4` can move. A full commit SHA cannot. Resolve
the currently reviewed tags:

```console
git ls-remote https://github.com/actions/checkout.git \
  'refs/tags/v4^{}' refs/tags/v4
git ls-remote https://github.com/actions/setup-node.git \
  'refs/tags/v4^{}' refs/tags/v4
git ls-remote https://github.com/actions/upload-artifact.git \
  'refs/tags/v4^{}' refs/tags/v4
git ls-remote https://github.com/actions/download-artifact.git \
  'refs/tags/v4^{}' refs/tags/v4
```

For an annotated tag, use the `^{}` result. For a lightweight tag, use the
plain result. Verify the commit belongs to the official repository, then put
the 40-character SHA in the workflow. Add a comment with the human version:

```yaml
- uses: actions/checkout@<CHECKOUT_V4_FULL_SHA> # v4
```

Repeat this process whenever Dependabot proposes an action update.

### Do this

Create `.github/workflows/ci.yml`:

```yaml
name: ci

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  validate:
    name: validate
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Check out source
        uses: actions/checkout@<CHECKOUT_V4_FULL_SHA> # v4

      - name: Use Node.js 24
        uses: actions/setup-node@<SETUP_NODE_V4_FULL_SHA> # v4
        with:
          node-version: 24
          cache: npm

      - name: Install locked dependencies
        run: npm ci

      - name: Check Astro and TypeScript
        run: npm run check

      - name: Build static site
        run: npm run build

      - name: Verify deployable entrypoints
        shell: bash
        run: |
          set -euo pipefail
          test -f dist/index.html
          test -f dist/pl/index.html
          test -f dist/en/index.html
          grep -q '/pl/' dist/index.html
```

Do not attach environments, secrets, `id-token: write`, or deployment keys to
this workflow. Pull-request code is untrusted input.

Push the workflow, wait for it to pass, then configure its status check in the
`main` ruleset.

### Inspecting runs

Without GitHub CLI, use the repository's **Actions** tab. A run page exposes
each job, step, log, annotation, and artifact.

Optionally install GitHub CLI using GitHub's official package instructions,
authenticate, and use:

```console
gh auth login
gh run list --workflow ci.yml
gh run view <RUN_ID> --log
gh run watch <RUN_ID> --exit-status
gh run download <RUN_ID> --dir /tmp/bearworks-run
```

### Checkpoint

- A pull request starts `ci`.
- A push to `main` starts `ci`.
- Two pushes to the same pull request cancel the obsolete run.
- The workflow permissions page shows read-only repository contents.
- A failing type check prevents the build step.

### Break it deliberately

Create a short-lived branch, change an entrypoint assertion to a nonexistent
file, and open a pull request. Confirm CI fails and the ruleset blocks merging.
Restore the assertion and confirm the same PR becomes mergeable.

### Commit boundary

```console
git add .github/workflows/ci.yml
git commit -m "ci: validate static Astro build"
```

## 4. Build the server-side release mechanism

Work in `/home/kubaxius/Projects/VPS` for this section.

### What you are building

Ansible prepares a generic static-site release target. The deploy account may
upload to `incoming` and invoke one audited helper through `sudo`, but it cannot
write completed releases or change Nginx configuration directly.

Use this layout:

```text
/srv/www/bearworks/
├── incoming/                    # bearworks-deploy can write
├── releases/                    # root-owned completed releases
│   └── v0.1.0-0123456789ab/
└── current -> releases/v0.1.0-0123456789ab
```

Ansible must create:

- user and group `bearworks-deploy`;
- `incoming` owned by `bearworks-deploy`, mode `0750`;
- `releases` owned by `root:www-data`, mode `0750`;
- a root-owned helper at `/usr/local/sbin/bearworks-release`;
- a sudoers entry allowing only that executable;
- environment-specific authorized keys; and
- a retention default of five inactive releases.

<!-- ai_generated:start -->
The executable in `/usr/local/sbin` is a small, root-owned launcher rendered
for this site. It contains the site configuration and imports the shared,
root-owned release logic from
`/usr/local/lib/static-site-release/static_site_release.py`. A second instance
of the Ansible role installs another launcher with its own configuration while
reusing the same logic file. The helper never discovers configuration from its
working directory, invocation path, environment, or the site root.
<!-- ai_generated:end -->

The account has no general sudo rights. Its one allowed command is the release
API:

```sudoers
bearworks-deploy ALL=(root) NOPASSWD: /usr/local/sbin/bearworks-release *
```

The wildcard makes the helper's own validation security-critical. It must
hard-code or strictly allow-list the site root and never evaluate arguments as
shell code.

### Release interface

Use these subcommands:

```console
sudo -n /usr/local/sbin/bearworks-release install \
  --archive /srv/www/bearworks/incoming/<ARCHIVE> \
  --checksum /srv/www/bearworks/incoming/<ARCHIVE>.sha256 \
  --manifest /srv/www/bearworks/incoming/<MANIFEST>

sudo -n /usr/local/sbin/bearworks-release activate <RELEASE_ID>
sudo -n /usr/local/sbin/bearworks-release current
sudo -n /usr/local/sbin/bearworks-release list
sudo -n /usr/local/sbin/bearworks-release rollback <RELEASE_ID>
```

Artifact names are:

```text
bearworks-<tag>-<12-char-sha>.tar.gz
bearworks-<tag>-<12-char-sha>.tar.gz.sha256
bearworks-<tag>-<12-char-sha>.manifest.json
```

The manifest contract is:

```json
{
  "schema_version": 1,
  "site": "bearworks",
  "tag": "v0.1.0",
  "commit": "<40-character lowercase hexadecimal Git SHA>",
  "release_id": "v0.1.0-<first 12 characters of commit>"
}
```

Validate all relationships, not merely each field:

- tag matches `^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`;
- commit matches `^[0-9a-f]{40}$`;
- `release_id` equals `tag + "-" + commit[0:12]`;
- archive basename equals `bearworks-<release_id>.tar.gz`;
- the checksum file names that exact archive;
- the manifest inside the archive is byte-identical to the supplied manifest.

Before extraction, inspect the archive and reject:

- absolute paths;
- empty names or names containing a `..` path component;
- device nodes, FIFOs, sockets, hard links, and symbolic links;
- files outside one expected payload root;
- an unreasonable file count or expanded size.

Extract into a temporary directory under `releases`, verify
`index.html`, `pl/index.html`, and `en/index.html`, normalize ownership and
permissions, and rename it to `releases/<RELEASE_ID>`. A rename within one
filesystem is atomic.

If that release already exists:

- return success when its stored manifest and checksum match; this makes a
  workflow rerun safe;
- fail when either differs.

Installation never changes `current`.

For activation:

1. Resolve and record the existing `current` target.
2. Reject a target not directly inside `releases`.
3. Create a temporary relative symlink.
4. replace `current` with `mv -Tf`;
5. run the configured Nginx health checks;
6. restore the previous symlink atomically if any check fails;
7. prune only after successful activation.

Never prune `current` or the recorded previous release.

### Checkpoint

```console
cd /home/kubaxius/Projects/VPS
ANSIBLE_LOCAL_TEMP=/tmp/pantheon-ansible-local \
  ansible-playbook --syntax-check ansible/site.yml
ansible-lint ansible
pantheon ansible run ares-local
pantheon ansible run ares-local
ssh ares-local 'sudo -n /usr/local/sbin/bearworks-release list'
```

The second Ansible run should report no changes relevant to static-site
hosting.

### Break it deliberately

Try invoking an unrelated sudo command as `bearworks-deploy`. It must fail.
Try passing `../../etc` as a release ID or archive component. The helper must
fail without creating anything outside `incoming` or `releases`.

### Commit boundary

```console
git add ansible/roles/static_site ansible/inventories
git commit -m "feat(static-site): add atomic release installation"
```

## 5. Configure and verify Nginx

### Required behavior

The BearWorks server block must:

- serve `/srv/www/bearworks/current`;
- return `308 /pl/` for exactly `/`;
- resolve directory routes through their `index.html`;
- return a real 404 instead of falling back to the home page;
- add `Cache-Control: public, max-age=31536000, immutable` only to hashed
  `/_astro/` files;
- avoid long-lived caching for HTML and unhashed files;
- redirect `www.bearworks.pl` to `bearworks.pl`;
- validate with `nginx -t` before reload.

Model the main location on:

```nginx
location = / {
    return 308 /pl/;
}

location / {
    try_files $uri $uri/ =404;
}

location /_astro/ {
    try_files $uri =404;
    add_header Cache-Control "public, max-age=31536000, immutable";
}
```

Do not use `try_files ... /index.html` as the final fallback; that turns every
unknown path into a successful home page.

Use a locally generated self-signed certificate on `ares-local` so the HTTPS
server block is exercised before public DNS exists. Production ACME comes
later.

### Verify

Use the host header even before DNS points to the machine:

```console
curl -sS -D- -o /dev/null -H 'Host: bearworks.pl' \
  http://<ARES_LOCAL_TAILSCALE_IP>/
curl -fsS -H 'Host: bearworks.pl' \
  http://<ARES_LOCAL_TAILSCALE_IP>/pl/ >/dev/null
curl -fsS -H 'Host: bearworks.pl' \
  http://<ARES_LOCAL_TAILSCALE_IP>/en/ >/dev/null
curl -sS -D- -o /dev/null -H 'Host: bearworks.pl' \
  http://<ARES_LOCAL_TAILSCALE_IP>/missing-page
curl -kfsS -H 'Host: bearworks.pl' \
  https://<ARES_LOCAL_TAILSCALE_IP>/pl/ >/dev/null
curl -sS -D- -o /dev/null -H 'Host: www.bearworks.pl' \
  http://<ARES_LOCAL_TAILSCALE_IP>/pl/
```

Expected status codes:

- `/`: `308` with `Location: /pl/`;
- `/pl/` and `/en/`: `200`;
- unknown route: `404`;
- `www`: permanent redirect to the apex.

Locate a built `/_astro/` asset and check its headers:

```console
ASSET_PATH="$(find dist/_astro -type f -printf '/_astro/%f\n' | head -n 1)"
curl -sS -D- -o /dev/null -H 'Host: bearworks.pl' \
  "http://<ARES_LOCAL_TAILSCALE_IP>${ASSET_PATH}"
```

On the server:

```console
ssh ares-local 'sudo nginx -t'
ssh ares-local 'sudo systemctl reload nginx'
ssh ares-local 'sudo systemctl reboot'
# Wait for SSH to return, then repeat the HTTP checks.
```

### Break it deliberately

Point a temporary Nginx root at a nonexistent release and run `nginx -t`.
Observe that syntax validation alone cannot prove content exists. Restore the
configuration through Ansible and ensure release health checks test actual
HTTP responses.

### Commit boundary

```console
git add ansible/roles/nginx ansible/roles/static_site
git commit -m "feat(nginx): serve versioned BearWorks releases"
```

## 6. Manual release laboratory

Do this before allowing GitHub Actions to deploy.

### Build release A

In the website repository:

```console
TAG=v0.1.0
COMMIT="$(git rev-parse HEAD)"
SHORT_SHA="$(git rev-parse --short=12 HEAD)"
RELEASE_ID="${TAG}-${SHORT_SHA}"
ARCHIVE="bearworks-${RELEASE_ID}.tar.gz"
MANIFEST="bearworks-${RELEASE_ID}.manifest.json"
SOURCE_DATE_EPOCH="$(git show -s --format=%ct "${COMMIT}")"

npm ci
npm run check
npm run build

jq -n \
  --arg tag "${TAG}" \
  --arg commit "${COMMIT}" \
  --arg release_id "${RELEASE_ID}" \
  '{
    schema_version: 1,
    site: "bearworks",
    tag: $tag,
    commit: $commit,
    release_id: $release_id
  }' > "${MANIFEST}"

cp "${MANIFEST}" dist/.release-manifest.json
tar --sort=name \
  --mtime="@${SOURCE_DATE_EPOCH}" \
  --owner=0 --group=0 --numeric-owner \
  -C dist -cf - . | gzip -n > "${ARCHIVE}"
sha256sum "${ARCHIVE}" > "${ARCHIVE}.sha256"
```

The tar stream contains the contents of `dist/` at archive root, not a nested
`dist` directory.

Inspect it:

```console
tar -tzf "${ARCHIVE}" | sed -n '1,80p'
sha256sum --check "${ARCHIVE}.sha256"
jq . "${MANIFEST}"
```

### Upload, install, and activate

```console
scp "${ARCHIVE}" "${ARCHIVE}.sha256" "${MANIFEST}" \
  bearworks-deploy@ares-local:/srv/www/bearworks/incoming/

ssh bearworks-deploy@ares-local \
  "sudo -n /usr/local/sbin/bearworks-release install \
  --archive /srv/www/bearworks/incoming/${ARCHIVE} \
  --checksum /srv/www/bearworks/incoming/${ARCHIVE}.sha256 \
  --manifest /srv/www/bearworks/incoming/${MANIFEST}"

ssh bearworks-deploy@ares-local \
  "sudo -n /usr/local/sbin/bearworks-release activate ${RELEASE_ID}"

ssh bearworks-deploy@ares-local \
  'sudo -n /usr/local/sbin/bearworks-release current'
```

Create a visible but harmless content change, commit it, build release B under
a new tag value, and activate it. Then roll back without rebuilding:

```console
ssh bearworks-deploy@ares-local \
  "sudo -n /usr/local/sbin/bearworks-release rollback <RELEASE_A_ID>"
```

### Failure experiments

Run each experiment independently and record `current` before and after.

| Experiment            | How                                                     | Expected result                             |
| --------------------- | ------------------------------------------------------- | ------------------------------------------- |
| Bad checksum          | Change one checksum character                           | Install fails; `current` is unchanged       |
| Traversal             | Add an archive entry containing `../`                   | Install fails before extraction             |
| Unsafe link           | Add a symlink entry                                     | Install fails before extraction             |
| Missing locale        | Remove `en/index.html`                                  | Install fails; no completed release appears |
| Interrupted upload    | Upload a truncated archive                              | Checksum fails; `current` is unchanged      |
| Identical retry       | Install the same valid files again                      | Success/no-op                               |
| Conflicting duplicate | Reuse an ID with different bytes                        | Install fails                               |
| Failed health check   | Make the staged Polish entrypoint invalid for the check | Activation restores the previous symlink    |
| Retention             | Install more than six releases                          | Active plus five inactive releases remain   |

Afterward:

```console
cd /home/kubaxius/Projects/VPS
pantheon ansible run ares-local
ssh bearworks-deploy@ares-local \
  'sudo -n /usr/local/sbin/bearworks-release current'
```

Ansible must not change the selected release.

Finally destroy and recreate the VM using the Pantheon commands, apply Ansible,
and repeat releases A and B plus rollback. This is the gate for adding CI
deployment.

### Commit boundary

No website commit is required for disposable laboratory tags or artifacts.
Delete local test archives after recording the results; do not commit them.

## 7. Add Tailscale

### Concepts

- A **tailnet** is your private Tailscale network.
- A **node identity** identifies one enrolled machine.
- A **tag** gives a non-human node a role.
- **tag ownership** controls who may assign that role.
- A **grant** states which identity may reach which destination and protocol.
- **MagicDNS** resolves tailnet machine names.
- An **ephemeral node** disappears after a short-lived CI job.
- **OIDC federation** lets GitHub prove the job identity to Tailscale without a
  stored Tailscale auth secret.

Tailscale only creates the network path. OpenSSH still authenticates the
`bearworks-deploy` user. This is deliberate defense in depth.

References:

- [Tailscale installation](https://tailscale.com/docs/install)
- [Device tags](https://tailscale.com/docs/features/tags)
- [Grants](https://tailscale.com/docs/features/access-control/grants)
- [Grant syntax](https://tailscale.com/docs/reference/syntax/grants)
- [Workload identity federation](https://tailscale.com/docs/features/workload-identity-federation)
- [Tailscale GitHub Action](https://tailscale.com/docs/integrations/github/github-action)

### Create the tailnet

Create a personal tailnet at Tailscale using your GitHub identity. Enable
MagicDNS. In the policy editor define:

```json
{
  "tagOwners": {
    "tag:bearworks-vm": [],
    "tag:bearworks-production": [],
    "tag:bearworks-ci-vm": [],
    "tag:bearworks-ci-production": []
  },
  "grants": [
    {
      "src": ["tag:bearworks-ci-vm"],
      "dst": ["tag:bearworks-vm"],
      "ip": ["tcp:22"]
    },
    {
      "src": ["tag:bearworks-ci-production"],
      "dst": ["tag:bearworks-production"],
      "ip": ["tcp:22"]
    }
  ]
}
```

An empty tag-owner list means only tailnet owners/admins may assign the tag.
Merge these entries with any policy needed for your own workstation access;
do not replace useful existing grants blindly.

Add policy tests for:

- CI VM tag -> VM tag TCP 22: allow;
- CI VM tag -> VM tag TCP 80: deny;
- CI VM tag -> production tag TCP 22: deny;
- CI production tag -> production tag TCP 22: allow;
- CI production tag -> VM tag TCP 22: deny.

Use the policy editor's preview/test facility before saving.

### Enroll persistent servers

Generate a one-off, pre-approved auth key tagged for the target, with the
shortest practical expiry. Put it temporarily in the relevant Ansible Vault
variable. The Tailscale role should:

- install from Tailscale's official Ubuntu repository;
- enable `tailscaled`;
- run enrollment only when the node is logged out;
- use `--ssh=false` because this design uses OpenSSH;
- advertise only the environment's server tag;
- preserve `/var/lib/tailscale` across ordinary Ansible runs.

The effective enrollment commands are:

```console
sudo tailscale up \
  --auth-key='<ONE_TIME_VM_AUTH_KEY>' \
  --hostname=ares-local \
  --advertise-tags=tag:bearworks-vm \
  --ssh=false

sudo tailscale up \
  --auth-key='<ONE_TIME_PRODUCTION_AUTH_KEY>' \
  --hostname=ares \
  --advertise-tags=tag:bearworks-production \
  --ssh=false
```

After successful enrollment, revoke/expire the pre-auth key and remove it from
the decrypted working copy. A future VM rebuild receives a new one-off key.

Make UFW allow OpenSSH on `tailscale0`. Preserve the local-LAN SSH rule for the
VM and a separately considered break-glass administrator CIDR for production;
do not expose deployment SSH broadly for GitHub runner IPs.

Verify from a workstation enrolled in the tailnet:

```console
tailscale status
tailscale ping ares-local
ssh ares-local
```

### Create GitHub federated identities

In Tailscale **Admin console -> Trust credentials**, create two OpenID Connect
credentials using the GitHub Actions issuer.

VM credential:

```text
Subject: repo:kubaxius/bw-website:environment:vm-test
Scope: auth_keys
Allowed tag: tag:bearworks-ci-vm
```

Production credential:

```text
Subject: repo:kubaxius/bw-website:environment:production
Scope: auth_keys
Allowed tag: tag:bearworks-ci-production
```

If the console expresses the tag restriction as a separate claim or scope,
apply it there. Also restrict the `repository` and, where offered,
`job_workflow_ref` claims to this repository and the intended workflow on
`main`. Copy each generated Client ID and Audience. They are identifiers, not
passwords.

### Break it deliberately

Connect a temporary node as `tag:bearworks-ci-vm`. Confirm TCP 22 to the VM is
reachable and TCP 80 plus production TCP 22 are not. Remove the temporary node
when finished.

### Commit boundary

```console
cd /home/kubaxius/Projects/VPS
git add ansible/roles/tailscale ansible/inventories ansible/site.yml
git commit -m "feat(tailscale): add scoped server enrollment"
```

Do not commit an auth key or decrypted Vault value.

## 8. Configure GitHub environments

Create `vm-test` and `production` under **Settings -> Environments**.

Use these names consistently:

| Name              | Kind     | VM value                       | Production value                 |
| ----------------- | -------- | ------------------------------ | -------------------------------- |
| `DEPLOY_HOST`     | variable | `ares-local`                   | `ares` or its MagicDNS FQDN      |
| `DEPLOY_USER`     | variable | `bearworks-deploy`             | `bearworks-deploy`               |
| `SITE_NAME`       | variable | `bearworks`                    | `bearworks`                      |
| `SITE_DOMAIN`     | variable | `bearworks.pl`                 | `bearworks.pl`                   |
| `TS_CLIENT_ID`    | variable | VM federation ID               | production federation ID         |
| `TS_AUDIENCE`     | variable | VM audience                    | production audience              |
| `RELEASE_SIGNER`  | variable | signing principal + public key | same trusted signer              |
| `SSH_KNOWN_HOSTS` | variable | pinned VM host-key line        | pinned production line           |
| `DEPLOY_SSH_KEY`  | secret   | VM private key                 | different production private key |

Generate separate deployment keypairs:

```console
ssh-keygen -t ed25519 \
  -f ~/.ssh/bearworks_vm_deploy_ed25519 \
  -C 'github-actions vm bearworks'
ssh-keygen -t ed25519 \
  -f ~/.ssh/bearworks_production_deploy_ed25519 \
  -C 'github-actions production bearworks'
```

Put public keys in the appropriate Ansible inventory variables. Put private
keys only in their matching GitHub environment secret.

Obtain host keys through an already trusted path, preferably directly from the
server console:

```console
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Create a known-hosts line with the exact Tailscale hostname used by CI and
store the complete line in `SSH_KNOWN_HOSTS`. Do not disable
`StrictHostKeyChecking` and do not trust an unverified `ssh-keyscan` result.

Restrict `production` to tags matching `v*`. Because this workshop uses
automatic signed-tag deployment, it does not add a reviewer gate. Understand
the tradeoff: repository administrators can change environment configuration,
so protect the GitHub account with MFA and keep repository write access small.

## 9. Deploy manually from GitHub to the VM

### What you are building

`deploy-vm.yml` is manually triggered. It is the bridge between the already
tested release helper and production automation. It must package once, pass the
files between jobs as an artifact, join Tailscale, and deploy.

Resolve and pin the Tailscale action:

```console
git ls-remote https://github.com/tailscale/github-action.git \
  'refs/tags/v4^{}' refs/tags/v4
```

### Workflow interface

```yaml
name: deploy-vm

on:
  workflow_dispatch:
    inputs:
      ref:
        description: Commit SHA, branch, or tag to build
        required: true
        type: string
      version:
        description: SemVer used for this VM release, for example v0.0.1
        required: true
        type: string

permissions:
  contents: read

concurrency:
  group: deploy-vm
  cancel-in-progress: false
```

Keep the VM manifest compatible with the server's production validator. Use a
throwaway but valid version such as `v0.0.<GITHUB_RUN_NUMBER>`; the resulting
release ID remains `<version>-<short-sha>`. VM versions are not Git tags and
must never be pushed. Do not weaken the production SemVer validator to
accommodate VM experiments.

Organize the workflow into:

1. `package` job without an environment or deployment credentials;
2. `deploy` job using `environment: vm-test` and the package artifact.

The package job checks out `inputs.ref`, installs, checks, builds, writes the
manifest, creates the deterministic archive, verifies it, and uploads all
three files with `actions/upload-artifact`. Emit `commit`, `release_id`,
`archive`, and `manifest` through `GITHUB_OUTPUT`.

The deploy job needs:

```yaml
permissions:
  contents: read
  id-token: write

environment:
  name: vm-test

steps:
  - uses: actions/download-artifact@<DOWNLOAD_ARTIFACT_V4_FULL_SHA> # v4
    with:
      name: bearworks-release
      path: release

  - name: Join the tailnet
    uses: tailscale/github-action@<TAILSCALE_V4_FULL_SHA> # v4
    with:
      oauth-client-id: ${{ vars.TS_CLIENT_ID }}
      audience: ${{ vars.TS_AUDIENCE }}
      tags: tag:bearworks-ci-vm

  - name: Configure OpenSSH
    shell: bash
    env:
      DEPLOY_KEY: ${{ secrets.DEPLOY_SSH_KEY }}
      KNOWN_HOSTS: ${{ vars.SSH_KNOWN_HOSTS }}
    run: |
      set -euo pipefail
      install -d -m 0700 ~/.ssh
      printf '%s\n' "${DEPLOY_KEY}" > ~/.ssh/deploy_key
      chmod 0600 ~/.ssh/deploy_key
      printf '%s\n' "${KNOWN_HOSTS}" > ~/.ssh/known_hosts

  # Upload the three artifact files with scp -i ~/.ssh/deploy_key.
  # Invoke install, activate, current, and HTTP health checks over SSH.
```

Use a shared SSH options array or checked-in wrapper to avoid repeating options:

```console
-i ~/.ssh/deploy_key
-o BatchMode=yes
-o IdentitiesOnly=yes
-o StrictHostKeyChecking=yes
-o UserKnownHostsFile=~/.ssh/known_hosts
```

Do not print secrets, private keys, or full environment contents. Delete the
private-key file in an `if: always()` cleanup step even though the hosted runner
is ephemeral.

### Checkpoint

- A manual run packages the requested ref.
- The package job has no environment or deployment credentials.
- The deploy job appears under the `vm-test` environment.
- Tailscale shows a temporary CI node while the job runs and removes it later.
- The workflow prints the previous and current release IDs.
- Nginx serves the selected release after the workflow ends.
- Re-running the same workflow safely reports an already-installed artifact.

### Break it deliberately

Change the VM grant temporarily so the runner cannot reach TCP 22. Confirm the
job times out quickly with a bounded SSH timeout and never affects `current`.
Restore and re-test the policy.

### Commit boundary

```console
git add .github/workflows/deploy-vm.yml
git commit -m "ci: deploy versioned releases to test VM"
```

## 10. Authorize releases with SSH-signed tags

### Generate a dedicated signing key

```console
ssh-keygen -t ed25519 \
  -f ~/.ssh/bearworks_release_signing_ed25519 \
  -C 'jakub.niedzwiedz@gmail.com BearWorks release signing'

git config --local gpg.format ssh
git config --local user.signingkey \
  ~/.ssh/bearworks_release_signing_ed25519.pub
git config --local tag.gpgSign true
```

Add the public key to GitHub under **Settings -> SSH and GPG keys -> New SSH
key**, selecting **Signing key**. Do not upload the private key.

Create a local allowed-signers file outside the repository:

```console
printf '%s %s\n' \
  'jakub.niedzwiedz@gmail.com' \
  "$(cat ~/.ssh/bearworks_release_signing_ed25519.pub)" \
  > ~/.ssh/bearworks_allowed_signers

git config --local gpg.ssh.allowedSignersFile \
  ~/.ssh/bearworks_allowed_signers
```

Create and verify a release tag:

```console
git tag -s -a v0.1.0 -m 'BearWorks v0.1.0'
git verify-tag v0.1.0
git show --show-signature v0.1.0
```

Do not push the tag until the production workflow and server have passed their
pre-DNS tests.

The site release tag and `package.json.version` serve different purposes. The
package version describes the Node project/package; the signed tag identifies
a deployed website snapshot. Do not add a fragile requirement to keep them
equal.

### CI verification

Set `RELEASE_SIGNER` to one complete allowed-signers line:

```text
jakub.niedzwiedz@gmail.com ssh-ed25519 AAAA... comment
```

In CI:

```console
TAG="${GITHUB_REF_NAME}"
printf '%s\n' "${RELEASE_SIGNER}" > "${RUNNER_TEMP}/allowed_signers"
git config gpg.ssh.allowedSignersFile "${RUNNER_TEMP}/allowed_signers"

[[ "${TAG}" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
test "$(git cat-file -t "refs/tags/${TAG}")" = tag
git verify-tag "${TAG}"

git fetch origin main --no-tags
COMMIT="$(git rev-list -n 1 "refs/tags/${TAG}")"
git merge-base --is-ancestor "${COMMIT}" origin/main
```

Checking `cat-file` ensures the reference is an annotated tag object rather
than a lightweight tag.

### Security limitation to understand

A tag-triggered workflow is loaded from the tagged commit. Signature
verification inside the workflow is a release gate, not a magical sandbox.
Protect `main` and release tags, keep write access narrow, pin actions, scope
environment secrets, and require MFA. For a future multi-maintainer repository,
add a production reviewer or move privileged deployment into a trusted reusable
workflow on protected `main`.

### Break it deliberately

Create an unsigned local tag and confirm `git verify-tag` rejects it. Create a
signed tag on a commit not contained in `main` and confirm the ancestor check
rejects it. Delete both local test tags.

## 11. Create the production release workflow

### Trigger and permissions

Create `.github/workflows/release.yml`:

```yaml
name: release

on:
  push:
    tags:
      - "v*.*.*"

concurrency:
  group: production
  cancel-in-progress: false

permissions:
  contents: read
```

The glob only reduces noise; the shell regular expression performs the real
validation.

Use three jobs:

1. `package`: verify tag/signature/ancestry, run CI, build, package, checksum,
   and upload the workflow artifact;
2. `deploy`: download that artifact, join Tailscale as
   `tag:bearworks-ci-production`, upload, install, activate, and health-check;
3. `publish`: after successful deployment, create the GitHub Release and attach
   the exact archive, checksum, and manifest.

Only `deploy` has:

```yaml
environment:
  name: production
permissions:
  contents: read
  id-token: write
```

Only `publish` has:

```yaml
permissions:
  contents: write
```

Publish with the GitHub CLI already available on GitHub-hosted runners:

```console
gh release create "${TAG}" \
  "release/${ARCHIVE}" \
  "release/${ARCHIVE}.sha256" \
  "release/${MANIFEST}" \
  --verify-tag \
  --title "BearWorks ${TAG}" \
  --generate-notes
```

Set `GH_TOKEN=${{ github.token }}` only on that step.

If deployment fails after switching `current`, the server helper must restore
the previous target before the job exits. Publication must not run. A rerun
uses the same workflow artifact when available or deterministically rebuilds
the same tagged source, and server installation accepts an identical existing
release.

### Manual rollback workflow

Create `rollback.yml` with one required `release_id` input and no checkout,
Node, npm, build, archive, or GitHub Release steps. It:

1. uses the `production` environment;
2. obtains the production Tailscale identity;
3. configures the production SSH key and pinned host key;
4. calls `list` and confirms the exact ID exists;
5. calls `rollback <RELEASE_ID>`;
6. performs HTTP health checks;
7. prints previous and active IDs.

Use the same `production` concurrency group so deployment and rollback cannot
overlap.

### Checkpoint

Before pushing the first real tag:

- action references are full SHAs;
- `package` cannot access deployment secrets;
- `deploy` cannot write repository contents;
- `publish` cannot access the SSH key or Tailscale identity;
- tag signature and ancestry fail before packaging;
- VM deployment has already passed the full lifecycle.

### Commit boundary

```console
git add .github/workflows/release.yml .github/workflows/rollback.yml
git commit -m "ci: add signed production releases and rollback"
```

## 12. Production and DNS cutover

Do not let the desire to see the public site skip the private validation.

### Provision without changing DNS

In the Pantheon repository:

1. replace `example.server.net` with the real host;
2. set production firewall, deploy key, TLS-disabled, and Tailscale variables;
3. apply the same roles tested on `ares-local`;
4. enroll `ares` as `tag:bearworks-production`;
5. revoke its one-off enrollment key;
6. verify only intended public ports and break-glass SSH policy.

Run:

```console
ANSIBLE_LOCAL_TEMP=/tmp/pantheon-ansible-local \
  ansible-playbook --syntax-check ansible/site.yml
ansible-lint ansible
pantheon ansible run ares
pantheon ansible run ares
tailscale ping ares
```

Deploy the first release through the production workflow while public DNS
still points at the old host. From SSH:

```console
curl -fsS -H 'Host: bearworks.pl' http://127.0.0.1/pl/ >/dev/null
curl -fsS -H 'Host: bearworks.pl' http://127.0.0.1/en/ >/dev/null
curl -sS -D- -o /dev/null -H 'Host: bearworks.pl' \
  http://127.0.0.1/missing
sudo nginx -t
sudo systemctl reboot
```

Reconnect and repeat the tests. Perform one rollback and reactivate the newest
release.

### DNS and TLS sequence

1. Record the authoritative apex and `www` records and TTLs for rollback.
2. Lower TTL in advance.
3. Confirm TCP 80 and the ACME challenge path reach the new VPS.
4. Point the apex A and AAAA records to the VPS.
5. Point `www` to the selected apex alias/redirect target.
6. Wait for authoritative propagation; query authoritative nameservers
   directly rather than trusting one recursive resolver.
7. Obtain a certificate for `bearworks.pl` and `www.bearworks.pl`.
8. Enable the production HTTPS and HTTP-to-HTTPS configuration through
   Ansible.
9. Run a certificate-renewal dry run.

Typical verification:

```console
dig +short A bearworks.pl
dig +short AAAA bearworks.pl
dig +short CNAME www.bearworks.pl
curl -fsSIL https://bearworks.pl/
curl -fsSIL https://bearworks.pl/pl/
curl -fsSIL https://bearworks.pl/en/
curl -fsSIL https://www.bearworks.pl/
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://bearworks.pl/definitely-missing
ssh ares 'sudo certbot renew --dry-run'
```

Also test from a network outside the tailnet on IPv4 and IPv6.

Configure an independent uptime check for `https://bearworks.pl/pl/` and a
certificate-expiry alert. Keep the recorded old DNS values until the rollback
window closes.

### Release the tag

After all preconditions exist:

```console
git tag -s -a v0.1.0 -m 'BearWorks v0.1.0'
git verify-tag v0.1.0
git push origin v0.1.0
```

Watch the workflow through GitHub's Actions tab or:

```console
gh run list --workflow release.yml
gh run watch <RUN_ID> --exit-status
gh release view v0.1.0
```

## 13. Future blog workflow

Start with Markdown or MDX in this repository using an Astro build-time content
collection. A post change then has exactly the same lifecycle as a layout
change: pull request, CI, merge, signed tag, static artifact, deployment.

Do not split content merely because it is conceptually different. A second
repository introduces:

- two revisions that must be pinned together;
- credentials for cross-repository checkout;
- preview coordination;
- ambiguous ownership of release triggers;
- two-dimensional rollback.

Split only when an actual editorial workflow needs independent permissions,
draft previews, media management, or non-Git authors. At that point add these
manifest fields:

```json
{
  "content_repository": "kubaxius/<CONTENT_REPOSITORY>",
  "content_commit": "<40-character commit SHA>"
}
```

The build must check out that exact commit. Never deploy "whatever is currently
on the content main branch" under an existing site tag.

Astro reference:
[Content collections](https://docs.astro.build/en/guides/content-collections/).

## 14. Final acceptance checklist

### Repository and CI

- [ ] Public GitHub repository uses protected `main`.
- [ ] Release tags cannot be updated or deleted casually.
- [ ] Node 24 is pinned locally and in CI.
- [ ] Clean `npm ci`, `npm run check`, and `npm run build` pass.
- [ ] Build has no root-route conflict warning.
- [ ] PR CI has read-only contents and no environment secrets.
- [ ] Every external action is pinned to a reviewed full SHA.

### Release host

- [ ] Ansible creates all accounts, paths, permissions, Nginx, and Tailscale
      state.
- [ ] A second Ansible run is idempotent.
- [ ] Deploy user can write only incoming files and invoke the release helper.
- [ ] Unsafe archives and invalid manifests are rejected.
- [ ] Installation is idempotent only for identical bytes and metadata.
- [ ] Activation and rollback switch `current` atomically.
- [ ] Failed health checks restore the previous release.
- [ ] Retention never removes the active or immediately previous release.
- [ ] Reboot preserves the active release.

### Tailscale and SSH

- [ ] VM and production servers have separate tags.
- [ ] VM and production CI have separate federated identities.
- [ ] CI tags reach only their target's TCP 22.
- [ ] Tailscale auth uses OIDC; no reusable CI auth key is stored in GitHub.
- [ ] VM and production OpenSSH keys are different.
- [ ] CI enforces pinned SSH host keys.

### Production release

- [ ] Only annotated, correctly formatted, SSH-signed tags pass.
- [ ] Tagged commit must be contained in `main`.
- [ ] Site is built exactly once per workflow run.
- [ ] Deployment uses the package-job artifact.
- [ ] GitHub Release receives the exact deployed files after health succeeds.
- [ ] Manual rollback performs no build.
- [ ] DNS, trusted TLS, renewal, external IPv4/IPv6, 404s, redirects, and cache
      headers are verified.
- [ ] External uptime and certificate-expiry monitoring are active.

## 15. Troubleshooting matrix

| Symptom                               | Inspect                                      | Likely cause                                                   |
| ------------------------------------- | -------------------------------------------- | -------------------------------------------------------------- |
| Workflow does not start for a tag     | Actions filters and tag name                 | Tag glob did not match or workflow was absent at tagged commit |
| `id-token` error                      | Job `permissions`                            | Missing `id-token: write`                                      |
| Tailscale token exchange denied       | OIDC subject, audience, custom claims        | Environment/repository/workflow claim mismatch                 |
| CI node joins but SSH times out       | Grants, UFW, destination tag, MagicDNS       | TCP 22 not allowed end to end                                  |
| SSH reports changed host key          | Console fingerprint and known-hosts variable | VM rebuilt or possible interception                            |
| SSH authentication denied             | Environment secret and authorized key        | Wrong environment's deploy key                                 |
| `sudo -n` denied                      | Sudoers validation and exact helper path     | Command not allow-listed                                       |
| Checksum fails                        | Uploaded names and `sha256sum -c`            | Partial upload or artifact mismatch                            |
| Manifest fails                        | `jq` output and internal manifest            | Tag, SHA, ID, or archive disagree                              |
| Archive rejected                      | `tar -tvzf`                                  | Unsafe path/link/type or wrong root layout                     |
| Install succeeds but activation fails | Nginx logs and local Host-header curl        | Missing route, permissions, or vhost mismatch                  |
| Site returns 200 for missing routes   | `try_files`                                  | SPA-style fallback incorrectly enabled                         |
| Rerun reports conflicting duplicate   | Stored checksum/manifest                     | Same ID was built from different bytes                         |
| GitHub Release missing                | Publish job and deployment result            | Release is published only after healthy deployment             |
| Certificate request fails             | DNS, port 80, ACME path, firewall            | Public validation cannot reach the VPS                         |

When diagnosing, preserve the failed artifact, manifest, helper output, active
release ID, previous release ID, Nginx error log, and GitHub run ID. Do not
"fix" a failed production release by editing files under `releases/`; correct
the source or deployment mechanism and create a new signed version.
