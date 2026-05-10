"""Tests for BranchEngine methods."""

import uuid
import pytest
from core.branch_engine import BranchEngine


class TestMigrateLinear:
    """Tests for the migrate_linear method."""

    def test_empty_list(self):
        """Empty message list returns empty result."""
        engine = BranchEngine([])
        result = engine.migrate_linear([])
        assert result == []

    def test_single_message(self):
        """Single message gets node_id and parent_id=None."""
        engine = BranchEngine([])
        messages = [{"role": "system", "content": "You are helpful."}]
        result = engine.migrate_linear(messages)

        assert len(result) == 1
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are helpful."
        assert result[0]["parent_id"] is None
        assert "node_id" in result[0]
        # Verify node_id is a valid UUID
        uuid.UUID(result[0]["node_id"])

    def test_linear_chain(self):
        """Multiple messages form a linear parent_id chain."""
        engine = BranchEngine([])
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = engine.migrate_linear(messages)

        assert len(result) == 3
        # First message: parent_id is None
        assert result[0]["parent_id"] is None
        # Second message: parent_id points to first
        assert result[1]["parent_id"] == result[0]["node_id"]
        # Third message: parent_id points to second
        assert result[2]["parent_id"] == result[1]["node_id"]

    def test_preserves_original_fields(self):
        """Migration preserves all original message fields."""
        engine = BranchEngine([])
        messages = [
            {
                "role": "user",
                "content": "Hello",
                "ts": "2024-01-01T00:00:00Z",
                "attachments": [{"name": "file.txt"}],
                "images": ["img1.png"],
                "custom_field": "custom_value",
            }
        ]
        result = engine.migrate_linear(messages)

        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"
        assert result[0]["ts"] == "2024-01-01T00:00:00Z"
        assert result[0]["attachments"] == [{"name": "file.txt"}]
        assert result[0]["images"] == ["img1.png"]
        assert result[0]["custom_field"] == "custom_value"

    def test_does_not_modify_original(self):
        """Migration does not modify the original message list."""
        engine = BranchEngine([])
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        # Keep a copy to compare
        original_messages = [dict(m) for m in messages]
        engine.migrate_linear(messages)

        assert messages == original_messages

    def test_unique_node_ids(self):
        """Each message gets a unique node_id."""
        engine = BranchEngine([])
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "User 1"},
            {"role": "assistant", "content": "Assistant 1"},
            {"role": "user", "content": "User 2"},
            {"role": "assistant", "content": "Assistant 2"},
        ]
        result = engine.migrate_linear(messages)

        node_ids = [msg["node_id"] for msg in result]
        assert len(node_ids) == len(set(node_ids))

    def test_preserves_existing_node_id(self):
        """Messages that already have node_id keep their existing value."""
        engine = BranchEngine([])
        existing_id = "existing-uuid-123"
        messages = [
            {"role": "user", "content": "Hello", "node_id": existing_id},
            {"role": "assistant", "content": "Hi"},
        ]
        result = engine.migrate_linear(messages)

        assert result[0]["node_id"] == existing_id
        assert result[1]["parent_id"] == existing_id

    def test_updates_internal_index(self):
        """After migration, internal tree index is updated."""
        engine = BranchEngine([])
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        result = engine.migrate_linear(messages)

        # Verify internal nodes are populated
        assert len(engine._nodes) == 3
        for msg in result:
            assert msg["node_id"] in engine._nodes

        # Verify children mapping
        assert result[1]["node_id"] in engine._children[result[0]["node_id"]]
        assert result[2]["node_id"] in engine._children[result[1]["node_id"]]
        # Leaf node has empty children list
        assert engine._children[result[2]["node_id"]] == []

    def test_single_path_no_branches(self):
        """Migrated tree has only one path (no branches)."""
        engine = BranchEngine([])
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm good!"},
        ]
        result = engine.migrate_linear(messages)

        # Each node should have at most one child (linear chain)
        for node_id, children in engine._children.items():
            assert len(children) <= 1, f"Node {node_id} has {len(children)} children, expected <= 1"


class TestCreateBranch:
    """Tests for the create_branch method."""

    def test_creates_new_node(self):
        """create_branch returns a new node_id that exists in the tree."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
        ]
        engine = BranchEngine(messages)
        new_id = engine.create_branch("n1")

        assert new_id in engine._nodes
        assert engine._nodes[new_id]["parent_id"] == "n1"

    def test_returns_valid_uuid(self):
        """The returned node_id is a valid UUID string."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)
        new_id = engine.create_branch("root")

        # Should not raise
        uuid.UUID(new_id)

    def test_new_node_is_child_of_branch_point(self):
        """New node appears in the branch point's children list."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
        ]
        engine = BranchEngine(messages)
        new_id = engine.create_branch("n1")

        assert new_id in engine._children["n1"]

    def test_branch_point_child_count_increases(self):
        """Creating a branch increases the branch point's child count by 1."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi"},
        ]
        engine = BranchEngine(messages)
        # n1 already has one child (n2)
        assert len(engine._children["n1"]) == 1

        engine.create_branch("n1")
        assert len(engine._children["n1"]) == 2

    def test_multiple_branches_at_same_point(self):
        """Multiple branches can be created at the same branch point."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
        ]
        engine = BranchEngine(messages)

        id1 = engine.create_branch("n1")
        id2 = engine.create_branch("n1")
        id3 = engine.create_branch("n1")

        assert id1 != id2 != id3
        assert len(engine._children["n1"]) == 3
        assert id1 in engine._children["n1"]
        assert id2 in engine._children["n1"]
        assert id3 in engine._children["n1"]

    def test_existing_nodes_unchanged(self):
        """Creating a branch does not modify existing nodes' node_id or parent_id."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi"},
        ]
        engine = BranchEngine(messages)

        # Capture state before
        nodes_before = {nid: dict(node) for nid, node in engine._nodes.items()}

        engine.create_branch("n1")

        # Verify existing nodes unchanged
        for nid, node_before in nodes_before.items():
            assert engine._nodes[nid]["node_id"] == node_before["node_id"]
            assert engine._nodes[nid]["parent_id"] == node_before["parent_id"]

    def test_existing_paths_still_reachable(self):
        """After creating a branch, existing paths remain reachable."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi"},
        ]
        engine = BranchEngine(messages)

        engine.create_branch("n1")

        # Original path to n2 still works
        path = engine.get_path_to_node("n2")
        assert len(path) == 3
        assert [n["node_id"] for n in path] == ["root", "n1", "n2"]

    def test_new_branch_path_includes_ancestors(self):
        """Path to new branch node includes all ancestors from root."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi"},
        ]
        engine = BranchEngine(messages)

        new_id = engine.create_branch("n1")
        path = engine.get_path_to_node(new_id)

        # Path should be: root -> n1 -> new_id
        assert len(path) == 3
        assert path[0]["node_id"] == "root"
        assert path[1]["node_id"] == "n1"
        assert path[2]["node_id"] == new_id

    def test_nonexistent_branch_point_raises_error(self):
        """Branching from a non-existent node raises ValueError with the invalid ID."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)

        with pytest.raises(ValueError) as exc_info:
            engine.create_branch("nonexistent-id")
        assert "nonexistent-id" in str(exc_info.value)

    def test_new_node_has_empty_children(self):
        """The newly created branch node starts with an empty children list."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)
        new_id = engine.create_branch("root")

        assert engine._children[new_id] == []

    def test_branch_on_root_node(self):
        """Branching from the root node works correctly."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
        ]
        engine = BranchEngine(messages)

        new_id = engine.create_branch("root")
        assert new_id in engine._children["root"]
        assert engine._nodes[new_id]["parent_id"] == "root"

        # Root now has two children: n1 and new_id
        assert len(engine._children["root"]) == 2


class TestGetPathToNode:
    """Tests for the get_path_to_node method."""

    def test_single_node_path(self):
        """Root node path contains only itself."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "System"}
        ]
        engine = BranchEngine(messages)
        path = engine.get_path_to_node("root")

        assert len(path) == 1
        assert path[0]["node_id"] == "root"
        assert path[0]["parent_id"] is None

    def test_linear_path(self):
        """Path through a linear chain returns all nodes in order."""
        messages = [
            {"node_id": "n1", "parent_id": None, "role": "system", "content": "System"},
            {"node_id": "n2", "parent_id": "n1", "role": "user", "content": "Hello"},
            {"node_id": "n3", "parent_id": "n2", "role": "assistant", "content": "Hi"},
        ]
        engine = BranchEngine(messages)
        path = engine.get_path_to_node("n3")

        assert len(path) == 3
        assert path[0]["node_id"] == "n1"
        assert path[1]["node_id"] == "n2"
        assert path[2]["node_id"] == "n3"

    def test_path_starts_with_root(self):
        """First element in path has parent_id == None (root)."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "child", "parent_id": "root", "role": "user", "content": "Hi"},
        ]
        engine = BranchEngine(messages)
        path = engine.get_path_to_node("child")

        assert path[0]["parent_id"] is None

    def test_path_ends_with_target(self):
        """Last element in path has node_id == target."""
        messages = [
            {"node_id": "n1", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n2", "parent_id": "n1", "role": "user", "content": "Hello"},
            {"node_id": "n3", "parent_id": "n2", "role": "assistant", "content": "Hi"},
        ]
        engine = BranchEngine(messages)
        path = engine.get_path_to_node("n3")

        assert path[-1]["node_id"] == "n3"

    def test_adjacent_elements_linked(self):
        """Adjacent elements satisfy path[i+1].parent_id == path[i].node_id."""
        messages = [
            {"node_id": "n1", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n2", "parent_id": "n1", "role": "user", "content": "Hello"},
            {"node_id": "n3", "parent_id": "n2", "role": "assistant", "content": "Hi"},
            {"node_id": "n4", "parent_id": "n3", "role": "user", "content": "More"},
        ]
        engine = BranchEngine(messages)
        path = engine.get_path_to_node("n4")

        for i in range(len(path) - 1):
            assert path[i + 1]["parent_id"] == path[i]["node_id"]

    def test_branched_tree_correct_path(self):
        """In a branched tree, path only includes ancestors of target node."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "a1", "parent_id": "root", "role": "user", "content": "Branch A"},
            {"node_id": "a2", "parent_id": "a1", "role": "assistant", "content": "Reply A"},
            {"node_id": "b1", "parent_id": "root", "role": "user", "content": "Branch B"},
            {"node_id": "b2", "parent_id": "b1", "role": "assistant", "content": "Reply B"},
        ]
        engine = BranchEngine(messages)

        # Path to b2 should not include a1 or a2
        path = engine.get_path_to_node("b2")
        node_ids = [n["node_id"] for n in path]
        assert node_ids == ["root", "b1", "b2"]

    def test_nonexistent_node_raises_error(self):
        """Requesting path to non-existent node raises ValueError."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)

        with pytest.raises(ValueError) as exc_info:
            engine.get_path_to_node("nonexistent-id")
        assert "nonexistent-id" in str(exc_info.value)

    def test_path_after_migrate_linear(self):
        """get_path_to_node works correctly after migrate_linear."""
        engine = BranchEngine([])
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        migrated = engine.migrate_linear(messages)

        leaf_id = migrated[-1]["node_id"]
        path = engine.get_path_to_node(leaf_id)

        assert len(path) == 3
        assert path[0]["parent_id"] is None
        assert path[-1]["node_id"] == leaf_id
        # Content preserved in order
        assert path[0]["content"] == "System"
        assert path[1]["content"] == "Hello"
        assert path[2]["content"] == "Hi"


class TestBuildContext:
    """Tests for the build_context method."""

    def test_simple_linear_context(self):
        """build_context returns all messages from root to leaf in order."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "System prompt"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi there"},
        ]
        engine = BranchEngine(messages)
        context = engine.build_context("n2")

        assert len(context) == 3
        assert context[0]["content"] == "System prompt"
        assert context[1]["content"] == "Hello"
        assert context[2]["content"] == "Hi there"

    def test_context_isolation_excludes_other_branches(self):
        """build_context does NOT include messages from other branches."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "a1", "parent_id": "root", "role": "user", "content": "Branch A msg"},
            {"node_id": "a2", "parent_id": "a1", "role": "assistant", "content": "Reply A"},
            {"node_id": "b1", "parent_id": "root", "role": "user", "content": "Branch B msg"},
            {"node_id": "b2", "parent_id": "b1", "role": "assistant", "content": "Reply B"},
        ]
        engine = BranchEngine(messages)

        # Context for branch B should NOT contain branch A messages
        context_b = engine.build_context("b2")
        context_node_ids = {msg["node_id"] for msg in context_b}
        assert "a1" not in context_node_ids
        assert "a2" not in context_node_ids
        assert "root" in context_node_ids
        assert "b1" in context_node_ids
        assert "b2" in context_node_ids

    def test_context_isolation_branch_a(self):
        """build_context for branch A does NOT include branch B messages."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "a1", "parent_id": "root", "role": "user", "content": "Branch A"},
            {"node_id": "a2", "parent_id": "a1", "role": "assistant", "content": "Reply A"},
            {"node_id": "b1", "parent_id": "root", "role": "user", "content": "Branch B"},
            {"node_id": "b2", "parent_id": "b1", "role": "assistant", "content": "Reply B"},
        ]
        engine = BranchEngine(messages)

        context_a = engine.build_context("a2")
        context_node_ids = {msg["node_id"] for msg in context_a}
        assert "b1" not in context_node_ids
        assert "b2" not in context_node_ids
        assert context_node_ids == {"root", "a1", "a2"}

    def test_context_filters_empty_placeholder_nodes(self):
        """build_context filters out empty placeholder nodes created by create_branch."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
        ]
        engine = BranchEngine(messages)

        # Create a branch (produces an empty placeholder node)
        branch_id = engine.create_branch("n1")
        context = engine.build_context(branch_id)

        # The empty placeholder should be filtered out
        assert all(msg.get("content") for msg in context)
        assert len(context) == 2  # root + n1, not the empty branch node

    def test_context_for_root_node(self):
        """build_context for root node returns only the root message."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "System"},
        ]
        engine = BranchEngine(messages)
        context = engine.build_context("root")

        assert len(context) == 1
        assert context[0]["node_id"] == "root"

    def test_nonexistent_node_raises_error(self):
        """build_context raises ValueError for non-existent node_id."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)

        with pytest.raises(ValueError) as exc_info:
            engine.build_context("nonexistent-id")
        assert "nonexistent-id" in str(exc_info.value)

    def test_context_preserves_message_order(self):
        """build_context returns messages in root-to-leaf order."""
        messages = [
            {"node_id": "n1", "parent_id": None, "role": "system", "content": "First"},
            {"node_id": "n2", "parent_id": "n1", "role": "user", "content": "Second"},
            {"node_id": "n3", "parent_id": "n2", "role": "assistant", "content": "Third"},
            {"node_id": "n4", "parent_id": "n3", "role": "user", "content": "Fourth"},
        ]
        engine = BranchEngine(messages)
        context = engine.build_context("n4")

        contents = [msg["content"] for msg in context]
        assert contents == ["First", "Second", "Third", "Fourth"]

    def test_context_is_subset_of_path(self):
        """build_context result is a subset of get_path_to_node result."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi"},
        ]
        engine = BranchEngine(messages)

        path = engine.get_path_to_node("n2")
        context = engine.build_context("n2")

        path_ids = {msg["node_id"] for msg in path}
        context_ids = {msg["node_id"] for msg in context}
        assert context_ids.issubset(path_ids)

    def test_context_after_branch_creation(self):
        """build_context works correctly after creating branches."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi"},
        ]
        engine = BranchEngine(messages)

        # Create a branch at n1
        engine.create_branch("n1")

        # Original path context should still work correctly
        context = engine.build_context("n2")
        assert len(context) == 3
        assert [msg["node_id"] for msg in context] == ["root", "n1", "n2"]

    def test_deep_branch_context(self):
        """build_context works for deeply nested branches."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "L1"},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "L2"},
            {"node_id": "n3", "parent_id": "n2", "role": "user", "content": "L3"},
            # Branch from n2
            {"node_id": "b1", "parent_id": "n2", "role": "user", "content": "B1"},
            {"node_id": "b2", "parent_id": "b1", "role": "assistant", "content": "B2"},
            {"node_id": "b3", "parent_id": "b2", "role": "user", "content": "B3"},
        ]
        engine = BranchEngine(messages)

        context = engine.build_context("b3")
        node_ids = [msg["node_id"] for msg in context]
        assert node_ids == ["root", "n1", "n2", "b1", "b2", "b3"]
        # n3 should NOT be in the context
        assert "n3" not in node_ids


class TestDeleteBranch:
    """Tests for the delete_branch method."""

    def _build_tree(self):
        """Helper: build a tree with branches for testing.

        Tree structure:
            root
            ├── a1
            │   ├── a2
            │   │   └── a3
            │   └── b1 (branch from a1)
            │       └── b2
            └── c1 (branch from root)
        """
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "a1", "parent_id": "root", "role": "user", "content": "A1"},
            {"node_id": "a2", "parent_id": "a1", "role": "assistant", "content": "A2"},
            {"node_id": "a3", "parent_id": "a2", "role": "user", "content": "A3"},
            {"node_id": "b1", "parent_id": "a1", "role": "user", "content": "B1"},
            {"node_id": "b2", "parent_id": "b1", "role": "assistant", "content": "B2"},
            {"node_id": "c1", "parent_id": "root", "role": "user", "content": "C1"},
        ]
        return BranchEngine(messages)

    def test_delete_leaf_node(self):
        """Deleting a leaf node removes only that node."""
        engine = self._build_tree()
        # Delete b2 (leaf), active path is on a3
        count = engine.delete_branch("b2", "a3")

        assert count == 1
        assert "b2" not in engine._nodes
        assert "b2" not in engine._children
        # b1 no longer has b2 as child
        assert "b2" not in engine._children["b1"]

    def test_delete_subtree(self):
        """Deleting a node removes it and all its descendants."""
        engine = self._build_tree()
        # Delete b1 (has child b2), active path is on a3
        count = engine.delete_branch("b1", "a3")

        assert count == 2
        assert "b1" not in engine._nodes
        assert "b2" not in engine._nodes
        assert "b1" not in engine._children
        assert "b2" not in engine._children
        # a1 no longer has b1 as child
        assert "b1" not in engine._children["a1"]

    def test_delete_larger_subtree(self):
        """Deleting a node with a deeper subtree removes all descendants."""
        engine = self._build_tree()
        # Delete a2 (has child a3), active path is on c1
        count = engine.delete_branch("a2", "c1")

        assert count == 2
        assert "a2" not in engine._nodes
        assert "a3" not in engine._nodes
        # a1 still has b1 as child
        assert "b1" in engine._children["a1"]
        assert "a2" not in engine._children["a1"]

    def test_nonexistent_node_raises_error(self):
        """Deleting a non-existent node raises ValueError."""
        engine = self._build_tree()

        with pytest.raises(ValueError) as exc_info:
            engine.delete_branch("nonexistent", "a3")
        assert "nonexistent" in str(exc_info.value)

    def test_delete_root_raises_error(self):
        """Deleting the root node raises ValueError."""
        engine = self._build_tree()

        with pytest.raises(ValueError) as exc_info:
            engine.delete_branch("root", "a3")
        assert "root" in str(exc_info.value).lower() or "根" in str(exc_info.value)

    def test_delete_active_node_raises_error(self):
        """Deleting the active node itself raises ValueError."""
        engine = self._build_tree()

        with pytest.raises(ValueError) as exc_info:
            engine.delete_branch("a3", "a3")
        assert "活跃" in str(exc_info.value) or "切换" in str(exc_info.value)

    def test_delete_ancestor_of_active_node_raises_error(self):
        """Deleting an ancestor of the active node raises ValueError."""
        engine = self._build_tree()
        # a1 is an ancestor of a3 (active)
        with pytest.raises(ValueError) as exc_info:
            engine.delete_branch("a1", "a3")
        assert "活跃" in str(exc_info.value) or "切换" in str(exc_info.value)

    def test_remaining_nodes_have_valid_parent_ids(self):
        """After deletion, all remaining nodes' parent_ids point to existing nodes or None."""
        engine = self._build_tree()
        engine.delete_branch("b1", "a3")

        for nid, node in engine._nodes.items():
            parent_id = node.get("parent_id")
            if parent_id is not None:
                assert parent_id in engine._nodes, (
                    f"Node {nid} has parent_id {parent_id} which doesn't exist"
                )

    def test_tree_still_connected_after_deletion(self):
        """After deletion, all remaining nodes are reachable from root."""
        engine = self._build_tree()
        engine.delete_branch("b1", "a3")

        # Find root
        root_id = None
        for nid, node in engine._nodes.items():
            if node.get("parent_id") is None:
                root_id = nid
                break
        assert root_id is not None

        # BFS from root to check all nodes are reachable
        visited = set()
        queue = [root_id]
        while queue:
            current = queue.pop(0)
            visited.add(current)
            queue.extend(engine._children.get(current, []))

        assert visited == set(engine._nodes.keys())

    def test_delete_returns_correct_count(self):
        """delete_branch returns the exact number of removed nodes."""
        engine = self._build_tree()
        # c1 is a leaf
        count = engine.delete_branch("c1", "a3")
        assert count == 1

    def test_delete_does_not_affect_sibling_branches(self):
        """Deleting one branch does not affect sibling branches."""
        engine = self._build_tree()
        # Delete the a2->a3 subtree, active on c1
        engine.delete_branch("a2", "c1")

        # b1 and b2 should still exist
        assert "b1" in engine._nodes
        assert "b2" in engine._nodes
        # Path to b2 still works
        path = engine.get_path_to_node("b2")
        assert [n["node_id"] for n in path] == ["root", "a1", "b1", "b2"]

    def test_delete_with_active_on_different_branch(self):
        """Deletion succeeds when active node is on a completely different branch."""
        engine = self._build_tree()
        # Active on c1 (different branch from root), delete b1 subtree
        count = engine.delete_branch("b1", "c1")
        assert count == 2
        assert "b1" not in engine._nodes
        assert "b2" not in engine._nodes


class TestAppendMessage:
    """Tests for the append_message method."""

    def test_returns_valid_uuid(self):
        """append_message returns a valid UUID string."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)
        new_id = engine.append_message("root", {"role": "user", "content": "Hello"})

        # Should not raise
        uuid.UUID(new_id)

    def test_message_added_to_nodes_index(self):
        """The new message is stored in the internal _nodes index."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)
        new_id = engine.append_message("root", {"role": "user", "content": "Hello"})

        assert new_id in engine._nodes
        assert engine._nodes[new_id]["role"] == "user"
        assert engine._nodes[new_id]["content"] == "Hello"

    def test_message_node_id_and_parent_id_set(self):
        """The message dict gets node_id and parent_id fields set."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)
        msg = {"role": "user", "content": "Hello"}
        new_id = engine.append_message("root", msg)

        assert msg["node_id"] == new_id
        assert msg["parent_id"] == "root"

    def test_added_to_parent_children_list(self):
        """The new node appears in the parent's children list."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)
        new_id = engine.append_message("root", {"role": "user", "content": "Hello"})

        assert new_id in engine._children["root"]

    def test_new_node_has_empty_children(self):
        """The newly appended node starts with an empty children list."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)
        new_id = engine.append_message("root", {"role": "user", "content": "Hello"})

        assert engine._children[new_id] == []

    def test_nonexistent_parent_raises_error(self):
        """Appending to a non-existent parent raises ValueError."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)

        with pytest.raises(ValueError) as exc_info:
            engine.append_message("nonexistent-id", {"role": "user", "content": "Hi"})
        assert "nonexistent-id" in str(exc_info.value)

    def test_preserves_message_fields(self):
        """append_message preserves all original fields in the message."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)
        msg = {
            "role": "user",
            "content": "Hello",
            "ts": "2024-01-01T00:00:00Z",
            "attachments": [{"name": "file.txt"}],
        }
        new_id = engine.append_message("root", msg)

        stored = engine._nodes[new_id]
        assert stored["role"] == "user"
        assert stored["content"] == "Hello"
        assert stored["ts"] == "2024-01-01T00:00:00Z"
        assert stored["attachments"] == [{"name": "file.txt"}]

    def test_path_to_appended_node(self):
        """get_path_to_node works correctly for the appended node."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
        ]
        engine = BranchEngine(messages)
        new_id = engine.append_message("n1", {"role": "assistant", "content": "Hi"})

        path = engine.get_path_to_node(new_id)
        assert len(path) == 3
        assert path[0]["node_id"] == "root"
        assert path[1]["node_id"] == "n1"
        assert path[2]["node_id"] == new_id

    def test_multiple_appends_to_same_parent(self):
        """Multiple messages can be appended to the same parent (creates siblings)."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)

        id1 = engine.append_message("root", {"role": "user", "content": "Msg 1"})
        id2 = engine.append_message("root", {"role": "user", "content": "Msg 2"})

        assert id1 != id2
        assert id1 in engine._children["root"]
        assert id2 in engine._children["root"]
        assert len(engine._children["root"]) == 2

    def test_append_chain(self):
        """Messages can be appended in a chain (child of child)."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
        ]
        engine = BranchEngine(messages)

        id1 = engine.append_message("root", {"role": "user", "content": "Hello"})
        id2 = engine.append_message(id1, {"role": "assistant", "content": "Hi"})
        id3 = engine.append_message(id2, {"role": "user", "content": "How are you?"})

        path = engine.get_path_to_node(id3)
        assert len(path) == 4
        assert [n["node_id"] for n in path] == ["root", id1, id2, id3]

    def test_existing_nodes_unchanged(self):
        """Appending a message does not modify existing nodes."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
        ]
        engine = BranchEngine(messages)

        # Capture state before
        root_before = dict(engine._nodes["root"])
        n1_before = dict(engine._nodes["n1"])

        engine.append_message("n1", {"role": "assistant", "content": "Hi"})

        assert engine._nodes["root"]["node_id"] == root_before["node_id"]
        assert engine._nodes["root"]["parent_id"] == root_before["parent_id"]
        assert engine._nodes["root"]["content"] == root_before["content"]
        assert engine._nodes["n1"]["node_id"] == n1_before["node_id"]
        assert engine._nodes["n1"]["parent_id"] == n1_before["parent_id"]
        assert engine._nodes["n1"]["content"] == n1_before["content"]

    def test_build_context_includes_appended_message(self):
        """build_context includes the appended message in the context path."""
        messages = [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "Sys"},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello"},
        ]
        engine = BranchEngine(messages)
        new_id = engine.append_message("n1", {"role": "assistant", "content": "Hi there"})

        context = engine.build_context(new_id)
        assert len(context) == 3
        assert context[2]["content"] == "Hi there"
