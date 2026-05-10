"""Tests for POST /api/sessions/<id>/switch endpoint."""
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
def session_with_tree():
    """Create a session data dict with a tree structure for testing."""
    session_id = uuid.uuid4().hex
    now = "2024-01-01T00:00:00+00:00"
    session_data = {
        "id": session_id,
        "title": "Test Session",
        "created_at": now,
        "updated_at": now,
        "active_node_id": "n2",
        "messages": [
            {"node_id": "root", "parent_id": None, "role": "system", "content": "System prompt", "ts": now},
            {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Hello", "ts": now},
            {"node_id": "n2", "parent_id": "n1", "role": "assistant", "content": "Hi there", "ts": now},
            {"node_id": "n3", "parent_id": "n1", "role": "user", "content": "Branch msg", "ts": now},
        ],
        "summary": "",
        "summarized_until": 1,
    }
    return session_id, session_data


class TestSwitchBranchEndpoint:
    """Tests for POST /api/sessions/<id>/switch."""

    def test_switch_branch_success(self, client, session_with_tree):
        """Successfully switching branch returns ok, active_node_id, and messages."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data
            mock_store.save_messages.return_value = None

            response = client.post(
                f"/api/sessions/{session_id}/switch",
                json={"target_node_id": "n3"},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
        assert data["active_node_id"] == "n3"
        assert isinstance(data["messages"], list)
        # Path from root to n3: root -> n1 -> n3
        node_ids = [m["node_id"] for m in data["messages"]]
        assert node_ids == ["root", "n1", "n3"]

    def test_switch_branch_missing_target_node_id(self, client):
        """Missing target_node_id returns 400."""
        response = client.post(
            "/api/sessions/some-id/switch",
            json={},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "missing_field"

    def test_switch_branch_empty_target_node_id(self, client):
        """Empty string target_node_id returns 400."""
        response = client.post(
            "/api/sessions/some-id/switch",
            json={"target_node_id": ""},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "missing_field"

    def test_switch_branch_session_not_found(self, client):
        """Non-existent session returns 404."""
        with patch("web_app.store") as mock_store:
            mock_store.load_session.side_effect = KeyError("Session not found")

            response = client.post(
                "/api/sessions/nonexistent/switch",
                json={"target_node_id": "n1"},
            )

        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "session_not_found"

    def test_switch_branch_invalid_node_id(self, client, session_with_tree):
        """Invalid target_node_id returns 404 with error."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            response = client.post(
                f"/api/sessions/{session_id}/switch",
                json={"target_node_id": "nonexistent-node"},
            )

        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "invalid_node_id"

    def test_switch_branch_persists_active_node_id(self, client, session_with_tree):
        """Switching branch should persist the updated active_node_id via store.save_messages."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data
            mock_store.save_messages.return_value = None

            response = client.post(
                f"/api/sessions/{session_id}/switch",
                json={"target_node_id": "n3"},
            )

        assert response.status_code == 200
        # Verify save_messages was called with the correct active_node_id
        mock_store.save_messages.assert_called_once()
        call_args = mock_store.save_messages.call_args
        assert call_args[0][0] == session_id
        assert call_args[1]["active_node_id"] == "n3"

    def test_switch_branch_returns_full_path_messages(self, client, session_with_tree):
        """Switching to a node returns all messages from root to that node."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data
            mock_store.save_messages.return_value = None

            response = client.post(
                f"/api/sessions/{session_id}/switch",
                json={"target_node_id": "n2"},
            )

        assert response.status_code == 200
        data = response.get_json()
        messages = data["messages"]
        # Path from root to n2: root -> n1 -> n2
        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["content"] == "Hello"
        assert messages[2]["content"] == "Hi there"
