# Kairos API (FastAPI)

The backend for the Kairos prototype. It holds the scheduling, conflict, reminder, analytics and forecast engines, the AI layer (Claude, plus an offline heuristic twin), and a REST API.

```powershell
uv sync                                   # install deps into .venv
uv run uvicorn app.main:app --reload      # http://127.0.0.1:8000  (OpenAPI docs at /docs)
uv run pytest                             # unit + API tests
uv run python -m evals.run_evals          # NL-command golden-set evaluation (offline parser)
```

Configuration lives in environment variables or `services/api/.env` (see `.env.example` at the repo root).
