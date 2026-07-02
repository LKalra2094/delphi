# Delphi — Build Spec (Portfolio Edition)

> **Purpose:** A complete, self-contained specification to build Delphi from scratch as a portfolio project. Any LLM or engineer with no prior context should be able to build the entire product from this document alone.
> **Nature:** Clean-room, generic multi-agent customer-intelligence system. No proprietary/employer identifiers. Safe to open-source.
> **Source of truth:** This document.
> **Date:** 2026-07-02

---

## Table of Contents

1. [Product Concept & Story](#1-product-concept--story)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Monorepo Layout](#4-monorepo-layout)
5. [Environment Variables](#5-environment-variables)
6. [Shared Libraries (LLM, DB, A2A)](#6-shared-libraries-llm-db-a2a)
7. [Neon Database Schemas](#7-neon-database-schemas)
8. [A2A Protocol Implementation](#8-a2a-protocol-implementation)
9. [The Three Agents](#9-the-three-agents)
10. [Intelligence Layer (LangGraph)](#10-intelligence-layer-langgraph)
    - 10.1 [QueryState & Reducers](#101-querystate--reducers)
    - 10.2 [Graph Topology — Fan-out / Fan-in](#102-graph-topology--fan-out--fan-in)
    - 10.3 [Nodes — Full Contracts](#103-nodes--full-contracts)
    - 10.4 [A2A Client Adapter & Card Discovery](#104-a2a-client-adapter--card-discovery)
    - 10.5 [Persistence — Three-Write Pattern](#105-persistence--three-write-pattern)
11. [Domains](#11-domains)
12. [Orchestrator App & `/chat` Streaming Handler](#12-orchestrator-app--chat-streaming-handler)
13. [Frontend (Next.js on Vercel)](#13-frontend-nextjs-on-vercel)
14. [Seed Data (Fake Reviews)](#14-seed-data-fake-reviews)
15. [Local Development & Run Script](#15-local-development--run-script)
16. [Deployment](#16-deployment)
17. [Testing Strategy](#17-testing-strategy)
18. [Invariants — Do Not Violate](#18-invariants--do-not-violate)
19. [README Content](#19-readme-content)
20. [Glossary](#20-glossary)

---

## 1. Product Concept & Story

Large e-commerce companies collect customer feedback across **several independent systems** — app-store reviews, post-purchase surveys/support tickets, and external market/news signals. Each system is siloed and owned by a different team, and each increasingly exposes its own **agent** rather than a raw API.

**Delphi** is an AI intelligence layer that federates those agents behind one chat interface. A user (e.g., a Product Manager) asks a natural-language question; Delphi classifies the business domain, crafts a tailored sub-question for each source agent, calls all agents **in parallel**, then synthesizes one grounded, factual answer.

**What this project demonstrates:**
- **LangGraph** orchestration with real **dynamic fan-out / fan-in** (`Send` API + channel reducers)
- **A2A** (Agent-to-Agent) protocol: agent cards, discovery, JSON-RPC `message/send`
- Multi-agent planning (per-source planners), deterministic analysis, LLM synthesis
- Multi-turn session/turn state with persistent history (Neon Postgres)
- Provider-agnostic LLM integration; each agent independently deployable
- Streaming chat UX (SSE) with a Next.js frontend

**The three source agents:**
| Agent (source key) | Data | Live? | LLM? |
|---|---|---|---|
| **NEWS** | Google News RSS (market/competitor headlines) | Yes (live) | Yes |
| **REVIEWS_A** | App-store style product reviews (Neon table, seeded) | No (static seed) | Yes |
| **REVIEWS_B** | Post-purchase survey / support feedback (Neon table, seeded) | No (static seed) | Yes |

Two review agents are intentional: they model **two separate feedback silos with separate agents**, and demonstrate that adding another source is trivial.

---

## 2. High-Level Architecture

```
Browser (Next.js chat UI, Vercel)
  │  POST /chat  (SSE stream back)
  ▼
Orchestrator  (FastAPI + LangGraph)  ── Neon: sessions, turns, agent_calls
  │  _oracle_chat(): mint session_id + turn_id, load history, run graph, stream synthesizer
  ▼
LangGraph graph
  │  [turn 1] domain_classifier → persist_session ─┐
  │  [turn 2+, domain set] ─────────────────────────┤
  │                                          source_router
  │                                                │  (conditional edges → Send[])
  │                        ┌──────────── fan-out (LangGraph Send) ───────────┐
  │                        ▼                        ▼                          ▼
  │                  agent_worker(NEWS)     agent_worker(REVIEWS_A)   agent_worker(REVIEWS_B)
  │                  · per-source planner (LLM)                        (parallel supersteps)
  │                  · A2A message/send  ──────────────────────────────────┐
  │                        └──────────── fan-in (reducer: responses) ───────┘
  │                                                │
  │                                            analyser  (pure Python)
  │                                                │
  │                                        persist_responses
  │                                                │
  │                                          synthesizer  (LLM, streamed)
  │                                                │
  │                                          persist_final → END

External A2A agents (each own FastAPI server, own Agent Card, own Neon table, own LLM):
   NEWS      http://localhost:8101   GET /.well-known/agent-card.json   POST / (JSON-RPC)
   REVIEWS_A http://localhost:8102   ...
   REVIEWS_B http://localhost:8103   ...
```

**A2A between orchestrator and agents:** synchronous `message/send`.
**Streaming between orchestrator and browser:** SSE (synthesizer tokens). `message/stream` (per-agent streaming) is a documented future extension, not implemented.

---

## 3. Tech Stack

- **Language:** Python 3.11+ (backend), TypeScript/React (frontend)
- **Orchestration:** `langgraph`, `langchain-core`
- **Web:** `fastapi`, `uvicorn`
- **HTTP client:** `httpx` (async)
- **DB:** Neon Postgres via `asyncpg`
- **LLM:** OpenAI-compatible client (`openai` SDK) — works with Groq / OpenRouter / Together / OpenAI / local. Provider-agnostic via `LLM_BASE_URL`.
- **Models:** `pydantic` v2
- **RSS:** `feedparser` (news agent)
- **Frontend:** Next.js 14 (App Router), React, hosted on Vercel
- **Tests:** `pytest`, `pytest-asyncio`

---

## 4. Monorepo Layout

```
delphi/
├── README.md
├── .gitignore
├── scripts/
│   └── run_all.sh                 # launch orchestrator + 3 agents locally
│
├── libs/
│   └── delphi_common/             # shared helpers, pip-installable (editable)
│       ├── pyproject.toml
│       └── delphi_common/
│           ├── __init__.py
│           ├── llm.py             # OpenAI-compatible async LLM client + execute_prompt
│           ├── db.py              # asyncpg PostgresClient (ensure_table/insert/upsert/query)
│           └── a2a.py             # A2A server helpers + client + card models
│
├── orchestrator/
│   ├── main.py                    # FastAPI app, POST /chat (SSE), /health
│   ├── config.py                  # env config, agent registry, analysis thresholds
│   ├── requirements.txt
│   ├── .env.example
│   ├── intelligence_layer/
│   │   ├── __init__.py
│   │   ├── state.py               # QueryState, AgentTask, NormalisedResponse
│   │   ├── graph.py               # build_graph() with Send fan-out/fan-in
│   │   ├── nodes.py               # all node functions + per-source planner
│   │   └── persistence.py         # three-write pattern
│   ├── adapters/
│   │   └── a2a_client.py          # discover() + send() over A2A
│   ├── domains/
│   │   ├── _domains.md            # advisory index for classifier
│   │   ├── search.md
│   │   ├── checkout.md
│   │   ├── delivery.md
│   │   ├── returns.md
│   │   ├── payments.md
│   │   └── account.md
│   └── tests/
│       ├── conftest.py            # asyncio_mode=auto
│       ├── test_graph_smoke.py
│       └── test_persistence.py
│
├── agents/
│   ├── news/
│   │   ├── main.py                # FastAPI A2A server (RSS + LLM)
│   │   ├── requirements.txt
│   │   └── .env.example
│   ├── reviews_a/
│   │   ├── main.py                # FastAPI A2A server (Neon table + LLM)
│   │   ├── requirements.txt
│   │   └── .env.example
│   └── reviews_b/
│       ├── main.py
│       ├── requirements.txt
│       └── .env.example
│
├── db/
│   ├── schema.sql                 # all tables
│   ├── seed.py                    # load seed JSON into Neon
│   ├── seed_reviews_store.json    # REVIEWS_A dataset (~200 rows)
│   └── seed_feedback_survey.json  # REVIEWS_B dataset (~200 rows)
│
└── frontend/                      # Next.js app (Vercel)
    ├── package.json
    ├── next.config.js
    ├── .env.local.example
    └── app/
        ├── page.tsx               # chat UI
        ├── layout.tsx
        └── lib/delphi.ts          # /chat SSE client
```

> **Shared library & deploy independence:** `libs/delphi_common` is a real installable package (`pyproject.toml`) shared by all four backend services — write the LLM/DB/A2A helpers once, fix bugs once. It coexists with independent deploys:
> - **Local dev:** `pip install -e libs/delphi_common` into your venv → all services import it live.
> - **Deploy (Render/Railway monorepo):** set each service's **root directory to the repo root**, build with `pip install ./libs/delphi_common && pip install -r <service>/requirements.txt`, start with `cd <service> && uvicorn main:app --host 0.0.0.0 --port $PORT`. Because the build context is the repo root, the shared package is reachable.
> - **Rule:** do NOT list `delphi_common` in any per-service `requirements.txt`; install it from the repo path in the build step.

---

## 5. Environment Variables

Each **service has its own environment** (separate processes / deploys), so no prefixes are needed — every service reads the same variable names from its own env.

> **Single shared LLM key (default).** All four backend services use the **same** `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` — one key powers every LLM call (orchestrator planner + synthesizer, and each agent). You simply repeat the same three values in every `.env`. Per-service values are fully supported (e.g., a different model per agent) but **not** required; use one key unless you have a reason not to.

**Common to every backend service (orchestrator + each agent):**
| Variable | Example | Notes |
|---|---|---|
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` | OpenAI-compatible endpoint |
| `LLM_API_KEY` | `PLACEHOLDER` | **Single shared key** — put the same value in all four `.env` files (default) |
| `LLM_MODEL` | `llama-3.3-70b-versatile` | Model id for that endpoint |
| `LLM_TIMEOUT_SECONDS` | `30` | Per-call timeout |

**DB (orchestrator + reviews agents):**
| Variable | Example | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://user:pass@ep-xxx.neon.tech/delphi?sslmode=require` | Neon pooled connection string |

**Orchestrator only:**
| Variable | Example | Notes |
|---|---|---|
| `AGENT_NEWS_URL` | `http://localhost:8101` | Base URL of NEWS agent |
| `AGENT_REVIEWS_A_URL` | `http://localhost:8102` | Base URL of REVIEWS_A agent |
| `AGENT_REVIEWS_B_URL` | `http://localhost:8103` | Base URL of REVIEWS_B agent |
| `PORT` | `8000` | |

**Reviews agents only:**
| Variable | Example | Notes |
|---|---|---|
| `REVIEWS_TABLE` | `reviews_store` / `feedback_survey` | Which table this agent owns |
| `PORT` | `8102` / `8103` | |

**News agent only:**
| Variable | Example | Notes |
|---|---|---|
| `PORT` | `8101` | |
| `NEWS_QUERIES` | `Amazon,Target,Costco,Instacart` | Comma-separated topics (optional; has default) |

**Frontend (`frontend/.env.local`):**
| Variable | Example |
|---|---|
| `NEXT_PUBLIC_ORCHESTRATOR_URL` | `http://localhost:8000` (prod: Render/Railway URL) |

### 5.1 `.env` files — generate these

**Loading:** every backend service loads its own `.env` at startup via **`python-dotenv`**. Add `python-dotenv` to each service's `requirements.txt` and call `load_dotenv()` as the first line of each `main.py` and `db/seed.py`. The frontend uses Next.js's built-in `.env.local` (no dotenv needed).

**The build must generate, for each service, BOTH:**
- a committed `.env.example` (placeholders — safe to commit), and
- a gitignored `.env` (copied from `.env.example`; the user pastes the real key).

Because of the single-key default, the four LLM values are identical across all backend files.

`orchestrator/.env.example`
```
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=PLACEHOLDER
LLM_MODEL=llama-3.3-70b-versatile
LLM_TIMEOUT_SECONDS=30
DATABASE_URL=postgresql://USER:PASSWORD@HOST.neon.tech/delphi?sslmode=require
AGENT_NEWS_URL=http://localhost:8101
AGENT_REVIEWS_A_URL=http://localhost:8102
AGENT_REVIEWS_B_URL=http://localhost:8103
PORT=8000
```

`agents/news/.env.example`
```
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=PLACEHOLDER
LLM_MODEL=llama-3.3-70b-versatile
LLM_TIMEOUT_SECONDS=30
PORT=8101
NEWS_QUERIES=Amazon,Target,Costco,Kroger,Instacart,Walmart
```

`agents/reviews_a/.env.example`
```
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=PLACEHOLDER
LLM_MODEL=llama-3.3-70b-versatile
LLM_TIMEOUT_SECONDS=30
DATABASE_URL=postgresql://USER:PASSWORD@HOST.neon.tech/delphi?sslmode=require
REVIEWS_TABLE=reviews_store
PORT=8102
```

`agents/reviews_b/.env.example`
```
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=PLACEHOLDER
LLM_MODEL=llama-3.3-70b-versatile
LLM_TIMEOUT_SECONDS=30
DATABASE_URL=postgresql://USER:PASSWORD@HOST.neon.tech/delphi?sslmode=require
REVIEWS_TABLE=feedback_survey
PORT=8103
```

`frontend/.env.local.example`
```
NEXT_PUBLIC_ORCHESTRATOR_URL=http://localhost:8000
```

**Root `.gitignore` must include** (so real keys are never committed):
```
.env
*.env
!.env.example
!*.env.example
frontend/.env.local
.venv/
__pycache__/
*.pyc
node_modules/
.next/
```

The user fills in `LLM_API_KEY` (one key, repeated) and `DATABASE_URL` (Neon). Services start with placeholders and will only error on the first real LLM/DB call until the values are set — expected.

---

## 6. Shared Libraries (LLM, DB, A2A)

### 6.1 `delphi_common/llm.py`

An OpenAI-compatible async LLM client used by every service.

```python
import os
from openai import AsyncOpenAI

_client = None
def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=os.environ["LLM_BASE_URL"],
                              api_key=os.environ["LLM_API_KEY"])
    return _client

async def execute_prompt(system_prompt: str, user_prompt: str, *, model: str = "",
                         temperature: float = 0.2, max_tokens: int = 700) -> str:
    """Single-shot completion. Raises on failure; callers decide fallback."""
    import asyncio
    timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))
    model = model or os.environ["LLM_MODEL"]
    resp = await asyncio.wait_for(
        _get_client().chat.completions.create(
            model=model, temperature=temperature, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_prompt}]),
        timeout=timeout)
    return (resp.choices[0].message.content or "").strip()

def stream_prompt(system_prompt: str, user_prompt: str, *, model: str = "",
                  temperature: float = 0.3, max_tokens: int = 700):
    """Async generator yielding text chunks. Used by the synthesizer for SSE."""
    async def _gen():
        model_ = model or os.environ["LLM_MODEL"]
        stream = await _get_client().chat.completions.create(
            model=model_, temperature=temperature, max_tokens=max_tokens, stream=True,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_prompt}])
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    return _gen()
```

> **Provider swap:** to use Anthropic or Gemini natively, replace `_get_client`/calls with that SDK. OpenAI-compatible mode covers Groq, OpenRouter, Together, OpenAI, and local servers with no code change — just env vars.

### 6.2 `delphi_common/db.py`

Thin async Postgres client over `asyncpg`, exposing an interface that preserves the original three-write pattern. Uses a shared connection pool.

```python
import asyncpg, os
from typing import Any

_pool = None
async def _get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=5)
    return _pool

class PostgresClient:
    async def query_rows(self, table: str, filters: list[dict] | None = None,
                         columns: str = "*", limit: int | None = None,
                         order_by: str | None = None) -> list[dict]:
        where, args = "", []
        if filters:
            clauses = []
            for i, f in enumerate(filters, 1):
                op = {"eq": "=", "gte": ">=", "lte": "<=", "like": "LIKE"}[f["op"]]
                clauses.append(f'"{f["column"]}" {op} ${i}'); args.append(f["value"])
            where = "WHERE " + " AND ".join(clauses)
        order = f'ORDER BY {order_by}' if order_by else ""
        lim = f'LIMIT {int(limit)}' if limit else ""
        sql = f'SELECT {columns} FROM "{table}" {where} {order} {lim}'
        pool = await _get_pool()
        async with pool.acquire() as c:
            return [dict(r) for r in await c.fetch(sql, *args)]

    async def insert_rows(self, table: str, rows: list[dict]) -> int:
        if not rows: return 0
        cols = list(rows[0].keys())
        collist = ", ".join(f'"{c}"' for c in cols)
        pool = await _get_pool(); n = 0
        async with pool.acquire() as c:
            for r in rows:
                ph = ", ".join(f"${i+1}" for i in range(len(cols)))
                await c.execute(f'INSERT INTO "{table}" ({collist}) VALUES ({ph})',
                                *[r[k] for k in cols]); n += 1
        return n

    async def upsert_rows(self, table: str, rows: list[dict],
                          conflict_columns: list[str], update_columns: list[str]) -> int:
        if not rows: return 0
        cols = list(rows[0].keys()); collist = ", ".join(f'"{c}"' for c in cols)
        conflict = ", ".join(f'"{c}"' for c in conflict_columns)
        sets = ", ".join(f'"{c}"=EXCLUDED."{c}"' for c in update_columns)
        pool = await _get_pool(); n = 0
        async with pool.acquire() as c:
            for r in rows:
                ph = ", ".join(f"${i+1}" for i in range(len(cols)))
                await c.execute(
                    f'INSERT INTO "{table}" ({collist}) VALUES ({ph}) '
                    f'ON CONFLICT ({conflict}) DO UPDATE SET {sets}',
                    *[r[k] for k in cols]); n += 1
        return n
```

All persistence calls are **fire-and-forget** at the node layer (see §10.5): wrap in try/except, log, never raise.

### 6.3 `delphi_common/a2a.py`

A2A server helpers, client, and card models. See §8 for full protocol detail. Key exports:
- `AgentCard`, `AgentSkill` (pydantic models)
- `build_a2a_app(card, handler)` → returns a FastAPI app exposing `GET /.well-known/agent-card.json` and `POST /` (JSON-RPC `message/send`). `handler(prompt: str) -> str` is the agent's async business logic.
- `A2AClient.discover(base_url) -> AgentCard`
- `A2AClient.send(base_url, prompt, request_id) -> str`

---

## 7. Neon Database Schemas

`db/schema.sql` (run once against Neon). All timestamps stored as `TEXT` ISO-8601 UTC for portability (mirrors original) except where noted.

```sql
-- ORCHESTRATOR-OWNED TABLES ------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT,
    domain      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    turn_id      TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    turn_index   INTEGER NOT NULL,
    pm_query     TEXT NOT NULL,
    final_answer TEXT,
    timestamp    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);

CREATE TABLE IF NOT EXISTS agent_calls (
    id         BIGSERIAL PRIMARY KEY,
    turn_id    TEXT NOT NULL,
    call_index INTEGER,
    agent      TEXT,
    activated  BOOLEAN,
    prompt     TEXT,
    raw_text   TEXT,
    success    BOOLEAN,
    error      TEXT,
    timestamp  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_calls_turn ON agent_calls(turn_id);

-- REVIEWS_A-OWNED TABLE (app-store style) ----------------------------------
CREATE TABLE IF NOT EXISTS reviews_store (
    ext_id     TEXT PRIMARY KEY,
    source     TEXT NOT NULL,          -- 'app_store' | 'play_store'
    title      TEXT,
    body       TEXT NOT NULL,
    rating     REAL,                   -- 1..5
    author     TEXT,
    sentiment  TEXT NOT NULL,          -- positive|neutral|negative
    review_dt  TEXT,                   -- when customer wrote it (ISO-8601)
    domain_tag TEXT                    -- optional pre-tag: search|checkout|...
);

-- REVIEWS_B-OWNED TABLE (survey / support feedback) ------------------------
CREATE TABLE IF NOT EXISTS feedback_survey (
    ext_id      TEXT PRIMARY KEY,
    channel     TEXT NOT NULL,         -- 'survey' | 'support_ticket' | 'nps'
    body        TEXT NOT NULL,
    nps_score   INTEGER,               -- 0..10 (nullable)
    order_id    TEXT,
    sentiment   TEXT NOT NULL,
    feedback_dt TEXT,                  -- ISO-8601
    domain_tag  TEXT
);
```

> The NEWS agent has **no table** — it fetches Google News RSS live.

---

## 8. A2A Protocol Implementation

Implements a practical subset of the A2A spec (v0.2.x family): **Agent Card discovery** + **`message/send`** (JSON-RPC 2.0). This matches how real A2A agents advertise capabilities and answer.

### 8.1 Agent Card

Served at `GET /.well-known/agent-card.json` (also alias `GET /.well-known/agent.json` for older clients).

```json
{
  "name": "Store Reviews Agent",
  "description": "Answers questions about app-store and play-store product reviews, including sentiment, themes, and verbatim quotes.",
  "url": "http://localhost:8102/",
  "version": "1.0.0",
  "protocolVersion": "0.2.5",
  "capabilities": { "streaming": false, "pushNotifications": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "skills": [
    {
      "id": "search_reviews",
      "name": "Search product reviews",
      "description": "Find and summarize what customers say about a topic, with sentiment and example quotes.",
      "tags": ["reviews", "sentiment", "quotes"],
      "examples": ["What are people saying about checkout failures?",
                   "Summarize negative reviews about search this month."]
    }
  ]
}
```

### 8.2 `message/send` request (JSON-RPC 2.0, `POST /`)

```json
{
  "jsonrpc": "2.0",
  "id": "delphi-0",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "messageId": "uuid-here",
      "parts": [{ "kind": "text", "text": "<crafted question>" }]
    }
  }
}
```

### 8.3 `message/send` response (synchronous Message result)

```json
{
  "jsonrpc": "2.0",
  "id": "delphi-0",
  "result": {
    "role": "agent",
    "messageId": "uuid-here",
    "kind": "message",
    "parts": [{ "kind": "text", "text": "<agent answer>" }]
  }
}
```

**Error response** (JSON-RPC error object) on failure:
```json
{ "jsonrpc": "2.0", "id": "delphi-0", "error": { "code": -32000, "message": "..." } }
```

### 8.4 Server helper (`build_a2a_app`)

```python
from fastapi import FastAPI, Request
from pydantic import BaseModel
import uuid

class AgentSkill(BaseModel):
    id: str; name: str; description: str
    tags: list[str] = []; examples: list[str] = []

class AgentCard(BaseModel):
    name: str; description: str; url: str; version: str = "1.0.0"
    protocolVersion: str = "0.2.5"
    capabilities: dict = {"streaming": False, "pushNotifications": False}
    defaultInputModes: list[str] = ["text/plain"]
    defaultOutputModes: list[str] = ["text/plain"]
    skills: list[AgentSkill] = []

def build_a2a_app(card: AgentCard, handler) -> FastAPI:
    app = FastAPI(title=card.name)

    @app.get("/.well-known/agent-card.json")
    @app.get("/.well-known/agent.json")
    async def get_card():
        return card.model_dump()

    @app.get("/health")
    async def health(): return {"status": "ok"}

    @app.post("/")
    async def rpc(req: Request):
        body = await req.json()
        rid = body.get("id")
        try:
            if body.get("method") != "message/send":
                raise ValueError(f"Unsupported method: {body.get('method')}")
            parts = body["params"]["message"]["parts"]
            text = next(p["text"] for p in parts if p.get("kind") == "text")
            answer = await handler(text)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "role": "agent", "messageId": str(uuid.uuid4()), "kind": "message",
                "parts": [{"kind": "text", "text": answer}]}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32000, "message": str(e)}}
    return app
```

### 8.5 Client helper (`A2AClient`)

```python
import httpx, uuid

class A2AClient:
    def __init__(self, timeout: float | None = 60.0):
        self._timeout = timeout
        self._cards: dict[str, dict] = {}

    async def discover(self, base_url: str) -> dict:
        if base_url in self._cards: return self._cards[base_url]
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(base_url.rstrip("/") + "/.well-known/agent-card.json")
            r.raise_for_status(); card = r.json()
        self._cards[base_url] = card; return card

    async def send(self, base_url: str, prompt: str, request_id: str) -> str:
        payload = {"jsonrpc": "2.0", "id": request_id, "method": "message/send",
                   "params": {"message": {"role": "user", "messageId": str(uuid.uuid4()),
                                          "parts": [{"kind": "text", "text": prompt}]}}}
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(base_url.rstrip("/") + "/", json=payload)
            r.raise_for_status(); body = r.json()
        if "error" in body:
            raise RuntimeError(body["error"].get("message", "A2A error"))
        parts = body["result"]["parts"]
        return next(p["text"] for p in parts if p.get("kind") == "text")
```

> **Future extension (documented, not built):** `message/stream` — agents would expose SSE streaming with A2A task lifecycle (`working` → `completed`) and the client would consume `text/event-stream`. Not needed because the user watches the synthesizer, not individual agents.

---

## 9. The Three Agents

Each agent: standalone FastAPI app built via `build_a2a_app(card, handler)`. Each has its **own LLM env config** and (for reviews) its **own Neon table**. The `handler(prompt)` is the agent's brain — it fetches its data and answers the crafted sub-question with its own LLM.

### 9.1 NEWS agent (`agents/news/main.py`, port 8101)

- **Data:** Google News RSS. Build RSS URL per topic: `https://news.google.com/rss/search?q={quote(topic)}&hl=en-US&gl=US&ceid=US:en`. Parse with `feedparser`. Default topics from `NEWS_QUERIES` env or a built-in list (`["Amazon", "Target", "Costco", "Kroger", "Instacart", "Walmart"]` — generic retailers).
- **handler(prompt):**
  1. Fetch top ~20 recent headlines across topics (title, source, published, link).
  2. Build a context block of headlines.
  3. LLM call: system = *"You are a market-news analyst. Answer ONLY from the provided headlines. Cite publisher and date. If nothing relevant, say so."*; user = prompt + headlines block.
  4. Return the answer text.
- **Card skill:** `id="market_news"`, examples like *"What's the latest news about our competitors' delivery offerings?"*

### 9.2 REVIEWS_A agent (`agents/reviews_a/main.py`, port 8102)

- **Table:** `reviews_store` (`REVIEWS_TABLE=reviews_store`).
- **handler(prompt):**
  1. Extract keywords from the prompt (simple: lowercase tokens minus stopwords) OR pass the whole prompt.
  2. Query up to ~40 rows: keyword-scored matches first (ILIKE on `body`/`title`), backfilled with a **sentiment-stratified** sample so the LLM sees positive/neutral/negative. Filter to a recent window on `review_dt` if the prompt implies recency.
  3. Build an XML-ish reviews block: `<review id="R001" source="app_store" date="..." rating="1.0" sentiment="negative">body</review>`.
  4. LLM call: system = *"You are a product-reviews analyst. Answer ONLY from the <reviews> provided. Qualify claims ('Based on the reviews provided…'). Include 1–2 short verbatim quotes. Never cite reviews outside the stated window."*
  5. Return answer.
- **Card skill:** `id="search_reviews"` (see §8.1 example).

### 9.3 REVIEWS_B agent (`agents/reviews_b/main.py`, port 8103)

- **Table:** `feedback_survey` (`REVIEWS_TABLE=feedback_survey`).
- Same handler shape as REVIEWS_A but over survey/support feedback. Include `channel`, `nps_score` in the context block. System prompt framed as *"You are a customer-survey & support-feedback analyst…"*.
- **Card skill:** `id="search_feedback"`, examples like *"What are the top reasons for low NPS after delivery?"*

> **Sentiment for seed data** is precomputed and stored (`sentiment` column). Agents do not recompute it. Rating≥4 → positive, ≤2 → negative, ==3 → neutral; for survey use `nps_score` (≥9 promoter/positive, ≤6 detractor/negative, else neutral) or explicit tag in the seed.

**Agent `main.py` skeleton (reviews example):**
```python
import os, functools
from delphi_common.a2a import AgentCard, AgentSkill, build_a2a_app
from delphi_common.db import PostgresClient
from delphi_common.llm import execute_prompt

CARD = AgentCard(
    name="Store Reviews Agent",
    description="Answers questions about app-store product reviews...",
    url=f"http://localhost:{os.environ.get('PORT','8102')}/",
    skills=[AgentSkill(id="search_reviews", name="Search product reviews",
                       description="Find and summarize what customers say...",
                       tags=["reviews","sentiment"],
                       examples=["What are people saying about checkout?"])])

db = PostgresClient()
TABLE = os.environ["REVIEWS_TABLE"]

async def handler(prompt: str) -> str:
    rows = await _sample_reviews(prompt)          # keyword + sentiment-stratified
    block = _to_xml(rows)
    system = ("You are a product-reviews analyst. Answer ONLY from the <reviews> "
              "provided. Qualify claims. Include 1-2 short verbatim quotes.")
    return await execute_prompt(system, f"Question: {prompt}\n\n{block}")

app = build_a2a_app(CARD, handler)
# run: uvicorn main:app --port $PORT
```

---

## 10. Intelligence Layer (LangGraph)

### 10.1 QueryState & Reducers

`orchestrator/intelligence_layer/state.py`

```python
import operator
from typing import Annotated, Optional
from pydantic import BaseModel, Field

class NormalisedResponse(BaseModel):
    agent: str
    call_index: int
    success: bool
    raw_text: str = ""
    error: str = ""
    prompt: str = ""            # crafted question (filled by worker)

class AgentTask(BaseModel):
    """Payload carried by each LangGraph Send to agent_worker."""
    source: str
    call_index: int
    pm_query: str
    domain_context: str = ""
    conversation_history: list[dict] = Field(default_factory=list)
    per_source_history: list[dict] = Field(default_factory=list)  # this source only
    card_skills: list[dict] = Field(default_factory=list)         # this agent's skills
    agent_url: str = ""

class QueryState(BaseModel):
    # Input
    pm_query: str = ""

    # Identity (minted in main.py, NOT the graph)
    session_id: str = ""
    turn_id: str = ""
    turn_index: int = 0

    # Multi-turn history (loaded by main.py on turn 2+)
    conversation_history: list[dict] = Field(default_factory=list)   # {pm_query, final_answer}
    per_source_history: dict = Field(default_factory=dict)           # {source: [{prompt, raw_text}]}

    # Domain
    domain: str = ""
    domain_context: str = ""

    # Source selection
    enabled_sources: list[str] = Field(default_factory=lambda: ["NEWS", "REVIEWS_A", "REVIEWS_B"])

    # Fan-in channels (REDUCERS — concurrent worker writes merge)
    responses: Annotated[list[NormalisedResponse], operator.add] = Field(default_factory=list)
    failed_agents: Annotated[list[str], operator.add] = Field(default_factory=list)

    # Analyser / synthesizer output
    analysis: dict = Field(default_factory=dict)
    final_answer: str = ""

    errors: list[str] = Field(default_factory=list)
```

The `Annotated[..., operator.add]` reducers are what make LangGraph fan-in work: each parallel `agent_worker` returns `{"responses": [one], "failed_agents": [...]}` and LangGraph **concatenates** them into the parent state.

### 10.2 Graph Topology — Fan-out / Fan-in

`orchestrator/intelligence_layer/graph.py`

```python
import functools
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from .state import QueryState, AgentTask
from . import nodes

def build_graph(registry: dict):
    """registry: {source: {"url": str, "skills": list[dict]}} discovered at startup."""
    g = StateGraph(QueryState)
    g.add_node("domain_classifier", nodes.domain_classifier)
    g.add_node("persist_session",   nodes.persist_session)
    g.add_node("source_router",     nodes.source_router)
    g.add_node("agent_worker",      functools.partial(nodes.agent_worker, registry=registry))
    g.add_node("analyser",          nodes.analyser)
    g.add_node("persist_responses", nodes.persist_responses)
    g.add_node("synthesizer",       nodes.synthesizer)
    g.add_node("persist_final",     nodes.persist_final)

    # Conditional entry: classify only when domain is unknown
    def entry(state: QueryState):
        return "domain_classifier" if not state.domain else "source_router"
    g.add_conditional_edges(START, entry, ["domain_classifier", "source_router"])

    g.add_edge("domain_classifier", "persist_session")
    g.add_edge("persist_session",   "source_router")

    # FAN-OUT: one Send per enabled source
    def fan_out(state: QueryState):
        return [
            Send("agent_worker", AgentTask(
                source=s, call_index=i, pm_query=state.pm_query,
                domain_context=state.domain_context,
                conversation_history=state.conversation_history[-5:],
                per_source_history=state.per_source_history.get(s, [])[-3:],
                card_skills=registry.get(s, {}).get("skills", []),
                agent_url=registry.get(s, {}).get("url", "")))
            for i, s in enumerate(state.enabled_sources)
        ]
    g.add_conditional_edges("source_router", fan_out, ["agent_worker"])

    # FAN-IN: LangGraph joins all agent_worker branches before analyser runs once
    g.add_edge("agent_worker",      "analyser")
    g.add_edge("analyser",          "persist_responses")
    g.add_edge("persist_responses", "synthesizer")
    g.add_edge("synthesizer",       "persist_final")
    g.add_edge("persist_final",     END)
    return g.compile()
```

**Why this over `asyncio.gather`:** the parallelism is expressed as graph structure (dynamic `Send` fan-out + reducer fan-in), which is the idiomatic LangGraph map-reduce pattern and is independently observable/traceable per branch. Adding a 4th source is one more registry entry — no topology change.

### 10.3 Nodes — Full Contracts

`orchestrator/intelligence_layer/nodes.py`

**`domain_classifier`** (async, LLM; turn 1 only)
- Reads `pm_query`. Lists `domains/*.md` excluding files starting with `_`. Loads `domains/_domains.md` as advisory context if present.
- Prompt: *"Available domains: {list}. Advisory:\n{index}\n\nUser question: {pm_query}\n\nReply with ONLY the domain name."* Take first word, lowercase; if not in list → `"general"`.
- Loads `domains/{domain}.md` → `domain_context` (empty if missing / general).
- Returns `{"domain": str, "domain_context": str}`.

**`source_router`** (pure Python, every turn)
- Filter `enabled_sources` to known sources `["NEWS","REVIEWS_A","REVIEWS_B"]`; if empty, use all three.
- Returns `{"enabled_sources": [...]}`. (Fan-out happens in the conditional edge, not here.)

**`agent_worker`** (async; runs once per Send, in parallel)
- Signature: `async def agent_worker(task: AgentTask, registry: dict) -> dict`
- **Step 1 — per-source planner (LLM):** build a capabilities block from `task.card_skills`; include `task.domain_context`, last 5 `conversation_history`, last 3 `per_source_history`, and `task.pm_query`. System: *"You are a per-source planner for Delphi. Output ONLY the single question to ask the {source} agent — nothing else."* Wrap in `asyncio.wait_for(timeout=LLM_TIMEOUT)`. On any failure → fall back to `task.pm_query`.
- **Step 2 — A2A call:** `A2AClient().send(task.agent_url, crafted, request_id=f"delphi-{task.call_index}")`.
- On success → `NormalisedResponse(agent=source, call_index, success=True, raw_text=answer, prompt=crafted)`, return `{"responses": [resp]}`.
- On A2A failure → `NormalisedResponse(success=False, error=str(e), prompt=crafted)`, return `{"responses": [resp], "failed_agents": [source]}`.

**`analyser`** (pure Python — NO LLM)
- Split `responses` into successful / failed. Build `unavailability_note` if `failed_agents` (e.g., *"Note: {agents} were unavailable for this question."*).
- Returns `{"analysis": {"raw_responses": [...], "failed_agents": [...], "total_calls": n, "successful_calls": m, "unavailability_note": str}}`.

**`synthesizer`** (async, LLM — **streamed**)
- Two clearly-labelled buckets:
  ```
  {domain_block if domain}
  CONVERSATION HISTORY (context/tone only — do not cite as current data):
    [Turn N] User asked: "…"  Delphi answered: "…"
  CURRENT TURN AGENT DATA (source of truth — answer from these facts only):
    NEWS: {raw_text}
    REVIEWS_A: {raw_text}
    REVIEWS_B: {raw_text}
  User question: "{pm_query}"
  Write a 2-4 sentence, grounded answer. Cite which source supports each claim.
  ```
- Uses `stream_prompt(...)` so `main.py` can forward tokens to SSE. After the stream completes, if `unavailability_note` is non-empty it is appended **deterministically** (not by the LLM).
- Returns `{"final_answer": full_text}`.
- **Streaming detail:** the node itself can call `stream_prompt` and accumulate; `main.py` streams via `graph.astream_events(...)` filtering the synthesizer's chat-model stream (see §12). For a non-streaming fallback, the node just uses `execute_prompt`.

### 10.4 A2A Client Adapter & Card Discovery

`orchestrator/adapters/a2a_client.py` re-exports `delphi_common.a2a.A2AClient`. **Discovery happens at orchestrator startup** (FastAPI lifespan): for each configured `AGENT_*_URL`, call `discover()` and build the `registry`:

```python
registry = {
  "NEWS":      {"url": AGENT_NEWS_URL,      "skills": card_news["skills"]},
  "REVIEWS_A": {"url": AGENT_REVIEWS_A_URL, "skills": card_a["skills"]},
  "REVIEWS_B": {"url": AGENT_REVIEWS_B_URL, "skills": card_b["skills"]},
}
```

If an agent is unreachable at startup, register it with empty skills and let the worker fail gracefully at call time (it becomes a `failed_agent`, disclosed to the user). The **agent cards replace the old `agents.yaml`** — capabilities are discovered at runtime, which is the whole point of A2A.

### 10.5 Persistence — Three-Write Pattern

`orchestrator/intelligence_layer/persistence.py`. All three nodes are **fire-and-forget** (try/except, log, never raise).

- **`persist_session`** (turn 1 only, after classifier): `insert_rows("sessions", [{session_id, user_id=None, domain, created_at}])`. INSERT, never upsert (upsert would reset `created_at`).
- **`persist_responses`** (every turn): two writes —
  1. Turns placeholder: `insert_rows("turns", [{turn_id, session_id, turn_index, pm_query, timestamp}])` (`final_answer` omitted → NULL).
  2. Agent calls — **full roster**: iterate `_ALL_SOURCES = ["NEWS","REVIEWS_A","REVIEWS_B"]` (not just enabled). For enabled+responded sources write real values; toggled-off sources get `activated=False, prompt=None, raw_text=None, success=None, error=None`.
- **`persist_final`** (every turn, after synthesizer): `upsert_rows("turns", [{turn_id, session_id, turn_index, pm_query, timestamp, final_answer}], conflict_columns=["turn_id"], update_columns=["final_answer"])`. **Resend ALL not-null columns** (INSERT-on-conflict semantics).

**DB write traps (do not violate):**
1. `persist_final` must resend all not-null `turns` columns.
2. `sessions` uses INSERT, not upsert.
3. `agent_calls` writes a row for the full `_ALL_SOURCES` roster each turn.

---

## 11. Domains

`orchestrator/domains/`. One `.md` per domain; files prefixed `_` are excluded from the domain list. Content below is authoritative — create these files verbatim (trim/expand prose as needed).

### `_domains.md` (advisory index for the classifier)
```markdown
# Domain Index (advisory)

- **search** — finding products: query relevance, zero/low results, ranking, autocomplete, filters, typos.
- **checkout** — completing a purchase: cart, payment entry, promo codes, order placement errors, funnel drop-off.
- **delivery** — fulfillment after purchase: shipping speed, tracking, delivery windows, pickup, missing/damaged items.
- **returns** — post-purchase reversal: refunds, return labels, exchange flow, refund timing, restocking.
- **payments** — money movement & billing: card declines, saved cards, wallets, gift cards, double charges, refunds to card.
- **account** — identity & profile: login, password reset, MFA, account lockout, profile/address management, loyalty membership.

If none fit, use **general**.
```

### `search.md`
```markdown
# Domain: Search & Discovery
Vocabulary: null/zero results, low-result queries, search reformulation, ranking quality,
autocomplete/type-ahead, misspellings, filters & facets, out-of-stock in results, relevance.
Analysis lens: which queries fail, whether users retry or abandon, CTR from search results.
```

### `checkout.md`
```markdown
# Domain: Checkout
Vocabulary: cart abandonment, payment entry failures, promo/coupon code errors, address entry,
order placement errors, funnel drop-off by step, guest vs. logged-in checkout, tax/fees surprises.
Analysis lens: where in the funnel users drop, error messages seen, retries before abandon.
```

### `delivery.md`
```markdown
# Domain: Delivery & Fulfillment
Vocabulary: shipping speed, delivery windows, tracking accuracy, late/missing deliveries,
damaged items, pickup/curbside, substitutions (grocery), driver/handoff issues.
Analysis lens: on-time rate perception, tracking trust, pickup vs. delivery sentiment.
```

### `returns.md`
```markdown
# Domain: Returns & Refunds
Vocabulary: refund timing, return labels, drop-off/mail-back, exchange flow, restocking fees,
refund to original payment, partial refunds, return policy confusion.
Analysis lens: refund latency complaints, friction in initiating returns, policy clarity.
```

### `payments.md`
```markdown
# Domain: Payments & Billing
Vocabulary: card declines, saved cards, digital wallets, gift/EBT cards, double charges,
authorization holds, refunds to card, billing errors, currency/tax.
Analysis lens: decline reasons, trust in charges, refund-to-card timing.
```

### `account.md`
```markdown
# Domain: Account & Access
Vocabulary: login failures, password reset, MFA/2FA, account lockout, email verification,
profile/address management, loyalty/membership, session expiry.
Analysis lens: login friction, reset success, membership value perception.
```

**Adding a domain:** drop a new `domains/{name}.md`, add a line to `_domains.md`. The classifier discovers it on restart.

---

## 12. Orchestrator App & `/chat` Streaming Handler

`orchestrator/main.py`

**Startup (FastAPI lifespan):** discover all agent cards → build `registry`; build no graph here (graph is cheap; build per request or cache — since it only depends on `registry`, it can be built once at startup and reused).

**`POST /chat`** — form or JSON body: `{ query: str, session_id?: str, sources?: "NEWS,REVIEWS_A,REVIEWS_B" }`. Returns `text/event-stream`.

Handler logic (`_oracle_chat`):

**Turn 1 (no session_id):**
1. Mint `session_id=uuid4()`, `turn_id=uuid4()`, `turn_index=1`.
2. Empty history; `domain=""`, `domain_context=""`.

**Turn 2+ (session_id present):**
1. Mint new `turn_id`.
2. Query `sessions` for locked `domain`; if found, load `domains/{domain}.md` → `domain_context`.
3. Query `turns` for this session; last 5 with non-null `final_answer` → `conversation_history`; `turn_index = max(existing)+1`.
4. Query `agent_calls` for those turn_ids → build `per_source_history` `{source: [{prompt, raw_text}]}`.
5. On any DB error: log, fall back to `domain=""`, empty history (graph re-classifies — safe).

**Source toggles:** parse `sources` CSV → `enabled_sources`.

**Streaming the answer:** run the graph with `astream_events` and forward synthesizer tokens as SSE. Also emit lightweight status events for the UI (optional but nice):

```python
from fastapi.responses import StreamingResponse
import json, uuid

async def _oracle_chat(query, session_id, enabled_sources, request):
    is_turn1 = not session_id
    session_id = session_id or str(uuid.uuid4())
    turn_id = str(uuid.uuid4())
    # ... load history / domain as above -> init_state dict ...

    async def event_stream():
        yield _sse("session", {"session_id": session_id})
        yield _sse("status", {"stage": "classifying" if is_turn1 else "routing"})
        final_parts = []
        async for ev in GRAPH.astream_events(init_state, version="v2"):
            et = ev["event"]; name = ev.get("name", "")
            if et == "on_chain_start" and name == "agent_worker":
                yield _sse("status", {"stage": "agents_working"})
            if et == "on_chat_model_stream" and _is_synth(ev):   # tag synth node
                tok = ev["data"]["chunk"].content
                if tok:
                    final_parts.append(tok)
                    yield _sse("token", {"text": tok})
        yield _sse("done", {"final_answer": "".join(final_parts)})

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"X-Session-Id": session_id})

def _sse(event, data): return f"event: {event}\ndata: {json.dumps(data)}\n\n"
```

> To identify synthesizer token events, tag the synthesizer's model call with LangGraph run metadata/tags (e.g., configure the node with `tags=["synth"]`) and check `ev["tags"]` in `_is_synth`. Non-streaming fallback: `result = await GRAPH.ainvoke(init_state)`, then emit one `done` event with `result["final_answer"]`.

**Also:** `GET /health` → `{"status":"ok"}`. Enable CORS for the Vercel frontend origin.

---

## 13. Frontend (Next.js on Vercel)

Minimal single-page chatbot. Talks to `NEXT_PUBLIC_ORCHESTRATOR_URL`.

- **`app/page.tsx`:** message list + input + source toggle checkboxes (NEWS / REVIEWS_A / REVIEWS_B). On submit, POST to `/chat`, read the SSE stream, append tokens to the streaming assistant bubble. Persist `session_id` in `sessionStorage` (key `delphi_session_id`); send it on subsequent requests.
- **`app/lib/delphi.ts`:** SSE client using `fetch` + `ReadableStream` (since `/chat` is POST). Parse `event:`/`data:` frames; handle `session`, `status`, `token`, `done`.

```ts
export async function* chat(query: string, sources: string[]) {
  const sid = sessionStorage.getItem("delphi_session_id") || "";
  const res = await fetch(`${process.env.NEXT_PUBLIC_ORCHESTRATOR_URL}/chat`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, session_id: sid, sources: sources.join(",") }),
  });
  const reader = res.body!.getReader(); const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    const frames = buf.split("\n\n"); buf = frames.pop() || "";
    for (const f of frames) {
      const ev = f.match(/event: (.*)/)?.[1];
      const data = JSON.parse(f.match(/data: (.*)/)?.[1] || "{}");
      if (ev === "session") sessionStorage.setItem("delphi_session_id", data.session_id);
      yield { ev, data };
    }
  }
}
```

- **Styling:** clean, minimal chat (Tailwind or plain CSS). Show a "thinking" indicator on `status` events and stream `token` events into the current bubble.
- **`.env.local.example`:** `NEXT_PUBLIC_ORCHESTRATOR_URL=http://localhost:8000`.

---

## 14. Seed Data (Fake Reviews)

Static, committed JSON — deterministic, no key needed to seed. Target **~150–250 rows per table**, spread across all 6 domains, across sentiments, and across dates in the last ~90 days (so recency filters work).

**`db/seed_reviews_store.json`** — array of objects matching `reviews_store`:
```json
[
  {"ext_id":"as_0001","source":"app_store","title":"Search never finds anything",
   "body":"I searched for 'AA batteries' and got zero results. Search is broken.",
   "rating":1.0,"author":"jenny_r","sentiment":"negative",
   "review_dt":"2026-06-18T14:22:00Z","domain_tag":"search"},
  {"ext_id":"as_0002","source":"play_store","title":"Checkout keeps failing",
   "body":"Payment page spins forever and my promo code won't apply.",
   "rating":2.0,"author":"marcus88","sentiment":"negative",
   "review_dt":"2026-06-25T09:10:00Z","domain_tag":"checkout"},
  {"ext_id":"as_0003","source":"app_store","title":"Love the pickup flow",
   "body":"Curbside pickup was fast and the app tracking was accurate.",
   "rating":5.0,"author":"dana_k","sentiment":"positive",
   "review_dt":"2026-06-28T17:40:00Z","domain_tag":"delivery"}
]
```

**`db/seed_feedback_survey.json`** — array matching `feedback_survey`:
```json
[
  {"ext_id":"sv_0001","channel":"nps","body":"Return took three weeks to refund. Frustrating.",
   "nps_score":3,"order_id":"ORD-91822","sentiment":"negative",
   "feedback_dt":"2026-06-20T11:00:00Z","domain_tag":"returns"},
  {"ext_id":"sv_0002","channel":"survey","body":"Login with MFA is smooth now, thanks.",
   "nps_score":9,"order_id":null,"sentiment":"positive",
   "feedback_dt":"2026-06-27T08:30:00Z","domain_tag":"account"},
  {"ext_id":"sv_0003","channel":"support_ticket","body":"Card was double-charged on one order.",
   "nps_score":2,"order_id":"ORD-90011","sentiment":"negative",
   "feedback_dt":"2026-06-30T15:05:00Z","domain_tag":"payments"}
]
```

> When building, generate the full ~200-row datasets (an LLM can produce them once and commit the JSON). Ensure a realistic mix: ~40% negative, ~25% neutral, ~35% positive; cover every domain; vary dates across the window.

**`db/seed.py`:** read each JSON, `INSERT ... ON CONFLICT (ext_id) DO NOTHING` into the matching table via `delphi_common.db`. Idempotent.

Run:
```bash
psql "$DATABASE_URL" -f db/schema.sql        # create tables
python db/seed.py                            # load fake reviews
```

---

## 15. Local Development & Run Script

Each service has its own `.env` (copy from `.env.example`, fill `LLM_API_KEY`). Install `libs/delphi_common` editable in each venv (or one shared venv).

**`scripts/run_all.sh`:**
```bash
#!/usr/bin/env bash
set -e
( cd agents/news      && uvicorn main:app --port 8101 ) &
( cd agents/reviews_a && uvicorn main:app --port 8102 ) &
( cd agents/reviews_b && uvicorn main:app --port 8103 ) &
sleep 2   # let agents publish their cards
( cd orchestrator     && uvicorn main:app --port 8000 ) &
( cd frontend         && npm run dev ) &
wait
```

Order matters: agents up first (so the orchestrator can discover cards at startup). Frontend at `http://localhost:3000`.

---

## 16. Deployment

- **Frontend → Vercel.** Import `frontend/`. Set `NEXT_PUBLIC_ORCHESTRATOR_URL` to the deployed orchestrator URL.
- **Backend (orchestrator + 3 agents) → Render or Railway** (free tier). Reasons: they are **long-running** services making chained LLM calls; Vercel serverless timeouts (and the awkwardness of 4 Python services) make it a poor fit for the backend. Each service = one Render/Railway service with its own env vars. Because all four share `delphi_common`, set each service's **root directory to the repo root** and build with `pip install ./libs/delphi_common && pip install -r <service>/requirements.txt`, start with `cd <service> && uvicorn main:app --host 0.0.0.0 --port $PORT` (see the shared-library note in §4).
- **Neon** is the shared managed Postgres (serverless). Use the **pooled** connection string.
- Set orchestrator's `AGENT_*_URL` to the deployed agent URLs. Enable CORS for the Vercel domain.
- No Docker required. (Optional: add a `render.yaml` blueprint describing the four services.)

**If you insist on all-Vercel:** deploy each service as a separate Vercel Python project (serverless function exposing the same routes), accept per-invocation timeout limits, and use a fast model (e.g., Groq). Documented as an option; Render/Railway is recommended.

---

## 17. Testing Strategy

`orchestrator/tests/` — no network, no live LLM, runs fast. `conftest.py` sets `asyncio_mode = "auto"`.

**Mock pattern:** patch where names are bound — `patch("intelligence_layer.nodes.execute_prompt", ...)` and patch the A2A client's `send` to return canned text. Provide a fake `registry` with the three sources.

**`test_graph_smoke.py`:**
1. Full flow returns a non-empty `final_answer`.
2. Partial failure (one agent's `send` raises) → flow completes, that source in `failed_agents`, `unavailability_note` present in `final_answer`.
3. Fan-out breadth: with all three enabled, `responses` has 3 entries (reducer merged); with one disabled, 2.
4. Conditional entry: pre-set `domain` skips the classifier (assert classifier LLM not called).
5. Conversation history threads through unchanged.
6. Domain classifier loads `domains/search.md` into `domain_context` for a search-y question.

**`test_persistence.py`:** with a mocked `PostgresClient`, assert the three-write traps: `persist_final` resends all not-null columns; `agent_calls` writes 3 rows (full roster) even when 1 source disabled; `sessions` uses insert not upsert.

**Optional live smoke (manual):** start all services, ask *"What are customers saying about checkout this week?"*, verify a `turns` row with non-empty `final_answer` and 3 `agent_calls` rows.

Run:
```bash
cd orchestrator && pip install -r requirements.txt pytest pytest-asyncio && pytest tests/ -v
```

---

## 18. Invariants — Do Not Violate

1. **IDs minted in `main.py`**, not the graph: `session_id`, `turn_id`, `turn_index` are inputs to `ainvoke/astream`.
2. **Conditional entry uses falsy check** (`not state.domain`) — catches `""` and `None`; doubles as the re-classify fallback if `persist_session` silently failed.
3. **Fan-out is LangGraph `Send` + reducer**, not `asyncio.gather`. `responses`/`failed_agents` are `Annotated[..., operator.add]`.
4. **Fire-and-forget persistence:** persistence nodes log and never raise; a DB failure must not break the chat response.
5. **Per-source planner** sees only that agent's card skills and that source's history; raw `pm_query` is the fallback.
6. **Analyser does no LLM work**; the `unavailability_note` is appended deterministically by the synthesizer after the LLM stream.
7. **Agent capabilities come from A2A cards** discovered at runtime — not a static manifest.
8. **Three DB write traps** (§10.5): resend all not-null `turns` cols on final upsert; `sessions` insert-only; `agent_calls` full roster every turn.
9. **A2A = `message/send`** between orchestrator and agents; SSE streaming is only orchestrator→browser.
10. **Each agent is independently deployable** with its own LLM env and (for reviews) its own table; orchestrator never reads an agent's table directly.
11. **Date filtering uses the customer-authored date** (`review_dt` / `feedback_dt`), never an ingestion timestamp.

---

## 19. README Content

Public README must be **generic** — no employer name. Suggested sections:

- **Tagline:** "Delphi — a multi-agent customer-intelligence layer that federates siloed feedback sources behind one chat interface."
- **The problem** (generic story from §1: multiple independent feedback systems, each with its own agent).
- **Architecture diagram** (from §2) + a sentence on LangGraph fan-out/fan-in and A2A.
- **What it demonstrates** (bullets from §1).
- **Tech stack** (§3).
- **Run locally** (§15) + **seed data** (§14) + env setup (§5).
- **Deployment** (§16).
- **Design notes**: why `Send` over `asyncio.gather`; why A2A cards for discovery; three-write persistence; deterministic unavailability disclosure.
- **Screenshots / GIF** of the streaming chat.

Do **not** reference any specific company, internal URL, App ID, or proprietary system anywhere in the repo.

---

## 20. Glossary

| Term | Meaning |
|---|---|
| Delphi | This project — the orchestration / intelligence layer |
| Agent | A standalone A2A server answering NL questions about one data source |
| A2A | Agent-to-Agent protocol: agent cards + JSON-RPC (`message/send`) |
| Agent Card | JSON at `/.well-known/agent-card.json` advertising name, skills, capabilities |
| Fan-out / fan-in | LangGraph `Send` (dynamic parallel branches) + reducer merge |
| Per-source planner | LLM call that crafts a tailored sub-question for one agent from its card skills |
| Synthesizer | LLM node fusing all agent answers into one grounded response (streamed) |
| Analyser | Pure-Python node packaging results + unavailability disclosure |
| Three-write pattern | persist_session / persist_responses / persist_final, all fire-and-forget |
| Domain | Business-topic classification (search, checkout, …), locked per session at turn 1 |
| session_id / turn_id / turn_index | Conversation id / single Q&A id / order within a session |
| NEWS / REVIEWS_A / REVIEWS_B | The three source agents |
```
