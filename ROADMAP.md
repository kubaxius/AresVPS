---
tags: ai_generated
---

# Pantheon Systems roadmap

Pantheon is the configuration for a growing private network of servers, not just
a website deployment. Start with one Hetzner VPS (`hermes`) acting as a NetBird
internet exit node and, later, hosting the public BearWorks website. Add a
separate server for private Podman services after the first VPS is working.
File hosting and backups come later. NetBird Cloud provides the control plane;
this project does not need to host NetBird's management services.

Each phase should leave a useful, recoverable system. Later services are not
prerequisites for the first VPS. Keep server configuration in Ansible and
secrets outside plaintext inventory and Git. Do not run production changes
automatically from GitHub Actions.

## Existing foundation

- [x] Local Ubuntu 24.04 VM, cloud-init users, SSH access, and VM lifecycle commands
- [x] Local and production Ansible inventories and base, access, firewall, and Nginx roles
- [x] Static-site configuration, signed-release download/verification, and `pantheon-srv` activation tooling
- [x] BearWorks site definition and local VM configuration path

These are implementation pieces, **not** proof of production readiness. The
production inventory still has a placeholder address; its SSH keys and firewall
policy need production-specific values. The Nginx site currently serves HTTP,
and the production signed-release publishing path needs end-to-end testing.
The full `ansible/site.yml` also attempts a site update on every apply, so use
a separate, limited bootstrap path until a compatible signed release exists.

## Phase 1 — First VPS: NetBird exit node and private administration

Goal: an independently useful, recoverable Hetzner VPS that provides internet
egress to selected NetBird peers. Website deployment comes later.

- [ ] Decide the initial Hetzner location, Ubuntu 24.04 x86-64 server size,
      public IPv4/IPv6, backup option, and how the server will be rebuilt.
- [ ] Prepare distinct production SSH keys and production cloud-init for the
      `ansible` and `jbear` users; do not reuse local-VM keys or its QEMU setup.
- [ ] Prepare a NetBird peer group, narrowly scoped administration policy, and
      one-off, non-ephemeral setup key. Keep enrollment credentials out of Git,
      cloud-init/user data, and the website release pipeline.
- [ ] Create a Hetzner Cloud Firewall with outbound traffic permitted and only
      temporary, key-only public SSH access for bootstrap. Record the recovery
      procedure using Hetzner Console/Rescue if NetBird becomes unavailable.
- [x] Provision Hermes and connect it to NetBird.
- [ ] Verify access to both administrative accounts over NetBird and confirm
      website DNS has not been changed for the VPS.
- [ ] Set the production Ansible inventory to the VPS's NetBird address and
      configure production SSH keys and host firewall rules. Apply only the
      base/access/firewall bootstrap roles at this stage.
- [ ] Test UFW alongside NetBird on the `wt0` interface. Permit private SSH
      without exposing port 22 publicly; verify NetBird access policies still
      restrict which peers can connect. Do not assume the local-VM SSH rule
      (`192.168.122.0/24`) is suitable for production.
- [ ] Remove the temporary public SSH rule **after** a new NetBird SSH session
      and Ansible connection both work. Retest access after a reboot.
- [x] Confirm a NetBird client reaches the Internet through Hermes as an exit node.
- [ ] Verify exit-node access is limited to the intended group; check DNS,
      IPv4/IPv6 behavior, masquerading, and routing after reboot. Check the
      interactions between NetBird's routing rules and UFW's default
      routed-traffic policy.
- [ ] **Gate:** the VPS is usable as an exit node, is manageable privately,
      exposes no public SSH, and can be recovered if NetBird fails.

## Phase 2 — Reproducible production deployment

Goal: recreate the first VPS and its network role without undocumented manual
server changes. Manual Hetzner provisioning is acceptable initially; OpenTofu
is an option if it materially improves repeatability.

- [ ] Document the Hetzner resources, IPs, firewall, enrollment, SSH key
      recovery, inventory, and backup choices; keep credentials out of the repo.
- [ ] Automate or document the NetBird client installation and safe enrollment
      path. Keep its administration and exit-node policies separate from website
      configuration.
- [ ] Split first-boot configuration from full `ansible/site.yml`, so a missing
      website release cannot block access and network setup.
- [ ] Test a new-server bootstrap, repeat Ansible for idempotence, and verify
      NetBird and SSH reconnect after reboot. Exercise the recovery procedure.
- [ ] If adopting OpenTofu, pin the Hetzner provider, secure state and API
      credentials, and review plans before applying; DNS provider automation
      is not required for the first deployment.
- [ ] **Gate:** the first VPS's exit-node and administration setup can be
      reproduced safely before adding the public website.

## Phase 3 — Public BearWorks website on the first VPS

Goal: add one public static website to the existing exit node without making
administrative or NetBird services public.

- [ ] Confirm the separate Astro website repository reproducibly builds the
      required Polish and English static pages and publishes compatible signed
      GitHub Release archives. Keep CI free of VPS and NetBird credentials.
- [ ] Exercise signed download, rejection of invalid releases, activation,
      rollback, retention, and reboot recovery on a clean VM and the VPS.
- [ ] Finish the BearWorks Nginx vhost: directory routes and real 404s,
      appropriate asset caching and headers, apex/`www` redirects, and
      configuration validation before reload.
- [ ] Open public TCP 80/443 in both the Hetzner Cloud Firewall and UFW.
      Configure trusted HTTPS for the apex and `www`, automatic renewal, and
      HTTP-to-HTTPS redirects. Leave public SSH closed.
- [ ] Test the site by public IP/explicit hostname before DNS migration.
      Record current DNS and rollback steps, then switch A/AAAA and `www`.
- [ ] Verify the website externally over IPv4/IPv6, the exit node and private
      SSH from NetBird, release rollback, certificate renewal, and reboot
      recovery. Do not make release updates depend on NetBird availability.
- [ ] **Gate:** the VPS has exactly two intended workloads: NetBird exit node
      and public static website. No Astro/Node runtime or other public app
      ports are required on the server.

## Phase 4 — Second server: private Podman hosting

Goal: add another Ansible-managed host for private services, without turning
the first VPS into a general-purpose application host.

- [ ] Choose where the second server runs, what resources it needs, and how it
      is reached and recovered over NetBird.
- [ ] Extend inventories and host/group variables so shared base/access rules
      are reusable while website, exit-node, and Podman roles target only the
      appropriate hosts.
- [ ] Establish a Podman image/service pattern: approved image sources and
      versions, least-privilege users, volumes, systemd/Quadlet startup,
      health checks, logging, upgrades, and rollback.
- [ ] Bind private services only to appropriate private interfaces or
      localhost behind a NetBird-accessible proxy; verify they cannot be
      reached from the public internet.
- [ ] Rebuild and reboot the second host to verify services recover without
      disrupting the website or exit node.

## Phase 5 — File hosting, backups, and further hosts

- [ ] Define file access, capacity, privacy, and persistence requirements
      before selecting a file-hosting service or adding it to Podman.
- [ ] Select an independent off-server backup destination; implement encrypted
      scheduled backups, retention, and backup-health alerts.
- [ ] Test restoring both service configuration and actual user data to a
      replacement host. Hetzner server backups alone are not the off-server
      data-backup plan.
- [ ] Add future servers and private services as separate Ansible inventory
      hosts/groups with explicit NetBird access policies and recovery steps.

## Not on the critical path

Do not delay the first VPS for a CMS, contact-form backend, analytics, private
file hosting, Podman, automated DNS management, or CI-driven infrastructure
applies. This plan replaces the previous Tailscale and Docker Compose work with
NetBird and a later Podman-based private-service host.
