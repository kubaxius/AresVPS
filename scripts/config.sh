#!/usr/bin/env bash

VM_DIR_NAME=vm
VM_NAME="vps-local"
VM_NETWORK="default"
VM_MAC="52:54:00:00:00:10"
VM_IP="192.168.122.10"

PROJECT_DIR="$(cd "$SCRIPT_DIR/.." >/dev/null && pwd)"


VM_DIR="${PROJECT_DIR}/${VM_DIR_NAME}"


export VM_NAME
export VM_NETWORK
export VM_MAC
export VM_IP
export PROJECT_DIR
export VM_DIR
