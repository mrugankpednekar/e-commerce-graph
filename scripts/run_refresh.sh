#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -z "${CEREBRAS_API_KEY:-}" ]]; then
  echo "CEREBRAS_API_KEY is not set."
  exit 1
fi

exec .venv/bin/python -c "from backend.refresh_pipeline import run_refresh; run_refresh()"
