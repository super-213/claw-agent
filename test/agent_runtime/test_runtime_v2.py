import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from agent_runtime import (
    AgentModelResponse,
    ArtifactStore,
    MemoryStore,
    RunStore,
    ToolApprovalRequired,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolRegistry,
    ToolRouter,
)
from agent_runtime.builtin_tools import build_tool_registry
from core.conversation import ConversationManager
from core.orchestrator import AgentOrchestrator
from services.executor import CommandExecutor
from services.model_providers import DashScopeAdapter, OpenAIAdapter, OtherCompatibleAdapter, provider_for
from skills.registry import SkillRegistry


class FakeLLM:
    model = "runtime-v2-test"

    def __init__(self, responses):
        self.responses = list(responses)

    async def achat_with_tools(self, messages, tools):
        return self.responses.pop(0)


def make_orchestrator(tmp_path, responses, registry, **kwargs):
    return AgentOrchestrator(
        llm_client=FakeLLM(responses),
        conversation=ConversationManager("system"),
        skill_registry=SkillRegistry(str(tmp_path / "skills")),
        tool_registry=registry,
        run_store=RunStore(tmp_path / "runs"),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        max_steps=20,
        **kwargs,
    )


def test_tool_protocol_is_split_into_registry_router_executor():
    registry = ToolRegistry()
    assert isinstance(registry.router, ToolRouter)
    assert isinstance(registry.executor, ToolExecutor)


def test_provider_selection_and_normalized_capabilities():
    assert isinstance(provider_for("https://api.openai.com/v1"), OpenAIAdapter)
    assert isinstance(provider_for("https://dashscope.aliyuncs.com/compatible-mode/v1"), DashScopeAdapter)
    assert isinstance(provider_for("https://models.example/v1"), OtherCompatibleAdapter)
    assert provider_for("https://models.example/v1").supports_function_calling is True


@pytest.mark.parametrize("adapter", [OpenAIAdapter(), DashScopeAdapter(), OtherCompatibleAdapter()])
def test_provider_adapters_normalize_the_same_tool_call(adapter):
    function = SimpleNamespace(name="file_read", arguments='{"path":"README.md"}')
    choice = SimpleNamespace(
        message=SimpleNamespace(
            content=None, tool_calls=[SimpleNamespace(id="same-call", function=function)]
        ),
        finish_reason="tool_calls",
    )
    response = adapter.parse_choice(choice)
    assert response.tool_calls == [ToolCall("same-call", "file_read", {"path": "README.md"})]


def test_token_budget_prevents_tool_execution(tmp_path):
    executed = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="side_effect", description="effect",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args: executed.append(True),
    ))
    response = AgentModelResponse(
        tool_calls=[ToolCall("budget-call", "side_effect", {})],
        usage={"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11},
    )
    orchestrator = make_orchestrator(tmp_path, [response], registry, max_tokens=10)

    asyncio.run(orchestrator.process_user_input_async("run", session_id="budget"))

    assert executed == []
    assert orchestrator.run["status"] == "budget_exceeded"
    assert orchestrator.run["tokens_used"] == 11


def test_repeated_call_guard_stops_loop(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="noop", description="noop",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args: None, idempotent=True,
    ))
    responses = [
        AgentModelResponse(tool_calls=[ToolCall(f"call-{index}", "noop", {})])
        for index in range(3)
    ]
    orchestrator = make_orchestrator(tmp_path, responses, registry, max_repeated_calls=3)

    asyncio.run(orchestrator.process_user_input_async("loop", session_id="repeat"))

    assert orchestrator.run["status"] == "failed"
    assert orchestrator.run["error"] == "repeated_tool_call"


def test_approval_is_bound_to_parameters_and_expiry(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="danger", description="danger",
        input_schema={"type": "object", "properties": {"value": {"type": "string"}},
                      "required": ["value"], "additionalProperties": False},
        handler=lambda args: args, requires_confirmation=True,
    ))
    orchestrator = make_orchestrator(
        tmp_path,
        [AgentModelResponse(tool_calls=[ToolCall("danger-call", "danger", {"value": "a"})])],
        registry,
    )
    asyncio.run(orchestrator.process_user_input_async("run", session_id="approval"))
    token = orchestrator.pending_approval_token
    pending = orchestrator.run["pending_approval"]
    assert pending["parameter_hash"]
    assert pending["call_id"] == "danger-call"

    pending["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    orchestrator.run_store.update(orchestrator.run, pending_approval=pending)
    with pytest.raises(PermissionError, match="approval_expired"):
        asyncio.run(_collect(orchestrator.resume_after_approval_stream_async(
            orchestrator.run["id"], token, approved=True
        )))


def test_non_idempotent_uncertain_execution_is_not_replayed(tmp_path):
    executed = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="send", description="send",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args: executed.append(True), idempotent=False,
    ))
    orchestrator = make_orchestrator(tmp_path, [AgentModelResponse(content="unused")], registry)
    run = orchestrator.run_store.create(
        session_id="recover", goal="send", max_steps=20, max_runtime_seconds=180
    )
    call = ToolCall("uncertain", "send", {})
    run = orchestrator.run_store.append_step(run, {
        "kind": "model", "tool_calls": [call.as_dict()]
    })
    run = orchestrator.run_store.record_tool_started(
        run, call_id=call.id,
        fingerprint=__import__("agent_runtime").argument_hash(call.name, call.arguments),
        idempotent=False,
    )
    orchestrator.run_store.update(run, status="interrupted")
    orchestrator.conversation.add_assistant_message("", tool_calls=[call.as_openai()])

    events = asyncio.run(_collect(orchestrator.resume_run_stream_async(run["id"])))

    assert executed == []
    assert orchestrator.run["status"] == "waiting_user"
    assert any(event["type"] == "user_input_required" for event in events)

    resolved = orchestrator.run_store.resolve_tool_uncertainty(
        run["id"], call_id=call.id, action="assume_succeeded", output={"sent": True}
    )
    assert resolved["status"] == "interrupted"
    assert resolved["tool_ledger"][call.id]["result"]["metadata"]["recovery_decision"] == "assume_succeeded"


def test_persisted_cancel_signal_stops_run(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="noop", description="noop",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args: None,
    ))
    orchestrator = make_orchestrator(tmp_path, [AgentModelResponse(content="unused")], registry)
    orchestrator._start_run(session_id="cancel", goal="cancel")
    orchestrator.run_store.request_cancel(orchestrator.run["id"])

    asyncio.run(orchestrator._consume_ai_loop())

    assert orchestrator.run["status"] == "cancelled"


def test_large_tool_output_is_externalized(tmp_path):
    result = __import__("agent_runtime").ToolResult(
        "large", "tool", "success", output={"text": "x" * 5000}
    )
    store = ArtifactStore(tmp_path / "artifacts")
    result = store.externalize(result, max_chars=1000)
    assert result.output["truncated"] is True
    assert result.artifacts and result.artifacts[0]["sha256"]
    assert (tmp_path / "artifacts" / f"{result.artifacts[0]['id']}.json").exists()


def test_skill_manifest_catalog_and_tool_permissions(tmp_path):
    root = tmp_path / "skills" / "report"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("# Report\nFull private instructions", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "name": "report", "description": "Build a report", "version": "2.0.0",
        "required_tools": ["file_read"], "allowed_tools": ["file_read", "file_write"],
        "allow_auto": True,
    }), encoding="utf-8")
    registry = SkillRegistry(str(tmp_path / "skills"), auto_reload=False)
    assert registry.catalog()[0]["summary"] == "report: Build a report (v2.0.0)"
    loaded = registry.load_for_runtime("report", available_tools={"file_read", "file_write"})
    assert "Full private instructions" in loaded["instructions"]
    assert loaded["allowed_tools"] == ["file_read", "file_write"]


def test_long_term_memory_requires_authorization_and_supports_correction(tmp_path):
    store = MemoryStore(tmp_path / "memory")
    with pytest.raises(PermissionError):
        store.save(
            content="preference", scope="user", owner_id="u1", source="test",
            user_authorized=False,
        )
    row = store.save(
        content="prefers blue", scope="user", owner_id="u1", source="user",
        user_authorized=True,
    )
    corrected = store.correct(
        row["id"], scope="user", owner_id="u1", content="prefers green", source="correction"
    )
    assert corrected["content"] == "prefers green"
    assert store.search("green", scopes=[("user", "u1")])[0]["source"] == "correction"
    assert store.delete(row["id"], scope="user", owner_id="u1") is True


def test_optional_browser_and_app_capabilities_are_always_gated(tmp_path):
    registry = build_tool_registry(
        project_root=tmp_path,
        generated_files_dir=tmp_path / "files",
        executor=CommandExecutor(
            cwd=tmp_path / "files", generated_files_dir=tmp_path / "files",
            sandbox_backend="restricted-process",
        ),
        browser_handler=lambda args: args,
        app_handler=lambda args: args,
    )
    for call in [
        ToolCall("browser", "browser_open", {"url": "https://example.com"}),
        ToolCall("app", "app_control", {"app": "Example", "action": "open"}),
    ]:
        with pytest.raises(ToolApprovalRequired):
            asyncio.run(registry.invoke(call))
    assert registry.get("browser.open") is registry.get("browser_open")
    assert registry.get("app.control") is registry.get("app_control")


async def _collect(iterator):
    return [item async for item in iterator]
