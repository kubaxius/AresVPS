# Repository instructions

## Scope

These instructions apply to the entire repository.

## Project overview

- This repository manages VPS infrastructure using Ansible.
- Python CLI code lives in `pantheon_systems_cli/`.
- Ansible roles live in `ansible/roles/`.
- Tests live in `tests/`.

## Working rules

- Read the relevant implementation and tests before editing.
- Preserve existing behavior unless the task explicitly requests a change.
- Keep changes narrowly scoped.
- Do not modify encrypted vault data.
- Do not commit, push, deploy, or destroy infrastructure unless explicitly requested.
- Never run destructive infrastructure commands merely to verify a change.
- Do not add dependencies without explaining why they are necessary.

## AI attribution

- Use Git AI to track new AI contributions; ensure its agent integration is
  installed and active before working (`git ai install-hooks`, then restart the
  agent). Check working attribution with `git ai status`.
- Do not add new inline AI attribution comments or metadata tags. Existing
  `ai_generated` comments and tags are legacy markers; leave them in place.
  They do not create retroactive Git AI attribution for previously committed
  content.

## Verification

- Run the smallest relevant test first.
- Run the complete test suite after changes that affect shared behavior.
- For Ansible changes, run syntax validation without contacting production hosts.
- If verification cannot be performed, state exactly what remains unverified.

## Code conventions

- Follow the style of surrounding code.
- Add or update tests for behavior changes.
- Avoid unrelated refactoring.
- Keep infrastructure defaults separate from secrets and host-specific values.

## Documentation

- Update `README.md` or `docs/` when commands, configuration, or behavior change.
