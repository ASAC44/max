#!/usr/bin/env bash
set -euo pipefail

MAX_REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MAX_API_PID=""
MAX_WEB_PID=""

cleanup() {
  trap - EXIT INT TERM
  [[ -n "$MAX_API_PID" ]] && kill "$MAX_API_PID" 2>/dev/null || true
  [[ -n "$MAX_WEB_PID" ]] && kill "$MAX_WEB_PID" 2>/dev/null || true
  wait "$MAX_API_PID" "$MAX_WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [[ ! -f "$MAX_REPO_ROOT/.env" ]]; then
  echo "Missing .env. Run ./scripts/setup.sh first." >&2
  exit 1
fi

(
  cd "$MAX_REPO_ROOT/apps/api"
  uv run --env-file ../../.env alembic upgrade head
  exec uv run --env-file ../../.env uvicorn max_api.main:app \
    --host 127.0.0.1 --port 8000 --reload
) &
MAX_API_PID=$!

(
  cd "$MAX_REPO_ROOT/apps/web"
  exec npm run dev
) &
MAX_WEB_PID=$!

echo "Max API:       http://127.0.0.1:8000"
echo "Mission control: http://127.0.0.1:5173"
echo "Press Ctrl+C to stop both services. The dedicated Swiggy browser is separate."

wait -n "$MAX_API_PID" "$MAX_WEB_PID"
