---
tags: ai_generated
---

# Project Structure

The repository separates machine provisioning from server configuration:

- **OpenTofu provisions machines:** either a local libvirt VM or the production Hetzner server.
- **Ansible configures the resulting machine:** the same roles and main playbook are used in both environments.
- Local-only artifacts, such as downloaded Ubuntu cloud images and VM disks, remain outside Git.

## Proposed repository layout

```text
VPS/
├── README.md
├── TODO.md
├── Makefile
├── .env.example
├── .gitignore
│
├── infra/
│   ├── local/
│   │   ├── versions.tf
│   │   ├── providers.tf
│   │   ├── variables.tf
│   │   ├── terraform.tfvars.example
│   │   ├── main.tf
│   │   ├── outputs.tf
│   │   └── cloud-init.yaml.tftpl
│   │
│   └── production/
│       ├── versions.tf
│       ├── providers.tf
│       ├── variables.tf
│       ├── terraform.tfvars.example
│       ├── server.tf
│       ├── firewall.tf
│       ├── dns.tf
│       └── outputs.tf
│
├── ansible/
│   ├── ansible.cfg
│   ├── requirements.yml
│   ├── site.yml
│   ├── inventories/
│   │   ├── local/
│   │   │   ├── hosts.yml
│   │   │   └── group_vars/
│   │   │       └── all.yml
│   │   └── production/
│   │       ├── hosts.yml
│   │       └── group_vars/
│   │           ├── all.yml
│   │           └── vault.yml
│   └── roles/
│       ├── base/
│       ├── access/
│       ├── firewall/
│       ├── tailscale/
│       ├── docker/
│       └── nginx/
│
├── scripts/
│   └── download-cloud-image
│
├── images/                 # Ignored; downloaded cloud images
│
└── .github/
    └── workflows/
        └── validate.yml
```

The provisioning and configuration flow is:

```text
infra/local ────────┐
                    ├── machine accessible by SSH ──→ ansible/site.yml
infra/production ───┘
```

## Local and production responsibilities

`infra/local/` contains only what is needed to create the test environment:

- download or reference the pinned cloud image;
- create the libvirt disk and VM;
- allocate CPU and memory;
- configure NAT networking;
- provide minimal cloud-init bootstrap configuration;
- output the VM's SSH address.

`infra/production/` contains only provider infrastructure:

- Hetzner server;
- Hetzner firewall;
- SSH key registration;
- public addresses;
- Netlify DNS.

Neither environment should contain the final server configuration. That belongs in the shared `ansible/roles/` directory. For example:

```text
infra/local/main.tf             ← creates an empty Ubuntu VM
infra/production/server.tf      ← creates an empty Ubuntu VPS
ansible/roles/docker/           ← installs Docker on either one
```

## Keep cloud-init small

Cloud-init should provide only what Ansible needs to connect:

- an administrative user;
- an authorized SSH public key;
- Python;
- optionally, the hostname.

After this initial bootstrap, Ansible owns the machine configuration. Configuring the entire server through cloud-init would duplicate Ansible's responsibilities and could cause the local and production environments to diverge.

## Store the cloud-image pin, not the image

The download script and pinning information belong in Git:

```text
scripts/download-cloud-image
infra/local/variables.tf
```

The downloaded image does not:

```text
images/
└── noble-server-cloudimg-amd64.img
```

The download script can define the approved source and checksum:

```bash
IMAGE_URL="https://cloud-images.ubuntu.com/..."
IMAGE_SHA256="the-approved-exact-checksum"
IMAGE_PATH="images/ubuntu-24.04-amd64.qcow2"
```

It should download the image only when it is absent and reject any file whose checksum does not match. The URL and checksum are versioned in Git, while the large image remains ignored.

The blanket `vm/` ignore rule should be removed, and the `vm/` directory is probably unnecessary. Local VM definitions are source code and belong in `infra/local/`. Only generated disks, images, OpenTofu state, and generated cloud-init artifacts should be ignored.

## Use one playbook with environment-specific inventories

Both inventories target the same logical group:

```yaml
# ansible/inventories/local/hosts.yml
all:
  children:
    servers:
      hosts:
        local-vps:
          ansible_host: 192.168.122.100
```

```yaml
# ansible/inventories/production/hosts.yml
all:
  children:
    servers:
      hosts:
        production-vps:
          ansible_host: example-public-address
```

The main playbook remains environment-independent:

```yaml
- name: Configure VPS
  hosts: servers
  become: true
  roles:
    - base
    - access
    - firewall
    - docker
    - nginx
    - role: tailscale
      when: tailscale_enabled
```

The local inventory can disable production-only behavior:

```yaml
tailscale_enabled: false
configure_production_tls: false
```

The production inventory can enable it. This creates one final server configuration that is exercised first against a replaceable local VM and then applied to the real VPS.
