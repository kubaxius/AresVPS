# VPS Infrastructure TODO

## Repository setup

- [ ] Create `infra/`, `ansible/`, and `.github/workflows/` directories
- [ ] Add `.gitignore` entries for OpenTofu state, `.env` files, Vault passwords, private keys, generated inventories, and certificates
- [ ] Add example environment and variable files without secrets
- [ ] Add local commands for creating, configuring, testing, and destroying the environment
- [ ] Document the local and production workflows

## Local Ubuntu VM

- [ ] Download and pin an Ubuntu Server 24.04 LTS cloud image
- [ ] Create a libvirt VM with 2 vCPU, 4 GB RAM, and a 25 GB disk
- [ ] Configure NAT networking
- [ ] Create cloud-init configuration for the administrative user, SSH key, and Python
- [ ] Add commands to create, start, stop, rebuild, and destroy the VM
- [ ] Confirm SSH access to the VM

## Ansible structure

- [ ] Add local and production inventories
- [ ] Add shared group variables
- [ ] Create the main server playbook
- [ ] Create roles for the base system, access, firewall, Tailscale, Docker, and Nginx
- [ ] Add required Ansible collections and roles to a requirements file
- [ ] Add an Ansible configuration file
- [ ] Add Ansible Vault configuration and encrypted production variables

## Base system and hardening

- [ ] Configure hostname, timezone, locale, and time synchronization
- [ ] Install required system packages
- [ ] Configure unattended security upgrades
- [ ] Configure journald limits and log rotation
- [ ] Create the administrative user and sudo configuration
- [ ] Configure key-only SSH authentication
- [ ] Disable SSH password authentication
- [ ] Disable direct root SSH login
- [ ] Configure the host firewall
- [ ] Allow public HTTP and HTTPS traffic
- [ ] Restrict public SSH to configured administrator CIDRs

## Tailscale

- [ ] Add the Tailscale repository and package
- [ ] Store the Tailscale enrollment secret in Ansible Vault
- [ ] Enable Tailscale in the production inventory
- [ ] Keep Tailscale disabled by default in the local inventory
- [ ] Configure SSH administration over Tailscale
- [ ] Verify private connectivity from an authorized device

## Docker Compose

- [ ] Install Docker Engine and the Docker Compose plugin
- [ ] Add the administrative user to the Docker group
- [ ] Configure Docker daemon log rotation
- [ ] Create `/opt/services`
- [ ] Define the directory convention for individual Compose services
- [ ] Create a containerized test service
- [ ] Bind application ports only to `127.0.0.1`
- [ ] Configure services to restart after a reboot

## Nginx and TLS

- [ ] Install Nginx on the host
- [ ] Create a default static placeholder site
- [ ] Add a reverse-proxy configuration for the test service
- [ ] Add reusable public virtual-host configuration
- [ ] Add reusable private virtual-host configuration
- [ ] Configure security headers
- [ ] Install Certbot and its Nginx integration
- [ ] Configure production certificates for the temporary VPS hostname
- [ ] Configure HTTP-to-HTTPS redirects in production
- [ ] Verify automatic certificate renewal

## OpenTofu

- [ ] Install OpenTofu locally
- [ ] Configure pinned OpenTofu and provider versions
- [ ] Configure the Hetzner Cloud provider
- [ ] Configure the Netlify provider
- [ ] Define input variables for tokens, location, server type, domain, SSH key, and administrator CIDRs
- [ ] Keep provider credentials in an untracked environment file
- [ ] Configure encrypted local state
- [ ] Exclude state and plan files from Git
- [ ] Add outputs for public addresses and hostnames
- [ ] Connect OpenTofu outputs to the production Ansible inventory

## Hetzner resources

- [ ] Provision one CX23 server in `nbg1`
- [ ] Use the Ubuntu Server 24.04 LTS image
- [ ] Register the administrative SSH public key
- [ ] Provision persistent IPv4 and IPv6 addresses
- [ ] Create and attach a Hetzner Cloud Firewall
- [ ] Allow TCP 80 and 443 from the Internet
- [ ] Allow TCP 22 only from configured administrator CIDRs
- [ ] Add server labels for Ansible inventory discovery
- [ ] Enable delete and rebuild protection
- [ ] Enable automatic Hetzner server backups
- [ ] Run and review an OpenTofu plan before applying

## Netlify DNS migration

- [ ] Import or reference the existing Netlify DNS zone
- [ ] Preserve the current Netlify website records during VPS setup
- [ ] Create A and AAAA records for `vps.<domain>`
- [ ] Validate the VPS through the temporary hostname
- [ ] Record the existing apex and `www` values for rollback
- [ ] Lower DNS TTL before the production migration
- [ ] Move the apex and `www` records to the VPS
- [ ] Validate DNS and HTTPS after the migration
- [ ] Remove obsolete Netlify website records after the rollback window

## GitHub Actions validation

- [ ] Add YAML linting
- [ ] Add `ansible-lint`
- [ ] Add Ansible syntax checks
- [ ] Add OpenTofu formatting checks
- [ ] Add OpenTofu initialization without a backend
- [ ] Add OpenTofu validation
- [ ] Pin workflow action versions
- [ ] Confirm CI does not receive production credentials
- [ ] Confirm CI cannot run infrastructure applies or deployments

## Local acceptance tests

- [ ] Destroy and recreate the local VM from the repository
- [ ] Run the complete Ansible playbook successfully
- [ ] Run Ansible a second time and confirm idempotence
- [ ] Validate the Nginx configuration
- [ ] Verify the static placeholder site
- [ ] Verify the containerized service through Nginx
- [ ] Confirm the container port is not externally reachable
- [ ] Confirm key-based SSH access works
- [ ] Confirm password-based and root SSH access fail
- [ ] Reboot the VM and verify all services recover

## Production acceptance tests

- [ ] Verify the Hetzner firewall rules
- [ ] Verify public HTTP redirects to HTTPS
- [ ] Verify valid TLS certificates
- [ ] Verify the portfolio hostname responds through Nginx
- [ ] Verify application ports are not publicly reachable
- [ ] Verify SSH over Tailscale
- [ ] Verify break-glass SSH only from configured CIDRs
- [ ] Reboot the VPS and verify all services recover
- [ ] Verify the Netlify DNS rollback procedure
- [ ] Run the documented rebuild procedure

## Future backups and stateful services

- [ ] Define persistent-data locations before adding a stateful service
- [ ] Select an independent off-server backup destination
- [ ] Configure encrypted scheduled data backups
- [ ] Configure backup retention
- [ ] Add backup health monitoring
- [ ] Document and test data restoration
- [ ] Add a private-service template for Tailscale-only applications
- [ ] Evaluate Obsidian synchronization and hosting options
- [ ] Add monitoring and external uptime checks
- [ ] Evaluate remote OpenTofu state before enabling CI deployments or adding collaborators
