"""End-to-end test: create branch → switch → conversation → context highlighting → delete.

Validates the complete branching workflow through the API layer:
- Req 1: Branch creation
- Req 3: Branch navigation & switching
- Req 5: Context path highlighting (context_nodes)
- Req 7: Branch deletion
"""
import json
import uuid
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from web_app import app


@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _build_session_with_conversation():
    """Build a session with an initial conversation (system + 2 user/assistant exchanges).

    Tree structure:
        root (system)
         └── n1 (user: "Hello")
              └── n2 (assistant: "Hi! How can I help?")
                   └── n3 (user: "Tell me about Python")
                        └── n4 (assistant: "Python is a programming language...")
    """
    session_id = uuid.uuid4().hex
    now = "2024-01-15T10:00:00+00:00"
    return session_id, {
        "id": session_id,
        "title": "E2E Test Session",
        "created_at": now,
        "updated_at": now,
        "active_node_id": "n4",
        "messages": [
            {"node_id": "root", "parent_id": None, "role": "system",
             "content": "You are a helpful assistant.", "ts": now},
            {"node_id": "n1", "parent_id": "root", "role": "user",
             "content": "Hello", "ts": now},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant",
             "content": "Hi! How can I help?", "ts": now},
            {"node_id": "n3", "parent_id": "n2", "role": "user",
             "content": "Tell me about Python", "ts": now},
            {"node_id": "n4", "parent_id": "n3", "role": "assistant",
             "content": "Python is a programming language...", "ts": now},
        ],
        "summary": "",
        "summarized_until": 1,
    }


class TestE2EBranchingWorkflow:
    """End-to-end test for the complete branching workflow.

    Tests the full flow: create branch → switch → conversation → context → delete.
    """

    def test_full_branching_workflow(self, client):
        """Complete end-to-end branching workflow through the API layer.

        Steps:
        1. Start with a session that has conversation history
        2. Create a branch at message n2 (the first assistant reply)
        3. Switch to the new branch
        4. Verify the tree structure shows the branch
        5. Send a message on the new branch (verify context_nodes)
        6. Delete the branch
        7. Verify the branch is removed from the tree
        """
        session_id, session_data = _build_session_with_conversation()

        # We'll track session state across API calls to simulate persistence
        current_session = deepcopy(session_data)

        def mock_load_session(sid):
            if sid != session_id:
                raise KeyError(f"Session not found: {sid}")
            return deepcopy(current_session)

        def mock_save_messages(sid, messages, **kwargs):
            """Simulate persistence by updating current_session in place."""
            current_session["messages"] = messages
            if "active_node_id" in kwargs and kwargs["active_node_id"] is not None:
                current_session["active_node_id"] = kwargs["active_node_id"]
            if "summary" in kwargs and kwargs["summary"] is not None:
                current_session["summary"] = kwargs["summary"]
            if "summarized_until" in kwargs and kwargs["summarized_until"] is not None:
                current_session["summarized_until"] = kwargs["summarized_until"]
            return current_session

        with patch("web_app.store") as mock_store:
            mock_store.load_session.side_effect = mock_load_session
            mock_store.save_messages.side_effect = mock_save_messages

            # ─── Step 1: Verify initial tree structure ───
            response = client.get(f"/api/sessions/{session_id}/tree")
            assert response.status_code == 200
            tree_data = response.get_json()
            assert tree_data["active_node_id"] == "n4"
            assert len(tree_data["nodes"]) == 5  # root, n1, n2, n3, n4

            # Verify active path: root → n1 → n2 → n3 → n4
            nodes_by_id = {n["node_id"]: n for n in tree_data["nodes"]}
            for nid in ["root", "n1", "n2", "n3", "n4"]:
                assert nodes_by_id[nid]["is_active"] is True

            # ─── Step 2: Create a branch at n2 (first assistant reply) ───
            response = client.post(
                f"/api/sessions/{session_id}/branch",
                json={"branch_point_node_id": "n2"},
            )
            assert response.status_code == 200
            branch_data = response.get_json()
            assert branch_data["ok"] is True
            branch_node_id = branch_data["branch_node_id"]
            assert branch_node_id is not None
            assert len(branch_node_id) > 0

            # ancestor_path should be: root → n1 → n2 → new_branch_node
            assert branch_data["ancestor_path"][0] == "root"
            assert branch_data["ancestor_path"][1] == "n1"
            assert branch_data["ancestor_path"][2] == "n2"
            assert branch_data["ancestor_path"][-1] == branch_node_id

            # ─── Step 3: Switch to the new branch ───
            response = client.post(
                f"/api/sessions/{session_id}/switch",
                json={"target_node_id": branch_node_id},
            )
            assert response.status_code == 200
            switch_data = response.get_json()
            assert switch_data["ok"] is True
            assert switch_data["active_node_id"] == branch_node_id

            # Messages should be the path from root to the branch node
            switch_messages = switch_data["messages"]
            switch_node_ids = [m["node_id"] for m in switch_messages]
            assert switch_node_ids == ["root", "n1", "n2", branch_node_id]

            # Verify the branch node is an empty placeholder
            branch_msg = switch_messages[-1]
            assert branch_msg["content"] == ""
            assert branch_msg["parent_id"] == "n2"

            # ─── Step 4: Verify tree structure shows the branch ───
            response = client.get(f"/api/sessions/{session_id}/tree")
            assert response.status_code == 200
            tree_data = response.get_json()

            # Now active_node_id should be the branch node
            assert tree_data["active_node_id"] == branch_node_id

            # Tree should have 6 nodes: original 5 + new branch node
            assert len(tree_data["nodes"]) == 6

            nodes_by_id = {n["node_id"]: n for n in tree_data["nodes"]}
            assert branch_node_id in nodes_by_id

            # n2 should now have 2 children (n3 from original + branch_node)
            assert nodes_by_id["n2"]["child_count"] == 2

            # Active path should be: root → n1 → n2 → branch_node
            assert nodes_by_id["root"]["is_active"] is True
            assert nodes_by_id["n1"]["is_active"] is True
            assert nodes_by_id["n2"]["is_active"] is True
            assert nodes_by_id[branch_node_id]["is_active"] is True

            # n3 and n4 should NOT be on the active path anymore
            assert nodes_by_id["n3"]["is_active"] is False
            assert nodes_by_id["n4"]["is_active"] is False

            # ─── Step 5: Simulate sending a message on the new branch ───
            # We simulate what happens after a chat: a user message and assistant
            # reply are appended to the branch, with context_nodes recorded.
            # Since /api/chat/stream requires LLM integration, we simulate by
            # directly adding messages to the session and verifying context_nodes.
            user_msg_node_id = uuid.uuid4().hex
            assistant_msg_node_id = uuid.uuid4().hex
            now = "2024-01-15T10:05:00+00:00"

            # Add user message on the branch
            current_session["messages"].append({
                "node_id": user_msg_node_id,
                "parent_id": branch_node_id,
                "role": "user",
                "content": "Tell me about JavaScript instead",
                "ts": now,
            })
            # Add assistant reply with context_nodes
            context_nodes = ["root", "n1", "n2", user_msg_node_id]
            current_session["messages"].append({
                "node_id": assistant_msg_node_id,
                "parent_id": user_msg_node_id,
                "role": "assistant",
                "content": "JavaScript is a scripting language...",
                "ts": now,
                "context_nodes": context_nodes,
            })
            current_session["active_node_id"] = assistant_msg_node_id

            # ─── Step 5b: Verify context_nodes via tree and switch ───
            # Switch to the assistant message to verify the path
            response = client.post(
                f"/api/sessions/{session_id}/switch",
                json={"target_node_id": assistant_msg_node_id},
            )
            assert response.status_code == 200
            switch_data = response.get_json()
            assert switch_data["ok"] is True
            assert switch_data["active_node_id"] == assistant_msg_node_id

            # The path should be: root → n1 → n2 → branch_node → user_msg → assistant_msg
            path_node_ids = [m["node_id"] for m in switch_data["messages"]]
            assert path_node_ids == [
                "root", "n1", "n2", branch_node_id,
                user_msg_node_id, assistant_msg_node_id,
            ]

            # Verify context_nodes is present on the assistant message
            assistant_in_path = switch_data["messages"][-1]
            assert assistant_in_path["role"] == "assistant"
            assert assistant_in_path.get("context_nodes") == context_nodes

            # Context nodes should NOT include n3 or n4 (other branch)
            assert "n3" not in context_nodes
            assert "n4" not in context_nodes

            # ─── Step 6: Verify tree shows correct structure with new messages ───
            response = client.get(f"/api/sessions/{session_id}/tree")
            assert response.status_code == 200
            tree_data = response.get_json()

            # 8 nodes total: root, n1, n2, n3, n4, branch_node, user_msg, assistant_msg
            assert len(tree_data["nodes"]) == 8
            assert tree_data["active_node_id"] == assistant_msg_node_id

            nodes_by_id = {n["node_id"]: n for n in tree_data["nodes"]}

            # Active path: root → n1 → n2 → branch_node → user_msg → assistant_msg
            for nid in ["root", "n1", "n2", branch_node_id,
                        user_msg_node_id, assistant_msg_node_id]:
                assert nodes_by_id[nid]["is_active"] is True

            # Other branch nodes should not be active
            assert nodes_by_id["n3"]["is_active"] is False
            assert nodes_by_id["n4"]["is_active"] is False

            # ─── Step 7: Switch back to original branch before deleting ───
            # We need to switch away from the branch we want to delete
            # (can't delete active path)
            response = client.post(
                f"/api/sessions/{session_id}/switch",
                json={"target_node_id": "n4"},
            )
            assert response.status_code == 200
            assert response.get_json()["active_node_id"] == "n4"

            # ─── Step 8: Delete the branch ───
            # Delete the branch_node (and its descendants: user_msg, assistant_msg)
            response = client.delete(
                f"/api/sessions/{session_id}/branch/{branch_node_id}",
            )
            assert response.status_code == 200
            delete_data = response.get_json()
            assert delete_data["ok"] is True
            # Should remove branch_node + user_msg + assistant_msg = 3 nodes
            assert delete_data["removed_count"] == 3

            # ─── Step 9: Verify the branch is removed from the tree ───
            response = client.get(f"/api/sessions/{session_id}/tree")
            assert response.status_code == 200
            tree_data = response.get_json()

            # Should be back to 5 nodes: root, n1, n2, n3, n4
            assert len(tree_data["nodes"]) == 5
            assert tree_data["active_node_id"] == "n4"

            nodes_by_id = {n["node_id"]: n for n in tree_data["nodes"]}
            assert branch_node_id not in nodes_by_id
            assert user_msg_node_id not in nodes_by_id
            assert assistant_msg_node_id not in nodes_by_id

            # n2 should be back to 1 child (n3 only)
            assert nodes_by_id["n2"]["child_count"] == 1

            # Active path should be restored: root → n1 → n2 → n3 → n4
            for nid in ["root", "n1", "n2", "n3", "n4"]:
                assert nodes_by_id[nid]["is_active"] is True

    def test_cannot_delete_active_branch(self, client):
        """Verify that deleting the active branch is rejected (Req 7.2)."""
        session_id, session_data = _build_session_with_conversation()
        current_session = deepcopy(session_data)

        def mock_load_session(sid):
            if sid != session_id:
                raise KeyError(f"Session not found: {sid}")
            return deepcopy(current_session)

        def mock_save_messages(sid, messages, **kwargs):
            current_session["messages"] = messages
            if "active_node_id" in kwargs and kwargs["active_node_id"] is not None:
                current_session["active_node_id"] = kwargs["active_node_id"]
            return current_session

        with patch("web_app.store") as mock_store:
            mock_store.load_session.side_effect = mock_load_session
            mock_store.save_messages.side_effect = mock_save_messages

            # Create a branch at n2
            response = client.post(
                f"/api/sessions/{session_id}/branch",
                json={"branch_point_node_id": "n2"},
            )
            assert response.status_code == 200
            branch_node_id = response.get_json()["branch_node_id"]

            # active_node_id is now the branch_node (set by create_branch)
            # Try to delete it — should be rejected
            response = client.delete(
                f"/api/sessions/{session_id}/branch/{branch_node_id}",
            )
            assert response.status_code == 400
            data = response.get_json()
            assert data["error"] == "delete_rejected"

    def test_branch_switch_preserves_all_data(self, client):
        """Verify that switching branches preserves all message data (Req 3.3)."""
        session_id, session_data = _build_session_with_conversation()
        current_session = deepcopy(session_data)

        def mock_load_session(sid):
            if sid != session_id:
                raise KeyError(f"Session not found: {sid}")
            return deepcopy(current_session)

        def mock_save_messages(sid, messages, **kwargs):
            current_session["messages"] = messages
            if "active_node_id" in kwargs and kwargs["active_node_id"] is not None:
                current_session["active_node_id"] = kwargs["active_node_id"]
            return current_session

        with patch("web_app.store") as mock_store:
            mock_store.load_session.side_effect = mock_load_session
            mock_store.save_messages.side_effect = mock_save_messages

            # Create a branch at n2
            response = client.post(
                f"/api/sessions/{session_id}/branch",
                json={"branch_point_node_id": "n2"},
            )
            branch_node_id = response.get_json()["branch_node_id"]

            # Switch to original branch (n4)
            response = client.post(
                f"/api/sessions/{session_id}/switch",
                json={"target_node_id": "n4"},
            )
            assert response.status_code == 200
            original_path = response.get_json()["messages"]
            original_node_ids = [m["node_id"] for m in original_path]
            assert original_node_ids == ["root", "n1", "n2", "n3", "n4"]

            # Switch to branch
            response = client.post(
                f"/api/sessions/{session_id}/switch",
                json={"target_node_id": branch_node_id},
            )
            assert response.status_code == 200
            branch_path = response.get_json()["messages"]
            branch_node_ids = [m["node_id"] for m in branch_path]
            assert branch_node_ids == ["root", "n1", "n2", branch_node_id]

            # Switch back to original — all messages should still be intact
            response = client.post(
                f"/api/sessions/{session_id}/switch",
                json={"target_node_id": "n4"},
            )
            assert response.status_code == 200
            restored_path = response.get_json()["messages"]
            restored_node_ids = [m["node_id"] for m in restored_path]
            assert restored_node_ids == ["root", "n1", "n2", "n3", "n4"]

            # Verify content is preserved
            assert restored_path[1]["content"] == "Hello"
            assert restored_path[3]["content"] == "Tell me about Python"
            assert restored_path[4]["content"] == "Python is a programming language..."

    def test_multiple_branches_at_same_point(self, client):
        """Verify multiple branches can be created at the same point (Req 1.3)."""
        session_id, session_data = _build_session_with_conversation()
        current_session = deepcopy(session_data)

        def mock_load_session(sid):
            if sid != session_id:
                raise KeyError(f"Session not found: {sid}")
            return deepcopy(current_session)

        def mock_save_messages(sid, messages, **kwargs):
            current_session["messages"] = messages
            if "active_node_id" in kwargs and kwargs["active_node_id"] is not None:
                current_session["active_node_id"] = kwargs["active_node_id"]
            return current_session

        with patch("web_app.store") as mock_store:
            mock_store.load_session.side_effect = mock_load_session
            mock_store.save_messages.side_effect = mock_save_messages

            # Create first branch at n1
            response = client.post(
                f"/api/sessions/{session_id}/branch",
                json={"branch_point_node_id": "n1"},
            )
            assert response.status_code == 200
            branch1_id = response.get_json()["branch_node_id"]

            # Create second branch at n1
            response = client.post(
                f"/api/sessions/{session_id}/branch",
                json={"branch_point_node_id": "n1"},
            )
            assert response.status_code == 200
            branch2_id = response.get_json()["branch_node_id"]

            # Both branches should have different IDs
            assert branch1_id != branch2_id

            # Verify tree shows n1 with 3 children (n2 + branch1 + branch2)
            response = client.get(f"/api/sessions/{session_id}/tree")
            assert response.status_code == 200
            tree_data = response.get_json()
            nodes_by_id = {n["node_id"]: n for n in tree_data["nodes"]}
            assert nodes_by_id["n1"]["child_count"] == 3
