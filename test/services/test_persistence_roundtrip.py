"""Property-based tests for ConversationStore persistence round-trip.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Tests the following correctness property from the design document:

Property 4: Persistence Round-Trip
For any conversation tree structure T:
- save(T) followed by load() produces a tree structure equivalent to T
- Equivalence means: all nodes' node_id, parent_id, content are the same,
  and active_node_id is the same
"""

import uuid
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, assume, settings, HealthCheck
from hypothesis import strategies as st

from services.conversation_store import ConversationStore
from core.branch_engine import BranchEngine


# ---------------------------------------------------------------------------
# Strategies: generate valid tree-structured messages for persistence testing
# ---------------------------------------------------------------------------

@st.composite
def tree_messages(draw, min_nodes=2, max_nodes=15):
    """Generate a valid tree of messages with node_id/parent_id fields.

    Builds a tree by starting with a system root node and then adding
    children to randomly chosen existing nodes with alternating roles.
    """
    n = draw(st.integers(min_value=min_nodes, max_value=max_nodes))
    roles = ["user", "assistant"]
    messages = []

    # Root node (always system)
    root_id = uuid.uuid4().hex
    messages.append({
        "node_id": root_id,
        "parent_id": None,
        "role": "system",
        "content": draw(st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
            min_size=1,
            max_size=40,
        )),
    })

    node_ids = [root_id]

    for i in range(1, n):
        parent_idx = draw(st.integers(min_value=0, max_value=len(node_ids) - 1))
        parent_id = node_ids[parent_idx]
        node_id = uuid.uuid4().hex
        role = roles[i % 2]
        content = draw(st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
            min_size=1,
            max_size=40,
        ))

        messages.append({
            "node_id": node_id,
            "parent_id": parent_id,
            "role": role,
            "content": content,
        })
        node_ids.append(node_id)

    return messages


@st.composite
def tree_with_active_node(draw, min_nodes=2, max_nodes=15):
    """Generate a tree and pick a random node as active_node_id."""
    messages = draw(tree_messages(min_nodes=min_nodes, max_nodes=max_nodes))
    active_idx = draw(st.integers(min_value=0, max_value=len(messages) - 1))
    active_node_id = messages[active_idx]["node_id"]
    return messages, active_node_id


@st.composite
def tree_with_active_and_summarized(draw, min_nodes=3, max_nodes=15):
    """Generate a tree, pick active_node_id, and pick some summarized_nodes."""
    messages = draw(tree_messages(min_nodes=min_nodes, max_nodes=max_nodes))
    active_idx = draw(st.integers(min_value=0, max_value=len(messages) - 1))
    active_node_id = messages[active_idx]["node_id"]

    # Pick a random subset of node_ids as summarized_nodes
    all_node_ids = [m["node_id"] for m in messages]
    num_summarized = draw(st.integers(min_value=0, max_value=len(all_node_ids) - 1))
    summarized_indices = draw(
        st.lists(
            st.integers(min_value=0, max_value=len(all_node_ids) - 1),
            min_size=num_summarized,
            max_size=num_summarized,
            unique=True,
        )
    )
    summarized_nodes = [all_node_ids[i] for i in summarized_indices]

    return messages, active_node_id, summarized_nodes


@st.composite
def linear_messages_no_node_id(draw, min_size=2, max_size=10):
    """Generate a linear message list WITHOUT node_id (legacy format)."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    roles = ["system", "user", "assistant"]
    messages = []
    for i in range(n):
        role = roles[0] if i == 0 else roles[1 + (i - 1) % 2]
        content = draw(st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
            min_size=1,
            max_size=40,
        ))
        messages.append({"role": role, "content": content})
    return messages


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    """Create a ConversationStore with a temporary directory."""
    return ConversationStore(root_dir=tmp_path)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _structural_fields(msg):
    """Extract structural fields for equivalence comparison."""
    return {
        "node_id": msg.get("node_id"),
        "parent_id": msg.get("parent_id"),
        "role": msg.get("role"),
        "content": msg.get("content"),
    }


def _save_and_load(store, messages, active_node_id, summarized_nodes=None):
    """Helper: create session, save messages, then load and return loaded data."""
    # Create a session first
    session = store.create_session("placeholder", title="Test")
    session_id = session["id"]

    # Save the tree messages
    store.save_messages(
        session_id,
        messages,
        active_node_id=active_node_id,
        summarized_nodes=summarized_nodes,
    )

    # Load and return
    return store.load_session(session_id)


# ---------------------------------------------------------------------------
# Property 4: Persistence Round-Trip
# ---------------------------------------------------------------------------

class TestPersistenceRoundTripNodeIds:
    """Save messages then load: all node_ids preserved."""

    @given(data=tree_with_active_node())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    def test_all_node_ids_preserved(self, data, tmp_path):
        """All node_ids in the saved tree are present after loading."""
        messages, active_node_id = data
        store = ConversationStore(root_dir=tmp_path / uuid.uuid4().hex)

        loaded = _save_and_load(store, messages, active_node_id)
        loaded_messages = loaded["messages"]

        original_node_ids = {m["node_id"] for m in messages}
        loaded_node_ids = {m["node_id"] for m in loaded_messages}

        assert original_node_ids.issubset(loaded_node_ids)


class TestPersistenceRoundTripParentIds:
    """Save messages then load: all parent_ids preserved."""

    @given(data=tree_with_active_node())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    def test_all_parent_ids_preserved(self, data, tmp_path):
        """All parent_ids in the saved tree are preserved after loading."""
        messages, active_node_id = data
        store = ConversationStore(root_dir=tmp_path / uuid.uuid4().hex)

        loaded = _save_and_load(store, messages, active_node_id)
        loaded_messages = loaded["messages"]

        # Build node_id -> parent_id maps
        original_parents = {m["node_id"]: m["parent_id"] for m in messages}
        loaded_parents = {m["node_id"]: m.get("parent_id") for m in loaded_messages}

        for node_id, expected_parent in original_parents.items():
            assert node_id in loaded_parents, f"node_id {node_id} missing after load"
            assert loaded_parents[node_id] == expected_parent, (
                f"parent_id mismatch for {node_id}: "
                f"expected {expected_parent}, got {loaded_parents[node_id]}"
            )


class TestPersistenceRoundTripContent:
    """Save messages then load: all content preserved."""

    @given(data=tree_with_active_node())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    def test_all_content_preserved(self, data, tmp_path):
        """All message content is preserved after save/load round-trip."""
        messages, active_node_id = data
        store = ConversationStore(root_dir=tmp_path / uuid.uuid4().hex)

        loaded = _save_and_load(store, messages, active_node_id)
        loaded_messages = loaded["messages"]

        # Build node_id -> content maps
        original_content = {m["node_id"]: m["content"] for m in messages}
        loaded_content = {m["node_id"]: m.get("content") for m in loaded_messages}

        for node_id, expected_content in original_content.items():
            assert node_id in loaded_content, f"node_id {node_id} missing after load"
            assert loaded_content[node_id] == expected_content, (
                f"content mismatch for {node_id}: "
                f"expected {expected_content!r}, got {loaded_content[node_id]!r}"
            )


class TestPersistenceRoundTripActiveNodeId:
    """Save messages then load: active_node_id preserved."""

    @given(data=tree_with_active_node())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    def test_active_node_id_preserved(self, data, tmp_path):
        """active_node_id is preserved after save/load round-trip."""
        messages, active_node_id = data
        store = ConversationStore(root_dir=tmp_path / uuid.uuid4().hex)

        loaded = _save_and_load(store, messages, active_node_id)

        assert loaded["active_node_id"] == active_node_id


class TestPersistenceRoundTripTreeStructure:
    """Save messages then load: tree structure (children relationships) equivalent."""

    @given(data=tree_with_active_node())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    def test_tree_structure_equivalent(self, data, tmp_path):
        """The tree structure (parent-child relationships) is equivalent after round-trip."""
        messages, active_node_id = data
        store = ConversationStore(root_dir=tmp_path / uuid.uuid4().hex)

        loaded = _save_and_load(store, messages, active_node_id)
        loaded_messages = loaded["messages"]

        # Build children maps from both original and loaded
        original_children: dict = {}
        for m in messages:
            parent_id = m["parent_id"]
            if parent_id is not None:
                original_children.setdefault(parent_id, set()).add(m["node_id"])

        loaded_children: dict = {}
        for m in loaded_messages:
            parent_id = m.get("parent_id")
            node_id = m.get("node_id")
            if parent_id is not None and node_id is not None:
                loaded_children.setdefault(parent_id, set()).add(node_id)

        # Every parent in original should have the same children in loaded
        for parent_id, children in original_children.items():
            loaded_set = loaded_children.get(parent_id, set())
            assert children.issubset(loaded_set), (
                f"Children mismatch for parent {parent_id}: "
                f"expected {children}, got {loaded_set}"
            )


class TestClonePreservesTreeStructure:
    """Clone session preserves complete tree structure."""

    @given(data=tree_with_active_and_summarized(min_nodes=3, max_nodes=12))
    @settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    def test_clone_preserves_full_structure(self, data, tmp_path):
        """Cloning a session preserves all node_ids, parent_ids, content, and active_node_id."""
        messages, active_node_id, summarized_nodes = data
        store = ConversationStore(root_dir=tmp_path / uuid.uuid4().hex)

        # Create and save
        session = store.create_session("placeholder", title="Source")
        session_id = session["id"]
        store.save_messages(
            session_id,
            messages,
            active_node_id=active_node_id,
            summarized_nodes=summarized_nodes,
        )

        # Clone
        cloned = store.clone_session(session_id)

        # Load the clone
        cloned_loaded = store.load_session(cloned["id"])

        # Verify structural equivalence
        original_structs = {
            m["node_id"]: _structural_fields(m) for m in messages
        }
        cloned_structs = {
            m["node_id"]: _structural_fields(m) for m in cloned_loaded["messages"]
        }

        for node_id, orig_fields in original_structs.items():
            assert node_id in cloned_structs, f"node_id {node_id} missing in clone"
            cloned_fields = cloned_structs[node_id]
            assert cloned_fields["parent_id"] == orig_fields["parent_id"]
            assert cloned_fields["content"] == orig_fields["content"]
            assert cloned_fields["role"] == orig_fields["role"]

        # active_node_id preserved
        assert cloned_loaded["active_node_id"] == active_node_id

        # summarized_nodes preserved
        assert set(cloned_loaded.get("summarized_nodes", [])) == set(summarized_nodes)


class TestLegacyFormatMigration:
    """Load of legacy format (no node_id) auto-migrates to valid tree."""

    @given(messages=linear_messages_no_node_id(min_size=2, max_size=10))
    @settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    def test_legacy_load_produces_valid_tree(self, messages, tmp_path):
        """Loading a session with legacy messages (no node_id) auto-migrates to a valid tree."""
        import json

        store = ConversationStore(root_dir=tmp_path / uuid.uuid4().hex)
        session_id = uuid.uuid4().hex

        # Write a legacy-format session file directly (no node_id fields)
        legacy_data = {
            "id": session_id,
            "title": "Legacy Session",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "messages": messages,
            "summary": "",
            "summarized_until": 1,
        }
        session_path = store.root_dir / f"{session_id}.json"
        session_path.write_text(
            json.dumps(legacy_data, ensure_ascii=False),
            encoding="utf-8",
        )

        # Load triggers auto-migration
        loaded = store.load_session(session_id)
        loaded_messages = loaded["messages"]

        # All messages should now have node_id
        for msg in loaded_messages:
            assert "node_id" in msg
            assert msg["node_id"] is not None

        # First message should be root (parent_id is None)
        assert loaded_messages[0]["parent_id"] is None

        # Linear chain: each subsequent message points to previous
        for i in range(1, len(loaded_messages)):
            assert loaded_messages[i]["parent_id"] == loaded_messages[i - 1]["node_id"]

        # Content preserved
        for orig, loaded_msg in zip(messages, loaded_messages):
            assert loaded_msg["content"] == orig["content"]
            assert loaded_msg["role"] == orig["role"]

        # active_node_id should be set to last message
        assert loaded["active_node_id"] == loaded_messages[-1]["node_id"]

        # Tree is valid: BranchEngine can build it
        engine = BranchEngine(loaded_messages)
        leaf_id = loaded_messages[-1]["node_id"]
        path = engine.get_path_to_node(leaf_id)
        assert len(path) == len(messages)
