#!/usr/bin/env bash

set -e

IMAGE_NAME="capstone-dev"

docker build -t "$IMAGE_NAME" .devcontainer

docker run --rm -it \
    -v "$(pwd):/workspace" \
    -w /workspace \
    "$IMAGE_NAME" \
    bash