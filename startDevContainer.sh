#!/usr/bin/env bash
set -e

docker compose up -d --build
docker compose exec dev bash