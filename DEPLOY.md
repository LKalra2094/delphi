# Deploying Delphi

Frontend → **Vercel**. Backend (orchestrator + 3 agents) → **Render** (via `render.yaml`).
Shared Postgres → **Neon** (already provisioned & seeded).

The four backend services share `libs/delphi_common`, so each builds from the **repo root**
(`pip install ./libs/delphi_common && pip install -r <service>/requirements.txt`). The
`render.yaml` blueprint encodes all of this.

---

## 1. Backend on Render (one blueprint, 4 services)

1. Go to **render.com → New → Blueprint**, connect this GitHub repo. Render reads `render.yaml`
   and proposes 4 services: `delphi-news`, `delphi-reviews-a`, `delphi-reviews-b`, `delphi-orchestrator`.
2. Render will prompt for the `sync:false` env vars. Fill them:
   - **All four services** — `LLM_API_KEY` = your Gemini key.
   - **reviews-a, reviews-b, orchestrator** — `DATABASE_URL` = your Neon pooled connection string
     (the same one in your local `.env`).
   - Leave the orchestrator's `AGENT_*_URL` blank for now (set in step 3).
3. Click **Apply** and let the 3 agents deploy first. Copy each agent's public URL
   (e.g. `https://delphi-news-xxxx.onrender.com`), then on **delphi-orchestrator → Environment** set:
   - `AGENT_NEWS_URL` = the delphi-news URL
   - `AGENT_REVIEWS_A_URL` = the delphi-reviews-a URL
   - `AGENT_REVIEWS_B_URL` = the delphi-reviews-b URL
   Save → the orchestrator redeploys and discovers the agent cards at startup.
4. (Optional, recommended) Once the frontend is live, set the orchestrator's `CORS_ORIGINS`
   to your exact Vercel URL instead of `*`.

> **Free-tier note:** services sleep after ~15 min idle and cold-start in 30–60s. If the
> orchestrator wakes before the agents, it registers them with empty skills (planners fall
> back to the raw query) until its next restart. For a smoother always-on demo, upgrade the
> orchestrator (and ideally the agents) off free tier, or add a keep-alive pinger.

## 2. Frontend on Vercel

1. **vercel.com → Add New → Project**, import this repo, set **Root Directory = `frontend`**.
2. Add env var `NEXT_PUBLIC_ORCHESTRATOR_URL` = your `delphi-orchestrator` Render URL.
3. Deploy. Vercel auto-detects Next.js.

## 3. Database

Already done for local dev. If deploying against a fresh Neon project:
```bash
psql "$DATABASE_URL" -f db/schema.sql
python db/seed.py
```

## 4. Smoke test

```bash
curl -N -X POST https://<orchestrator>.onrender.com/chat \
  -H 'Content-Type: application/json' \
  -d '{"query":"What are customers saying about checkout this week?"}'
```
Expect SSE frames: `session` → `status` → `token`… → `done`.
