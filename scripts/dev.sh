#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/backend"
uv run uvicorn lubriflow.api:app --host 127.0.0.1 --port 8000 &
api_pid=$!
uv run python -m lubriflow.worker &
worker_pid=$!
cleanup() { kill "$api_pid" "$worker_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
npm --prefix frontend run dev
