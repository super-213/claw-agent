from unittest.mock import patch

import pytest

from agent_runtime import MemoryStore, RunStore
from services import ConversationStore
from web_app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_session_runs_returns_persisted_run_state(client, tmp_path):
    conversation_store = ConversationStore(tmp_path / "conversations")
    runtime_store = RunStore(tmp_path / "runs")
    with patch("web_app.store", conversation_store), patch("web_app.run_store", runtime_store):
        session = client.post("/api/sessions").get_json()
        run = runtime_store.create(
            session_id=session["id"],
            goal="test goal",
            max_steps=5,
            max_runtime_seconds=30,
        )
        runtime_store.append_step(run, {"kind": "model", "content": "checkpoint"})

        response = client.get(f"/api/sessions/{session['id']}/runs")

    assert response.status_code == 200
    data = response.get_json()
    assert data["runs"][0]["id"] == run["id"]
    assert data["runs"][0]["step_count"] == 1


def test_resume_unknown_run_returns_404(client, tmp_path):
    runtime_store = RunStore(tmp_path / "runs")
    with patch("web_app.run_store", runtime_store):
        response = client.post(f"/api/runs/{'a' * 32}/resume")

    assert response.status_code == 404


def test_runtime_tools_exposes_schema_without_handlers(client):
    response = client.get("/api/runtime/tools")

    assert response.status_code == 200
    tools = response.get_json()["tools"]
    names = {tool["name"] for tool in tools}
    assert {"datetime_now", "file_read", "file_write", "http_request", "shell_execute"} <= names
    assert all("input_schema" in tool and "description" in tool for tool in tools)
    canonical = {name for tool in tools for name in tool.get("canonical_names", [])}
    assert {"datetime.now", "file.read", "file.write", "http.request", "shell.execute"} <= canonical


def test_run_cancel_endpoint_persists_signal(client, tmp_path):
    conversation_store = ConversationStore(tmp_path / "conversations")
    runtime_store = RunStore(tmp_path / "runs")
    with patch("web_app.store", conversation_store), patch("web_app.run_store", runtime_store):
        session = client.post("/api/sessions").get_json()
        run = runtime_store.create(
            session_id=session["id"], goal="cancel", max_steps=5, max_runtime_seconds=30
        )
        response = client.post(f"/api/runs/{run['id']}/cancel")
    assert response.status_code == 200
    assert runtime_store.load(run["id"])["cancel_requested"] is True


def test_memory_api_requires_explicit_write_and_supports_delete(client, tmp_path):
    conversation_store = ConversationStore(tmp_path / "conversations")
    memories = MemoryStore(tmp_path / "memories")
    with patch("web_app.store", conversation_store), patch("web_app.memory_store", memories):
        session = client.post("/api/sessions").get_json()
        created = client.post("/api/memories", json={
            "scope": "session", "session_id": session["id"],
            "content": "project uses green", "source": "test",
        })
        assert created.status_code == 201
        memory_id = created.get_json()["memory"]["id"]
        found = client.get(f"/api/memories?session_id={session['id']}&query=green")
        assert found.get_json()["memories"][0]["id"] == memory_id
        deleted = client.delete(
            f"/api/memories/{memory_id}?scope=session&session_id={session['id']}"
        )
        assert deleted.get_json()["deleted"] is True
