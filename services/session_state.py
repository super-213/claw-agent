"""Helpers for loading and persisting session conversation state."""
from __future__ import annotations

from typing import Any

from core import ConversationManager


def load_session_conversation(
    session: dict[str, Any],
    system_prompt: str,
    conversation: ConversationManager | None = None,
) -> ConversationManager:
    conversation = conversation or ConversationManager(system_prompt)
    stored_messages = session.get("messages", [])
    if stored_messages:
        conversation.load_messages(
            stored_messages,
            active_node_id=session.get("active_node_id"),
        )
    conversation.load_summary(
        session.get("summary", ""),
        session.get("summarized_until", 1),
    )
    return conversation


def conversation_messages_for_save(
    conversation: ConversationManager,
) -> list[dict[str, Any]]:
    return conversation.get_all_messages()


def last_context_nodes(messages: list[dict[str, Any]]) -> Any | None:
    for message in reversed(messages):
        if message.get("role") == "assistant" and "context_nodes" in message:
            return message["context_nodes"]
    return None
