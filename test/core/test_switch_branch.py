"""Tests for ConversationManager.switch_branch() method (Task 3.3)"""

import pytest
from core.conversation import ConversationManager


class TestSwitchBranch:
    """Test ConversationManager.switch_branch() method."""

    def _make_manager_with_branches(self):
        """Helper: create a ConversationManager with a branching tree structure.

        Tree structure:
            root (system) -> n1 (user) -> n2 (assistant)
                                       -> n3 (user) -> n4 (assistant)
        """
        cm = ConversationManager("System")
        messages = [
            {"role": "system", "content": "System", "node_id": "root", "parent_id": None},
            {"role": "user", "content": "Hello", "node_id": "n1", "parent_id": "root"},
            {"role": "assistant", "content": "Hi there", "node_id": "n2", "parent_id": "n1"},
            {"role": "user", "content": "Bye", "node_id": "n3", "parent_id": "n1"},
            {"role": "assistant", "content": "Goodbye", "node_id": "n4", "parent_id": "n3"},
        ]
        cm.load_messages(messages, active_node_id="n2")
        return cm

    def test_switch_branch_returns_path_to_target(self):
        """switch_branch should return messages from root to target node."""
        cm = self._make_manager_with_branches()

        result = cm.switch_branch("n4")

        assert len(result) == 4
        assert result[0]["node_id"] == "root"
        assert result[1]["node_id"] == "n1"
        assert result[2]["node_id"] == "n3"
        assert result[3]["node_id"] == "n4"

    def test_switch_branch_updates_active_node_id(self):
        """switch_branch should update active_node_id to the target node."""
        cm = self._make_manager_with_branches()
        assert cm.active_node_id == "n2"

        cm.switch_branch("n4")

        assert cm.active_node_id == "n4"

    def test_switch_branch_get_messages_reflects_new_path(self):
        """After switch_branch, get_messages should return the new active path."""
        cm = self._make_manager_with_branches()

        cm.switch_branch("n4")
        messages = cm.get_messages()

        assert len(messages) == 4
        assert messages[0]["content"] == "System"
        assert messages[1]["content"] == "Hello"
        assert messages[2]["content"] == "Bye"
        assert messages[3]["content"] == "Goodbye"

    def test_switch_branch_to_same_node_is_idempotent(self):
        """Switching to the same node twice should return the same result (Property 7)."""
        cm = self._make_manager_with_branches()

        result1 = cm.switch_branch("n4")
        result2 = cm.switch_branch("n4")

        assert len(result1) == len(result2)
        for m1, m2 in zip(result1, result2):
            assert m1["node_id"] == m2["node_id"]
            assert m1["content"] == m2["content"]

    def test_switch_branch_preserves_all_branch_data(self):
        """Switching branches should not lose any data from other branches."""
        cm = self._make_manager_with_branches()

        # Switch to branch n4
        cm.switch_branch("n4")

        # The other branch (n2) should still be accessible
        path_to_n2 = cm.branch_engine.get_path_to_node("n2")
        assert len(path_to_n2) == 3
        assert path_to_n2[2]["content"] == "Hi there"

    def test_switch_branch_to_intermediate_node(self):
        """switch_branch should work for non-leaf nodes too."""
        cm = self._make_manager_with_branches()

        result = cm.switch_branch("n1")

        assert len(result) == 2
        assert result[0]["node_id"] == "root"
        assert result[1]["node_id"] == "n1"
        assert cm.active_node_id == "n1"

    def test_switch_branch_to_root(self):
        """switch_branch should work for the root node."""
        cm = self._make_manager_with_branches()

        result = cm.switch_branch("root")

        assert len(result) == 1
        assert result[0]["node_id"] == "root"
        assert cm.active_node_id == "root"

    def test_switch_branch_invalid_node_raises_error(self):
        """switch_branch should raise ValueError for non-existent node_id."""
        cm = self._make_manager_with_branches()

        with pytest.raises(ValueError, match="节点不存在"):
            cm.switch_branch("nonexistent")

    def test_switch_branch_without_branch_engine_raises_error(self):
        """switch_branch should raise ValueError if BranchEngine is not initialized."""
        cm = ConversationManager("System")

        with pytest.raises(ValueError, match="BranchEngine 未初始化"):
            cm.switch_branch("some_node")

    def test_switch_branch_active_node_id_not_changed_on_error(self):
        """active_node_id should not change if switch_branch raises an error."""
        cm = self._make_manager_with_branches()
        assert cm.active_node_id == "n2"

        with pytest.raises(ValueError):
            cm.switch_branch("nonexistent")

        # active_node_id should remain unchanged
        assert cm.active_node_id == "n2"
