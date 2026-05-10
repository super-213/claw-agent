"""Tests for DELETE /api/sessions/<id>/branch/<node_id> endpoint."""
import uuid
from unittest.mock import patch

import pytest

from web_app import app


@pytest.fixture
def client():
    """Create a Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def session_with_branches():
    """Create a session data dict with a branching tree structure for testing.

    Tree structure:
        root (system)
         └── n1 (user: "Hello")
              ├── n2 (assistant: "Hi there")  ← active
              │    └── n4 (user: "Follow up")
              └── n3 (user: "Branch msg")
                   └── n5 (assistant: "Branch reply")
    """
    session_id = uuid.uuid4().hex
    now = "2024-01-01T00:00:00+00:00"
    session_data = {
        "id": session_id,
        "title": "Test Session",
        "created_at": now,
        "updated_at": now,
        "active_node_id": "n4",
        "messages": [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "System prompt", "ts": now},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello", "ts": now},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi there", "ts": now},
            {"node_id": "n3", "parent_id": "n1", "role": "user", "content": "Branch msg", "ts": now},
            {"node_id": "n4", "parent_id": "n2", "role": "user", "content": "Follow up", "ts": now},
            {"node_id": "n5", "parent_id": "n3", "role": "assistant", "content": "Branch reply", "ts": now},
        ],
        "summary": "",
        "summarized_until": 1,
    }
    return session_id, session_data


class TestDeleteBranchEndpoint:
    """Tests for DELETE /api/sessions/<id>/branch/<node_id>."""

    def test_delete_branch_success(self, client, session_with_branches):
        """Successfully deleting a branch returns ok and removed_count."""
        session_id, session_data = session_with_branches

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data
            mock_store.save_messages.return_value = None

            # Delete n3 and its descendant n5 (not on active path)
            response = client.delete(
                f"/api/sessions/{session_id}/branch/n3",
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
        assert data["removed_count"] == 2  # n3 + n5

    def test_delete_branch_session_not_found(self, client):
        """Non-existent session returns 404."""
        with patch("web_app.store") as mock_store:
            mock_store.load_session.side_effect = KeyError("Session not found")

            response = client.delete(
                "/api/sessions/nonexistent/branch/n3",
            )

        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "session_not_found"

    def test_delete_branch_invalid_node_id(self, client, session_with_branches):
        """Non-existent node_id returns 404."""
        session_id, session_data = session_with_branches

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            response = client.delete(
                f"/api/sessions/{session_id}/branch/nonexistent-node",
            )

        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "invalid_node_id"

    def test_delete_branch_refuses_active_path(self, client, session_with_branches):
        """Deleting a node on the active path returns 400."""
        session_id, session_data = session_with_branches

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            # n2 is on the active path (root -> n1 -> n2 -> n4)
            response = client.delete(
                f"/api/sessions/{session_id}/branch/n2",
            )

        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "delete_rejected"
        assert "活跃" in data["message"] or "切换" in data["message"]

    def test_delete_branch_refuses_root_node(self, client, session_with_branches):
        """Deleting the root node returns 400."""
        session_id, session_data = session_with_branches

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            response = client.delete(
                f"/api/sessions/{session_id}/branch/root",
            )

        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "delete_rejected"
        assert "根节点" in data["message"]

    def test_delete_branch_persists_updated_messages(self, client, session_with_branches):
        """Deleting a branch should persist the updated messages via store.save_messages."""
        session_id, session_data = session_with_branches

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data
            mock_store.save_messages.return_value = None

            response = client.delete(
                f"/api/sessions/{session_id}/branch/n3",
            )

        assert response.status_code == 200
        # Verify save_messages was called
        mock_store.save_messages.assert_called_once()
        call_args = mock_store.save_messages.call_args
        assert call_args[0][0] == session_id
        # The saved messages should not contain n3 or n5
        saved_messages = call_args[0][1]
        saved_node_ids = {m["node_id"] for m in saved_messages}
        assert "n3" not in saved_node_ids
        assert "n5" not in saved_node_ids
        # But should still contain the active path nodes
        assert "root" in saved_node_ids
        assert "n1" in saved_node_ids
        assert "n2" in saved_node_ids
        assert "n4" in saved_node_ids

    def test_delete_branch_refuses_active_leaf_node(self, client, session_with_branches):
        """Deleting the active leaf node itself returns 400."""
        session_id, session_data = session_with_branches

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            # n4 is the active_node_id
            response = client.delete(
                f"/api/sessions/{session_id}/branch/n4",
            )

        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "delete_rejected"

    def test_delete_branch_no_branch_engine(self, client):
        """Session with no messages (no branch engine) returns 404 for any node."""
        session_id = uuid.uuid4().hex
        session_data = {
            "id": session_id,
            "title": "Empty Session",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "active_node_id": None,
            "messages": [],
            "summary": "",
            "summarized_until": 1,
        }

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            response = client.delete(
                f"/api/sessions/{session_id}/branch/some-node",
            )

        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "invalid_node_id"
