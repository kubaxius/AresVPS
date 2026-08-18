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

## File and code generation

- Mark content only when the AI creates it from scratch. Do not add an
  `ai_generated` marker when modifying, fixing, refactoring, or completing a
  file, function, or content span originally written by the user.
- For an entirely AI-created file that supports metadata (such as Markdown
  with front matter), add `ai_generated` to its tags.
- For an entirely AI-created file that does not support metadata, add an
  `ai_generated` comment near the top, using the file's native comment syntax.
- In an existing file, wrap every entirely AI-created function or contiguous
  span of content in an `ai_generated` block using the file's native comment
  syntax. Use `ai_generated:start` before the generated content and
  `ai_generated:end` after it.
- Do not add nested or redundant block markers inside a file that is already
  marked as entirely AI-generated.

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
