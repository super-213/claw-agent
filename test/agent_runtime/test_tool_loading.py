import asyncio
from copy import deepcopy
import json

import pytest

from agent_runtime import AgentModelResponse, RunStore, ToolCall, ToolDefinition, ToolRegistry
from agent_runtime.tool_loading import ToolLoadingSession
from core.conversation import ConversationManager
from core.orchestrator import AgentOrchestrator
from skills.registry import SkillRegistry


def register(registry, name, description="test", handler=None, **kwargs):
    registry.register(ToolDefinition(name=name, description=description,
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler or (lambda args: "ok"), **kwargs))


def names(schemas):
    return {s["function"]["name"] for s in schemas}


def test_initial_schema_is_bounded_even_with_many_registered_tools():
    registry = ToolRegistry()
    for index in range(100):
        register(registry, f"external_tool_{index}")
    register(registry, "skill_load")
    session = ToolLoadingSession(registry, lambda: None)
    assert names(session.schemas()) == {"tool_load", "skill_load"}
    assert len(session.catalog()) < 150
    assert "parameters" not in session.catalog()
    assert registry.get("tool_load") is None


def test_search_loads_related_tools_without_running_handlers():
    registry = ToolRegistry()
    executed = []
    register(registry, "http_request", "访问公网网页和天气", lambda args: executed.append(True))
    register(registry, "family_task_list", "读取家庭事项清单")
    register(registry, "knowledge_search", "搜索以前保存的资料")
    session = ToolLoadingSession(registry, lambda: None)
    result = session.discover({"query": "查询天气"})
    assert [row["name"] for row in result["loaded"]] == ["http_request"]
    assert names(session.schemas()) == {"tool_load", "http_request"}
    assert not executed
    assert "parameters" not in json.dumps(result)


def test_exact_alias_no_matches_unknown_names_and_no_automatic_eviction():
    registry = ToolRegistry()
    register(registry, "file_read")
    registry.register_alias("file.read", "file_read")
    for index in range(12):
        register(registry, f"custom_{index}")
    session = ToolLoadingSession(registry, lambda: None)
    assert session.discover({"query": "file.read"})["loaded"][0]["name"] == "file_read"
    assert not session.discover({"query": "nothing-matches-here"})["loaded"]
    before = list(session.loaded)
    with pytest.raises(ValueError):
        session.discover({"names": ["file_read", "nonexistent"]})
    assert session.loaded == before  # Atomic loading on invalid requests.
    for index in range(12):
        session.discover({"names": [f"custom_{index}"]})
    assert len(session.loaded) == 13 and "custom_0" in session.loaded
    assert "file_read" in names(session.schemas())
    assert "custom_11" in names(session.schemas())


def test_sessions_and_skill_permissions_are_isolated():
    registry = ToolRegistry()
    register(registry, "file_read")
    register(registry, "file_write")
    allowed = None
    first = ToolLoadingSession(registry, lambda: allowed)
    second = ToolLoadingSession(registry, lambda: None)
    first.load(["file_write"])
    assert names(second.schemas()) == {"tool_load"}
    allowed = {"file_read"}
    assert "file_write" not in names(first.schemas())
    with pytest.raises(ValueError, match="not_allowed"):
        first.discover({"names": ["file_write"]})
    result = first.discover({"query": "file_write"})
    assert all(row["name"] != "file_write" for row in result["loaded"])
    first.restore(["file_write", "file_read", "removed_tool"])
    assert first.loaded == ["file_read"]


@pytest.mark.parametrize("load_request", [{"group": "other"}, {"query": "custom"},
                                      {"names": [f"custom_{i:02}" for i in range(12)]}])
def test_all_matches_and_explicit_names_can_load_more_than_eight(load_request):
    registry = ToolRegistry()
    for index in range(12):
        register(registry, f"custom_{index:02}")
    session = ToolLoadingSession(registry, lambda: None)
    assert names(session.schemas()) == {"tool_load"}
    result = session.discover(load_request)
    assert [row["name"] for row in result["loaded"]] == [f"custom_{i:02}" for i in range(12)]
    assert len(session.loaded) == 12 and len(session.schemas()) == 13
    assert result["next_offset"] is None
    assert "maxItems" not in session.controls.schemas()[0]["function"]["parameters"]["properties"]["names"]
    restored = ToolLoadingSession(registry, lambda: None)
    restored.restore(session.loaded)
    assert restored.loaded == session.loaded


def make_orchestrator(tmp_path, registry, llm, skills=None):
    return AgentOrchestrator(llm_client=llm, conversation=ConversationManager("test"),
        tool_registry=registry, skill_registry=skills or SkillRegistry(str(tmp_path / "skills")),
        run_store=RunStore(tmp_path / "runs"), max_steps=12)


@pytest.mark.parametrize("streaming", [False, True])
def test_discovery_execution_and_next_turn_reset_use_native_protocol(tmp_path, streaming):
    registry = ToolRegistry()
    executed = []
    register(registry, "http_request", "访问公网网页", lambda args: executed.append(True) or "page")
    register(registry, "family_task_list", "读取事项")
    snapshots = []

    class Model:
        model = "test"
        async def achat_with_tools(self, messages, schemas):
            snapshots.append(deepcopy(schemas))
            turn = len(snapshots)
            if turn == 1:
                assert names(schemas) == {"tool_load"}
                return AgentModelResponse(tool_calls=[ToolCall("discover", "tool_load", {"query": "查询网页"})])
            if turn == 2:
                assert names(schemas) == {"tool_load", "http_request"}
                return AgentModelResponse(tool_calls=[ToolCall("fetch", "http_request", {})])
            if turn == 3:
                assert any(m.get("name") == "http_request" for m in messages)
            if turn == 4:
                assert names(schemas) == {"tool_load"}
            return AgentModelResponse(content="done")
        async def astream_with_tools(self, messages, schemas):
            yield {"type": "done", "response": await self.achat_with_tools(messages, schemas)}

    orchestrator = make_orchestrator(tmp_path, registry, Model())
    async def run():
        if streaming:
            return [event async for event in orchestrator.process_user_input_stream_async("查网页", session_id="first")]
        await orchestrator.process_user_input_async("查网页", session_id="first")
    asyncio.run(run())
    assert executed == [True]
    assert orchestrator.run["loaded_tools"] == ["http_request"]
    starts = [e for e in orchestrator.run["events"] if e.get("phase") == "start"]
    assert starts[0]["tool_names"] == ["tool_load"]
    assert starts[1]["tool_schema_chars"] > starts[0]["tool_schema_chars"]
    asyncio.run(orchestrator.process_user_input_async("你好", session_id="second"))
    assert len(snapshots) == 4
    assert orchestrator.run["loaded_tools"] == []


def test_loaded_state_survives_approval_and_fresh_orchestrator_resume(tmp_path):
    registry = ToolRegistry()
    executed = []
    register(registry, "write_report", handler=lambda args: executed.append(True), requires_confirmation=True)
    extra = [f"support_{i}" for i in range(10)]
    for name in extra:
        register(registry, name)
    class Model:
        model = "test"
        turn = 0
        async def achat_with_tools(self, messages, schemas):
            self.turn += 1
            if self.turn == 1:
                return AgentModelResponse(tool_calls=[ToolCall("load", "tool_load", {"names": ["write_report", *extra]})])
            return AgentModelResponse(tool_calls=[ToolCall("write", "write_report", {})])
    first = make_orchestrator(tmp_path, registry, Model())
    asyncio.run(first.process_user_input_async("写报告", session_id="approval"))
    assert first.run["status"] == "waiting_approval" and not executed
    class ResumedModel:
        model = "test"
        async def achat_with_tools(self, messages, schemas):
            assert names(schemas) == {"tool_load", "write_report", *extra}
            return AgentModelResponse(content="done")
    second = make_orchestrator(tmp_path, registry, ResumedModel())
    second.conversation = first.conversation
    async def resume():
        return [e async for e in second.resume_after_approval_stream_async(
            first.run["id"], first.pending_approval_token)]
    asyncio.run(resume())
    assert executed == [True] and second.run["status"] == "completed"


def test_skill_required_tools_are_loaded_and_other_tools_stay_deferred(tmp_path):
    root = tmp_path / "skills" / "report"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("Build report")
    required = ["file_read", *[f"required_{i}" for i in range(10)]]
    (root / "manifest.json").write_text(json.dumps({"name": "report",
        "required_tools": required, "allowed_tools": [*required, "file_write"]}))
    registry = ToolRegistry()
    for name in (*required, "file_write", "http_request"):
        register(registry, name)
    orchestrator = make_orchestrator(tmp_path, registry, object())
    assert orchestrator._load_skill("report")
    orchestrator._start_run(session_id="skill", goal="report")
    assert names(orchestrator._tool_schemas()) == {"tool_load", *required}
    assert orchestrator.tool_loading.discover({"names": ["file_write"]})["loaded"]
    with pytest.raises(ValueError):
        orchestrator.tool_loading.discover({"names": ["http_request"]})


def test_loader_cannot_bypass_skill_permissions_even_in_same_batch(tmp_path):
    registry = ToolRegistry()
    writes = []
    register(registry, "file_read")
    register(registry, "file_write", handler=lambda args: writes.append(True))
    class Model:
        model = "test"
        turn = 0
        async def achat_with_tools(self, messages, schemas):
            self.turn += 1
            if self.turn == 1:
                return AgentModelResponse(tool_calls=[
                    ToolCall("load-denied", "tool_load", {"names": ["file_write"]}),
                    ToolCall("write-denied", "file_write", {}),
                ])
            assert names(schemas) == {"tool_load"}
            return AgentModelResponse(content="denied")
    orchestrator = make_orchestrator(tmp_path, registry, Model())
    orchestrator.active_skill_allowed_tools = {"file_read"}
    asyncio.run(orchestrator.process_user_input_async("write", session_id="denied"))
    assert not writes
    results = [s["tool_result"] for s in orchestrator.run["steps"] if "tool_result" in s]
    assert results[0]["status"] == "error"
    assert results[1]["error"] == "tool_not_allowed_by_active_skill"


def test_native_skill_load_activates_required_schema(tmp_path):
    root = tmp_path / "skills" / "report"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("Build report")
    (root / "manifest.json").write_text(json.dumps({"name": "report",
        "required_tools": ["file_read"], "allowed_tools": ["file_read", "file_write"]}))
    registry = ToolRegistry()
    for name in ("file_read", "file_write", "http_request"):
        register(registry, name)
    register(registry, "skill_load", handler=lambda args: {"name": "report"})
    class Model:
        model = "test"
        turn = 0
        async def achat_with_tools(self, messages, schemas):
            self.turn += 1
            if self.turn == 1:
                assert names(schemas) == {"tool_load", "skill_load"}
                return AgentModelResponse(tool_calls=[ToolCall("skill", "skill_load", {})])
            assert names(schemas) == {"tool_load", "skill_load", "file_read"}
            return AgentModelResponse(content="loaded")
    orchestrator = make_orchestrator(tmp_path, registry, Model())
    asyncio.run(orchestrator.process_user_input_async("report", session_id="skill"))
    assert orchestrator.run["active_skill"] == "report"
    assert orchestrator.run["loaded_tools"] == ["file_read"]
