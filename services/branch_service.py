"""Session branch operations used by the web API."""
from __future__ import annotations

from typing import Any

from .session_state import (
    conversation_messages_for_save,
    load_session_conversation,
)


def create_session_branch(
    store: Any,
    system_prompt: str,
    session_id: str,
    branch_point_node_id: str,
) -> dict[str, Any]:
    session = store.load_session(session_id)
    conversation = load_session_conversation(session, system_prompt)
    result = conversation.create_branch(branch_point_node_id)

    store.save_messages(
        session_id,
        conversation_messages_for_save(conversation),
        active_node_id=conversation.active_node_id,
    )

    return {
        "ok": True,
        "branch_node_id": result["branch_node_id"],
        "ancestor_path": result["ancestor_path"],
    }


def switch_session_branch(
    store: Any,
    system_prompt: str,
    session_id: str,
    target_node_id: str,
) -> dict[str, Any]:
    session = store.load_session(session_id)
    conversation = load_session_conversation(session, system_prompt)
    path_messages = conversation.switch_branch(target_node_id)

    store.save_messages(
        session_id,
        conversation_messages_for_save(conversation),
        active_node_id=conversation.active_node_id,
    )

    return {
        "ok": True,
        "active_node_id": target_node_id,
        "messages": path_messages,
    }


def get_session_tree(
    store: Any,
    system_prompt: str,
    session_id: str,
) -> dict[str, Any]:
    session = store.load_session(session_id)
    conversation = load_session_conversation(session, system_prompt)

    if conversation.branch_engine is None:
        return {"nodes": [], "active_node_id": None}

    active_node_id = conversation.active_node_id or ""
    return {
        "nodes": conversation.branch_engine.get_tree_summary(active_node_id),
        "active_node_id": active_node_id,
    }


def delete_session_branch(
    store: Any,
    system_prompt: str,
    session_id: str,
    node_id: str,
) -> dict[str, Any]:
    session = store.load_session(session_id)
    conversation = load_session_conversation(session, system_prompt)

    if conversation.branch_engine is None:
        raise ValueError(f"节点不存在: {node_id}")

    active_node_id = conversation.active_node_id or ""
    removed_count = conversation.branch_engine.delete_branch(node_id, active_node_id)

    store.save_messages(
        session_id,
        conversation_messages_for_save(conversation),
        active_node_id=active_node_id,
    )

    return {
        "ok": True,
        "removed_count": removed_count,
    }
