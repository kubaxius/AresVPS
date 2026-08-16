#!/usr/bin/env bash

IMAGE_DIR_NAME=vm
VM_NAME="ares-local"
VM_NETWORK="default"
VM_MAC="52:54:00:00:00:10"
VM_IP="192.168.122.10"

PROJECT_DIR="$(cd "$SCRIPT_DIR/.." >/dev/null && pwd)"


IMAGE_DIR="${PROJECT_DIR}/${IMAGE_DIR_NAME}"


export VM_NAME
export VM_NETWORK
export VM_MAC
export VM_IP
export PROJECT_DIR
export IMAGE_DIR
