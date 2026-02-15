#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-8080}"

cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "Missing .venv. Create it first:"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/pip install -r requirements.txt"
  exit 1
fi

EXISTING_PID="$(lsof -tiTCP:${PORT} -sTCP:LISTEN || true)"
if [[ -n "${EXISTING_PID}" ]]; then
  echo "Stopping existing server on port ${PORT} (pid ${EXISTING_PID})"
  kill ${EXISTING_PID} || true
  sleep 1
fi

if [[ -z "${CEREBRAS_API_KEY:-}" ]]; then
  echo "Warning: CEREBRAS_API_KEY is not set. Refresh with LLM will fail."
fi

echo "Serving UI at http://localhost:${PORT}"
exec .venv/bin/uvicorn backend.ui_server:app --host 127.0.0.1 --port "${PORT}"
