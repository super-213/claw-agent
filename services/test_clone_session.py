"""Tests for ConversationStore.clone_session() - branch tree preservation"""

import json
import tempfile
import uuid
from pathlib import Path

import pytest

from services.conversation_store import ConversationStore


@pytest.fixture
def store(tmp_path):
    """Create a ConversationStore with a temporary directory."""
    return ConversationStore(root_dir=tmp_path)


@pytest.fixture
def branched_session(store):
    """Create a session with a branch tree structure for testing."""
    # Create a session
    session = store.create_session("You are a helpful assistant.", title="Test Session")
    session_id = session["id"]

    # Build a branched message tree:
    #   root (system) -> n1 (user) -> n2 (assistant)
    #                               -> n3 (user, branch from n1)
    root_node_id = session["messages"][0]["node_id"]
    n1_id = uuid.uuid4().hex
    n2_id = uuid.uuid4().hex
    n3_id = uuid.uuid4().hex

    messages = [
        {
            "node_id": root_node_id,
            "parent_id": None,
            "role": "system",
            "content": "You are a helpful assistant.",
        },
        {
            "node_id": n1_id,
            "parent_id": root_node_id,
            "role": "user",
            "content": "Hello",
        },
        {
            "node_id": n2_id,
            "parent_id": n1_id,
            "role": "assistant",
            "content": "Hi there!",
        },
        {
            "node_id": n3_id,
            "parent_id": n1_id,
            "role": "user",
            "content": "Branch message",
        },
    ]

    summarized_nodes = [root_node_id, n1_id]

    store.save_messages(
        session_id,
        messages,
        active_node_id=n2_id,
        summarized_nodes=summarized_nodes,
    )

    return store.load_session(session_id)


def test_clone_preserves_node_ids(store, branched_session):
    """Cloned session messages retain original node_id values."""
    cloned = store.clone_session(branched_session["id"])

    source_node_ids = [m["node_id"] for m in branched_session["messages"]]
    cloned_node_ids = [m["node_id"] for m in cloned["messages"]]

    assert source_node_ids == cloned_node_ids


def test_clone_preserves_parent_ids(store, branched_session):
    """Cloned session messages retain original parent_id values."""
    cloned = store.clone_session(branched_session["id"])

    source_parent_ids = [m.get("parent_id") for m in branched_session["messages"]]
    cloned_parent_ids = [m.get("parent_id") for m in cloned["messages"]]

    assert source_parent_ids == cloned_parent_ids


def test_clone_preserves_active_node_id(store, branched_session):
    """Cloned session retains the active_node_id from the source."""
    cloned = store.clone_session(branched_session["id"])

    assert cloned["active_node_id"] == branched_session["active_node_id"]
    assert cloned["active_node_id"] is not None


def test_clone_preserves_summarized_nodes(store, branched_session):
    """Cloned session retains the summarized_nodes list from the source."""
    cloned = store.clone_session(branched_session["id"])

    assert cloned["summarized_nodes"] == branched_session["summarized_nodes"]
    assert len(cloned["summarized_nodes"]) == 2


def test_clone_gets_new_session_id(store, branched_session):
    """Cloned session gets a new unique session ID."""
    cloned = store.clone_session(branched_session["id"])

    assert cloned["id"] != branched_session["id"]


def test_clone_title_has_suffix(store, branched_session):
    """Cloned session title has '副本' suffix."""
    cloned = store.clone_session(branched_session["id"])

    assert cloned["title"].endswith("副本")


def test_clone_preserves_message_content(store, branched_session):
    """Cloned session messages retain their content."""
    cloned = store.clone_session(branched_session["id"])

    source_contents = [m["content"] for m in branched_session["messages"]]
    cloned_contents = [m["content"] for m in cloned["messages"]]

    assert source_contents == cloned_contents


def test_clone_preserves_tree_structure_integrity(store, branched_session):
    """Cloned session's tree structure is valid (parent_ids reference existing node_ids)."""
    cloned = store.clone_session(branched_session["id"])

    node_ids = {m["node_id"] for m in cloned["messages"]}

    for msg in cloned["messages"]:
        parent_id = msg.get("parent_id")
        if parent_id is not None:
            assert parent_id in node_ids, (
                f"parent_id {parent_id} not found in cloned message node_ids"
            )


def test_clone_summarized_nodes_is_independent_copy(store, branched_session):
    """Modifying cloned summarized_nodes does not affect the source."""
    cloned = store.clone_session(branched_session["id"])

    # Modify the cloned list
    cloned["summarized_nodes"].append("fake_node")

    # Reload source and verify it's unchanged
    source = store.load_session(branched_session["id"])
    assert "fake_node" not in source.get("summarized_nodes", [])


def test_clone_session_without_branches(store):
    """Cloning a session without branches still works correctly."""
    session = store.create_session("System prompt", title="Simple")
    cloned = store.clone_session(session["id"])

    assert cloned["active_node_id"] == session["active_node_id"]
    assert len(cloned["messages"]) == len(session["messages"])
    assert cloned["messages"][0]["node_id"] == session["messages"][0]["node_id"]
    assert cloned["messages"][0]["parent_id"] is None
