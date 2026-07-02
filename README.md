# Delphi

**A multi-agent customer-intelligence layer that federates siloed feedback sources behind one chat interface.**

Large e-commerce companies collect customer feedback across several independent systems — app-store reviews, post-purchase surveys/support tickets, and external market/news signals. Each system is siloed, owned by a different team, and increasingly exposes its own **agent** rather than a raw API.

Delphi is an AI intelligence layer that federates those agents behind one chat interface. A user (e.g., a Product Manager) asks a natural-language question; Delphi classifies the business domain, crafts a tailored sub-question for each source agent, calls all agents **in parallel**, then synthesizes one grounded, factual answer.

## Architecture

```
Browser (Next.js chat UI, Vercel)
  │  POST /chat  (SSE stream back)
  ▼
Orchestrator  (FastAPI + LangGraph)  ── Neon: sessions, turns, agent_calls
  │  mint session_id + turn_id, load history, run graph, stream synthesizer
  ▼
LangGraph graph
  domain_classifier → persist_session → source_router
        │  (conditional edges → Send[])   ← dynamic fan-out
        ├─ agent_worker(NEWS)      · per-source planner (LLM) · A2A message/send
        ├─ agent_worker(REVIEWS_A)   (parallel supersteps)
        └─ agent_worker(REVIEWS_B)
        │  ← reducer fan-in (responses)
        ▼
   analyser (pure Python) → persist_responses → synthesizer (LLM, streamed) → persist_final

External A2A agents (each own FastAPI server, Agent Card, Neon table, LLM):
   NEWS      http://localhost:8101   REVIEWS_A 8102   REVIEWS_B 8103
```

- **Fan-out / fan-in:** LangGraph `Send` (dynamic parallel branches) + `Annotated[list, operator.add]` reducers. Adding a source is one registry entry — no topology change.
- **A2A:** each agent advertises an Agent Card at `/.well-known/agent-card.json`; the orchestrator discovers cards at startup and calls agents over JSON-RPC `message/send`.

## What it demonstrates

- **LangGraph** orchestration with real dynamic fan-out / fan-in (`Send` API + channel reducers)
- **A2A** (Agent-to-Agent) protocol: agent cards, discovery, JSON-RPC `message/send`
- Multi-agent planning (per-source planners), deterministic analysis, LLM synthesis
- Multi-turn session/turn state with persistent history (Neon Postgres)
- Provider-agnostic LLM integration; each agent independently deployable
- Streaming chat UX (SSE) with a Next.js frontend

## Tech stack

Python 3.11+, `langgraph` / `langchain-core`, `fastapi` / `uvicorn`, `httpx`, `asyncpg` (Neon Postgres), OpenAI-compatible LLM client (`openai` SDK — Groq / OpenRouter / Together / OpenAI / local), `pydantic` v2, `feedparser` (news). Frontend: Next.js 14 (App Router) on Vercel. Tests: `pytest` / `pytest-asyncio`.

## The three source agents

| Agent | Data | Live? | LLM? |
|---|---|---|---|
| **NEWS** | Google News RSS (market/competitor headlines) | Yes (live) | Yes |
| **REVIEWS_A** | App-store style product reviews (Neon table, seeded) | No (static seed) | Yes |
| **REVIEWS_B** | Post-purchase survey / support feedback (Neon table, seeded) | No (static seed) | Yes |

Two review agents model two separate feedback silos with separate agents, and show that adding another source is trivial.

## Run locally

### 1. Environment

Each backend service has its own `.env` (copy from `.env.example`). By default all four services share **one** LLM key — paste the same `LLM_API_KEY` into each. Set `DATABASE_URL` (Neon pooled connection string) in the orchestrator and both reviews agents.

```bash
cp orchestrator/.env.example       orchestrator/.env
cp agents/news/.env.example        agents/news/.env
cp agents/reviews_a/.env.example   agents/reviews_a/.env
cp agents/reviews_b/.env.example   agents/reviews_b/.env
cp frontend/.env.local.example     frontend/.env.local
# then edit each .env: set LLM_API_KEY (same key) and DATABASE_URL (Neon)
```

### 2. Install (one shared venv)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e libs/delphi_common
pip install -r orchestrator/requirements.txt \
            -r agents/news/requirements.txt \
            -r agents/reviews_a/requirements.txt
```

### 3. Database + seed data

```bash
psql "$DATABASE_URL" -f db/schema.sql   # create tables
python db/seed.py                       # load ~200 fake reviews per table (idempotent)
```

Seed data is static committed JSON (`db/seed_*.json`, ~200 rows each), spread across all 6 domains, mixed sentiment, and dated across the last ~90 days so recency filters work. Regenerate with `python db/_generate_seed.py`.

### 4. Run everything

```bash
./scripts/run_all.sh
```

Agents start first (so the orchestrator can discover their cards), then the orchestrator on `:8000`, then the frontend on `http://localhost:3000`.

### 5. Tests

```bash
cd orchestrator && pip install pytest pytest-asyncio && pytest tests/ -v
```

No network, no live LLM. Covers the fan-out/fan-in graph, partial-failure disclosure, conditional entry, and the three persistence write-traps.

## Deployment

- **Frontend → Vercel.** Import `frontend/`; set `NEXT_PUBLIC_ORCHESTRATOR_URL` to the deployed orchestrator URL.
- **Backend (orchestrator + 3 agents) → Render or Railway.** Each service = one deploy. Set each service's **root directory to the repo root** and build with `pip install ./libs/delphi_common && pip install -r <service>/requirements.txt`, start with `cd <service> && uvicorn main:app --host 0.0.0.0 --port $PORT`. Do **not** list `delphi_common` in any per-service `requirements.txt` — install it from the repo path.
- **Neon** is the shared managed Postgres (use the pooled connection string).
- Set the orchestrator's `AGENT_*_URL` to the deployed agent URLs; enable CORS for the Vercel domain.

## Design notes

- **Why `Send` over `asyncio.gather`:** parallelism is expressed as graph structure (dynamic `Send` fan-out + reducer fan-in) — the idiomatic LangGraph map-reduce pattern, independently observable/traceable per branch.
- **Why A2A cards for discovery:** agent capabilities are discovered at runtime from cards, not a static manifest. Adding a source is a registry entry.
- **Three-write persistence:** `persist_session` / `persist_responses` / `persist_final`, all fire-and-forget — a DB failure never breaks the chat response.
- **Deterministic unavailability disclosure:** the analyser (pure Python) builds an unavailability note; the synthesizer appends it after the LLM stream, so failures are always disclosed verbatim.
