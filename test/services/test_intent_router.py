import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.home_assistant_service import HomeAssistantService
from services.home_service import HomeDataService
from services.intent_router import HybridIntentRouter
from skills.registry import SkillRegistry


class FakeIntentLLM:
    def __init__(self, response: str):
        self.response = response
        self.model = "fake-intent"

    async def achat(self, messages):
        return self.response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


def _actor():
    return {"id": "u_001", "username": "alice", "role": "admin", "status": "active"}


def _router(tmp_path, llm_response: str, ha_service: HomeAssistantService | None = None):
    skills_dir = tmp_path / "skills"
    (skills_dir / "search").mkdir(parents=True)
    (skills_dir / "search" / "search.md").write_text("# Search\n", encoding="utf-8")
    (skills_dir / "calculator").mkdir(parents=True)
    (skills_dir / "calculator" / "calculator.md").write_text("# Calculator\n", encoding="utf-8")

    return HybridIntentRouter(
        llm_factory=lambda: FakeIntentLLM(llm_response),
        home_assistant_service=ha_service
        or HomeAssistantService(
            base_url="http://ha.local:8123",
            token="token",
            allowed_entities="switch.desk|书桌插座",
        ),
        home_service=HomeDataService(tmp_path / "home", timezone_name="Asia/Shanghai"),
        skill_registry=SkillRegistry(str(skills_dir)),
    )


def test_llm_home_assistant_intent_executes_through_local_service(tmp_path, monkeypatch):
    ha_service = HomeAssistantService(
        base_url="http://ha.local:8123",
        token="token",
        allowed_entities="switch.desk|书桌插座",
    )
    calls = []
    monkeypatch.setattr(
        ha_service,
        "_request",
        lambda method, path, payload=None: calls.append((method, path, payload)) or [],
    )
    router = _router(
        tmp_path,
        '{"domain":"home_assistant","intent":"turn_on","confidence":0.91,'
        '"slots":{"entity_alias":"书桌插座"},"reason":"control device"}',
        ha_service,
    )

    result = asyncio.run(router.route("帮我把书桌那个插座开一下", _actor(), "s1"))

    assert result.action == "direct_response"
    assert "switch.desk" in result.reply
    assert calls == [("POST", "/api/services/switch/turn_on", {"entity_id": "switch.desk"})]


def test_llm_home_assistant_unknown_entity_does_not_execute(tmp_path, monkeypatch):
    ha_service = HomeAssistantService(
        base_url="http://ha.local:8123",
        token="token",
        allowed_entities="switch.desk|书桌插座",
    )
    calls = []
    monkeypatch.setattr(
        ha_service,
        "_request",
        lambda method, path, payload=None: calls.append((method, path, payload)) or [],
    )
    router = _router(
        tmp_path,
        '{"domain":"home_assistant","intent":"turn_on","confidence":0.95,'
        '"slots":{"entity_alias":"陌生设备"},"reason":"control device"}',
        ha_service,
    )

    result = asyncio.run(router.route("打开陌生设备", _actor(), "s1"))

    assert result.action == "general_chat"
    assert calls == []


def test_llm_skill_intent_returns_auto_skill(tmp_path):
    router = _router(
        tmp_path,
        '{"domain":"skill","intent":"web_search","confidence":0.72,'
        '"slots":{"skill":"search"},"reason":"needs fresh info"}',
    )

    result = asyncio.run(router.route("帮我查一下这个库的最新版本", _actor(), "s1"))

    assert result.action == "load_skills"
    assert result.skills == ["search"]
