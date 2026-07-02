"""REVIEWS_B agent — post-purchase survey / support feedback (Neon) + LLM. Port 8103."""
import os
import re
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from delphi_common.a2a import AgentCard, AgentSkill, build_a2a_app
from delphi_common.db import PostgresClient
from delphi_common.llm import execute_prompt

TABLE = os.environ.get("REVIEWS_TABLE", "feedback_survey")
db = PostgresClient()

CARD = AgentCard(
    name="Survey & Support Feedback Agent",
    description=(
        "Answers questions about post-purchase surveys, NPS, and support-ticket "
        "feedback, including sentiment, themes, and verbatim quotes."
    ),
    url=f"http://localhost:{os.environ.get('PORT', '8103')}/",
    skills=[
        AgentSkill(
            id="search_feedback",
            name="Search survey & support feedback",
            description=(
                "Find and summarize customer survey, NPS, and support feedback on a "
                "topic, with sentiment and example quotes."
            ),
            tags=["survey", "nps", "support", "sentiment"],
            examples=[
                "What are the top reasons for low NPS after delivery?",
                "Summarize support tickets about refunds this month.",
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
    "top", "main", "most", "common", "issues", "issue", "problems", "problem", "reasons",
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


async def _sample_feedback(prompt: str, limit: int = 40) -> list[dict]:
    cutoff = _recency_cutoff(prompt)
    date_filter = [{"column": "feedback_dt", "op": "gte", "value": cutoff}] if cutoff else []
    seen: dict[str, dict] = {}

    # 1) keyword-scored matches (ILIKE on body)
    for kw in _keywords(prompt):
        rows = await db.query_rows(
            TABLE,
            filters=[{"column": "body", "op": "ilike", "value": f"%{kw}%"}] + date_filter,
            limit=20,
            order_by="feedback_dt DESC",
        )
        for r in rows:
            seen.setdefault(r["ext_id"], r)
        if len(seen) >= limit:
            break

    # 2) sentiment-stratified backfill
    if len(seen) < limit:
        per = max(4, (limit - len(seen)) // 3 + 4)
        for sentiment in ("negative", "neutral", "positive"):
            rows = await db.query_rows(
                TABLE,
                filters=[{"column": "sentiment", "op": "eq", "value": sentiment}] + date_filter,
                limit=per,
                order_by="feedback_dt DESC",
            )
            for r in rows:
                seen.setdefault(r["ext_id"], r)

    return list(seen.values())[:limit]


def _to_xml(rows: list[dict]) -> str:
    if not rows:
        return "<feedback>(no matching feedback found)</feedback>"
    parts = ["<feedback>"]
    for r in rows:
        nps = r.get("nps_score")
        nps_attr = f' nps="{nps}"' if nps is not None else ""
        parts.append(
            f'  <item id="{r["ext_id"]}" channel="{r.get("channel", "")}" '
            f'date="{r.get("feedback_dt", "")}"{nps_attr} '
            f'sentiment="{r.get("sentiment", "")}">{r.get("body", "")}</item>'
        )
    parts.append("</feedback>")
    return "\n".join(parts)


async def handler(prompt: str) -> str:
    rows = await _sample_feedback(prompt)
    block = _to_xml(rows)
    system = (
        "You are a customer-survey & support-feedback analyst. Answer ONLY from the "
        "<feedback> provided. Qualify claims (e.g. 'Based on the feedback provided...'). "
        "Reference NPS scores and channels where relevant. Include 1-2 short verbatim "
        "quotes. Never cite feedback outside the stated window."
    )
    return await execute_prompt(system, f"Question: {prompt}\n\n{block}")


app = build_a2a_app(CARD, handler)
