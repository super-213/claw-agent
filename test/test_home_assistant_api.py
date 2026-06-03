from unittest.mock import patch

import pytest

from web_app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_config_includes_home_assistant_section(client):
    response = client.get("/api/config")

    assert response.status_code == 200
    data = response.get_json()
    assert "home_assistant" in data
    assert "token" not in data["home_assistant"]


def test_home_assistant_entities_returns_whitelist(client):
    with patch("web_app.home_assistant_service") as mock_service:
        mock_service.list_allowed_entities.return_value = {
            "configured": True,
            "entities": [{"entity_id": "switch.allowed"}],
        }

        response = client.get("/api/home-assistant/entities")

    assert response.status_code == 200
    assert response.get_json()["entities"][0]["entity_id"] == "switch.allowed"
    mock_service.list_allowed_entities.assert_called_once_with(include_states=False)


def test_home_assistant_tool_call(client):
    with patch("web_app.home_assistant_service") as mock_service:
        mock_service.call_tool.return_value = {
            "ok": True,
            "tool": "home_assistant.turn_on",
            "result": {"entity_id": "switch.allowed"},
        }

        response = client.post(
            "/api/home-assistant/tools/call",
            json={
                "name": "home_assistant.turn_on",
                "arguments": {"entity_id": "switch.allowed"},
            },
        )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    mock_service.call_tool.assert_called_once()


def test_home_assistant_rejects_non_whitelisted_entity(client):
    with patch("web_app.home_assistant_service") as mock_service:
        mock_service.set_power.side_effect = ValueError("entity_not_allowed")

        response = client.post("/api/home-assistant/entities/switch.blocked/turn-on")

    assert response.status_code == 403
    assert response.get_json()["error"] == "entity_not_allowed"
