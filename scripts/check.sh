#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run ruff check backend
uv run pytest
npm --prefix frontend run typecheck
npm --prefix frontend run build
