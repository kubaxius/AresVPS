#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"

source "$SCRIPT_DIR/config.sh"


cd "$PROJECT_DIR" || exit

mkdir -p "$VM_DIR_NAME"/images

cd "$VM_DIR_NAME"/images || exit

curl --fail --location --remote-name \
"https://cloud-images.ubuntu.com/releases/noble/release/ubuntu-24.04-server-cloudimg-amd64.img"

curl --fail --location --remote-name \
"https://cloud-images.ubuntu.com/releases/noble/release/SHA256SUMS"

sha256sum --check SHA256SUMS \
  --ignore-missing