#!/usr/bin/env bash

set -Eeuo pipefail

# SUDO CHECK
if [[ $EUID -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

# PULL GLOBAL CONFIG #
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"
source "$SCRIPT_DIR/config.sh"

# DEFINE VARIABLES #
BASE_IMAGE="${VM_DIR}/images/ubuntu-24.04-server-cloudimg-amd64.img"
VM_DISK="/var/lib/libvirt/images/${VM_NAME}.qcow2"
USER_DATA="${PROJECT_DIR}/infra/local/cloud-init/user-data"
META_DATA="${PROJECT_DIR}/infra/local/cloud-init/meta-data"

# SANITY CHECKS #

# If base image exists
[[ -f "$BASE_IMAGE" ]] || {
  echo "Base image not found: $BASE_IMAGE" >&2
  exit 1
}

# If cloud-init files exist
[[ -f "$USER_DATA" && -f "$META_DATA" ]] || {
  echo "Cloud-init files are missing." >&2
  exit 1
}

# Check if VM already exists
if virsh --connect qemu:///system dominfo "$VM_NAME" >/dev/null 2>&1; then
  echo "VM already exists: $VM_NAME" >&2
  exit 1
fi

# Check if VM disk already exists
if [[ -e "$VM_DISK" ]]; then
  echo "VM disk already exists: $VM_DISK" >&2
  exit 1
fi

# VM NETWORK SETUP #

virsh --connect qemu:///system net-info default >/dev/null || {
  echo "The libvirt 'default' network does not exist." >&2
  exit 1
}

if [[ "$(virsh --connect qemu:///system net-info default |
  awk '$1 == "Active:" { print $2 }')" != "yes" ]]; then
  virsh --connect qemu:///system net-start default
fi

virsh --connect qemu:///system net-autostart default


cd "$VM_DIR" || exit

# IMAGE #

# copy the image to proper directory
qemu-img convert -f qcow2 -O qcow2 "$BASE_IMAGE" "$VM_DISK"
# resize the copied image
qemu-img resize "$VM_DISK" 25G

# --import tells no installer needed, Ubuntu is already in the image
virt-install \
  --connect qemu:///system \
  --name "$VM_NAME" \
  --memory 4096 \
  --vcpus 2 \
  --cpu host \
  --osinfo ubuntu24.04 \
  --import \
  --disk path="$VM_DISK",format=qcow2,bus=virtio \
  --network network=default,model=virtio \
  --graphics spice \
  --cloud-init "user-data=${USER_DATA},meta-data=${META_DATA}" \
  --noautoconsole
