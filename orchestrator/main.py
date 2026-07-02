"""Delphi orchestrator — FastAPI app, POST /chat (SSE), /health.

Startup: discover all agent cards -> registry -> build the graph once.
Per request: mint ids, load history/domain, run the graph, stream synth tokens.
IDs (session_id/turn_id/turn_index) are minted HERE, not in the graph (§18.1).
"""
import json
import logging
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from adapters.a2a_client import A2AClient
from config import AGENT_URLS, ALL_SOURCES, CORS_ORIGINS
from intelligence_layer.graph import build_graph
from intelligence_layer.nodes import _load_domain_context
from delphi_common.db import PostgresClient

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("delphi.orchestrator")

GRAPH = None
REGISTRY: dict = {}
db = PostgresClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global GRAPH, REGISTRY
    client = A2AClient()
    registry: dict = {}
    for source in ALL_SOURCES:
        url = AGENT_URLS[source]
        try:
            card = await client.discover(url)
            registry[source] = {"url": url, "skills": card.get("skills", [])}
            log.info("Discovered %s at %s (%d skills)", source, url, len(card.get("skills", [])))
        except Exception as e:
            log.warning("Could not discover %s at %s: %s (registering with no skills)", source, url, e)
            registry[source] = {"url": url, "skills": []}
    REGISTRY = registry
    GRAPH = build_graph(registry)
    yield


app = FastAPI(title="Delphi Orchestrator", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    # No cookies/credentials are used; keeping this False lets allow_origins=["*"]
    # stay valid (browsers reject wildcard origin WITH credentials).
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-Id"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _is_synth(ev: dict) -> bool:
    return "synth" in (ev.get("tags") or [])


async def _load_history(session_id: str) -> dict:
    """Turn 2+: load locked domain, conversation history, per-source history.

    On ANY DB error, fall back to a fresh classify (domain="", empty history).
    """
    ctx = {
        "domain": "",
        "domain_context": "",
        "conversation_history": [],
        "per_source_history": {},
        "turn_index": 1,
    }
    try:
        sessions = await db.query_rows(
            "sessions", filters=[{"column": "session_id", "op": "eq", "value": session_id}], limit=1
        )
        if sessions:
            domain = sessions[0].get("domain") or ""
            ctx["domain"] = domain
            ctx["domain_context"] = _load_domain_context(domain)

        turns = await db.query_rows(
            "turns",
            filters=[{"column": "session_id", "op": "eq", "value": session_id}],
            order_by="turn_index ASC",
        )
        if turns:
            ctx["turn_index"] = max(t["turn_index"] for t in turns) + 1
            answered = [t for t in turns if t.get("final_answer")]
            ctx["conversation_history"] = [
                {"pm_query": t["pm_query"], "final_answer": t["final_answer"]}
                for t in answered[-5:]
            ]
            turn_ids = [t["turn_id"] for t in turns]
            per_source: dict[str, list] = {}
            for tid in turn_ids:
                calls = await db.query_rows(
                    "agent_calls",
                    filters=[{"column": "turn_id", "op": "eq", "value": tid}],
                    order_by="call_index ASC",
                )
                for c in calls:
                    if c.get("activated") and c.get("raw_text"):
                        per_source.setdefault(c["agent"], []).append(
                            {"prompt": c.get("prompt", ""), "raw_text": c.get("raw_text", "")}
                        )
            ctx["per_source_history"] = per_source
    except Exception as e:
        log.warning("history load failed for %s, re-classifying: %s", session_id, e)
        return {
            "domain": "",
            "domain_context": "",
            "conversation_history": [],
            "per_source_history": {},
            "turn_index": 1,
        }
    return ctx


async def _read_body(request: Request) -> dict:
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        return await request.json()
    form = await request.form()
    return dict(form)


@app.post("/chat")
async def chat(request: Request):
    body = await _read_body(request)
    query = (body.get("query") or "").strip()
    session_id = (body.get("session_id") or "").strip()
    sources_csv = (body.get("sources") or "").strip()

    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)

    enabled_sources = (
        [s.strip().upper() for s in sources_csv.split(",") if s.strip()]
        if sources_csv
        else list(ALL_SOURCES)
    )
    enabled_sources = [s for s in enabled_sources if s in ALL_SOURCES] or list(ALL_SOURCES)

    is_turn1 = not session_id
    session_id = session_id or str(uuid.uuid4())
    turn_id = str(uuid.uuid4())

    if is_turn1:
        hist = {"domain": "", "domain_context": "", "conversation_history": [],
                "per_source_history": {}, "turn_index": 1}
    else:
        hist = await _load_history(session_id)

    init_state = {
        "pm_query": query,
        "session_id": session_id,
        "turn_id": turn_id,
        "turn_index": hist["turn_index"],
        "conversation_history": hist["conversation_history"],
        "per_source_history": hist["per_source_history"],
        "domain": hist["domain"],
        "domain_context": hist["domain_context"],
        "enabled_sources": enabled_sources,
    }

    async def event_stream():
        yield _sse("session", {"session_id": session_id})
        yield _sse("status", {"stage": "classifying" if not init_state["domain"] else "routing"})
        streamed = ""
        node_final = ""
        try:
            async for ev in GRAPH.astream_events(init_state, version="v2"):
                et = ev["event"]
                name = ev.get("name", "")
                if et == "on_chain_start" and name == "agent_worker":
                    yield _sse("status", {"stage": "agents_working"})
                elif et == "on_chat_model_stream" and _is_synth(ev):
                    tok = ev["data"]["chunk"].content
                    if tok:
                        streamed += tok
                        yield _sse("token", {"text": tok})
                elif et == "on_chain_end" and name == "synthesizer":
                    out = ev["data"].get("output") or {}
                    if isinstance(out, dict):
                        node_final = out.get("final_answer", "") or ""
        except Exception as e:
            log.error("graph stream failed: %s", e)
            yield _sse("error", {"message": str(e)})
            yield _sse("done", {"final_answer": streamed})
            return

        # The deterministic unavailability note is appended after the token
        # stream — emit the suffix so the browser's bubble matches final_answer.
        final_answer = node_final or streamed
        suffix = final_answer[len(streamed):] if final_answer.startswith(streamed) else ""
        if suffix:
            yield _sse("token", {"text": suffix})
        yield _sse("done", {"final_answer": final_answer})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Session-Id": session_id, "Cache-Control": "no-cache"},
    )
