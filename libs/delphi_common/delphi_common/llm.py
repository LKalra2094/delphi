"""OpenAI-compatible async LLM client used by every Delphi service.

Provider-agnostic: point LLM_BASE_URL at Groq / OpenRouter / Together / OpenAI /
a local server. Swap to a native SDK (Anthropic, Gemini) by replacing _get_client.
"""
import asyncio
import os

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=os.environ["LLM_BASE_URL"],
            api_key=os.environ["LLM_API_KEY"],
        )
    return _client


def _extra_kwargs(reasoning_effort: str | None) -> dict:
    """Optional provider passthroughs.

    `reasoning_effort` controls "thinking" models (e.g. Gemini 2.5, OpenAI o-series).
    Set env LLM_REASONING_EFFORT=none to disable thinking so short deterministic
    calls (classifier/planner) can't have their token budget eaten by hidden
    reasoning. Omitted entirely when unset, so non-thinking providers are unaffected.
    """
    val = reasoning_effort if reasoning_effort is not None else os.environ.get(
        "LLM_REASONING_EFFORT", ""
    )
    return {"reasoning_effort": val} if val else {}


async def execute_prompt(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str = "",
    temperature: float = 0.2,
    max_tokens: int = 700,
    reasoning_effort: str | None = None,
) -> str:
    """Single-shot completion. Raises on failure; callers decide fallback."""
    timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))
    model = model or os.environ["LLM_MODEL"]
    resp = await asyncio.wait_for(
        _get_client().chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **_extra_kwargs(reasoning_effort),
        ),
        timeout=timeout,
    )
    return (resp.choices[0].message.content or "").strip()


def stream_prompt(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str = "",
    temperature: float = 0.3,
    max_tokens: int = 700,
    reasoning_effort: str | None = None,
):
    """Async generator yielding text chunks. Used by the synthesizer for SSE."""

    async def _gen():
        model_ = model or os.environ["LLM_MODEL"]
        stream = await _get_client().chat.completions.create(
            model=model_,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **_extra_kwargs(reasoning_effort),
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    return _gen()
