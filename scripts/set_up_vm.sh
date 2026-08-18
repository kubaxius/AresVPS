#!/usr/bin/env bash

set -Eeuo pipefail

# SUDO CHECK
if [[ $EUID -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 <vm-name> <network> <mac-address> <ip-address>" >&2
  exit 2
fi

# DEFINE VARIABLES #
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." >/dev/null && pwd)"
IMAGE_DIR="${PROJECT_DIR}/vm"

VM_NAME="$1"
VM_NETWORK="$2"
VM_MAC="$3"
VM_IP="$4"
BASE_IMAGE="${IMAGE_DIR}/ubuntu-24.04-server-cloudimg-amd64.img"
VM_DISK="/var/lib/libvirt/images/${VM_NAME}.qcow2"
USER_DATA="${PROJECT_DIR}/infra/local/cloud-init/user-data"
META_DATA="$(mktemp --tmpdir pantheon-cloud-init.XXXXXX)"
trap 'rm -f -- "$META_DATA"' EXIT

printf 'instance-id: %s-001\nlocal-hostname: %s\n' \
  "$VM_NAME" "$VM_NAME" >"$META_DATA"

# SANITY CHECKS #

# If base image exists
[[ -f "$BASE_IMAGE" ]] || {
  echo "Base image not found: $BASE_IMAGE" >&2
  exit 1
}

# If cloud-init files exist
[[ -f "$USER_DATA" ]] || {
  echo "Cloud-init user-data is missing: $USER_DATA" >&2
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

virsh --connect qemu:///system net-info "$VM_NETWORK" >/dev/null || {
  echo "The libvirt '${VM_NETWORK}' network does not exist." >&2
  exit 1
}

if [[ "$(virsh --connect qemu:///system net-info "$VM_NETWORK" |
  awk '$1 == "Active:" { print $2 }')" != "yes" ]]; then
  virsh --connect qemu:///system net-start "$VM_NETWORK"
fi

virsh --connect qemu:///system net-autostart "$VM_NETWORK"

# IP AND MAC SETUP #

# Keep the VM's address stable across rebuilds by reserving it for a fixed MAC.
# Check if MAC or IP are already reserved.
NETWORK_XML="$(virsh --connect qemu:///system net-dumpxml "$VM_NETWORK")"
MAC_RESERVATION="$(grep -F "mac='${VM_MAC}'" <<<"$NETWORK_XML" || true)"
IP_RESERVATION="$(grep -F "ip='${VM_IP}'" <<<"$NETWORK_XML" || true)"

if [[ -n "$MAC_RESERVATION" && "$MAC_RESERVATION" != *"ip='${VM_IP}'"* ]]; then
  echo "MAC address ${VM_MAC} already has a different DHCP reservation:" >&2
  echo "$MAC_RESERVATION" >&2
  exit 1
fi

if [[ -n "$IP_RESERVATION" && "$IP_RESERVATION" != *"mac='${VM_MAC}'"* ]]; then
  echo "IP address ${VM_IP} is already reserved for a different MAC address:" >&2
  echo "$IP_RESERVATION" >&2
  exit 1
fi

if [[ -z "$MAC_RESERVATION" ]]; then
  virsh --connect qemu:///system net-update "$VM_NETWORK" add-last ip-dhcp-host \
    "<host mac='${VM_MAC}' name='${VM_NAME}' ip='${VM_IP}'/>" \
    --live --config
fi


cd "$IMAGE_DIR" || exit

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
  --network network="$VM_NETWORK",model=virtio,mac="$VM_MAC" \
  --graphics spice \
  --cloud-init "user-data=${USER_DATA},meta-data=${META_DATA}" \
  --noautoconsole
