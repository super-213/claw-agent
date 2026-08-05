"""Tests for dashboard aggregation endpoints."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services import TokenUsageEstimator
from web_app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _sample_session():
    now = "2026-05-25T08:00:00+00:00"
    estimator = TokenUsageEstimator()
    messages = estimator.annotate_messages([
        {"node_id": "root", "parent_id": None, "role": "system", "content": "System prompt", "ts": now},
        {"node_id": "n1", "parent_id": "root", "role": "user", "content": "请分析 dashboard token 使用情况", "ts": now},
        {
            "node_id": "n2",
            "parent_id": "n1",
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {"name": "shell_execute", "arguments": '{"command":"rg token -n"}'},
            }],
            "ts": now,
        },
        {
            "node_id": "n3",
            "parent_id": "n2",
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "shell_execute",
            "content": '{"status":"success","output":{"return_code":0,"output":"token output"}}',
            "ts": now,
        },
        {"node_id": "n4", "parent_id": "n3", "role": "assistant", "content": "已完成 token 分析", "ts": now},
    ])
    return {
        "id": "session-1",
        "title": "Dashboard Session",
        "created_at": now,
        "updated_at": now,
        "active_node_id": "n4",
        "messages": messages,
        "summary": "",
        "summarized_until": 1,
        "token_usage": estimator.summarize_session(messages),
    }


def test_dashboard_page_not_served_by_backend(client):
    response = client.get("/dashboard")

    assert response.status_code == 404


def test_dashboard_summary_infers_tool_calls(client):
    session = _sample_session()
    with patch("web_app.store") as mock_store:
        mock_store.list_sessions.return_value = [SimpleNamespace(id=session["id"])]
        mock_store.load_session.return_value = session

        response = client.get("/api/dashboard/summary")

    assert response.status_code == 200
    data = response.get_json()
    assert data["kpis"]["total_sessions"] == 1
    assert data["kpis"]["tool_calls"] == 1
    assert data["kpis"]["tool_success_rate"] == 100.0
    assert data["tool_summary"]["by_category"][0]["category"] == "shell_read"
    assert data["word_cloud"]


def test_dashboard_session_detail_and_word_cloud(client):
    session = _sample_session()
    with patch("web_app.store") as mock_store:
        mock_store.list_sessions.return_value = [SimpleNamespace(id=session["id"])]
        mock_store.load_session.return_value = session

        detail_response = client.get(f"/api/dashboard/sessions/{session['id']}")
        cloud_response = client.get("/api/dashboard/word-cloud?scope=tool")

    assert detail_response.status_code == 200
    detail = detail_response.get_json()
    assert detail["session"]["id"] == session["id"]
    assert detail["session"]["tool_calls"] == 1
    assert detail["tool_calls"][0]["label"] == "rg"

    assert cloud_response.status_code == 200
    assert cloud_response.get_json()["words"]


def test_dashboard_session_not_found(client):
    with patch("web_app.store") as mock_store:
        mock_store.load_session.side_effect = KeyError("missing")

        response = client.get("/api/dashboard/sessions/missing")

    assert response.status_code == 404
    assert response.get_json()["error"] == "session_not_found"
