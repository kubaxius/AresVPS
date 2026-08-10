#!/usr/bin/env bash

if [ "$EUID" -ne 0 ]; then echo "Not running as root" && exit; fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"

source "$SCRIPT_DIR/config.sh"

cd "$VM_DIR" || exit


qemu-img convert \
  -f qcow2 \
  -O qcow2 \
  images/ubuntu-24.04-server-cloudimg-amd64.img \
  /var/lib/libvirt/images/vps-local.qcow2

qemu-img resize \
  /var/lib/libvirt/images/vps-local.qcow2 \
  25G

# Ensure NAT is working
if [ "$(virsh --connect qemu:///system net-info default | awk '$1 == "Active:" { print $2 }')" != "yes" ]; then
  virsh --connect qemu:///system net-start default
fi
virsh --connect qemu:///system net-autostart default
