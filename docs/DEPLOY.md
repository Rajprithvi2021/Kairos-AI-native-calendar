# Deploy Kairos: Neon (Postgres) + Render

```
Browser ──► Render web service "kairos-ai-calendar"      (Next.js; proxies /api/*)
                │
                └──► Render web service "kairos-ai-calendar-api"  (FastAPI)
                        ├──► Neon Postgres            (KAIROS_DATABASE_URL)
                        └──► Gemini / Claude APIs     (keys stay on the server)
```

Both Render services and the Neon database fit on the free plans. Everything Render needs is in [`render.yaml`](../render.yaml): build and start commands, regions and environment variables.

**Verified before writing this (27 Nov 2026):**
- The whole backend test suite (85 tests) passes on Postgres 17, through the `pg8000` driver used in production.
- The API starts against an empty Postgres, creates its tables and seeds the demo in about 11 s.
- The production web build (`next build` + `next start`) serves the app and proxies `/api` to it.
- CI runs the backend suite on Postgres for every push (`api-postgres` job).

**Not verified:** a live Render or Neon deployment, which needs your accounts.

---

## 1. Neon: create the database (about 5 minutes)

1. Sign in at <https://console.neon.tech> (the free plan is enough).
2. Create a project:
   - **Name:** `kairos`.
   - **Postgres version:** 17.
   - **Region:** **AWS Asia Pacific (Singapore)**, the same region as `render.yaml`. To use a US region, change both (see Troubleshooting).
3. On the project dashboard, click **Connect** and copy the connection string.
   - Use the **direct** connection, not the pooled one: switch *Connection pooling* off. The API keeps its own small connection pool.
   - It looks like `postgresql://neondb_owner:…@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require`. Paste it as-is; the API converts it for its driver and keeps TLS on.
4. The string contains a password. Paste it only into Render (next step), never into the repo.

You don't create any tables yourself: the API creates them and seeds the demo company on its first start.

## 2. Render: deploy both services from the Blueprint (about 10 minutes)

1. Make sure `render.yaml` is on the `main` branch of your GitHub repo.
2. Sign in at <https://dashboard.render.com> with GitHub, and give Render access to the `Kairos-AI-native-calendar` repository.
3. Click **New +** → **Blueprint**, then pick the repository. Render reads `render.yaml` and lists two services:
   - `kairos-ai-calendar-api`: the FastAPI backend.
   - `kairos-ai-calendar`: the Next.js web app.
4. Fill in the values it asks for:

   | Variable | Service | Value |
   |---|---|---|
   | `KAIROS_DATABASE_URL` | api | The Neon connection string from step 1 |
   | `GEMINI_API_KEY` | api | Your Gemini key. Use a **newly created** one, since the old one appeared in a chat. Leave it empty to run on the offline engine only. |
   | `KAIROS_API_URL` | web | `https://kairos-ai-calendar-api.onrender.com` |

5. Click **Apply**. The first builds take about 5–10 minutes.
6. Open the API service in the dashboard and check its URL.
   - If Render added a suffix because the name was taken (for example `kairos-ai-calendar-api-x1y2.onrender.com`), set `KAIROS_API_URL` on the web service to that exact URL.
   - Then choose **Save, rebuild, and deploy**. The web app reads this value at build time, so it needs a rebuild.

## 3. Check it works

- Open `https://<your-api>.onrender.com/api/health`. You should see:
  - `"status":"ok"`;
  - `"events"` at about 1,300;
  - `"ai": {"engine": "gemini", …}`, or `"offline"` if you set no key.
- Open `https://kairos-ai-calendar.onrender.com`. The calendar loads, the sidebar pill says **Gemini**, and Ctrl+K understands requests.
- Settings → *AI engine & activity log* lists each AI call with its engine, model and latency.

## Good to know

- **Cold starts:** free Render services sleep after 15 minutes without traffic, so the next visit takes about a minute while the web app wakes and then the API.
  - Before a demo, open the API health URL first, then the app.
  - Neon's free compute also pauses when idle; it resumes in about a second.
- **A fresh demo:** the planted conflicts and reminders are relative to the day the data was seeded. Before demoing, use Settings → Demo controls → **Reset demo data**.
- **The URL is public and has no login.** Anyone with the link can view and change the (fictional) demo data and trigger AI calls.
  - `KAIROS_AI_MAX_CALLS_PER_HOUR=120` caps AI usage; past the cap, the offline engine answers.
  - Also set a usage or spending limit on your Google AI Studio project.
  - API keys stay on the server and never reach the browser.
- **Updates:** every push to `main` redeploys automatically. `buildFilter` rebuilds only the service whose folder changed (`services/api/**` or `apps/web/**`).
- **Claude:** add `ANTHROPIC_API_KEY` to the API service if you have one. Claude then goes first, with Gemini as its fallback.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Web build fails with *JavaScript heap out of memory* | Add `NODE_OPTIONS=--max-old-space-size=460` to the web service, or build on a paid instance |
| The app says "API offline", or `/api/...` returns 404 | `KAIROS_API_URL` on the web service is wrong: use the API's `https://…onrender.com` URL with no path. Then **Save, rebuild, and deploy** |
| API logs show database connection errors | Check the Neon connection string is complete and keeps `sslmode=require`. Use the direct (unpooled) one |
| `/api/health` shows `"engine": "offline"` | `GEMINI_API_KEY` is missing or invalid, or the hourly AI cap was reached (it resets on a rolling hour) |
| Slow responses | Keep Render and Neon in the same region. For the US: `region: oregon` for both services in `render.yaml`, and a Neon region in AWS US West (Oregon) |

## Running locally against Postgres

Put the connection string in `services/api/.env` as `KAIROS_DATABASE_URL=…` and restart the API. To run the backend tests against a Postgres database, set `KAIROS_TEST_DATABASE_URL`. The tests wipe and re-seed that database, so never point it at the one you deploy with.
