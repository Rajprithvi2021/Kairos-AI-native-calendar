#!/usr/bin/env bash
# One-time setup on macOS / Linux. Requires: git, uv, Node.js 22+.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)"; exit 1; }
command -v node >/dev/null || { echo "Node.js 22+ is required"; exit 1; }
(cd services/api && uv sync && uv run python -m app.seed && uv run python -m playwright install chromium)
(cd apps/web && npm ci)
echo "Done. Start with: scripts/dev.sh"
