"""build_graph() — LangGraph topology with Send fan-out / reducer fan-in.

Why Send over asyncio.gather: parallelism is expressed as graph structure
(dynamic Send fan-out + reducer fan-in), the idiomatic LangGraph map-reduce
pattern, independently observable/traceable per branch. Adding a 4th source is
one registry entry — no topology change.
"""
import functools

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from . import nodes
from .state import AgentTask, QueryState


def build_graph(registry: dict):
    """registry: {source: {"url": str, "skills": list[dict]}} discovered at startup."""
    g = StateGraph(QueryState)
    g.add_node("domain_classifier", nodes.domain_classifier)
    g.add_node("persist_session", nodes.persist_session)
    g.add_node("source_router", nodes.source_router)
    g.add_node("agent_worker", functools.partial(nodes.agent_worker, registry=registry))
    g.add_node("analyser", nodes.analyser)
    g.add_node("persist_responses", nodes.persist_responses)
    g.add_node("synthesizer", nodes.synthesizer)
    g.add_node("persist_final", nodes.persist_final)

    # Conditional entry: classify only when domain is unknown (falsy check).
    def entry(state: QueryState):
        return "domain_classifier" if not state.domain else "source_router"

    g.add_conditional_edges(START, entry, ["domain_classifier", "source_router"])

    g.add_edge("domain_classifier", "persist_session")
    g.add_edge("persist_session", "source_router")

    # FAN-OUT: one Send per enabled source.
    def fan_out(state: QueryState):
        return [
            Send(
                "agent_worker",
                AgentTask(
                    source=s,
                    call_index=i,
                    pm_query=state.pm_query,
                    domain_context=state.domain_context,
                    conversation_history=state.conversation_history[-5:],
                    per_source_history=state.per_source_history.get(s, [])[-3:],
                    card_skills=registry.get(s, {}).get("skills", []),
                    agent_url=registry.get(s, {}).get("url", ""),
                ),
            )
            for i, s in enumerate(state.enabled_sources)
        ]

    g.add_conditional_edges("source_router", fan_out, ["agent_worker"])

    # FAN-IN: LangGraph joins all agent_worker branches before analyser runs once.
    g.add_edge("agent_worker", "analyser")
    g.add_edge("analyser", "persist_responses")
    g.add_edge("persist_responses", "synthesizer")
    g.add_edge("synthesizer", "persist_final")
    g.add_edge("persist_final", END)
    return g.compile()
