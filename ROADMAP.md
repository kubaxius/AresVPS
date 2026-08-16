---
tags: ai_generated
---

# VPS Infrastructure TODO

VM-first roadmap for deploying the BearWorks Astro website. Complete each phase and its gate before moving to the next one. Build and deployment mechanics come before Tailscale; production provisioning and DNS migration come only after the complete workflow succeeds against the local VM.

## Completed foundation

- [x] Create `infra/`, `ansible/`, and `.github/workflows/` directories
- [x] Add `.gitignore` entries for OpenTofu state, environment files, Vault passwords, private keys, generated inventories, certificates, VM images, caches, and logs
- [x] Download an Ubuntu Server 24.04 LTS cloud image
- [x] Create a libvirt VM with 2 vCPU, 4 GB RAM, and a 25 GB disk
- [x] Configure NAT networking
- [x] Create cloud-init configuration for the administrative user, SSH key, and Python
- [x] Add commands to create, start, stop, rebuild, and destroy the local VM
- [x] Confirm SSH access to the local VM
- [x] Create the main Ansible playbook
- [x] Add the initial Ansible requirements and configuration
- [x] Install Nginx through Ansible

## Phase 1 — Stabilize the local Ansible foundation

- [ ] Pin the Ubuntu cloud image and record its checksum
- [x] Replace the single inventory with separate `local` and `production` inventories targeting the same `servers` group
- [x] Add shared variables and environment-specific variables
- [ ] Keep production TLS, production DNS, and the production Tailscale identity disabled in the local inventory
- [x] Refactor `site.yml` so roles run in this deterministic order:
  - base system
  - access and SSH
  - firewall
  - Nginx
  - static-site hosting
  - optional Tailscale
- [x] Complete the base-system role:
  - configure hostname, timezone, locale, and time synchronization
  - install required system packages
  - configure unattended security upgrades
  - configure journald limits and log rotation
- [ ] Complete the steady-state access role:
  - manage administrative users, authorized keys, and sudo policy
  - enforce key-only SSH authentication
  - disable SSH password authentication
  - disable direct root SSH login
  - validate SSH configuration before reloading
- [ ] Complete the firewall role while keeping local and production rules configurable
- [ ] Add Ansible Vault configuration and encrypted environment variables
- [ ] Add safe example configuration files:
  - add `.env.example` containing every required variable name with placeholder values
  - add example OpenTofu variable files for local and production inputs
  - confirm examples contain no credentials, private keys, or real infrastructure identifiers
- [ ] Add local commands to configure and test the VM with Ansible
- [ ] Add formatting and validation commands for Ansible and OpenTofu
- [x] Add YAML linting, `ansible-lint`, and Ansible syntax checks
- [ ] Rebuild the VM from scratch and confirm Ansible can connect
- [ ] Run the complete playbook twice and confirm the second run is idempotent
- [ ] Confirm key-based SSH succeeds and password-based and root SSH fail
- [ ] **Gate:** do not proceed until a clean VM can be recreated and configured without manual server changes

## Phase 2 — Prepare the Astro project for self-hosting

- [ ] Pin the Node major version used locally and in CI
- [ ] Add explicit scripts for `astro check` and the production build
- [ ] Replace the Netlify contact form with localized “temporarily unavailable” text and the existing email link
- [ ] Remove the Netlify form handler and form-specific attributes from the production output
- [ ] Keep `/pl/` and `/en/` statically generated through `getStaticPaths()`
- [ ] Keep `/` redirecting to `/pl/`
- [ ] Run `npm ci`, type checking, and the production build from a clean checkout
- [ ] Verify that `dist/` contains at least:
  - `index.html`
  - `pl/index.html`
  - `en/index.html`
  - the expected localized nested pages
  - hashed `/_astro/` assets
- [ ] **Gate:** do not proceed until the site builds reproducibly without Netlify or a running Astro server

## Phase 3 — Build the versioned static-site deployment role

- [ ] Add a reusable `static_site` Ansible role rather than an Astro-specific role
- [ ] Create the restricted `bearworks-deploy` account without sudo access
- [ ] Create the deployment paths:
  - `/srv/www/bearworks/incoming`
  - `/srv/www/bearworks/releases`
  - `/srv/www/bearworks/current`
- [ ] Give the deploy account write access only to the BearWorks deployment tree
- [ ] Give Nginx read access to deployed releases
- [ ] Install a deployment helper that:
  - accepts a release ID, archive, and SHA-256 checksum
  - permits release IDs matching `<semver-tag>-<short-sha>`
  - rejects duplicate releases
  - rejects invalid checksums and unsafe archives
  - extracts into a temporary directory
  - verifies the required Polish and English entrypoints
  - renames the completed directory into `releases/`
  - atomically replaces the `current` symlink
  - retains the five newest completed releases without deleting the active release
- [ ] Install a separate activation command for rolling back to a retained release
- [ ] Test the helper manually against the VM using an artifact built on the workstation
- [ ] **Gate:** do not proceed until an interrupted or invalid upload cannot replace the active release

## Phase 4 — Configure and test Nginx locally

- [ ] Extend the Nginx configuration with a BearWorks virtual host rooted at `/srv/www/bearworks/current`
- [ ] Redirect exactly `/` to `/pl/`
- [ ] Serve Astro directory routes and their `index.html` files
- [ ] Return a real 404 for unknown files and routes
- [ ] Add long-lived immutable caching only for hashed `/_astro/` assets
- [ ] Prevent long-lived caching of HTML and unhashed public files
- [ ] Add the intended security headers
- [ ] Redirect `www.bearworks.pl` to the canonical apex hostname
- [ ] Use a local self-signed certificate through configurable certificate paths to exercise the HTTPS vhost without public DNS
- [ ] Verify `nginx -t` before every configuration reload
- [ ] Test the vhost from the workstation using an `/etc/hosts` entry or explicit `Host` header
- [ ] Verify `/`, both languages, nested routes, static assets, cache headers, canonical-host redirects, HTTPS, and 404 behavior
- [ ] Reboot the VM and confirm Nginx and the active release recover correctly

## Phase 5 — Exercise releases and rollback on the VM

- [ ] Deploy release A and verify its content
- [ ] Deploy release B and verify the symlink switches atomically
- [ ] Roll back to release A without rebuilding it
- [ ] Attempt a duplicate release and confirm it is rejected
- [ ] Attempt an archive with a bad checksum and confirm the active site remains unchanged
- [ ] Attempt an archive missing a locale entrypoint and confirm it is rejected
- [ ] Deploy enough releases to verify retention pruning
- [ ] Run Ansible again and confirm it does not overwrite or reactivate a release
- [ ] Destroy and recreate the VM, then repeat the complete deployment test
- [ ] **Gate:** do not introduce CI or production until the entire release lifecycle passes on a freshly recreated VM

## Phase 6 — Add Tailscale after local deployment works

- [ ] Add a Tailscale Ansible role
- [ ] Store Tailscale enrollment secrets in Ansible Vault
- [ ] Keep Tailscale disabled by default in the local inventory until this phase
- [ ] Enroll the test VM as `tag:bearworks-vm`
- [ ] Create a GitHub workload identity for the `vm-test` environment
- [ ] Tag ephemeral VM-test runners as `tag:bearworks-ci-vm`
- [ ] Add a tailnet grant allowing `tag:bearworks-ci-vm` to reach only `tag:bearworks-vm` on TCP 22
- [ ] Keep the VM’s ordinary SSH key authentication; use Tailscale for private connectivity rather than Unix-account authentication
- [ ] Confirm the workstation can reach the VM over MagicDNS
- [ ] Confirm the CI tag cannot reach unrelated tailnet devices or VM ports
- [ ] Keep the public production SSH policy unchanged during this phase

## Phase 7 — Build and test GitHub Actions against the VM

- [ ] Add a normal CI workflow for pushes and pull requests that runs `npm ci`, `astro check`, and `npm run build` without deployment credentials
- [ ] Add a manually triggered VM deployment workflow using the protected `vm-test` environment
- [ ] Pin every third-party GitHub Action to a full commit SHA
- [ ] Grant the deployment job only `contents: read` and `id-token: write`
- [ ] Join Tailscale using the VM-test workload identity and wait for connectivity to the VM
- [ ] Build and package the selected commit in GitHub Actions
- [ ] Upload the artifact through Tailscale using the dedicated deploy SSH key
- [ ] Invoke the same deployment helper already tested manually
- [ ] Run post-deployment checks through SSH against Nginx on `127.0.0.1` with `Host: bearworks.pl`
- [ ] Confirm a failed verification does not activate or delete the previous release
- [ ] Repeat deployment and rollback tests through GitHub Actions
- [ ] Confirm CI validation jobs do not receive deployment or production credentials
- [ ] **Gate:** do not provision production until GitHub-hosted runners can reliably deploy to the local VM through Tailscale

## Phase 8 — Provision and validate the production VPS

- [ ] Install OpenTofu locally
- [ ] Configure pinned OpenTofu and provider versions
- [ ] Configure the Hetzner Cloud and Netlify providers
- [ ] Define inputs for tokens, location, server type, domain, SSH key, and administrator CIDRs
- [ ] Keep provider credentials in an untracked environment file
- [ ] Configure encrypted remote state, or document and secure the chosen local-state approach
- [ ] Add OpenTofu formatting, initialization-without-backend, and validation checks to CI
- [ ] Complete the production OpenTofu configuration for:
  - one Hetzner server using the chosen Ubuntu 24.04 LTS image and location
  - registered administrative SSH key
  - persistent IPv4 and IPv6 addresses
  - attached Hetzner Cloud Firewall
  - TCP 80 and 443 from the Internet
  - TCP 22 only from administrator break-glass CIDRs, never GitHub runner IP ranges
  - server labels for inventory discovery
  - delete and rebuild protection
  - automatic server backups
- [ ] Run and review an OpenTofu plan before applying
- [ ] Provision the VPS and create the production Ansible inventory from OpenTofu outputs
- [ ] Apply the same Ansible roles already exercised on the VM
- [ ] Enroll the VPS as `tag:bearworks-production`
- [ ] Create a separate GitHub workload identity bound to the protected `production` environment
- [ ] Tag production deployment runners as `tag:bearworks-ci-production`
- [ ] Allow that tag to reach only `tag:bearworks-production` on TCP 22
- [ ] Use a separate production deploy SSH key
- [ ] Deploy a release to the VPS before changing public DNS
- [ ] Validate it over SSH with local Nginx health checks and, where practical, through the public IP with an explicit `Host` header
- [ ] Verify application ports other than intended public HTTP and HTTPS are not publicly reachable
- [ ] Verify break-glass SSH is available only from configured CIDRs
- [ ] Reboot the VPS and confirm the selected release remains active
- [ ] **Gate:** do not change DNS until Ansible, deployment, rollback, reboot recovery, and Tailscale CI access all pass in production

## Phase 9 — Enable tag-only production releases

- [ ] Add a production workflow triggered only by tags matching `vMAJOR.MINOR.PATCH`
- [ ] Verify that the tagged commit is reachable from `master`
- [ ] Refuse to reuse or overwrite an existing release identifier
- [ ] Use the protected `production` GitHub environment and production-only Tailscale identity
- [ ] Build, validate, package, checksum, upload, activate, and health-check the release
- [ ] Ensure CI cannot run infrastructure applies
- [ ] Create the first production tag only after the untagged/manual VPS validation succeeds
- [ ] Document the rollback command and test it before DNS migration

## Phase 10 — Migrate DNS and enable trusted TLS

- [ ] Import or reference the existing Netlify DNS zone without changing live website records
- [ ] Record the current apex and `www` DNS records for rollback
- [ ] Lower their TTL before the migration
- [ ] Confirm the public HTTP vhost and ACME challenge path work on the VPS
- [ ] Optionally validate the VPS through a temporary `vps.<domain>` hostname
- [ ] Point the apex A and AAAA records to the VPS
- [ ] Point `www` to the VPS or the chosen apex alias
- [ ] Wait for authoritative DNS propagation
- [ ] Obtain a Let’s Encrypt certificate covering `bearworks.pl` and `www.bearworks.pl`
- [ ] Replace the local/test certificate paths with the production certificate paths
- [ ] Enable HTTP-to-HTTPS and `www`-to-apex redirects
- [ ] Verify automatic certificate renewal with a dry run
- [ ] Test the site from outside the tailnet on IPv4 and IPv6
- [ ] Verify Polish and English routes, assets, redirects, headers, 404s, and mobile behavior
- [ ] Monitor logs and availability throughout the rollback window
- [ ] Verify the documented DNS rollback procedure
- [ ] Remove obsolete Netlify website records only after the new deployment remains healthy

## Phase 11 — Documentation and post-migration work

- [ ] Document prerequisites and initial workstation setup
- [ ] Document the local VM creation, configuration, testing, and rebuild sequence
- [ ] Document production planning, provisioning, deployment, rollback, and DNS migration
- [ ] Add external uptime monitoring and certificate-expiry alerts
- [ ] Decide how the contact form backend should run
- [ ] Define rate limiting, spam protection, validation, mail delivery, secret management, logging, and privacy requirements before re-enabling the form
- [ ] Complete the Docker Compose foundation before adding a containerized form backend or another service:
  - install Docker Engine and the Docker Compose plugin
  - add the administrative user to the Docker group
  - configure Docker daemon log rotation
  - create `/opt/services`
  - define the directory convention for Compose services
  - bind application ports only to `127.0.0.1`
  - configure services to restart after a reboot
  - create and verify a containerized test service through Nginx
- [ ] Evaluate and select a CMS for Astro websites:
  - define editorial, preview, media, authentication, deployment, licensing, and backup requirements
  - prototype the preferred option with a complete draft-to-publish workflow
- [ ] Define persistent-data locations before adding a stateful service
- [ ] Select an independent off-server backup destination
- [ ] Configure encrypted scheduled backups and retention
- [ ] Add backup-health monitoring
- [ ] Document and test data restoration
- [ ] Add a private-service template for Tailscale-only applications
- [ ] Evaluate Obsidian synchronization and hosting options
- [ ] Evaluate and select privacy-conscious analytics
- [ ] Evaluate remote OpenTofu state before enabling CI deployments or adding collaborators

## Acceptance criteria

- [ ] The VM can be destroyed, recreated, configured, deployed, upgraded, and rolled back without manual server edits
- [ ] The exact artifact activation mechanism tested on the VM is used in production
- [ ] GitHub Actions reaches the VM and VPS through separately scoped Tailscale identities
- [ ] The Astro website runs as static Nginx content with no Astro or Node process on the server
- [ ] Production DNS changes only after the complete deployment path passes on both the VM and the unadvertised VPS
