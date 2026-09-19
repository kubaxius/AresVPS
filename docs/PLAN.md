# Replace the Custom Release Engine with `systemd-sysupdate`

## Summary

Use Ubuntu 24.04’s `systemd-sysupdate` to verify, extract, retain, and stage static-site releases. Preserve the existing Tailscale/SSH upload path by exposing the upload directory through a localhost-only Nginx feed. A small typed Python controller will coordinate locking, entrypoint checks, health checks, atomic promotion, and rollback; Polkit-authorized systemd units will be the privileged interface.

## Implementation Changes

### Release feed and artifact contract

- Install `systemd-container`, which provides `systemd-sysupdate` on Ubuntu 24.04, plus `curl`, `gnupg`, and Polkit support.
- Continue building one deterministic archive named `<site>-<release_id>.tar.gz`, with `<release_id>` remaining `vMAJOR.MINOR.PATCH-<12-char-sha>`.
- Replace the custom JSON/checksum validation protocol with:
  - the release archive;
  - standard `SHA256SUMS`;
  - detached `SHA256SUMS.gpg`.
- Keep `.release-manifest.json` inside the archive for provenance, but no longer use custom server code to validate it.
- Generate a dedicated CI GPG signing key:
  - store its private key and passphrase in protected GitHub environment secrets;
  - commit or inventory-manage only its public key;
  - build `/etc/systemd/import-pubring.gpg` through Ansible;
  - support multiple public keys during rotation.
- Upload feed files through the existing restricted SSH account into the site’s `incoming` directory, using temporary names followed by rename. Start deployment only after the archive, checksum manifest, and signature are all present.

### Ansible and systemd

- Replace the shared archive-processing module and generated launcher with:
  - a `sysupdate.d` definition per site;
  - a root-owned controller configuration file;
  - one shared, statically typed Python controller;
  - deploy and rollback systemd service templates;
  - a per-site Polkit authorization rule.
- Configure `systemd-sysupdate` with:
  - `Source Type=url-tar`;
  - a localhost HTTP feed served from the site’s `incoming` directory;
  - `MatchPattern=<site>-@v.tar.gz`;
  - `Target Type=directory`;
  - target pattern `releases/@v`;
  - `CurrentSymlink=staged`;
  - `InstancesMax={{ static_site_release_retention + 1 }}`;
  - signature verification enabled.
- Add a localhost-only Nginx feed listener on a configurable, per-site port. It must never bind to a public or Tailscale address.
- Add a second localhost-only Nginx server rooted at `staged`, mirroring production routing sufficiently to test required locale pages before promotion.
- Keep production Nginx rooted at `current`.
- Replace sudoers access with Polkit rules allowing the deploy account only to start:
  - `static-site-deploy-<site>@<valid-release-id>.service`;
  - `static-site-rollback-<site>@<valid-release-id>.service`.
- Reject every other systemd operation, unit name, verb, user, and malformed release ID.

### Small controller and lifecycle

- Install a shared controller at `/usr/local/libexec/static-site-release-control`; it accepts a root-owned config path plus `deploy RELEASE_ID` or `rollback RELEASE_ID`.
- Keep the controller narrowly scoped and fully typed. It must not parse archives, verify checksums/signatures, manage retention, or extract files.
- For deployment:
  1. Acquire a per-site `flock`.
  2. Validate the requested release ID.
  3. Initialize `staged` from a valid existing `current` during migration if needed.
  4. Run `systemd-sysupdate update RELEASE_ID` with the site’s fixed definitions directory.
  5. Require `staged` to point directly to `releases/<release_id>`.
  6. Verify configured entrypoint files.
  7. Run health checks through the staging-only Nginx listener.
  8. Atomically replace `current` with a relative symlink to the staged release.
  9. Run production localhost health checks.
  10. Restore both `current` and `staged` if post-promotion checks fail.
- For rollback:
  1. Acquire the same lock.
  2. Validate that the requested retained release exists directly under `releases`.
  3. Point `staged` at it and run entrypoint/staging health checks.
  4. Atomically promote it to `current`.
  5. Restore both symlinks if production health fails.
- Log controller and sysupdate output to the system journal; return service failure on any rejected signature, invalid release, missing entrypoint, or failed health check.
- Preserve read-only `current` and `list` inspection through the controller or `systemd-sysupdate list` without granting deployment privileges.

### Role variables and migration

- Retain reusable variables for site identity, root, deploy account, required entrypoints, retention, and health checks.
- Add variables for feed port, staging health port, signing public keys, sysupdate definitions path, unit-name prefix, and controller configuration path.
- Remove obsolete manifest-schema, archive-size/member-limit, helper-filename, launcher, and sudoers variables because sysupdate owns those responsibilities.
- On rollout:
  1. Provision sysupdate, feed, staging Nginx, controller, units, keyring, and Polkit alongside the existing `current` release.
  2. Initialize `staged` from `current`.
  3. deploy and roll back a test release on `ares-local`;
  4. only then remove the old Python archive engine, launcher, sudoers entry, and their tests.
- Rewrite the workshop’s helper, manual laboratory, VM deployment, production deployment, rollback, troubleshooting, and acceptance sections around the signed local feed and systemd units.
- Keep GitHub Release publication after successful production health checks; it receives the same archive deployed by sysupdate.

## Test Plan

- Unit-test the controller’s configuration typing, release-ID validation, locking, symlink-boundary checks, entrypoint checks, staged promotion, rollback, and restoration after health failure.
- Test rendered sysupdate definitions, systemd units, Polkit rules, controller config, and both Nginx listeners with two independent site instances.
- Use `systemd-analyze verify`, `nginx -t`, Ansible syntax checking, `ansible-lint`, BasedPyright strict mode, and the complete Python test suite.
- On `ares-local`, verify:
  - valid signed deployment and identical rerun;
  - corrupted archive, checksum mismatch, unknown key, and bad signature rejection;
  - partial feed upload cannot deploy;
  - missing entrypoint and failed staging health never change production;
  - failed post-promotion health restores both symlinks;
  - rollback to a retained release;
  - concurrent deploy/rollback serialization;
  - retention preserves the active rollback target;
  - feed and staging ports are reachable only from localhost;
  - the deploy account cannot start unrelated units or obtain general root access;
  - a second Ansible run is idempotent.

## Assumptions

- “systemd-update” means `systemd-sysupdate`.
- The deployment hosts remain Ubuntu 24.04 and use systemd 255’s `.conf` transfer-definition format.
- SSH/Tailscale remains the transport because it avoids introducing external artifact hosting.
- One dedicated artifact-signing key is acceptable; separate SSH credentials still isolate VM and production upload access.
- The small controller is retained only for coordination that sysupdate does not provide: cross-step locking, application-specific validation, health-gated promotion, and explicit rollback.
- The website repository is outside this workspace, so this repository implements host support and updates the workshop; workflow changes are implemented in the website repository separately.
