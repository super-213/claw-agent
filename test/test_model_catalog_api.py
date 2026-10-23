import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from config import ConfigManager
from services import UserStore
from services.auth_service import AuthSessionStore
from services.model_catalog import ModelCatalogError, fetch_available_models
import web_app


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    for key in ("DASHSCOPE_API_KEY", "API_BASE_URL", "MODEL_NAME", "VISION_MODEL"):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("DASHSCOPE_API_KEY=stored-secret\nAPI_BASE_URL=https://saved.example/v1\nMODEL_NAME=old-model\n")
    config = ConfigManager(str(env_file))
    monkeypatch.setattr(web_app, "config", config)
    monkeypatch.setattr(web_app, "user_store", UserStore(tmp_path / "users.json"))
    monkeypatch.setattr(web_app, "auth_sessions", AuthSessionStore())
    monkeypatch.setitem(web_app.app.config, "TESTING", False)
    # Keep bootstrap ownership migration isolated from the user's conversations.
    monkeypatch.setattr(web_app, "store", web_app.ConversationStore(tmp_path / "conversations"))
    with TestClient(web_app.app) as client:
        response = client.post("/api/auth/bootstrap-admin", json={"username": "admin", "password": "password123"})
        assert response.status_code == 200
        yield client, config, env_file


def test_discovery_uses_saved_credentials_and_does_not_write_config(admin_client, monkeypatch):
    client, config, env = admin_client
    before = env.read_text()
    fetch = AsyncMock(return_value=[{"id": "model-a", "owned_by": "vendor"}])
    monkeypatch.setattr(web_app, "fetch_available_models", fetch)
    response = client.post("/api/config/models", json={})
    assert response.status_code == 200
    assert response.json()["models"][0]["id"] == "model-a"
    assert response.headers["cache-control"] == "no-store"
    assert "secret" not in response.text
    fetch.assert_awaited_once_with(base_url="https://saved.example/v1", api_key="stored-secret")
    assert env.read_text() == before and config["model"] == "old-model"


def test_preview_uses_unsaved_url_and_key_then_admin_can_save_selection(admin_client, monkeypatch):
    client, config, env = admin_client
    before = env.read_text()
    fetch = AsyncMock(return_value=[{"id": "selected-model", "owned_by": "vendor"}])
    monkeypatch.setattr(web_app, "fetch_available_models", fetch)
    response = client.post("/api/config/models", json={"base_url": "https://preview.example/v1/", "api_key": "preview-secret"})
    assert response.status_code == 200
    fetch.assert_awaited_once_with(base_url="https://preview.example/v1", api_key="preview-secret")
    assert env.read_text() == before and config["api_key"] == "stored-secret"
    saved = client.post("/api/config", json={"model": "selected-model", "vision_model": "selected-vision"})
    assert saved.status_code == 200
    assert config["model"] == "selected-model" and config["vision_model"] == "selected-vision"
    assert "MODEL_NAME=selected-model" in env.read_text()
    assert "VISION_MODEL=selected-vision" in env.read_text()
    llm = web_app._new_llm_client()
    try:
        assert llm.model == "selected-model" and llm.vision_model == "selected-vision"
    finally:
        llm.close()


def test_regular_user_cannot_discover_or_change_models(admin_client, monkeypatch):
    client, config, env = admin_client
    client.post("/api/admin/users", json={"username": "alice", "password": "password123"})
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "alice", "password": "password123"}).status_code == 200
    fetch = AsyncMock()
    monkeypatch.setattr(web_app, "fetch_available_models", fetch)
    before = env.read_text()
    assert client.post("/api/config/models", json={}).status_code == 403
    assert client.post("/api/config", json={"model": "unauthorized-model"}).status_code == 403
    assert client.post("/api/config", json={"vision_model": "unauthorized-vision"}).status_code == 403
    assert env.read_text() == before and config["model"] == "old-model"
    fetch.assert_not_called()
    client.post("/api/auth/logout")
    assert client.post("/api/config/models", json={}).status_code == 401
    assert client.post("/api/config", json={"model": "unauthorized-model"}).status_code == 401


def test_discovery_errors_preserve_configuration_and_login(admin_client, monkeypatch):
    client, config, env = admin_client
    before = env.read_text()
    fetch = AsyncMock(side_effect=ModelCatalogError("模型服务鉴权失败，请检查 API KEY 及其访问权限"))
    monkeypatch.setattr(web_app, "fetch_available_models", fetch)
    response = client.post("/api/config/models", json={})
    assert response.status_code == 502
    assert "鉴权失败" in response.json()["message"]
    assert client.get("/api/auth/me").status_code == 200
    assert env.read_text() == before
    fetch.reset_mock()
    assert client.post("/api/config/models", json={"base_url": "not-a-url"}).status_code == 400
    fetch.assert_not_called()


def test_catalog_calls_models_endpoint_and_deduplicates_ids(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"object": "list", "data": [
            {"id": "z-model", "owned_by": "vendor"},
            {"id": "a-model"}, {"id": "z-model", "owned_by": "vendor"}, {"id": ""},
        ]})
    def client_factory(**kwargs):
        return AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr("services.model_catalog.AsyncOpenAI", client_factory)
    models = asyncio.run(fetch_available_models(base_url="https://example.com/v1", api_key="test-secret"))
    assert [model["id"] for model in models] == ["a-model", "z-model"]
    assert str(requests[0].url) == "https://example.com/v1/models"
    assert requests[0].headers["authorization"] == "Bearer test-secret"


@pytest.mark.parametrize("status,expected", [(401, "鉴权失败"), (403, "鉴权失败"), (404, "模型列表"), (429, "过于频繁"), (500, "HTTP 500")])
def test_catalog_hides_upstream_error_body_and_key(monkeypatch, status, expected):
    def client_factory(**kwargs):
        transport = httpx.MockTransport(lambda request: httpx.Response(status, json={"error": {"message": "private-secret raw provider error"}}))
        return AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=transport))
    monkeypatch.setattr("services.model_catalog.AsyncOpenAI", client_factory)
    with pytest.raises(ModelCatalogError, match=expected) as error:
        asyncio.run(fetch_available_models(base_url="https://example.com/v1", api_key="private-secret"))
    assert "private-secret" not in str(error.value)


def test_empty_catalog_is_a_valid_response(monkeypatch):
    def client_factory(**kwargs):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"object": "list", "data": []}))
        return AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=transport))
    monkeypatch.setattr("services.model_catalog.AsyncOpenAI", client_factory)
    assert asyncio.run(fetch_available_models(base_url="https://example.com/v1", api_key="test")) == []
