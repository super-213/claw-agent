"""Tests for GET /api/sessions/<id>/tree endpoint."""
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
            {"node_id": "n3", "parent_id": "n1", "role": "user", "content": "Branch message here", "ts": now},
        ],
        "summary": "",
        "summarized_until": 1,
    }
    return session_id, session_data


class TestGetSessionTreeEndpoint:
    """Tests for GET /api/sessions/<id>/tree."""

    def test_get_tree_success(self, client, session_with_tree):
        """Successfully getting tree returns nodes array and active_node_id."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            response = client.get(f"/api/sessions/{session_id}/tree")

        assert response.status_code == 200
        data = response.get_json()
        assert "nodes" in data
        assert "active_node_id" in data
        assert isinstance(data["nodes"], list)
        assert data["active_node_id"] == "n2"

    def test_get_tree_node_structure(self, client, session_with_tree):
        """Each node in the tree has the expected fields."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            response = client.get(f"/api/sessions/{session_id}/tree")

        data = response.get_json()
        assert len(data["nodes"]) == 4

        for node in data["nodes"]:
            assert "node_id" in node
            assert "parent_id" in node
            assert "role" in node
            assert "summary" in node
            assert "is_active" in node
            assert "child_count" in node

    def test_get_tree_active_path_marked(self, client, session_with_tree):
        """Nodes on the active path are marked with is_active=True."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            response = client.get(f"/api/sessions/{session_id}/tree")

        data = response.get_json()
        nodes_by_id = {n["node_id"]: n for n in data["nodes"]}

        # Active path is root -> n1 -> n2
        assert nodes_by_id["root"]["is_active"] is True
        assert nodes_by_id["n1"]["is_active"] is True
        assert nodes_by_id["n2"]["is_active"] is True
        # n3 is on a different branch
        assert nodes_by_id["n3"]["is_active"] is False

    def test_get_tree_child_count(self, client, session_with_tree):
        """child_count reflects the number of children for each node."""
        session_id, session_data = session_with_tree

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            response = client.get(f"/api/sessions/{session_id}/tree")

        data = response.get_json()
        nodes_by_id = {n["node_id"]: n for n in data["nodes"]}

        # root has 1 child (n1)
        assert nodes_by_id["root"]["child_count"] == 1
        # n1 has 2 children (n2, n3)
        assert nodes_by_id["n1"]["child_count"] == 2
        # n2 and n3 are leaves
        assert nodes_by_id["n2"]["child_count"] == 0
        assert nodes_by_id["n3"]["child_count"] == 0

    def test_get_tree_summary_truncation(self, client):
        """Long content is truncated to 30 chars + '...' in summary."""
        session_id = uuid.uuid4().hex
        now = "2024-01-01T00:00:00+00:00"
        long_content = "A" * 50
        session_data = {
            "id": session_id,
            "title": "Test",
            "created_at": now,
            "updated_at": now,
            "active_node_id": "n1",
            "messages": [
                {"node_id": "root", "parent_id": None, "role": "system", "content": long_content, "ts": now},
                {"node_id": "n1", "parent_id": "root", "role": "user", "content": "Short", "ts": now},
            ],
            "summary": "",
            "summarized_until": 1,
        }

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            response = client.get(f"/api/sessions/{session_id}/tree")

        data = response.get_json()
        nodes_by_id = {n["node_id"]: n for n in data["nodes"]}

        # Long content should be truncated
        assert nodes_by_id["root"]["summary"] == "A" * 30 + "..."
        # Short content should not be truncated
        assert nodes_by_id["n1"]["summary"] == "Short"

    def test_get_tree_session_not_found(self, client):
        """Non-existent session returns 404."""
        with patch("web_app.store") as mock_store:
            mock_store.load_session.side_effect = KeyError("Session not found")

            response = client.get("/api/sessions/nonexistent/tree")

        assert response.status_code == 404
        data = response.get_json()
        assert data["error"] == "session_not_found"

    def test_get_tree_empty_session(self, client):
        """Session with no messages returns empty nodes list."""
        session_id = uuid.uuid4().hex
        session_data = {
            "id": session_id,
            "title": "Empty",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "active_node_id": None,
            "messages": [],
            "summary": "",
            "summarized_until": 1,
        }

        with patch("web_app.store") as mock_store:
            mock_store.load_session.return_value = session_data

            response = client.get(f"/api/sessions/{session_id}/tree")

        assert response.status_code == 200
        data = response.get_json()
        assert data["nodes"] == []
