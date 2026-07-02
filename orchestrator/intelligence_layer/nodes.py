"""All LangGraph node functions + the per-source planner.

Node roster:
  domain_classifier  (LLM, turn 1 only)   -> {domain, domain_context}
  persist_session    (fire-and-forget)    -> {}
  source_router      (pure python)        -> {enabled_sources}
  agent_worker       (LLM planner + A2A)  -> {responses, [failed_agents]}  [parallel]
  analyser           (pure python, NO LLM)-> {analysis}
  persist_responses  (fire-and-forget)    -> {}
  synthesizer        (LLM, streamed)      -> {final_answer}
  persist_final      (fire-and-forget)    -> {}
"""
import asyncio
import logging
import os
from pathlib import Path

from delphi_common.llm import execute_prompt

from adapters.a2a_client import A2AClient
from config import ALL_SOURCES, LLM_TIMEOUT_SECONDS
from . import persistence
from .state import AgentTask, NormalisedResponse, QueryState

log = logging.getLogger("delphi.nodes")

DOMAINS_DIR = Path(__file__).resolve().parent.parent / "domains"
_a2a = A2AClient()


# --------------------------------------------------------------------------- #
# Domain helpers
# --------------------------------------------------------------------------- #
def _list_domains() -> list[str]:
    if not DOMAINS_DIR.is_dir():
        return []
    return sorted(
        p.stem for p in DOMAINS_DIR.glob("*.md") if not p.name.startswith("_")
    )


def _load_domain_context(domain: str) -> str:
    if not domain or domain == "general":
        return ""
    path = DOMAINS_DIR / f"{domain}.md"
    return path.read_text() if path.is_file() else ""


# --------------------------------------------------------------------------- #
# domain_classifier (LLM, turn 1 only)
# --------------------------------------------------------------------------- #
async def domain_classifier(state: QueryState) -> dict:
    domains = _list_domains()
    if not domains:
        return {"domain": "general", "domain_context": ""}

    index_path = DOMAINS_DIR / "_domains.md"
    index = index_path.read_text() if index_path.is_file() else ""
    system = "You are a domain classifier. Reply with ONLY the single domain name."
    user = (
        f"Available domains: {', '.join(domains)}.\n"
        f"Advisory:\n{index}\n\n"
        f"User question: {state.pm_query}\n\n"
        "Reply with ONLY the domain name."
    )
    try:
        raw = await execute_prompt(system, user, temperature=0.0, max_tokens=16)
        domain = raw.strip().split()[0].lower().strip(".,:;\"'") if raw.strip() else "general"
        if domain not in domains:
            domain = "general"
    except Exception as e:
        log.warning("domain_classifier LLM failed: %s", e)
        domain = "general"

    return {"domain": domain, "domain_context": _load_domain_context(domain)}


# --------------------------------------------------------------------------- #
# persist_session (fire-and-forget)
# --------------------------------------------------------------------------- #
async def persist_session(state: QueryState) -> dict:
    await persistence.persist_session(state.session_id, state.domain)
    return {}


# --------------------------------------------------------------------------- #
# source_router (pure python)
# --------------------------------------------------------------------------- #
def source_router(state: QueryState) -> dict:
    enabled = [s for s in state.enabled_sources if s in ALL_SOURCES]
    if not enabled:
        enabled = list(ALL_SOURCES)
    return {"enabled_sources": enabled}


# --------------------------------------------------------------------------- #
# agent_worker (per-source planner LLM + A2A message/send) — runs in parallel
# --------------------------------------------------------------------------- #
def _capabilities_block(card_skills: list[dict]) -> str:
    if not card_skills:
        return "(no advertised skills)"
    lines = []
    for s in card_skills:
        ex = "; ".join(s.get("examples", []))
        lines.append(f"- {s.get('name', s.get('id', '?'))}: {s.get('description', '')}"
                     + (f" (e.g. {ex})" if ex else ""))
    return "\n".join(lines)


async def _plan_subquestion(task: AgentTask) -> str:
    caps = _capabilities_block(task.card_skills)
    history_lines = []
    for h in task.conversation_history[-5:]:
        q = h.get("pm_query", "")
        a = h.get("final_answer", "")
        history_lines.append(f'  User: "{q}"  Delphi: "{a}"')
    src_lines = []
    for h in task.per_source_history[-3:]:
        src_lines.append(f'  asked: "{h.get("prompt", "")}" -> "{h.get("raw_text", "")}"')

    system = (
        f"You are a per-source planner for Delphi. You craft the single best question "
        f"to ask the {task.source} agent given its capabilities. "
        f"Output ONLY the single question to ask the {task.source} agent — nothing else."
    )
    user = (
        f"{task.source} agent capabilities:\n{caps}\n\n"
        + (f"Domain context:\n{task.domain_context}\n\n" if task.domain_context else "")
        + (f"Recent conversation:\n" + "\n".join(history_lines) + "\n\n" if history_lines else "")
        + (f"Prior {task.source} exchanges:\n" + "\n".join(src_lines) + "\n\n" if src_lines else "")
        + f"User question: {task.pm_query}\n\n"
        f"Write the single question to send to the {task.source} agent."
    )
    try:
        crafted = await asyncio.wait_for(
            execute_prompt(system, user, temperature=0.2, max_tokens=120),
            timeout=LLM_TIMEOUT_SECONDS,
        )
        return crafted.strip() or task.pm_query
    except Exception as e:
        log.warning("planner for %s failed, falling back to pm_query: %s", task.source, e)
        return task.pm_query


async def agent_worker(task: AgentTask, registry: dict) -> dict:
    crafted = await _plan_subquestion(task)
    agent_url = task.agent_url or registry.get(task.source, {}).get("url", "")
    try:
        answer = await _a2a.send(
            agent_url, crafted, request_id=f"delphi-{task.call_index}"
        )
        resp = NormalisedResponse(
            agent=task.source, call_index=task.call_index, success=True,
            raw_text=answer, prompt=crafted,
        )
        return {"responses": [resp]}
    except Exception as e:
        log.warning("agent_worker A2A call to %s failed: %s", task.source, e)
        resp = NormalisedResponse(
            agent=task.source, call_index=task.call_index, success=False,
            error=str(e), prompt=crafted,
        )
        return {"responses": [resp], "failed_agents": [task.source]}


# --------------------------------------------------------------------------- #
# analyser (pure python — NO LLM)
# --------------------------------------------------------------------------- #
def analyser(state: QueryState) -> dict:
    successful = [r for r in state.responses if r.success]
    failed = [r for r in state.responses if not r.success]
    unavailability_note = ""
    if state.failed_agents:
        agents = ", ".join(sorted(set(state.failed_agents)))
        unavailability_note = f"Note: {agents} were unavailable for this question."

    analysis = {
        "raw_responses": [r.model_dump() for r in state.responses],
        "failed_agents": sorted(set(state.failed_agents)),
        "total_calls": len(state.responses),
        "successful_calls": len(successful),
        "unavailability_note": unavailability_note,
    }
    return {"analysis": analysis}


# --------------------------------------------------------------------------- #
# persist_responses (fire-and-forget)
# --------------------------------------------------------------------------- #
async def persist_responses(state: QueryState) -> dict:
    await persistence.persist_responses(state)
    return {}


# --------------------------------------------------------------------------- #
# synthesizer (LLM — streamed; token events tagged "synth")
# --------------------------------------------------------------------------- #
_SYNTH_TAG = "synth"
_synth_model = None


def _get_synth_model():
    """Lazy langchain ChatOpenAI so graph.astream_events emits tagged token events."""
    global _synth_model
    if _synth_model is None:
        from langchain_openai import ChatOpenAI

        # Mirror the shared client's optional thinking control (e.g. Gemini 2.5).
        effort = os.environ.get("LLM_REASONING_EFFORT", "")
        extra = {"reasoning_effort": effort} if effort else {}
        _synth_model = ChatOpenAI(
            model=os.environ["LLM_MODEL"],
            base_url=os.environ["LLM_BASE_URL"],
            api_key=os.environ["LLM_API_KEY"],
            temperature=0.3,
            max_tokens=700,
            streaming=True,
            **extra,
        ).with_config(tags=[_SYNTH_TAG])
    return _synth_model


def _build_synth_prompt(state: QueryState) -> tuple[str, str]:
    by_source = {r.agent: r for r in state.responses}
    analysis = state.analysis or {}

    blocks = []
    if state.domain_context:
        blocks.append(f"DOMAIN CONTEXT:\n{state.domain_context}")

    if state.conversation_history:
        hist = ["CONVERSATION HISTORY (context/tone only — do not cite as current data):"]
        for i, h in enumerate(state.conversation_history[-5:], 1):
            hist.append(f'  [Turn {i}] User asked: "{h.get("pm_query", "")}"  '
                        f'Delphi answered: "{h.get("final_answer", "")}"')
        blocks.append("\n".join(hist))

    data = ["CURRENT TURN AGENT DATA (source of truth — answer from these facts only):"]
    for source in ALL_SOURCES:
        r = by_source.get(source)
        if r and r.success:
            data.append(f"  {source}: {r.raw_text}")
        elif r and not r.success:
            data.append(f"  {source}: (unavailable)")
    blocks.append("\n".join(data))

    system = (
        "You are Delphi, a customer-intelligence synthesizer. Fuse the agent data into "
        "one grounded, factual answer. Answer ONLY from the CURRENT TURN AGENT DATA. "
        "Cite which source supports each claim (NEWS / REVIEWS_A / REVIEWS_B). "
        "Write 2-4 sentences. Do not invent facts."
    )
    user = (
        "\n\n".join(blocks)
        + f'\n\nUser question: "{state.pm_query}"\n'
        "Write a 2-4 sentence, grounded answer. Cite which source supports each claim."
    )
    return system, user


async def _run_synth(system: str, user: str) -> str:
    """Stream the synthesis inside the node so astream_events surfaces tokens."""
    from langchain_core.messages import HumanMessage, SystemMessage

    parts: list[str] = []
    async for chunk in _get_synth_model().astream(
        [SystemMessage(content=system), HumanMessage(content=user)]
    ):
        if chunk.content:
            parts.append(chunk.content)
    return "".join(parts).strip()


async def synthesizer(state: QueryState) -> dict:
    system, user = _build_synth_prompt(state)
    try:
        text = await _run_synth(system, user)
    except Exception as e:
        log.warning("synthesizer streaming failed, falling back: %s", e)
        try:
            text = await execute_prompt(system, user, temperature=0.3)
        except Exception as e2:
            log.error("synthesizer fallback failed: %s", e2)
            text = "I couldn't generate an answer from the available sources right now."

    # Append the unavailability note deterministically (not by the LLM).
    note = (state.analysis or {}).get("unavailability_note", "")
    if note:
        text = f"{text}\n\n{note}" if text else note
    return {"final_answer": text}


# --------------------------------------------------------------------------- #
# persist_final (fire-and-forget)
# --------------------------------------------------------------------------- #
async def persist_final(state: QueryState) -> dict:
    await persistence.persist_final(state)
    return {}
