"""REVIEWS_A agent — app-store style reviews (Neon table) + LLM. Port 8102."""
import os
import re
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from delphi_common.a2a import AgentCard, AgentSkill, build_a2a_app
from delphi_common.db import PostgresClient
from delphi_common.llm import execute_prompt

TABLE = os.environ.get("REVIEWS_TABLE", "reviews_store")
db = PostgresClient()

CARD = AgentCard(
    name="Store Reviews Agent",
    description=(
        "Answers questions about app-store and play-store product reviews, "
        "including sentiment, themes, and verbatim quotes."
    ),
    url=f"http://localhost:{os.environ.get('PORT', '8102')}/",
    skills=[
        AgentSkill(
            id="search_reviews",
            name="Search product reviews",
            description=(
                "Find and summarize what customers say about a topic, with "
                "sentiment and example quotes."
            ),
            tags=["reviews", "sentiment", "quotes"],
            examples=[
                "What are people saying about checkout failures?",
                "Summarize negative reviews about search this month.",
            ],
        )
    ],
)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "to",
    "of", "in", "on", "for", "with", "about", "what", "whats", "how", "why", "our",
    "we", "us", "you", "your", "this", "that", "these", "those", "do", "does", "did",
    "customers", "customer", "people", "saying", "say", "tell", "me", "give", "show",
    "summarize", "summary", "reviews", "review", "feedback", "any", "there", "their",
    "have", "has", "had", "get", "got", "week", "month", "recent", "recently", "lately",
    "top", "main", "most", "common", "issues", "issue", "problems", "problem",
}
_RECENCY = re.compile(r"\b(this week|this month|recent|recently|lately|past week|past month|last week|last month)\b", re.I)


def _keywords(prompt: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", prompt.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 2][:6]


def _recency_cutoff(prompt: str) -> str | None:
    m = _RECENCY.search(prompt)
    if not m:
        return None
    text = m.group(0).lower()
    days = 7 if "week" in text else 30
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


async def _sample_reviews(prompt: str, limit: int = 40) -> list[dict]:
    cutoff = _recency_cutoff(prompt)
    date_filter = [{"column": "review_dt", "op": "gte", "value": cutoff}] if cutoff else []
    seen: dict[str, dict] = {}

    # 1) keyword-scored matches (ILIKE on body/title)
    for kw in _keywords(prompt):
        for col in ("body", "title"):
            rows = await db.query_rows(
                TABLE,
                filters=[{"column": col, "op": "ilike", "value": f"%{kw}%"}] + date_filter,
                limit=20,
                order_by="review_dt DESC",
            )
            for r in rows:
                seen.setdefault(r["ext_id"], r)
        if len(seen) >= limit:
            break

    # 2) sentiment-stratified backfill so the LLM sees the full spectrum
    if len(seen) < limit:
        per = max(4, (limit - len(seen)) // 3 + 4)
        for sentiment in ("negative", "neutral", "positive"):
            rows = await db.query_rows(
                TABLE,
                filters=[{"column": "sentiment", "op": "eq", "value": sentiment}] + date_filter,
                limit=per,
                order_by="review_dt DESC",
            )
            for r in rows:
                seen.setdefault(r["ext_id"], r)

    return list(seen.values())[:limit]


def _to_xml(rows: list[dict]) -> str:
    if not rows:
        return "<reviews>(no matching reviews found)</reviews>"
    parts = ["<reviews>"]
    for r in rows:
        parts.append(
            f'  <review id="{r["ext_id"]}" source="{r.get("source", "")}" '
            f'date="{r.get("review_dt", "")}" rating="{r.get("rating", "")}" '
            f'sentiment="{r.get("sentiment", "")}">{r.get("body", "")}</review>'
        )
    parts.append("</reviews>")
    return "\n".join(parts)


async def handler(prompt: str) -> str:
    rows = await _sample_reviews(prompt)
    block = _to_xml(rows)
    system = (
        "You are a product-reviews analyst. Answer ONLY from the <reviews> provided. "
        "Qualify claims (e.g. 'Based on the reviews provided...'). Include 1-2 short "
        "verbatim quotes. Never cite reviews outside the stated window."
    )
    return await execute_prompt(system, f"Question: {prompt}\n\n{block}")


app = build_a2a_app(CARD, handler)
