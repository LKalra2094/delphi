"""Env config, agent registry keys, and analysis constants for the orchestrator."""
import os

# Canonical source keys. Order defines fan-out order and the agent_calls roster.
ALL_SOURCES = ["NEWS", "REVIEWS_A", "REVIEWS_B"]

AGENT_URLS = {
    "NEWS": os.environ.get("AGENT_NEWS_URL", "http://localhost:8101"),
    "REVIEWS_A": os.environ.get("AGENT_REVIEWS_A_URL", "http://localhost:8102"),
    "REVIEWS_B": os.environ.get("AGENT_REVIEWS_B_URL", "http://localhost:8103"),
}

PORT = int(os.environ.get("PORT", "8000"))
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))

# CORS: allow the Vercel frontend origin(s). "*" is fine for a portfolio demo.
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]
