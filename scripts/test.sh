#!/usr/bin/env bash
# Run all automated checks (add --e2e to include the Playwright flows; needs scripts/dev.sh running).
set -euo pipefail
cd "$(dirname "$0")/.."
(cd services/api && uv run python -m ruff check app tests evals && uv run python -m pytest && uv run python -m evals.run_evals)
(cd apps/web && npx next typegen && npx tsc --noEmit && npx eslint src && npx vitest run && npm run build)
if [[ "${1:-}" == "--e2e" ]]; then
  (cd services/api && KAIROS_E2E_CHANNEL="${KAIROS_E2E_CHANNEL:-chromium}" uv run python -m pytest ../../tests/e2e)
fi
echo "All checks passed."
