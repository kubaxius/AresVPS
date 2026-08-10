#!/usr/bin/env bash

VM_DIR_NAME=vm


PROJECT_DIR="$(cd "$SCRIPT_DIR/.." >/dev/null && pwd)"
export PROJECT_DIR

VM_DIR="${PROJECT_DIR}/${VM_DIR_NAME}"
export VM_DIR