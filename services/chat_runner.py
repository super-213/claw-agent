"""Chat request execution for the web API."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any, Callable, AsyncIterator

from .session_state import (
    conversation_messages_for_save,
    last_context_nodes,
    load_session_conversation,
)


class SessionRunLocks:
    """Per-session async run locks for chat requests."""

    def __init__(self):
        self._guard = Lock()
        self._locks: dict[str, Lock] = {}

    @asynccontextmanager
    async def locked(self, session_id: str):
        with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = Lock()
                self._locks[session_id] = lock

        while not lock.acquire(blocking=False):
            await asyncio.sleep(0.05)
        try:
            yield
        finally:
            lock.release()


def stream_event(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


async def run_chat(
    *,
    store: Any,
    build_orchestrator: Callable[[], Any],
    session_run_locks: SessionRunLocks,
    session_id: str,
    user_message: str,
    attachments: list[dict[str, Any]],
    images: list[dict[str, Any]],
) -> dict[str, Any]:
    async with session_run_locks.locked(session_id):
        session = await asyncio.to_thread(store.load_session, session_id)
        orchestrator = build_orchestrator()
        conversation = orchestrator.conversation
        load_session_conversation(session, "", conversation)

        before_len = len(conversation.get_messages())

        async with orchestrator.llm_client:
            await orchestrator.process_user_input_async(
                user_message,
                attachments=attachments,
                images=images,
            )

        messages = conversation.get_messages()
        await _save_conversation(store, session_id, conversation)

    return {
        "messages": messages[before_len:],
        "session_id": session_id,
    }


async def stream_chat_events(
    *,
    store: Any,
    build_orchestrator: Callable[[], Any],
    session_run_locks: SessionRunLocks,
    session_id: str,
    user_message: str,
    attachments: list[dict[str, Any]],
    images: list[dict[str, Any]],
) -> AsyncIterator[str]:
    try:
        yield stream_event({
            "type": "step",
            "stage": "request",
            "message": "开始处理请求",
        })

        async with session_run_locks.locked(session_id):
            session = await asyncio.to_thread(store.load_session, session_id)
            orchestrator = build_orchestrator()
            conversation = orchestrator.conversation
            load_session_conversation(session, "", conversation)

            before_len = len(conversation.get_messages())

            async with orchestrator.llm_client:
                async for event in orchestrator.process_user_input_stream_async(
                    user_message,
                    attachments=attachments,
                    images=images,
                ):
                    if event.get("type") != "done":
                        yield stream_event(event)

            messages = conversation.get_messages()
            yield stream_event({
                "type": "step",
                "stage": "save",
                "message": "保存会话记录",
            })
            await _save_conversation(store, session_id, conversation)

            new_messages = messages[before_len:]
            done_event = {
                "type": "done",
                "stage": "done",
                "message": "响应完成",
                "messages": new_messages,
                "session_id": session_id,
            }
            context_nodes = last_context_nodes(new_messages)
            if context_nodes is not None:
                done_event["context_nodes"] = context_nodes
            if conversation.active_node_id is not None:
                done_event["active_node_id"] = conversation.active_node_id
            yield stream_event(done_event)
    except Exception as e:
        yield stream_event({
            "type": "error",
            "stage": "error",
            "message": str(e),
        })


async def _save_conversation(
    store: Any,
    session_id: str,
    conversation: Any,
) -> None:
    await asyncio.to_thread(
        store.save_messages,
        session_id,
        conversation_messages_for_save(conversation),
        summary=conversation.get_summary(),
        summarized_until=conversation.get_summarized_until(),
        active_node_id=conversation.active_node_id,
    )
