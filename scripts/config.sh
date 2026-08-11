#!/usr/bin/env bash

VM_DIR_NAME=vm
VM_NAME="vps-local"

PROJECT_DIR="$(cd "$SCRIPT_DIR/.." >/dev/null && pwd)"


VM_DIR="${PROJECT_DIR}/${VM_DIR_NAME}"


export VM_NAME
export PROJECT_DIR
export VM_DIR