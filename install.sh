#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

uv tool install --editable "$project_dir" --force

echo
echo "Installed pantheon-systems-cli."
echo "Run this once to enable shell completion:"
echo "  pantheon --install-completion"