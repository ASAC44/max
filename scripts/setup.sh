#!/usr/bin/env bash
set -euo pipefail

MAX_REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

for command in uv npm; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing required command: $command" >&2
    exit 1
  fi
done

if [[ ! -f "$MAX_REPO_ROOT/.env" ]]; then
  cp "$MAX_REPO_ROOT/.env.example" "$MAX_REPO_ROOT/.env"
  echo "Created .env from .env.example; fill it before running live integrations."
fi

(
  cd "$MAX_REPO_ROOT/apps/api"
  uv sync --extra dev
  uv run --env-file ../../.env alembic upgrade head
)

(
  cd "$MAX_REPO_ROOT/apps/web"
  npm ci
)

echo "Setup complete. Read docs/RUN.md, configure .env, then run ./scripts/dev.sh"
