#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f backend/.env ]]; then
  echo "Missing backend/.env. Copy deploy.env.example values into backend/.env first." >&2
  exit 1
fi

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.app-only.yml}"

echo "[1/3] Build images (${COMPOSE_FILE})"
docker compose -f "${COMPOSE_FILE}" build

echo "[2/3] Start services"
docker compose -f "${COMPOSE_FILE}" up -d

echo "[3/3] Service status"
docker compose -f "${COMPOSE_FILE}" ps
