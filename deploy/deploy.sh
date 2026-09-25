#!/usr/bin/env bash
# Runs ON the target VM (staging or production). Pulls the tagged images, applies
# migrations as an explicit gated step, then recreates the services and waits for health.
# Not exercised against a real VM from this repository -- rehearse on staging first.
# Usage: IMAGE_TAG=v1.2.3 IMAGE_PREFIX=ghcr.io/<owner>/motor-dt ./deploy/deploy.sh staging|production
set -euo pipefail
ENV_NAME="${1:?staging|production}"
ENV_FILE=".env.${ENV_NAME}"
: "${IMAGE_TAG:?IMAGE_TAG required}"
COMPOSE=(docker compose -f compose.yaml -f compose.prod.yaml --env-file "$ENV_FILE")

"${COMPOSE[@]}" pull backend frontend migrate
if [[ "$ENV_NAME" == "production" ]]; then
  ./deploy/backup/mysql_backup.sh mysql ./backups   # fresh backup before touching the schema
fi
"${COMPOSE[@]}" run --rm migrate                      # alembic upgrade head (explicit step)

# Recreate backend replicas on the new image and wait until healthy. Old containers get
# SIGTERM -> graceful shutdown (stop WS, flush writes). NOTE: plain Compose recreates all
# replicas together, so expect a few seconds of API/WebSocket interruption; true zero-downtime
# rolling updates need an orchestrator (Swarm/Kubernetes) or a blue/green nginx upstream switch.
"${COMPOSE[@]}" up -d --no-deps --wait --wait-timeout 120 backend
"${COMPOSE[@]}" up -d --no-deps --wait frontend edge
echo "deployed $IMAGE_TAG to $ENV_NAME"
