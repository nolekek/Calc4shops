#!/usr/bin/env bash
set -e

echo "=== Deploying Deal Auditor (Docker Production) ==="
docker compose down || true
docker compose build --no-cache
docker compose up -d
echo "=== Deal Auditor is live at http://localhost:8000 ==="
docker compose ps
