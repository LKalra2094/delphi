"""Three-write pattern — persist_session / persist_responses / persist_final.

ALL three are fire-and-forget: they try/except, log, and never raise. A DB
failure must never break the chat response (invariant §18.4).

DB write traps (do not violate, §10.5):
  1. persist_final resends ALL not-null `turns` columns (INSERT-on-conflict).
  2. `sessions` uses INSERT, never upsert (upsert would reset created_at).
  3. `agent_calls` writes a row for the full _ALL_SOURCES roster every turn.
"""
import logging
from datetime import datetime, timezone

from delphi_common.db import PostgresClient

from config import ALL_SOURCES

log = logging.getLogger("delphi.persistence")

_ALL_SOURCES = ALL_SOURCES
db = PostgresClient()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def persist_session(session_id: str, domain: str) -> None:
    """Turn 1 only, after the classifier. INSERT (never upsert)."""
    try:
        await db.insert_rows(
            "sessions",
            [{
                "session_id": session_id,
                "user_id": None,
                "domain": domain,
                "created_at": _now(),
            }],
        )
    except Exception as e:  # fire-and-forget
        log.warning("persist_session failed: %s", e)


async def persist_responses(state) -> None:
    """Every turn: turns placeholder + full-roster agent_calls."""
    ts = _now()
    # 1) turns placeholder (final_answer omitted -> NULL)
    try:
        await db.insert_rows(
            "turns",
            [{
                "turn_id": state.turn_id,
                "session_id": state.session_id,
                "turn_index": state.turn_index,
                "pm_query": state.pm_query,
                "timestamp": ts,
            }],
        )
    except Exception as e:
        log.warning("persist_responses(turns) failed: %s", e)

    # 2) agent_calls — full roster, even for toggled-off sources
    by_source = {r.agent: r for r in state.responses}
    rows = []
    for i, source in enumerate(_ALL_SOURCES):
        if source in by_source:
            r = by_source[source]
            rows.append({
                "turn_id": state.turn_id,
                "call_index": r.call_index,
                "agent": source,
                "activated": True,
                "prompt": r.prompt or None,
                "raw_text": r.raw_text or None,
                "success": r.success,
                "error": r.error or None,
                "timestamp": ts,
            })
        else:
            rows.append({
                "turn_id": state.turn_id,
                "call_index": i,
                "agent": source,
                "activated": False,
                "prompt": None,
                "raw_text": None,
                "success": None,
                "error": None,
                "timestamp": ts,
            })
    try:
        await db.insert_rows("agent_calls", rows)
    except Exception as e:
        log.warning("persist_responses(agent_calls) failed: %s", e)


async def persist_final(state) -> None:
    """Every turn, after synthesizer. Upsert turns, resending ALL not-null cols."""
    try:
        await db.upsert_rows(
            "turns",
            [{
                "turn_id": state.turn_id,
                "session_id": state.session_id,
                "turn_index": state.turn_index,
                "pm_query": state.pm_query,
                "timestamp": _now(),
                "final_answer": state.final_answer,
            }],
            conflict_columns=["turn_id"],
            update_columns=["final_answer"],
        )
    except Exception as e:
        log.warning("persist_final failed: %s", e)
