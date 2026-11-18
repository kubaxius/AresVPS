---
tags: ai_generated
---

# Pantheon Systems roadmap

Pantheon configures a growing private network of servers, not just a website.
Start with the Hetzner VPS (`hermes`) for NetBird-only administration. After a
minimal safe Ansible bootstrap, prioritize a trusted certificate for
`*.pan.bearworks.pl`, a NetBird-only HTTPS reverse proxy, and a small rootless
Podman service on Hermes. Deploy the public BearWorks website after that. Keep
private service URLs stable as backends move between Hermes, Deimos, and future
hosts. File hosting and backups come later. NetBird Cloud provides the control
plane; Hermes does not host its management services.

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
user reports a successful production base apply, successful checks of private
administration and public SSH blocking, and working SSH after a Hermes reboot.
The user has Hetzner console credentials saved and does not want a separate
recovery document; actual console access has not been demonstrated here. The
Nginx site currently serves HTTP, and the production signed-release
publishing path needs end-to-end testing. The former `ansible/site.yml` has
been removed; the CLI and deployment documentation still refer to it. Do not
use those entry points until they target the new, independently tested playbooks.

## Ansible layout to build

- [x] Add `ansible/base.yml` for `base`, `access`, and `firewall` on managed
      hosts. Keep public website and container setup out of the first apply.
- [ ] Add `ansible/web.yml` with **separate plays and roles** for `private_gateways`
      and `public_web`. The private gateway must work without a published
      website release; do not couple proxy changes to `pantheon-srv update`.
- [ ] Add `ansible/podman.yml` for `podman_hosts`. Define services separately
      from the shared Podman host setup so a machine can host only selected pods.
- [x] Put Hermes and hermes-local in the `private_gateways`, `public_web`, and
      `podman_hosts` capability groups in their respective inventories.
- [ ] Keep per-host firewall rules explicit as capability-specific playbooks
      develop; the current `firewall_rules` list is replaced, not merged, when
      inventory overrides it. Keep an optional combined entry point only after
      the individual playbooks are safe and independently testable.

Layout progress: `web.yml` has two plays but references a missing
`private_gateway` role, and its public-site tasks are not yet a separate role.
`podman.yml` references a missing `podman_host` role and does not yet select
individual services. Both inventories now name their respective hosts in the
capability groups. Firewall defaults have no inbound allow rules, with explicit
SSH rules in the production and local inventories.

## Phase 1 — Minimum safe Hermes bootstrap

Goal: a recoverable VPS administered over NetBird, with no public SSH or
unnecessary routing between NetBird peers and the public interface.

- [x] Provision Hermes and connect it to NetBird.
- [x] Prepare a production inventory using Hermes's NetBird IP and cloud-init
      with separate administrative SSH public keys.
- [x] Confirm the Ansible account can connect over NetBird and that the
      production base playbook completes.
- [x] Confirm both administrative accounts can open fresh SSH sessions over
      NetBird; restrict the peer-to-peer SSH policy to intended clients.
- [x] Verify Hetzner's public firewall has no inbound SSH rule.
- [x] Confirm that Hetzner Console can be opened and used as a fallback when
      NetBird is unavailable; credentials are saved, but console access has not
      been tested in this conversation. No separate recovery document requested.
- [x] Remove the obsolete Internet-forwarding rule from Hermes's production
      UFW variables. Keep private peer-to-peer access independent of routing.
- [x] Confirm Hermes no longer distributes an unwanted default route in the
      NetBird dashboard (user-reported dashboard check).
- [x] Apply `ansible/base.yml` to Hermes at this stage, without the public
      website or container playbooks; the user reports success and continued SSH
      access afterward.
- [x] Verify private SSH on `wt0` from fresh sessions for both accounts,
      unsolicited public traffic denial, and SSH access after a Hermes reboot
      (user-reported checks). Keep a working NetBird session and Hetzner
      recovery access for follow-up firewall work.
- [x] **Gate:** Hermes is manageable privately, has no public SSH or unintended
      forwarded traffic, and has a verified console recovery path. Proceed to
      private certificates and proxying without waiting for full rebuild automation.

## Phase 2 — Trusted certificate for private service names

Goal: obtain a renewable, browser-trusted certificate for services that will
never need public web listeners.

- [x] Identify the public DNS provider and DNS-01 automation: the user reports
      switching `bearworks.pl` from Netlify DNS to Cloudflare DNS while keeping
      Regery as registrar. Verify public delegation, DNS records, existing
      Netlify website, and DNSSEC before issuing a certificate. Use Certbot's
      Cloudflare DNS plugin with a zone-scoped API token. Do not publish private
      service A/AAAA records or expose Hermes's private listener for validation.
- [x] Obtain a certificate for `*.pan.bearworks.pl` using DNS-01 (user reports
      certificate ready). Cloudflare credentials are stored in an encrypted
      production host vault and copied to a protected file on Hermes. Add
      `pan.bearworks.pl` separately only if the bare name will be served.
- [ ] Prepare automatic renewal and inspect the renewal path and certificate
      permissions. Wire up the Nginx deploy hook and exercise it once the
      private listener exists. NetBird's private DNS zone alone cannot satisfy
      public ACME validation.
- [ ] **Gate:** the private certificate is issued on Hermes through DNS-01
      without opening a public listener for private services.

## Phase 3 — NetBird-only reverse proxy

Goal: keep `*.pan.bearworks.pl` URLs stable as services move between hosts.

- [ ] Create a NetBird Custom DNS Zone for `pan.bearworks.pl` and distribute it
      to intended peers. Point service names to Hermes's NetBird address; do not
      publish private service A/AAAA records in public DNS.
- [ ] Build the `private_gateway` role separately from website release tasks.
      Bind its Nginx HTTPS listener to Hermes's NetBird address, not a wildcard
      public listener. Plan for that address not existing when Nginx starts;
      do not let private proxy startup take down the public website later.
- [ ] Configure NetBird policies for clients to reach Hermes's private HTTPS
      listener and for Hermes to reach approved backend hosts. Keep backend
      services bound to loopback behind a private host proxy where appropriate.
- [ ] Pilot `search.pan.bearworks.pl` by proxying from Hermes to the existing
      SearXNG Apache vhost on Deimos over NetBird. Review host headers, HTTPS
      forwarding, SearXNG's base URL, and rollback; keep the old name working
      until the new one is verified.
- [ ] Validate Nginx before reload; test certificate renewal and its deploy
      hook. From another peer, verify DNS, TLS, search, and access policies.
      From the public Internet, verify that private hostnames cannot reach a
      private backend even with an explicit Host header and TLS SNI. Reboot and
      test proxy readiness again.
- [ ] **Gate:** the private URL works without exposing the backend publicly or
      depending on which machine currently hosts the container.

## Phase 4 — First rootless Podman service on Hermes

Goal: move SearXNG behind the same private URL before deploying the public site.

- [ ] Check Hermes's CPU, RAM, disk, bandwidth, and backup capacity. Add a
      `podman_hosts` role for the rootless Podman and systemd/Quadlet foundation;
      keep individual services selectable per host.
- [ ] Back up SearXNG's config and secret separately from its disposable cache.
      Start a Hermes instance on a loopback-only port with a supervised service
      and a documented secret/state location. Do not expose the container port.
- [ ] Switch only Hermes's proxy upstream from Deimos to localhost; keep
      `search.pan.bearworks.pl` and its certificate unchanged. Preserve the old
      Deimos service until searches, private access, rollback, and reboot
      recovery work on Hermes.
- [ ] Check resource usage and confirm the container is not reachable through
      Hermes's public interface. Do not move OpenClaw until its authentication,
      state backups, proxy headers, WebSockets, and host risk have been reviewed.
- [ ] Keep source definitions and secrets in their appropriate repositories;
      `~/services` is a separate repo, and its ignored live data is not a backup.
- [ ] **Gate:** Hermes serves a private Podman workload through the stable
      HTTPS proxy without interfering with private administration.

## Phase 5 — Public BearWorks website on Hermes

Goal: serve `bearworks.pl` and `www.bearworks.pl` publicly without exposing
private apps or administrative services.

- [ ] Confirm the separate Astro website repository reproducibly builds the
      required Polish and English static pages and publishes compatible signed
      GitHub Release archives. Keep CI free of VPS and NetBird credentials.
- [ ] Exercise signed download, rejection of invalid releases, activation,
      rollback, retention, and reboot recovery on a clean VM and the VPS.
- [ ] Finish the BearWorks Nginx vhost: directory routes and real 404s,
      appropriate asset caching and headers, apex/`www` redirects, and
      configuration validation before reload.
- [ ] Open public TCP 80/443 in both the Hetzner Cloud Firewall and UFW, only
      for the website. Configure separate trusted HTTPS for the apex and `www`,
      automatic renewal, and HTTP-to-HTTPS redirects. Leave public SSH closed.
- [ ] Test the site by public IP/explicit hostname before DNS migration.
      Record current DNS and rollback steps, then switch A/AAAA and `www`.
- [ ] Verify the website externally over IPv4/IPv6, private HTTPS and SSH over
      NetBird, release rollback, certificate renewal, and reboot recovery.
      Public website availability must not depend on NetBird being connected.
- [ ] **Gate:** the public website works without exposing the private gateway,
      and no Astro/Node runtime is required for the static site.

## Phase 6 — Reproducibility, more hosts, and movable services

Goal: reproduce Hermes's working configuration and add hosts without changing
client-facing URLs or certificates. Do not hold up the private proxy pilot for
infrastructure automation beyond its safe minimum bootstrap.

- [ ] Document Hetzner resources, IPs, firewall, NetBird enrollment, key
      recovery, inventory, and backup choices; keep credentials out of Git.
- [ ] Repeat Ansible runs for idempotence, test a clean-server bootstrap,
      verify NetBird and SSH after reboot, and exercise the recovery procedure.
- [ ] If adopting OpenTofu, pin the Hetzner provider, secure state and API
      credentials, and review plans before applying. Manual provisioning is
      acceptable initially; DNS provider automation outside DNS-01 is optional.
- [ ] Choose where the second server runs, what resources it needs, and how it
      is reached and recovered over NetBird.
- [ ] Extend inventories and host/group variables so shared base/access rules
      are reusable while website, gateway, and Podman roles target only the
      appropriate hosts.
- [ ] Establish a Podman image/service pattern: approved image sources and
      versions, least-privilege users, volumes, systemd/Quadlet startup,
      health checks, logging, upgrades, and rollback.
- [ ] Keep remote backends behind NetBird-only listeners; on moving a service,
      change its Hermes proxy upstream and peer policy, not its client-facing
      DNS record or certificate.
- [ ] Rebuild and reboot the second host to verify services recover without
      disrupting the website or private gateway.

## Phase 7 — File hosting, backups, and further hosts

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

Do not delay the initial private gateway or website for a CMS, contact-form
backend, analytics, file hosting, OpenClaw migration, a second server, or
CI-driven infrastructure applies. DNS-01 automation is needed for trusted
private HTTPS; fully automating the rest of public DNS is optional.
