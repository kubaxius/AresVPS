---
tags: ai_generated
---

# Pantheon static-site deployment workshop

Pantheon deploys public static websites from signed GitHub Releases. Adding a
website requires one YAML file; Ansible discovers it, configures the host, and
runs the initial update through `pantheon-srv`.

There is no update timer. An Ansible play checks every configured site, and an
operator can request updates or switch retained releases explicitly.

## Release flow

```text
ansible/sites/<site>.yml
  -> Ansible creates the site root, Nginx vhost, and sysupdate definition
  -> Ansible writes /etc/pantheon/sites.d/<site>.json
  -> Ansible runs pantheon-srv site <site> update
  -> systemd-sysupdate verifies and extracts the latest GitHub Release
  -> pantheon-srv validates required files and atomically switches current
  -> Nginx serves the selected release without a reload
```

## Add a website

Create `ansible/sites/<site>.yml`. The filename stem is the site name and must
contain only lowercase letters, digits, dots, underscores, and hyphens.

For example, `ansible/sites/bearworks.yml` contains:

```yaml
repository: kubaxius/bw-website-2
domain: bearworks.pl
required_entrypoints:
  - index.html
  - pl/index.html
  - en/index.html
```

Only `repository` and `domain` are required. If `required_entrypoints` is
omitted, it defaults to `index.html`.

Pantheon derives the remaining values:

| Setting | Derived value |
| --- | --- |
| Local domain | `<site>.test` |
| Production domain | Value of `domain` |
| Site root | `/srv/www/<site>` |
| Server config | `/etc/pantheon/sites.d/<site>.json` |
| Sysupdate definitions | `/etc/sysupdate.<site>.d` |
| GitHub source | `https://github.com/<repository>/releases/latest/download` |
| Archive pattern | `<site>-@v.tar.gz` |

Apply Ansible. No playbook or inventory edit is needed:

```console
ansible-playbook -i ansible/inventories/local ansible/site.yml
```

Ansible configures every YAML file in `ansible/sites/`, applies keyring and
Nginx handlers, and then synchronously updates every site. A failed download,
signature check, layout validation, or first installation fails the play.

## Publish compatible releases

Each website repository must be public and publish a full GitHub Release with:

```text
<site>-v1.2.3-0123456789ab.tar.gz
SHA256SUMS
SHA256SUMS.gpg
```

The release ID combines a semantic-version tag with the first twelve lowercase
characters of the commit SHA. The archive must expose every configured
entrypoint at its root.

All sites currently use one dedicated artifact-signing key. Configure its
public half in `ansible/group_vars/all.yml`:

```yaml
pantheon_server_release_signing_public_keys:
  - |
    -----BEGIN PGP PUBLIC KEY BLOCK-----
    ...
    -----END PGP PUBLIC KEY BLOCK-----
```

Keep the private key only in the website release workflow. Sysupdate verifies
the signed checksum manifest against `/etc/systemd/import-pubring.gpg` before
the agent activates an archive.

## Operate a site

Install and activate the latest published release:

```console
sudo pantheon-srv site bearworks update
```

List retained releases; `*` marks the active one:

```console
sudo pantheon-srv site bearworks list
```

Switch atomically to an installed release:

```console
sudo pantheon-srv site bearworks activate v1.1.0-fedcba987654
```

Nginx serves `/srv/www/<site>/current`, so activation does not require a
reload. An update that downloads nothing preserves a manually selected older
release. A genuinely new release becomes active after it passes validation.

## Retention and failures

Sysupdate retains four release directories: the active release and three older
choices. Before updating, `pantheon-srv` protects the current release through
sysupdate's `staged` link.

These failures leave `current` unchanged:

- GitHub or sysupdate failure;
- missing or invalid checksum signature;
- unexpected release installation state;
- malformed release identifier;
- missing, symlinked, or non-file required entrypoint.

A downloaded release that fails entrypoint validation remains inactive until
normal retention removes it. Publish a corrected higher version rather than
replacing immutable GitHub Release assets.

## Local acceptance pass

Before production:

1. Apply Ansible and confirm BearWorks retains its existing release state.
2. Add another site YAML file backed by a public test repository.
3. Reapply Ansible and confirm both sites update without editing `site.yml`.
4. Reapply with no new releases and confirm the play reports no release change.
5. Use `list` and `activate` independently for both sites.
6. Confirm an invalid signature or missing entrypoint fails without changing
   the active release.

Useful diagnostics:

```console
sudo pantheon-srv site bearworks list
systemd-sysupdate --definitions=/etc/sysupdate.bearworks.d list
readlink /srv/www/bearworks/current
readlink /srv/www/bearworks/staged
```
