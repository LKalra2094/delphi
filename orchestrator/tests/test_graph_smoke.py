"""Graph smoke tests — no network, no live LLM. Patch where names are bound."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intelligence_layer import nodes
from intelligence_layer.graph import build_graph

FAKE_REGISTRY = {
    "NEWS": {"url": "http://news.test", "skills": [{"id": "market_news", "name": "News"}]},
    "REVIEWS_A": {"url": "http://reviews_a.test", "skills": [{"id": "search_reviews", "name": "Reviews A"}]},
    "REVIEWS_B": {"url": "http://reviews_b.test", "skills": [{"id": "search_feedback", "name": "Reviews B"}]},
}


def _base_state(**overrides):
    state = {
        "pm_query": "What are customers saying about checkout this week?",
        "session_id": "sess-1",
        "turn_id": "turn-1",
        "turn_index": 1,
        "conversation_history": [],
        "per_source_history": {},
        "domain": "",
        "domain_context": "",
        "enabled_sources": ["NEWS", "REVIEWS_A", "REVIEWS_B"],
    }
    state.update(overrides)
    return state


async def _fake_send(base_url, prompt, request_id):
    if "news" in base_url:
        return f"NEWS answer for: {prompt}"
    if "reviews_a" in base_url:
        return f"REVIEWS_A answer for: {prompt}"
    return f"REVIEWS_B answer for: {prompt}"


async def _run(state, *, send=None, classify_return="checkout"):
    with patch.object(nodes, "execute_prompt", new=AsyncMock(return_value=classify_return)), \
         patch.object(nodes, "_run_synth", new=AsyncMock(return_value="Grounded answer citing sources.")), \
         patch.object(nodes._a2a, "send", new=AsyncMock(side_effect=send or _fake_send)):
        graph = build_graph(FAKE_REGISTRY)
        return await graph.ainvoke(state)


@pytest.mark.asyncio
async def test_full_flow_non_empty_answer():
    result = await _run(_base_state())
    assert result["final_answer"]
    assert len(result["responses"]) == 3


@pytest.mark.asyncio
async def test_partial_failure_disclosed():
    async def send(base_url, prompt, request_id):
        if "news" in base_url:
            raise RuntimeError("NEWS is down")
        return await _fake_send(base_url, prompt, request_id)

    result = await _run(_base_state(), send=send)
    assert "NEWS" in result["failed_agents"]
    assert "unavailable" in result["final_answer"].lower()
    # flow still completes with the other two
    assert len(result["responses"]) == 3


@pytest.mark.asyncio
async def test_fan_out_breadth():
    full = await _run(_base_state())
    assert len(full["responses"]) == 3

    two = await _run(_base_state(enabled_sources=["NEWS", "REVIEWS_A"]))
    assert len(two["responses"]) == 2
    assert {r.agent for r in two["responses"]} == {"NEWS", "REVIEWS_A"}


@pytest.mark.asyncio
async def test_preset_domain_skips_classifier():
    classifier_spy = AsyncMock(return_value={"domain": "search", "domain_context": "X"})
    with patch.object(nodes, "domain_classifier", new=classifier_spy), \
         patch.object(nodes, "execute_prompt", new=AsyncMock(return_value="q")), \
         patch.object(nodes, "_run_synth", new=AsyncMock(return_value="answer")), \
         patch.object(nodes._a2a, "send", new=AsyncMock(side_effect=_fake_send)):
        graph = build_graph(FAKE_REGISTRY)
        result = await graph.ainvoke(_base_state(domain="checkout", domain_context="preset"))
    classifier_spy.assert_not_called()
    assert result["domain"] == "checkout"


@pytest.mark.asyncio
async def test_conversation_history_threads_through():
    history = [{"pm_query": "prior q", "final_answer": "prior a"}]
    result = await _run(_base_state(domain="checkout", conversation_history=history))
    assert result["conversation_history"] == history


@pytest.mark.asyncio
async def test_classifier_loads_domain_context():
    # execute_prompt returns "search" -> classifier picks search domain, loads search.md
    result = await _run(_base_state(pm_query="Why do product searches return zero results?"),
                        classify_return="search")
    assert result["domain"] == "search"
    assert "Search & Discovery" in result["domain_context"]
