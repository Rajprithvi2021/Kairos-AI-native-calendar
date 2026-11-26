#!/usr/bin/env bash
# Start API (:8000) and web app (:3000) together; Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."
export NEXT_TELEMETRY_DISABLED=1
(cd services/api && exec uv run --no-sync python -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT
cd apps/web && npx next dev --webpack -p 3000
