#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.app-only.yml}"
PROJECT_NAME="${PROJECT_NAME:-ai-paper-system}"
DUMP_FILE="${DUMP_FILE:-/home/nguyenducthang/neo4j.dump}"
DB_NAME="${DB_NAME:-neo4j}"

if [[ ! -f "$DUMP_FILE" ]]; then
  echo "[error] dump file not found: $DUMP_FILE" >&2
  exit 1
fi

VOLUME_NAME="${PROJECT_NAME}_neo4j_data"

echo "[neo4j] stopping service"
docker compose -f "$COMPOSE_FILE" stop neo4j

echo "[neo4j] loading dump into volume: $VOLUME_NAME"
docker run --rm \
  -v "$VOLUME_NAME":/data \
  -v "$(dirname "$DUMP_FILE")":/import:ro \
  neo4j:5.26 \
  neo4j-admin database load "$DB_NAME" --from-path=/import --overwrite-destination=true

echo "[neo4j] starting service"
docker compose -f "$COMPOSE_FILE" up -d neo4j

echo "[neo4j] done"
