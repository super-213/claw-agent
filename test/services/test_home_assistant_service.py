import pytest

from services.home_assistant_service import HomeAssistantService


def test_parse_allowed_entities_with_aliases():
    rules = HomeAssistantService.parse_allowed_entities(
        "switch.desk_lamp|书桌插座|台灯\nlight.living_room|客厅灯"
    )

    assert [rule.entity_id for rule in rules] == ["switch.desk_lamp", "light.living_room"]
    assert rules[0].aliases == ("书桌插座", "台灯")


def test_turn_on_rejects_entity_outside_whitelist():
    service = HomeAssistantService(
        base_url="http://ha.local:8123",
        token="token",
        allowed_entities="switch.allowed",
    )

    with pytest.raises(ValueError, match="entity_not_allowed"):
        service.set_power("switch.blocked", True)


def test_turn_on_calls_home_assistant_service(monkeypatch):
    calls = []
    service = HomeAssistantService(
        base_url="http://ha.local:8123",
        token="token",
        allowed_entities="switch.allowed|允许插座",
    )

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        return [{"entity_id": "switch.allowed", "state": "on"}]

    monkeypatch.setattr(service, "_request", fake_request)

    result = service.set_power("switch.allowed", True, actor={"id": "u1"})

    assert result["ok"] is True
    assert result["service"] == "switch.turn_on"
    assert calls == [
        ("POST", "/api/services/switch/turn_on", {"entity_id": "switch.allowed"})
    ]


def test_tool_call_get_state(monkeypatch):
    service = HomeAssistantService(
        base_url="http://ha.local:8123",
        token="token",
        allowed_entities="light.living_room",
    )
    monkeypatch.setattr(
        service,
        "_request",
        lambda method, path, payload=None: {
            "entity_id": "light.living_room",
            "state": "off",
            "attributes": {"friendly_name": "Living Room"},
        },
    )

    result = service.call_tool(
        "home_assistant.get_state",
        {"entity_id": "light.living_room"},
    )

    assert result["ok"] is True
    assert result["result"]["state"] == "off"


def test_chat_intent_uses_alias(monkeypatch):
    service = HomeAssistantService(
        base_url="http://ha.local:8123",
        token="token",
        allowed_entities="switch.allowed|书桌插座",
    )
    monkeypatch.setattr(
        service,
        "_request",
        lambda method, path, payload=None: [],
    )

    reply = service.handle_chat_intent("帮我打开书桌插座", {"id": "u1"})

    assert "switch.allowed" in reply
    assert "switch.turn_on" in reply
