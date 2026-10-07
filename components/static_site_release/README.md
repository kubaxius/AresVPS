---
tags: ai_generated
---

# Static-site release agent

This component provides the runtime release mechanism for static sites managed
by Pantheon. Ansible installs and configures it but does not manage release
state.

The agent delegates signed GitHub Release downloads, signature verification,
extraction, and retention to `systemd-sysupdate`. It validates required files
and atomically switches the site’s `current` symlink.

## Usage

The agent must run as root because it invokes `systemd-sysupdate` and updates
root-owned release symlinks. Ansible installs one JSON configuration per site
under `/etc/static-site-release/`.

Normally, request an update through the generic systemd unit so output is kept
in the journal:

```console
sudo systemctl start static-site-update@bearworks.service
sudo systemctl status static-site-update@bearworks.service
sudo journalctl -u static-site-update@bearworks.service
```

The instance name (`bearworks`) selects
`/etc/static-site-release/bearworks.json`. Ansible also starts this service
asynchronously after applying the static-site role.

The CLI can perform the same update directly:

```console
/usr/local/libexec/static-site-release --config /etc/static-site-release/bearworks.json update
```

List retained releases before selecting one manually:

```console
/usr/local/libexec/static-site-release --config /etc/static-site-release/bearworks.json list
```

The active release is marked with `*`. Activate any other listed release by
its complete ID:

```console
/usr/local/libexec/static-site-release --config /etc/static-site-release/bearworks.json activate v1.2.3-0123456789ab
```

`update` installs and activates one newly published release. `activate` switches
to an already installed release, and `list` marks the active release with `*`.

Run `--help` for the command synopsis and examples:

```console
/usr/local/libexec/static-site-release --help
```

Automated tests can be added under `tests/` after the MVP has been exercised on
the local VM.
