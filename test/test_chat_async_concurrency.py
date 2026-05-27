"""Chat streaming concurrency tests."""
import asyncio
import json
import threading
from unittest.mock import patch

import httpx

from services import ConversationStore
from web_app import app


class ConcurrentFakeLLM:
    """Slow async LLM stub that records overlapping stream calls."""

    active = 0
    max_active = 0
    lock = threading.Lock()

    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 30):
        self.model = model

    async def astream_chat(self, messages):
        user_message = next(
            (
                msg.get("content", "")
                for msg in reversed(messages)
                if msg.get("role") == "user"
            ),
            "",
        )
        with self.lock:
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
        try:
            for part in ["[完成] ", user_message, " ok"]:
                await asyncio.sleep(0.05)
                yield part
        finally:
            with self.lock:
                type(self).active -= 1

    async def achat(self, messages):
        parts = []
        async for part in self.astream_chat(messages):
            parts.append(part)
        return "".join(parts)

    def stream_chat(self, messages):
        yield "[完成] sync ok"

    def chat(self, messages):
        return "[完成] sync ok"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None

    async def aclose(self):
        return None

    def close(self):
        return None


async def _collect_stream(client, session_id: str, message: str):
    events = []
    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"session_id": session_id, "message": message},
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.strip():
                events.append(json.loads(line))
    return events


def test_stream_chat_runs_different_sessions_concurrently(tmp_path):
    async def run():
        app.config["TESTING"] = True
        store = ConversationStore(tmp_path)
        ConcurrentFakeLLM.active = 0
        ConcurrentFakeLLM.max_active = 0

        with (
            patch("web_app.store", store),
            patch("web_app.LLMClient", ConcurrentFakeLLM),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                session_a = (await client.post("/api/sessions")).json()["id"]
                session_b = (await client.post("/api/sessions")).json()["id"]

                events_a, events_b = await asyncio.gather(
                    _collect_stream(client, session_a, "alpha"),
                    _collect_stream(client, session_b, "beta"),
                )

        assert ConcurrentFakeLLM.max_active >= 2

        done_a = next(event for event in events_a if event.get("type") == "done")
        done_b = next(event for event in events_b if event.get("type") == "done")
        assert done_a["session_id"] == session_a
        assert done_b["session_id"] == session_b
        assert any("[完成] alpha ok" == msg.get("content") for msg in done_a["messages"])
        assert any("[完成] beta ok" == msg.get("content") for msg in done_b["messages"])

    asyncio.run(run())
