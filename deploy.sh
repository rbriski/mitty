#!/usr/bin/env bash
set -euo pipefail

# Deploy Mitty to a remote server
# Usage: ./deploy.sh [SERVER_HOST] [SERVER_USER]

SERVER_HOST="${1:-${MITTY_SERVER_HOST:-}}"
SERVER_USER="${2:-${MITTY_SERVER_USER:-deploy}}"

if [[ -z "$SERVER_HOST" ]]; then
    echo "Error: SERVER_HOST is required."
    echo "Usage: ./deploy.sh <server_host> [server_user]"
    echo "   or: MITTY_SERVER_HOST=x.x.x.x ./deploy.sh"
    exit 1
fi

REMOTE_DIR="~/mitty"

echo "==> Deploying Mitty to ${SERVER_USER}@${SERVER_HOST}..."

rsync -avz --delete \
    --exclude='.env' \
    --exclude='.git/' \
    --exclude='infra/.terraform/' \
    --exclude='tests/' \
    --exclude='.venv/' \
    --exclude='.beads/' \
    --exclude='.claude/' \
    --exclude='.pytest_cache/' \
    --exclude='.ruff_cache/' \
    --exclude='.playwright-mcp/' \
    --exclude='plans/' \
    --exclude='tickets/' \
    --exclude='results.json' \
    --exclude='data/' \
    ./ "${SERVER_USER}@${SERVER_HOST}:${REMOTE_DIR}/"

echo "==> Files synced. Starting containers..."

ssh "${SERVER_USER}@${SERVER_HOST}" "cd ${REMOTE_DIR} && docker compose up --build -d"

echo ""
echo "==> Deploy complete!"
echo ""
echo "Useful commands:"
echo "  ssh ${SERVER_USER}@${SERVER_HOST} 'cd ${REMOTE_DIR} && docker compose ps'"
echo "  ssh ${SERVER_USER}@${SERVER_HOST} 'cd ${REMOTE_DIR} && docker compose logs -f'"
echo "  ssh ${SERVER_USER}@${SERVER_HOST} 'cd ${REMOTE_DIR} && docker compose down'"
