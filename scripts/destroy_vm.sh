#!/usr/bin/env bash
# ai_generated
set -Eeuo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

ASSUME_YES=false
if [[ ${1:-} == "--yes" ]]; then
  ASSUME_YES=true
  shift
fi

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 [--yes] <vm-name>" >&2
  exit 2
fi

VM_NAME="$1"
VM_DISK="/var/lib/libvirt/images/${VM_NAME}.qcow2"

if [[ $ASSUME_YES == false ]]; then
  read -r -p "Destroy ${VM_NAME} and delete ${VM_DISK}? [y/N] " reply
  if [[ $reply != "y" && $reply != "Y" ]]; then
    echo "Cancelled."
    exit 0
  fi
fi

if virsh --connect qemu:///system dominfo "$VM_NAME" >/dev/null 2>&1; then
  if virsh --connect qemu:///system list --name | grep -Fxq "$VM_NAME"; then
    echo "Stopping ${VM_NAME}..."
    virsh --connect qemu:///system destroy "$VM_NAME"
  fi

  # A transient domain disappears when it stops, so only persistent domains
  # still exist at this point and need to be undefined.
  if virsh --connect qemu:///system dominfo "$VM_NAME" >/dev/null 2>&1; then
    if virsh --connect qemu:///system dumpxml "$VM_NAME" | grep -q '<nvram'; then
      virsh --connect qemu:///system undefine "$VM_NAME" --nvram
    else
      virsh --connect qemu:///system undefine "$VM_NAME"
    fi
  fi
else
  echo "No libvirt domain named ${VM_NAME}; continuing with disk cleanup."
fi

if [[ -e $VM_DISK ]]; then
  rm -- "$VM_DISK"
  echo "Removed ${VM_DISK}."
else
  echo "No VM disk found at ${VM_DISK}."
fi

echo "${VM_NAME} has been removed."
