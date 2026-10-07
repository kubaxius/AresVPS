---
tags: ai_generated
---

# Pantheon server CLI

`pantheon-srv` is the dependency-free administrative CLI installed on every
Pantheon-managed server. The MVP exposes static-site release operations; later
server-side tools can be added as new command groups.

Ansible owns `/etc/pantheon/sites.d/`. Each `<site>.json` file describes one
site's release root, sysupdate definitions, and required entrypoints. Operators
refer to that configuration by site name instead of passing a path.

## Usage

Run the CLI as root because updates invoke `systemd-sysupdate` and release
selection changes root-owned symlinks.

Install the latest signed GitHub release and activate it:

```console
sudo pantheon-srv site bearworks update
```

List retained releases; `*` marks the active release:

```console
sudo pantheon-srv site bearworks list
```

Activate an already installed release without reloading Nginx:

```console
sudo pantheon-srv site bearworks activate v1.2.3-0123456789ab
```

Show the complete command synopsis:

```console
pantheon-srv --help
pantheon-srv site --help
```

Ansible runs `update` synchronously for every declared site at the end of each
play. There is no timer or background update service in the MVP.

## Adding a website

Create `ansible/sites/<site>.yml` in the infrastructure repository:

```yaml
repository: owner/public-repository
domain: example.com
required_entrypoints:
  - index.html
```

`required_entrypoints` is optional and defaults to `index.html`. The filename
becomes the site name, production uses `domain`, and the local inventory uses
`<site>.test`. The next Ansible play installs the complete site configuration
and invokes its first update.

Automated tests can be added under `tests/` after the MVP has been exercised on
the local VM.
