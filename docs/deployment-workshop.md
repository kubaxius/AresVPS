---
tags: ai_generated
---

# BearWorks signed-release workshop

This workshop deploys the static BearWorks site with a signed localhost feed,
`systemd-sysupdate`, and health-gated promotion. GitHub Actions builds exactly
one archive. SSH remains only the transport into the restricted `incoming`
directory; it is not a privilege boundary.

## 1. Release architecture

```text
annotated signed Git tag
  -> GitHub Actions builds dist/ once
  -> <site>-<release-id>.tar.gz
  -> SHA256SUMS + detached SHA256SUMS.gpg
  -> temporary upload names over Tailscale/SSH
  -> atomic rename into incoming/
  -> localhost-only Nginx feed
  -> systemd-sysupdate verifies, extracts, retains, and stages
  -> controller checks staged, atomically promotes current, checks production
  -> GitHub Release receives the same archive
```

The release ID is `vMAJOR.MINOR.PATCH-<first-12-lowercase-commit-hex>`. A
release archive is therefore named, for example,
`bearworks-v1.4.0-0123456789ab.tar.gz`.

Keep these invariants:

1. Build once; never install Node or build the site on a server.
2. Keep `.release-manifest.json` inside the archive for provenance.
3. Let `systemd-sysupdate` verify the signed checksum manifest and unpack the
   archive. The controller must not duplicate those jobs.
4. Upload all three feed files completely before starting a deployment.
5. Only `staged` is checked before promotion; production remains rooted at
   `current`.
6. Only Polkit-authorized `start` operations for well-formed deploy and
   rollback unit instances cross the privilege boundary.
7. Publish a GitHub Release only after production health checks pass.

## 2. Create and protect the artifact-signing key

Use a dedicated GPG key that is unrelated to SSH deploy credentials and Git
tag-signing credentials:

```console
gpg --quick-generate-key "BearWorks release artifacts" rsa4096 sign 2y
gpg --armor --export "BearWorks release artifacts" > bearworks-release-public.asc
gpg --armor --export-secret-keys "BearWorks release artifacts" > bearworks-release-private.asc
```

Store the armored private key and its passphrase as protected GitHub
environment secrets. Inventory-manage one or more armored public keys with
`static_site_signing_public_keys`; never put the private key in this repository
or an Ansible vault on the web host. During rotation, configure old and new
public keys together, roll out Ansible, switch CI signing, and remove the old
public key only after its releases no longer need to be accepted.

Example non-secret inventory data:

```yaml
static_site_signing_public_keys:
  - |
    -----BEGIN PGP PUBLIC KEY BLOCK-----
    ...
    -----END PGP PUBLIC KEY BLOCK-----
```

The role combines these keys into `/etc/systemd/import-pubring.gpg`.

## 3. Provision host support

The `static_site` role installs `systemd-container`, `curl`, `gnupg`, and
Polkit; creates the feed, release, and configuration directories; and renders:

- `/etc/sysupdate.<site>.d/10-site.conf`;
- `/etc/static-site-release/<site>.json`;
- `/usr/local/libexec/static-site-release-control`;
- deploy and rollback service templates;
- a per-site Polkit rule;
- production, staging, and feed Nginx listeners.

Choose unique loopback ports for every site:

```yaml
static_site_feed_port: 18080
static_site_staging_health_port: 18081
```

Apply the role to the local VM first:

```console
ansible-playbook -i ansible/inventories/local/hosts.yaml ansible/site.yml --syntax-check
ansible-playbook -i ansible/inventories/local/hosts.yaml ansible/site.yml --limit ares-local
```

Inspect without changing production:

```console
ssh ares-local 'sudo systemd-sysupdate --definitions=/etc/sysupdate.bearworks.d list'
ssh ares-local 'sudo ss -ltnp | grep -E "127.0.0.1:(18080|18081)"'
ssh ares-local 'sudo nginx -t'
ssh ares-local 'sudo systemd-analyze verify \
  static-site-deploy-bearworks@.service \
  static-site-rollback-bearworks@.service'
```

Both auxiliary listeners must bind only to `127.0.0.1`. Production remains
rooted at `/srv/www/bearworks/current`; staging is rooted at `staged`; the feed
is rooted at `incoming`.

## 4. Build a deterministic release

From a clean website checkout, derive the ID and provenance manifest:

```console
tag=v1.4.0
commit=$(git rev-parse HEAD)
release_id="${tag}-${commit%${commit#????????????}}"
archive="bearworks-${release_id}.tar.gz"
test "$(git rev-parse "${tag}^{commit}")" = "$commit"
```

Write `.release-manifest.json` into `dist/`. It remains provenance data, not a
second server-side verification protocol:

```json
{
  "schema_version": 1,
  "site": "bearworks",
  "tag": "v1.4.0",
  "commit": "0123456789abcdef0123456789abcdef01234567",
  "release_id": "v1.4.0-0123456789ab"
}
```

Normalize timestamps, owners, order, and gzip metadata:

```console
epoch=$(git show -s --format=%ct HEAD)
find dist -exec touch -h -d "@${epoch}" {} +
tar --sort=name --format=posix --pax-option=delete=atime,delete=ctime \
  --mtime="@${epoch}" --owner=0 --group=0 --numeric-owner \
  -C dist -cf - . | gzip -n -9 > "$archive"
printf '%s  %s\n' "$(sha256sum "$archive" | cut -d' ' -f1)" "$archive" > SHA256SUMS
gpg --batch --yes --detach-sign --output SHA256SUMS.gpg SHA256SUMS
```

`SHA256SUMS` must contain plain file names only. Keep older retained archives
listed when they remain in `incoming`; otherwise list only the complete set of
archives that the feed intentionally offers.

## 5. Upload the complete feed atomically

Upload temporary names first. Rename the archive before the manifest, and the
signature last, so deployment cannot observe a new signed manifest before its
payload exists:

```console
remote=/srv/www/bearworks/incoming
scp "$archive" "bearworks-deploy@ares-local:${remote}/${archive}.upload"
scp SHA256SUMS "bearworks-deploy@ares-local:${remote}/SHA256SUMS.upload"
scp SHA256SUMS.gpg "bearworks-deploy@ares-local:${remote}/SHA256SUMS.gpg.upload"
ssh bearworks-deploy@ares-local -- \
  mv "${remote}/${archive}.upload" "${remote}/${archive}" \
  && mv "${remote}/SHA256SUMS.upload" "${remote}/SHA256SUMS" \
  && mv "${remote}/SHA256SUMS.gpg.upload" "${remote}/SHA256SUMS.gpg"
```

In automation, upload directly as unique `.upload-<run-id>` files, then rename
them with these final operations:

```console
mv "${remote}/${archive}.upload-<run-id>" "${remote}/${archive}"
mv "${remote}/SHA256SUMS.upload-<run-id>" "${remote}/SHA256SUMS"
mv "${remote}/SHA256SUMS.gpg.upload-<run-id>" "${remote}/SHA256SUMS.gpg"
```

Do not start deployment unless all three final paths exist. The feed listener
is deliberately unavailable over public and Tailscale addresses.

## 6. Deploy on `ares-local`

The deploy user may start exactly one well-formed unit instance:

```console
systemctl start "static-site-deploy-bearworks@${release_id}.service"
systemctl status "static-site-deploy-bearworks@${release_id}.service"
journalctl -u "static-site-deploy-bearworks@${release_id}.service"
```

The unit runs as root. The controller serializes operations with a per-site
`flock`, runs sysupdate with the fixed definitions directory, requires
`staged -> releases/<release-id>`, checks entrypoints and the staging listener,
then atomically changes `current`. If production checks fail, it restores both
symlinks.

Read-only inspection does not grant deployment rights:

```console
/usr/local/libexec/static-site-release-control \
  --config /etc/static-site-release/bearworks.json current
/usr/local/libexec/static-site-release-control \
  --config /etc/static-site-release/bearworks.json list
systemd-sysupdate --definitions=/etc/sysupdate.bearworks.d list
```

An identical deployment rerun must succeed without changing content or links.

## 7. Roll back

Select an installed release from the read-only list, then start the rollback
unit:

```console
rollback_id=v1.3.0-fedcba987654
systemctl start "static-site-rollback-bearworks@${rollback_id}.service"
journalctl -u "static-site-rollback-bearworks@${rollback_id}.service"
```

Rollback accepts only a real directory directly below `releases`, points
`staged` to it, checks the staging listener, and promotes it. A failed
production check restores both previous symlinks.

## 8. Failure laboratory

Run these tests on `ares-local`, never against production:

1. Deploy a valid signed release, then deploy it again.
2. Change one archive byte after signing. Sysupdate must reject its checksum.
3. Change the digest in `SHA256SUMS`, sign it, and confirm the archive mismatch
   is rejected.
4. Sign with an unknown key and confirm GPG verification fails.
5. Alter `SHA256SUMS` after signing and confirm the signature fails.
6. Upload only one or two feed files and confirm no deployment can complete.
7. Omit `en/index.html`; staging must fail without changing `current`.
8. Make a staging route unhealthy; production must remain unchanged.
9. Make only the production route unhealthy; both symlinks must be restored.
10. Roll back to a retained release.
11. Start deploy and rollback concurrently; journal timestamps must show
    serialization.
12. Fill retention and confirm the active release and intended rollback target
    remain available before deploying further.
13. Test both auxiliary ports from localhost, the Tailscale address, and the
    public address. Only localhost may connect.
14. As the deploy account, try `stop`, `restart`, a malformed release ID, a
    different site unit, and an unrelated service. Polkit must reject all.
15. Apply Ansible twice; the second run must report no changes.

Restore the valid three-file feed after every corruption experiment.

## 9. GitHub environments and workflows

Create separate protected environments for the local VM and production. Each
environment receives only its own SSH private key, known-host entry, target,
and Tailscale/OIDC settings. Artifact-signing secrets belong to the protected
release environment.

The deployment job must:

1. Download the archive built by the build job; never rebuild it.
2. Import the protected artifact-signing private key non-interactively.
3. Create and sign `SHA256SUMS`.
4. Join Tailscale with the environment-specific ephemeral identity.
5. Upload three temporary files and rename them into place.
6. Start the deploy unit and wait for it to finish.
7. Verify production URLs from the runner.

For production, require an annotated SSH-signed SemVer tag whose commit is in
`main`. Use a concurrency group that permits only one production deployment.
Publish the GitHub Release afterward and attach the exact archive that was
uploaded. A rollback workflow takes a retained release ID and starts only the
rollback unit; it never rebuilds or republishes.

## 10. Production rollout

Provision production while its existing `current` release stays live. The role
installs sysupdate, the keyring, controller, units, Polkit, and auxiliary Nginx
listeners alongside it and initializes `staged` from a valid `current` link.

Proceed only after the complete local failure laboratory passes:

```console
ansible-playbook -i ansible/inventories/prod/hosts.yaml ansible/site.yml --syntax-check
ansible-playbook -i ansible/inventories/prod/hosts.yaml ansible/site.yml --limit ares
```

Upload the same signed artifact tested on the VM, start its production deploy
unit, and check the public site. DNS and trusted TLS changes remain separate
operations. Publish the GitHub Release only after production health succeeds.

## 11. Troubleshooting

| Symptom | Check |
| --- | --- |
| No versions listed | Fetch loopback `SHA256SUMS`; inspect its file names and source match pattern. |
| Signature rejected | Inspect `/etc/systemd/import-pubring.gpg`, signer fingerprint, and detached signature. |
| Archive rejected | Compare `sha256sum` with `SHA256SUMS`; confirm upload rename completed. |
| Requested version not staged | Inspect sysupdate output and `readlink staged`; confirm exact release ID. |
| Entry point failure | List the extracted release and reject symlinked path components. |
| Staging health fails | Curl `127.0.0.1:<staging-port>` with the configured Host header. |
| Production restored | Inspect the unit journal for the failed post-promotion route. |
| Unit authorization fails | Check the calling user, verb `start`, exact site prefix, and release-ID grammar. |
| Auxiliary port is remote-reachable | Stop rollout and inspect Nginx `listen`; it must name `127.0.0.1`. |
| Old release disappeared | Stop deploying and review retention before losing the rollback target. |

Useful diagnostics:

```console
systemd-sysupdate --definitions=/etc/sysupdate.bearworks.d list
curl -fsS http://127.0.0.1:18080/SHA256SUMS
curl -i -H 'Host: bearworks.pl' http://127.0.0.1:18081/en/
readlink /srv/www/bearworks/current
readlink /srv/www/bearworks/staged
journalctl -u 'static-site-*-bearworks@*.service'
```

## 12. Acceptance checklist

- The archive is deterministic and contains `.release-manifest.json`.
- `SHA256SUMS` and `SHA256SUMS.gpg` are present and accepted only by configured
  public keys.
- Sysupdate owns verification, extraction, and retention.
- The controller owns only locking, validation, health gates, promotion, and
  restoration.
- Production and staging point directly to `releases/<release-id>` with
  relative symlinks.
- Feed and staging bind only to loopback.
- The deploy account cannot start unrelated units or use other verbs.
- Valid deployment, identical rerun, rollback, corruption cases, concurrency,
  and two Ansible runs pass on `ares-local`.
- Production uses the artifact already tested on the VM.
- GitHub Release publication occurs only after production health checks.
