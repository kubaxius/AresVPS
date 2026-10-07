---
tags: ai_generated
---

# BearWorks signed-release MVP

The website build is published as a signed GitHub Release. A small release
agent on each server asks `systemd-sysupdate` to authenticate, download,
extract, and retain releases. The agent validates the required files and
atomically switches Nginx to the new release.

Ansible installs and configures this mechanism. It does not inspect or modify
the active release links.

## Release flow

```text
signed vMAJOR.MINOR.PATCH tag
  -> GitHub Actions builds dist/
  -> CI publishes the archive, SHA256SUMS, and SHA256SUMS.gpg
  -> an operator or Ansible requests an update
  -> systemd-sysupdate verifies and extracts the archive
  -> the release agent validates required entrypoints
  -> the agent atomically switches current
  -> Nginx serves the new release without a reload
```

The release ID combines the tag and the first twelve lowercase characters of
the commit SHA:

```text
v1.2.3-0123456789ab
```

The matching GitHub Release contains:

```text
bearworks-v1.2.3-0123456789ab.tar.gz
SHA256SUMS
SHA256SUMS.gpg
```

Published release assets are immutable. Corrections use a new version.

## Signing key

Generate a dedicated artifact-signing key on a trusted workstation:

```console
gpg --quick-generate-key "BearWorks release artifacts" rsa4096 sign 2y
gpg --armor --export "BearWorks release artifacts" > bearworks-release-public.asc
gpg --armor --export-secret-keys "BearWorks release artifacts" > bearworks-release-private.asc
```

Store the private key and passphrase only as protected secrets in the website
repository. Configure the public key in Pantheon:

```yaml
static_site_signing_public_keys:
  - |
    -----BEGIN PGP PUBLIC KEY BLOCK-----
    ...
    -----END PGP PUBLIC KEY BLOCK-----
```

Multiple public keys may be present temporarily during rotation.

## Artifact requirements

The archive must contain these files at its root:

```text
index.html
pl/index.html
en/index.html
```

Its filename must be `bearworks-<release-id>.tar.gz`. `SHA256SUMS` must contain
the archive checksum, and `SHA256SUMS.gpg` must be its detached signature.
The GitHub Release must be a full published release because the server reads
from `releases/latest/download`.

The default source is:

```yaml
static_site_release_feed_url: >-
  https://github.com/kubaxius/bw-website-2/releases/latest/download
```

## Provision the server

Apply Ansible to the local VM first:

```console
ansible-playbook -i ansible/inventories/local/hosts.yaml ansible/site.yml \
  --limit ares-local
```

The role installs:

- `/usr/local/libexec/static-site-release`;
- `/etc/static-site-release/bearworks.json`;
- `/etc/sysupdate.bearworks.d/10-site.conf`;
- `static-site-update@.service`;
- the systemd artifact-signing keyring;
- Nginx rooted at `/srv/www/bearworks/current`.

At the end of every apply, Ansible asynchronously starts
`static-site-update@bearworks.service`. The play does not wait for the download
or fail when the update fails. Inspect the service journal for the outcome.

## Operate releases

Request the latest signed release through systemd:

```console
sudo systemctl start static-site-update@bearworks.service
sudo journalctl -u static-site-update@bearworks.service
```

The same operation can be invoked directly:

```console
sudo /usr/local/libexec/static-site-release \
  --config /etc/static-site-release/bearworks.json update
```

List installed releases; `*` marks the active one:

```console
sudo /usr/local/libexec/static-site-release \
  --config /etc/static-site-release/bearworks.json list
```

Atomically activate an older retained release:

```console
sudo /usr/local/libexec/static-site-release \
  --config /etc/static-site-release/bearworks.json \
  activate v1.1.0-fedcba987654
```

Nginx follows the `current` symlink per request, so activation does not require
a reload. A later update check with no newly downloaded release preserves the
manual selection.

## Retention and failures

Sysupdate retains four release directories: the active release and three
rollback choices. Before an update, the agent points sysupdate’s internal
`staged` link at the active release so retention cannot prune it.

Signature verification occurs before extraction. After extraction, the agent
requires every configured entrypoint to be a regular file reached without
crossing symlinks. A signature failure, malformed release, missing entrypoint,
or unexpected sysupdate result leaves `current` unchanged.

A downloaded release that fails layout validation remains installed but
inactive until normal retention pruning removes it. Publish a corrected higher
version rather than replacing existing GitHub Release assets.

## Local acceptance pass

Exercise the MVP on `ares-local` before production:

1. Apply Ansible and confirm the asynchronous update activates the latest
   signed release.
2. Run `list` and confirm the active marker.
3. Activate an older release and confirm Nginx serves it without reloading.
4. Run `update` with no newer release and confirm the manual selection remains.
5. Publish successive releases and confirm only four are retained.
6. Confirm an invalid signature and a missing required entrypoint leave
   `current` unchanged.

Useful diagnostics:

```console
systemctl status static-site-update@bearworks.service
journalctl -u static-site-update@bearworks.service
systemd-sysupdate --definitions=/etc/sysupdate.bearworks.d list
readlink /srv/www/bearworks/current
readlink /srv/www/bearworks/staged
```
