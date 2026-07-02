"""QueryState, AgentTask, NormalisedResponse — the LangGraph channel schema.

The Annotated[..., operator.add] reducers are what make fan-in work: each
parallel agent_worker returns {"responses": [one], "failed_agents": [...]}
and LangGraph concatenates them into the parent state.
"""
import operator
from typing import Annotated

from pydantic import BaseModel, Field


class NormalisedResponse(BaseModel):
    agent: str
    call_index: int
    success: bool
    raw_text: str = ""
    error: str = ""
    prompt: str = ""  # crafted question (filled by worker)


class AgentTask(BaseModel):
    """Payload carried by each LangGraph Send to agent_worker."""

    source: str
    call_index: int
    pm_query: str
    domain_context: str = ""
    conversation_history: list[dict] = Field(default_factory=list)
    per_source_history: list[dict] = Field(default_factory=list)  # this source only
    card_skills: list[dict] = Field(default_factory=list)  # this agent's skills
    agent_url: str = ""


class QueryState(BaseModel):
    # Input
    pm_query: str = ""

    # Identity (minted in main.py, NOT the graph)
    session_id: str = ""
    turn_id: str = ""
    turn_index: int = 0

    # Multi-turn history (loaded by main.py on turn 2+)
    conversation_history: list[dict] = Field(default_factory=list)  # {pm_query, final_answer}
    per_source_history: dict = Field(default_factory=dict)  # {source: [{prompt, raw_text}]}

    # Domain
    domain: str = ""
    domain_context: str = ""

    # Source selection
    enabled_sources: list[str] = Field(
        default_factory=lambda: ["NEWS", "REVIEWS_A", "REVIEWS_B"]
    )

    # Fan-in channels (REDUCERS — concurrent worker writes merge)
    responses: Annotated[list[NormalisedResponse], operator.add] = Field(default_factory=list)
    failed_agents: Annotated[list[str], operator.add] = Field(default_factory=list)

    # Analyser / synthesizer output
    analysis: dict = Field(default_factory=dict)
    final_answer: str = ""

    errors: list[str] = Field(default_factory=list)
