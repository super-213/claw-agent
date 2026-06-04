import json
from datetime import datetime, timedelta

import pytest

from services.home_assistant_service import HomeAssistantService


def test_parse_allowed_entities_with_aliases():
    rules = HomeAssistantService.parse_allowed_entities(
        "switch.desk_lamp|书桌插座|台灯|risk=high\nlight.living_room|客厅灯"
    )

    assert [rule.entity_id for rule in rules] == ["switch.desk_lamp", "light.living_room"]
    assert rules[0].aliases == ("书桌插座", "台灯")
    assert rules[0].risk_level == "high"
    assert rules[0].requires_confirmation is True
    assert rules[1].risk_level == "low"


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


def test_high_risk_device_requires_confirmation_before_power_call(monkeypatch):
    calls = []
    service = HomeAssistantService(
        base_url="http://ha.local:8123",
        token="token",
        allowed_entities="switch.heater|热水器|high",
    )
    monkeypatch.setattr(
        service,
        "_request",
        lambda method, path, payload=None: calls.append((method, path, payload)) or [],
    )

    reply = service.handle_chat_intent("打开热水器", {"id": "u1"}, session_id="s1")

    assert "需要二次确认" in reply
    assert calls == []


def test_high_risk_device_runs_after_chat_confirmation(monkeypatch):
    calls = []
    service = HomeAssistantService(
        base_url="http://ha.local:8123",
        token="token",
        allowed_entities="switch.heater|热水器|high",
    )
    monkeypatch.setattr(
        service,
        "_request",
        lambda method, path, payload=None: calls.append((method, path, payload)) or [],
    )

    service.handle_chat_intent("打开热水器", {"id": "u1"}, session_id="s1")
    reply = service.handle_chat_intent("确认", {"id": "u1"}, session_id="s1")

    assert "已确认并调用" in reply
    assert calls == [
        ("POST", "/api/services/switch/turn_on", {"entity_id": "switch.heater"})
    ]


def test_tool_call_cannot_bypass_high_risk_with_confirmed_flag(monkeypatch):
    service = HomeAssistantService(
        base_url="http://ha.local:8123",
        token="token",
        allowed_entities="switch.heater|热水器|high",
    )
    monkeypatch.setattr(service, "_request", lambda method, path, payload=None: [])

    with pytest.raises(ValueError, match="confirmation_required"):
        service.call_tool(
            "home_assistant.turn_on",
            {"entity_id": "switch.heater", "confirmed": True},
            actor={"id": "u1"},
        )


def test_home_assistant_activity_prunes_entries_older_than_retention(tmp_path):
    root = tmp_path / "home_assistant"
    root.mkdir()
    rows = [
        {"id": "old", "at": (datetime.now().astimezone() - timedelta(days=16)).isoformat()},
        {"id": "recent", "at": (datetime.now().astimezone() - timedelta(days=2)).isoformat()},
        {"id": "unknown", "at": "not-a-date"},
    ]
    (root / "activity.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    service = HomeAssistantService(root_dir=root, log_retention_days=15)

    assert [row["id"] for row in service.activity_log()] == ["recent", "unknown"]
