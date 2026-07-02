"""Persistence trap tests — mocked PostgresClient. See §10.5 / §18.8."""
from unittest.mock import AsyncMock, patch

import pytest

from intelligence_layer import persistence
from intelligence_layer.state import NormalisedResponse, QueryState


def _fake_db():
    db = AsyncMock()
    db.insert_rows = AsyncMock(return_value=1)
    db.upsert_rows = AsyncMock(return_value=1)
    return db


def _state(**overrides):
    base = dict(
        pm_query="What about checkout?",
        session_id="sess-1",
        turn_id="turn-1",
        turn_index=2,
        final_answer="Grounded answer.",
        responses=[
            NormalisedResponse(agent="NEWS", call_index=0, success=True,
                               raw_text="news text", prompt="news q"),
            NormalisedResponse(agent="REVIEWS_A", call_index=1, success=True,
                               raw_text="reviews text", prompt="reviews q"),
        ],
    )
    base.update(overrides)
    return QueryState(**base)


@pytest.mark.asyncio
async def test_persist_final_resends_all_not_null_columns():
    db = _fake_db()
    with patch.object(persistence, "db", db):
        await persistence.persist_final(_state())
    db.upsert_rows.assert_awaited_once()
    args, kwargs = db.upsert_rows.call_args
    table, rows = args[0], args[1]
    assert table == "turns"
    row = rows[0]
    for col in ("turn_id", "session_id", "turn_index", "pm_query", "timestamp", "final_answer"):
        assert col in row and row[col] is not None
    assert kwargs["conflict_columns"] == ["turn_id"]


@pytest.mark.asyncio
async def test_agent_calls_full_roster_even_when_disabled():
    db = _fake_db()
    # Only NEWS + REVIEWS_A responded; REVIEWS_B toggled off.
    with patch.object(persistence, "db", db):
        await persistence.persist_responses(_state())

    # find the agent_calls insert
    agent_calls_rows = None
    for call in db.insert_rows.call_args_list:
        if call.args[0] == "agent_calls":
            agent_calls_rows = call.args[1]
    assert agent_calls_rows is not None
    assert len(agent_calls_rows) == 3  # full roster
    by_agent = {r["agent"]: r for r in agent_calls_rows}
    assert set(by_agent) == {"NEWS", "REVIEWS_A", "REVIEWS_B"}
    assert by_agent["NEWS"]["activated"] is True
    assert by_agent["REVIEWS_B"]["activated"] is False
    assert by_agent["REVIEWS_B"]["prompt"] is None


@pytest.mark.asyncio
async def test_sessions_uses_insert_not_upsert():
    db = _fake_db()
    with patch.object(persistence, "db", db):
        await persistence.persist_session("sess-1", "checkout")
    db.insert_rows.assert_awaited_once()
    assert db.insert_rows.call_args.args[0] == "sessions"
    db.upsert_rows.assert_not_awaited()
