# Kairos web app (Next.js 16 · React 19 · TypeScript)

The UI for Kairos. It talks only to `/api/*`, which `next.config.ts` proxies to the FastAPI service on port 8000.

```powershell
..\..\scripts\run-web.ps1        # dev server on http://localhost:3000 (webpack mode, see repo README)
npm run typecheck; npm run lint; npm test; npm run build
```

- `src/components/calendar/`: week grid, Copilot rail, and the schedule, conflict and event drawers.
- `src/components/CommandBar.tsx`: Ctrl+K natural-language command bar.
- `src/components/insights/`, `settings/`, `study/`: the other pages.
- `src/lib/`: typed API client, time-zone math (`time.ts`, Intl-only), and event layout (`layout.ts`), with Vitest tests.

Add dependencies with `..\..\scripts\web-npm.ps1 install <pkg>`. Inside OneDrive this keeps `node_modules` out of sync.
