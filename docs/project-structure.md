---
tags: ai_generated
---

# Project Structure

Pantheon uses Ansible inventory names as canonical machine names. The Python CLI
reads the inventory, Bash handles privileged libvirt operations, cloud-init
bootstraps SSH access, and Ansible applies the lasting system configuration.

## Repository layout

```text
VPS/
├── ansible.cfg
├── ansible/
│   ├── group_vars/all.yml
│   ├── inventories/
│   │   ├── local/hosts.yaml
│   │   └── prod/
│   │       ├── hosts.yaml
│   │       └── host_vars/ares/vault.yml
│   ├── roles/
│   └── site.yml
├── infra/local/cloud-init/user-data
├── pantheon_systems_cli/
│   ├── ansible.py
│   └── vm/
├── scripts/
│   ├── destroy_vm.sh
│   └── set_up_vm.sh
└── vm/                         # Ignored cloud image storage
```

## Machine identity

The Ansible inventory alias is the machine's identity everywhere:

| Environment | Inventory name | OS hostname  | Libvirt name   |
| ----------- | -------------- | ------------ | -------------- |
| Production  | `ares`         | `ares`       | Not applicable |
| Local       | `ares-local`   | `ares-local` | `ares-local`   |

Future machines follow the same convention: `hera` in production and
`hera-local` for its local test VM. `ansible_host`, when present, is only a
connection address; it does not define machine identity.

The base Ansible role assigns `inventory_hostname` as the OS hostname. Local VM
commands pass the same inventory name to libvirt and generate matching
cloud-init metadata at creation time.

## Inventories

Local machines and production machines remain in separate inventories so a
local command cannot accidentally target production.

```yaml
# ansible/inventories/local/hosts.yaml
all:
  hosts:
    ares-local:
      env_type: local
      configure_production_tls: false
      vm_network: default
      vm_mac: "52:54:00:00:00:10"
      vm_ip: "192.168.122.10"
```

```yaml
# ansible/inventories/prod/hosts.yaml
all:
  hosts:
    ares:
      ansible_host: example.server.net
      env_type: prod
      configure_production_tls: false
```

The playbook targets Ansible's built-in `all` group. Shared configuration,
including `ansible_user: ansible`, lives in `ansible/group_vars/all.yml`.
Machine-specific production secrets belong in that machine's encrypted
`host_vars/<name>/vault.yml` file.

## Local SSH configuration

Ansible connects to `ares-local` without an `ansible_host` override. OpenSSH
resolves that name to the reserved VM address:

```sshconfig
Host *-local
    User jbear
    IdentityFile ~/.ssh/pantheon_local_%r_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
    UserKnownHostsFile ~/.ssh/known_hosts.local-test
    HostKeyAlias %n-vm

Host ares-local
    HostName 192.168.122.10
```

For an interactive `ssh ares-local` session, `%r` expands to `jbear`. Ansible
sets the remote user to `ansible`, so the same entry resolves to
`~/.ssh/pantheon_local_ansible_ed25519`.

Cloud-init installs the corresponding public keys from
`infra/local/cloud-init/user-data`. When a VM is rebuilt and receives a new host
key, remove the old test-only entry before reconnecting:

```bash
ssh-keygen -R ares-local-vm -f ~/.ssh/known_hosts.local-test
```

## Local VM flow

```text
local Ansible inventory
    │
    ├── canonical name ──▶ Typer completion and libvirt domain name
    ├── vm_network ────▶ libvirt network
    ├── vm_mac ───────▶ DHCP reservation
    └── vm_ip ────────▶ DHCP reservation and SSH HostName
```

The supported lifecycle commands are:

```console
pantheon vm create ares-local
pantheon vm start ares-local
pantheon vm restart --all
pantheon vm shutdown --all --force
pantheon vm state --all
pantheon vm destroy ares-local
pantheon vm destroy --all
```

Host arguments are validated against the local inventory and participate in
shell completion. Pass `--all` instead of a host to apply any lifecycle command
to every VM in the local inventory. Bulk destruction lists the affected hosts
and asks for confirmation before proceeding. The privileged scripts receive
resolved values as arguments; they contain no machine-specific names or
addresses.

Cloud-init is limited to bootstrap responsibilities: creating the `ansible` and
`jbear` users, installing their authorized keys, installing Python and the QEMU
guest agent, and starting the guest agent. Ansible owns the steady-state system
configuration.

## Adding another local machine

Add the host and its unique network values to the local inventory:

```yaml
hera-local:
  env_type: local
  configure_production_tls: false
  vm_network: default
  vm_mac: "52:54:00:00:00:11"
  vm_ip: "192.168.122.11"
```

Then add its SSH address mapping:

```sshconfig
Host hera-local
    HostName 192.168.122.11
```

No Python, Bash, cloud-init, or playbook change is required. The new name is
automatically available to Pantheon's VM command completion.
