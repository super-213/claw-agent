"""Tests for ConversationManager.create_branch() method (Task 3.4)"""

import pytest
from core.conversation import ConversationManager


class TestCreateBranch:
    """Test ConversationManager.create_branch() method."""

    def _make_manager_with_tree(self):
        """Helper: create a ConversationManager with a linear tree structure.

        Tree structure:
            root (system) -> n1 (user) -> n2 (assistant)
        """
        cm = ConversationManager("System")
        messages = [
            {"role": "system", "content": "System", "node_id": "root", "parent_id": None},
            {"role": "user", "content": "Hello", "node_id": "n1", "parent_id": "root"},
            {"role": "assistant", "content": "Hi there", "node_id": "n2", "parent_id": "n1"},
        ]
        cm.load_messages(messages, active_node_id="n2")
        return cm

    def test_create_branch_returns_dict_with_branch_node_id(self):
        """create_branch should return a dict containing branch_node_id."""
        cm = self._make_manager_with_tree()

        result = cm.create_branch("n1")

        assert "branch_node_id" in result
        assert result["branch_node_id"] is not None
        assert isinstance(result["branch_node_id"], str)

    def test_create_branch_returns_ancestor_path(self):
        """create_branch should return ancestor_path from root to new node."""
        cm = self._make_manager_with_tree()

        result = cm.create_branch("n1")

        assert "ancestor_path" in result
        # Path should be: root -> n1 -> new_node
        assert result["ancestor_path"][0] == "root"
        assert result["ancestor_path"][1] == "n1"
        assert result["ancestor_path"][2] == result["branch_node_id"]
        assert len(result["ancestor_path"]) == 3

    def test_create_branch_updates_active_node_id(self):
        """create_branch should update active_node_id to the new branch node."""
        cm = self._make_manager_with_tree()
        assert cm.active_node_id == "n2"

        result = cm.create_branch("n1")

        assert cm.active_node_id == result["branch_node_id"]

    def test_create_branch_new_node_exists_in_engine(self):
        """The new branch node should exist in BranchEngine's node index."""
        cm = self._make_manager_with_tree()

        result = cm.create_branch("n1")

        assert result["branch_node_id"] in cm.branch_engine._nodes

    def test_create_branch_new_node_is_child_of_branch_point(self):
        """The new branch node should be a child of the specified branch point."""
        cm = self._make_manager_with_tree()

        result = cm.create_branch("n1")

        assert result["branch_node_id"] in cm.branch_engine._children["n1"]

    def test_create_branch_preserves_existing_branches(self):
        """Creating a branch should not affect existing nodes or paths."""
        cm = self._make_manager_with_tree()

        cm.create_branch("n1")

        # Original path to n2 should still be accessible
        path = cm.branch_engine.get_path_to_node("n2")
        assert len(path) == 3
        assert path[2]["content"] == "Hi there"

    def test_create_branch_multiple_at_same_point(self):
        """Multiple branches at the same point are allowed after leaving the empty branch."""
        cm = self._make_manager_with_tree()

        result1 = cm.create_branch("n1")
        cm.switch_branch("n2")
        result2 = cm.create_branch("n1")

        # Both should be different nodes
        assert result1["branch_node_id"] != result2["branch_node_id"]
        # Both should be children of n1
        assert result1["branch_node_id"] in cm.branch_engine._children["n1"]
        assert result2["branch_node_id"] in cm.branch_engine._children["n1"]

    def test_create_branch_rejects_when_active_branch_is_empty(self):
        """An empty active branch must be used before creating another branch."""
        cm = self._make_manager_with_tree()

        cm.create_branch("n1")

        with pytest.raises(ValueError, match="新分支尚未对话"):
            cm.create_branch("n1")

    def test_create_branch_invalid_node_raises_error(self):
        """create_branch should raise ValueError for non-existent node_id."""
        cm = self._make_manager_with_tree()

        with pytest.raises(ValueError, match="分支点不存在"):
            cm.create_branch("nonexistent")

    def test_create_branch_without_branch_engine_raises_error(self):
        """create_branch should raise ValueError if BranchEngine is not initialized."""
        cm = ConversationManager("System")

        with pytest.raises(ValueError, match="BranchEngine 未初始化"):
            cm.create_branch("some_node")

    def test_create_branch_active_node_id_not_changed_on_error(self):
        """active_node_id should not change if create_branch raises an error."""
        cm = self._make_manager_with_tree()
        assert cm.active_node_id == "n2"

        with pytest.raises(ValueError):
            cm.create_branch("nonexistent")

        assert cm.active_node_id == "n2"

    def test_create_branch_at_root(self):
        """create_branch should work at the root node."""
        cm = self._make_manager_with_tree()

        result = cm.create_branch("root")

        assert result["ancestor_path"] == ["root", result["branch_node_id"]]
        assert cm.active_node_id == result["branch_node_id"]

    def test_create_branch_at_leaf(self):
        """create_branch should work at a leaf node."""
        cm = self._make_manager_with_tree()

        result = cm.create_branch("n2")

        assert result["ancestor_path"] == ["root", "n1", "n2", result["branch_node_id"]]
        assert cm.active_node_id == result["branch_node_id"]
