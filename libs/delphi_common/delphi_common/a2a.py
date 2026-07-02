"""A2A protocol: agent-card models, server builder, and client.

Implements a practical subset of the A2A spec (v0.2.x family): Agent Card
discovery + `message/send` (JSON-RPC 2.0). See build spec §8.
"""
import uuid

import httpx
from fastapi import FastAPI, Request
from pydantic import BaseModel


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = []
    examples: list[str] = []


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str = "1.0.0"
    protocolVersion: str = "0.2.5"
    capabilities: dict = {"streaming": False, "pushNotifications": False}
    defaultInputModes: list[str] = ["text/plain"]
    defaultOutputModes: list[str] = ["text/plain"]
    skills: list[AgentSkill] = []


def build_a2a_app(card: AgentCard, handler) -> FastAPI:
    """Return a FastAPI app exposing agent-card discovery + `message/send`.

    handler(prompt: str) -> str is the agent's async business logic.
    """
    app = FastAPI(title=card.name)

    @app.get("/.well-known/agent-card.json")
    @app.get("/.well-known/agent.json")
    async def get_card():
        return card.model_dump()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/")
    async def rpc(req: Request):
        body = await req.json()
        rid = body.get("id")
        try:
            if body.get("method") != "message/send":
                raise ValueError(f"Unsupported method: {body.get('method')}")
            parts = body["params"]["message"]["parts"]
            text = next(p["text"] for p in parts if p.get("kind") == "text")
            answer = await handler(text)
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "role": "agent",
                    "messageId": str(uuid.uuid4()),
                    "kind": "message",
                    "parts": [{"kind": "text", "text": answer}],
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32000, "message": str(e)},
            }

    return app


class A2AClient:
    def __init__(self, timeout: float | None = 60.0):
        self._timeout = timeout
        self._cards: dict[str, dict] = {}

    async def discover(self, base_url: str) -> dict:
        if base_url in self._cards:
            return self._cards[base_url]
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(base_url.rstrip("/") + "/.well-known/agent-card.json")
            r.raise_for_status()
            card = r.json()
        self._cards[base_url] = card
        return card

    async def send(self, base_url: str, prompt: str, request_id: str) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "messageId": str(uuid.uuid4()),
                    "parts": [{"kind": "text", "text": prompt}],
                }
            },
        }
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(base_url.rstrip("/") + "/", json=payload)
            r.raise_for_status()
            body = r.json()
        if "error" in body:
            raise RuntimeError(body["error"].get("message", "A2A error"))
        parts = body["result"]["parts"]
        return next(p["text"] for p in parts if p.get("kind") == "text")
