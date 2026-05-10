"""Tests for ConversationManager + BranchEngine integration (Task 3.1)"""

import pytest
from core.conversation import ConversationManager
from core.branch_engine import BranchEngine


class TestConversationManagerBranchIntegration:
    """Test that ConversationManager correctly integrates BranchEngine on load_messages."""

    def test_branch_engine_is_none_initially(self):
        """branch_engine should be None before load_messages is called."""
        cm = ConversationManager("You are a helpful assistant.")
        assert cm.branch_engine is None

    def test_load_messages_with_node_ids_builds_branch_engine(self):
        """load_messages with node_id/parent_id should construct BranchEngine directly."""
        cm = ConversationManager("System")
        messages = [
            {"role": "system", "content": "System", "node_id": "root", "parent_id": None},
            {"role": "user", "content": "Hello", "node_id": "n1", "parent_id": "root"},
            {"role": "assistant", "content": "Hi", "node_id": "n2", "parent_id": "n1"},
        ]
        cm.load_messages(messages)

        assert cm.branch_engine is not None
        assert isinstance(cm.branch_engine, BranchEngine)

    def test_branch_engine_has_correct_nodes_after_load(self):
        """BranchEngine should index all loaded messages by node_id."""
        cm = ConversationManager("System")
        messages = [
            {"role": "system", "content": "System", "node_id": "root", "parent_id": None},
            {"role": "user", "content": "Hello", "node_id": "n1", "parent_id": "root"},
            {"role": "assistant", "content": "Hi", "node_id": "n2", "parent_id": "n1"},
        ]
        cm.load_messages(messages)

        # Verify all nodes are indexed
        assert "root" in cm.branch_engine._nodes
        assert "n1" in cm.branch_engine._nodes
        assert "n2" in cm.branch_engine._nodes

    def test_branch_engine_children_mapping(self):
        """BranchEngine should correctly map parent-child relationships."""
        cm = ConversationManager("System")
        messages = [
            {"role": "system", "content": "System", "node_id": "root", "parent_id": None},
            {"role": "user", "content": "Hello", "node_id": "n1", "parent_id": "root"},
            {"role": "assistant", "content": "Hi", "node_id": "n2", "parent_id": "n1"},
        ]
        cm.load_messages(messages)

        assert "n1" in cm.branch_engine._children["root"]
        assert "n2" in cm.branch_engine._children["n1"]

    def test_load_messages_legacy_format_migrates(self):
        """load_messages without node_id should migrate via BranchEngine.migrate_linear."""
        cm = ConversationManager("System")
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        cm.load_messages(messages)

        assert cm.branch_engine is not None
        assert isinstance(cm.branch_engine, BranchEngine)

        # After migration, messages should have node_id and parent_id
        loaded = cm.get_messages()
        for msg in loaded:
            assert "node_id" in msg
            assert "parent_id" in msg

        # First message should have parent_id = None (root)
        assert loaded[0]["parent_id"] is None
        # Second message should point to first
        assert loaded[1]["parent_id"] == loaded[0]["node_id"]
        # Third message should point to second
        assert loaded[2]["parent_id"] == loaded[1]["node_id"]

    def test_branch_engine_path_query_after_load(self):
        """BranchEngine should support path queries after load_messages."""
        cm = ConversationManager("System")
        messages = [
            {"role": "system", "content": "System", "node_id": "root", "parent_id": None},
            {"role": "user", "content": "Hello", "node_id": "n1", "parent_id": "root"},
            {"role": "assistant", "content": "Hi", "node_id": "n2", "parent_id": "n1"},
        ]
        cm.load_messages(messages)

        path = cm.branch_engine.get_path_to_node("n2")
        assert len(path) == 3
        assert path[0]["node_id"] == "root"
        assert path[1]["node_id"] == "n1"
        assert path[2]["node_id"] == "n2"

    def test_branch_engine_available_for_create_branch(self):
        """BranchEngine should be usable for create_branch after load."""
        cm = ConversationManager("System")
        messages = [
            {"role": "system", "content": "System", "node_id": "root", "parent_id": None},
            {"role": "user", "content": "Hello", "node_id": "n1", "parent_id": "root"},
            {"role": "assistant", "content": "Hi", "node_id": "n2", "parent_id": "n1"},
        ]
        cm.load_messages(messages)

        # Create a branch at n1
        new_node_id = cm.branch_engine.create_branch("n1")
        assert new_node_id is not None
        assert new_node_id in cm.branch_engine._nodes
        assert new_node_id in cm.branch_engine._children["n1"]

    def test_branch_engine_available_for_build_context(self):
        """BranchEngine should be usable for build_context after load."""
        cm = ConversationManager("System")
        messages = [
            {"role": "system", "content": "System", "node_id": "root", "parent_id": None},
            {"role": "user", "content": "Hello", "node_id": "n1", "parent_id": "root"},
            {"role": "assistant", "content": "Hi", "node_id": "n2", "parent_id": "n1"},
        ]
        cm.load_messages(messages)

        context = cm.branch_engine.build_context("n2")
        assert len(context) == 3
        assert context[0]["content"] == "System"
        assert context[1]["content"] == "Hello"
        assert context[2]["content"] == "Hi"

    def test_load_messages_with_branching_structure(self):
        """BranchEngine should handle messages with multiple branches."""
        cm = ConversationManager("System")
        messages = [
            {"role": "system", "content": "System", "node_id": "root", "parent_id": None},
            {"role": "user", "content": "Hello", "node_id": "n1", "parent_id": "root"},
            {"role": "assistant", "content": "Hi", "node_id": "n2", "parent_id": "n1"},
            # Branch from n1
            {"role": "user", "content": "Bye", "node_id": "n3", "parent_id": "n1"},
            {"role": "assistant", "content": "Goodbye", "node_id": "n4", "parent_id": "n3"},
        ]
        cm.load_messages(messages)

        # Both branches should be accessible
        path_to_n2 = cm.branch_engine.get_path_to_node("n2")
        assert len(path_to_n2) == 3

        path_to_n4 = cm.branch_engine.get_path_to_node("n4")
        assert len(path_to_n4) == 4
        assert path_to_n4[2]["content"] == "Bye"
        assert path_to_n4[3]["content"] == "Goodbye"

    def test_context_nodes_preserved_on_load(self):
        """context_nodes field should be preserved when loading messages."""
        cm = ConversationManager("System")
        messages = [
            {"role": "system", "content": "System", "node_id": "root", "parent_id": None},
            {"role": "user", "content": "Hello", "node_id": "n1", "parent_id": "root"},
            {"role": "assistant", "content": "Hi", "node_id": "n2", "parent_id": "n1",
             "context_nodes": ["root", "n1"]},
        ]
        cm.load_messages(messages)

        loaded = cm.get_messages()
        assert loaded[2].get("context_nodes") == ["root", "n1"]
