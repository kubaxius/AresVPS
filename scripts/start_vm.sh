#!/usr/bin/env bash

# SUDO CHECK
if [[ $EUID -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

virsh --connect qemu:///system start vps-local