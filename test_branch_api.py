"""Tests for POST /api/sessions/<id>/branch endpoint."""
import json
import uuid
from pathlib import Path
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
def session_with_tree(tmp_path):
    """Create a session file with a tree structure for testing."""
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
        ],
        "summary": "",
        "summarized_until": 1,
    }
    return session_id, session_data


class TestCreateBranchEndpoint:
    """Tests for POST /api/sessions/<id>/branch."""

    def test_create_branch_success(self, client, session_with_tree):
        """Successfully creating a branch returns ok, branch_node_id, and ancestor_path."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data
            mock_store.save_messages.return_value = session_data

            response = client.post(
                f"/api/sessions/{session_id}/branch",
                json={"branch_point_node_id": "n1"},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
        assert "branch_node_id" in data
        assert isinstance(data["branch_node_id"], str)
        assert "ancestor_path" in data
        assert isinstance(data["ancestor_path"], list)
        # ancestor_path should start from root and end at the new branch node
        assert data["ancestor_path"][0] == "root"
        assert data["ancestor_path"][1] == "n1"
        assert data["ancestor_path"][-1] == data["branch_node_id"]

    def test_create_branch_missing_branch_point_node_id(self, client):
        """Missing branch_point_node_id returns 400."""
        response = client.post(
            "/api/sessions/some-id/branch",
            json={},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "missing_field"

    def test_create_branch_empty_branch_point_node_id(self, client):
        """Empty string branch_point_node_id returns 400."""
        response = client.post(
            "/api/sessions/some-id/branch",
            json={"branch_point_node_id": ""},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["error"] == "missing_field"

    def test_create_branch_session_not_found(self, client):
        """Non-existent session returns 404."""
        with patch("web_app.store") as mock_store:
            mock_store.load_session.side_effect = KeyError("Session not found")

            response = client.post(
                "/api/sessions/nonexistent/branch",
                json={"branch_point_node_id": "n1"},
            )

        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "session_not_found"

    def test_create_branch_invalid_node_id(self, client, session_with_tree):
        """Invalid branch_point_node_id returns 404 with error."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            response = client.post(
                f"/api/sessions/{session_id}/branch",
                json={"branch_point_node_id": "nonexistent-node"},
            )

        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "invalid_node_id"

    def test_create_branch_at_root(self, client, session_with_tree):
        """Creating a branch at root node works correctly."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data
            mock_store.save_messages.return_value = session_data

            response = client.post(
                f"/api/sessions/{session_id}/branch",
                json={"branch_point_node_id": "root"},
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
        assert data["ancestor_path"][0] == "root"
        assert len(data["ancestor_path"]) == 2  # root + new branch node

    def test_create_branch_multiple_at_same_point(self, client, session_with_tree):
        """Multiple branches at the same point should be supported."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data
            mock_store.save_messages.return_value = session_data

            response1 = client.post(
                f"/api/sessions/{session_id}/branch",
                json={"branch_point_node_id": "n1"},
            )

        assert response1.status_code == 200
        data1 = response1.get_json()

        # Update session_data to include the first branch for the second call
        new_node = {
            "node_id": data1["branch_node_id"],
            "parent_id": "n1",
            "role": "user",
            "content": "",
            "ts": "2024-01-01T00:00:00+00:00",
        }
        session_data["messages"].append(new_node)
        session_data["active_node_id"] = data1["branch_node_id"]

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data
            mock_store.save_messages.return_value = session_data

            response2 = client.post(
                f"/api/sessions/{session_id}/branch",
                json={"branch_point_node_id": "n1"},
            )

        assert response2.status_code == 200
        data2 = response2.get_json()
        # Both branches should have different node IDs
        assert data1["branch_node_id"] != data2["branch_node_id"]

    def test_create_branch_persists_messages(self, client, session_with_tree):
        """Creating a branch should persist the updated messages via store.save_messages."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data
            mock_store.save_messages.return_value = session_data

            response = client.post(
                f"/api/sessions/{session_id}/branch",
                json={"branch_point_node_id": "n1"},
            )

        assert response.status_code == 200
        # Verify save_messages was called
        mock_store.save_messages.assert_called_once()
        call_args = mock_store.save_messages.call_args
        assert call_args[0][0] == session_id  # session_id
        # The messages list should include the new branch node
        saved_messages = call_args[0][1]
        assert len(saved_messages) == 4  # original 3 + new branch node
