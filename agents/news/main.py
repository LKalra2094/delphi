"""NEWS agent — Google News RSS + LLM. A2A server on port 8101."""
import asyncio
import os
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

import feedparser
import httpx

from delphi_common.a2a import AgentCard, AgentSkill, build_a2a_app
from delphi_common.llm import execute_prompt

DEFAULT_TOPICS = ["Amazon", "Target", "Costco", "Kroger", "Instacart", "Walmart"]
TOPICS = [t.strip() for t in os.environ.get("NEWS_QUERIES", "").split(",") if t.strip()] \
    or DEFAULT_TOPICS

CARD = AgentCard(
    name="Market News Agent",
    description=(
        "Answers questions about market and competitor news from live Google News "
        "headlines, citing publisher and date."
    ),
    url=f"http://localhost:{os.environ.get('PORT', '8101')}/",
    skills=[
        AgentSkill(
            id="market_news",
            name="Market & competitor news",
            description=(
                "Summarize recent market/competitor headlines relevant to a topic, "
                "with publisher and date citations."
            ),
            tags=["news", "market", "competitors"],
            examples=[
                "What's the latest news about our competitors' delivery offerings?",
                "Any recent headlines about retail checkout technology?",
            ],
        )
    ],
)


def _rss_url(topic: str) -> str:
    return (
        f"https://news.google.com/rss/search?q={quote(topic)}"
        "&hl=en-US&gl=US&ceid=US:en"
    )


async def _fetch_topic(client: httpx.AsyncClient, topic: str) -> list[dict]:
    try:
        r = await client.get(_rss_url(topic))
        r.raise_for_status()
    except Exception:
        return []
    feed = feedparser.parse(r.text)
    items = []
    for e in feed.entries[:6]:
        source = ""
        if getattr(e, "source", None) is not None:
            source = getattr(e.source, "title", "") or ""
        items.append({
            "topic": topic,
            "title": getattr(e, "title", ""),
            "source": source,
            "published": getattr(e, "published", ""),
            "link": getattr(e, "link", ""),
        })
    return items


async def _fetch_headlines() -> list[dict]:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        batches = await asyncio.gather(*[_fetch_topic(client, t) for t in TOPICS])
    headlines: list[dict] = []
    for b in batches:
        headlines.extend(b)
    return headlines[:20]


def _to_block(headlines: list[dict]) -> str:
    if not headlines:
        return "(no headlines available)"
    lines = []
    for h in headlines:
        src = h["source"] or "Unknown"
        pub = h["published"] or "n.d."
        lines.append(f"- [{h['topic']}] \"{h['title']}\" — {src}, {pub}")
    return "\n".join(lines)


async def handler(prompt: str) -> str:
    headlines = await _fetch_headlines()
    block = _to_block(headlines)
    system = (
        "You are a market-news analyst. Answer ONLY from the provided headlines. "
        "Cite publisher and date. If nothing relevant is present, say so plainly."
    )
    user = f"Question: {prompt}\n\nHEADLINES:\n{block}"
    return await execute_prompt(system, user)


app = build_a2a_app(CARD, handler)
