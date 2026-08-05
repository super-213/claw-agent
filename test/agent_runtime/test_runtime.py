import asyncio

from agent_runtime import (
    AgentModelResponse,
    RunStore,
    ToolApprovalRequired,
    ToolCall,
    ToolDefinition,
    ToolRegistry,
)
from agent_runtime.builtin_tools import build_tool_registry
from core.conversation import ConversationManager
from core.orchestrator import AgentOrchestrator
from services.executor import CommandExecutor
from services.home_assistant_service import HomeAssistantService
from skills.registry import SkillRegistry


class FakeToolLLM:
    model = "tool-model"

    def __init__(self, responses):
        self.responses = list(responses)

    async def achat_with_tools(self, messages, tools):
        return self.responses.pop(0)

    async def astream_with_tools(self, messages, tools):
        response = self.responses.pop(0)
        if response.content:
            yield {"type": "content_delta", "delta": response.content}
        yield {"type": "done", "response": response}


def _orchestrator(tmp_path, llm, registry, *, max_steps=8):
    files = tmp_path / "files"
    return AgentOrchestrator(
        llm_client=llm,
        conversation=ConversationManager("system"),
        skill_registry=SkillRegistry(str(tmp_path / "skills")),
        tool_registry=registry,
        run_store=RunStore(tmp_path / "runs"),
        max_steps=max_steps,
    )


def test_registry_validates_arguments_and_executes():
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="sum_values",
        description="sum",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        },
        handler=lambda args: args["a"] + args["b"],
    ))

    invalid = asyncio.run(registry.invoke(ToolCall("c1", "sum_values", {"a": 1})))
    valid = asyncio.run(registry.invoke(ToolCall("c2", "sum_values", {"a": 1, "b": 2})))

    assert invalid.status == "error"
    assert "b 为必填" in invalid.error
    assert valid.success is True
    assert valid.output == 3


def test_registry_does_not_retry_deterministic_errors():
    attempts = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="validated_action",
        description="validated",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args: attempts.append(1) or (_ for _ in ()).throw(ValueError("invalid_value")),
        idempotent=True,
        max_retries=3,
    ))

    result = asyncio.run(registry.invoke(ToolCall("bad", "validated_action", {})))

    assert result.status == "error"
    assert result.error == "invalid_value"
    assert result.attempts == 1
    assert len(attempts) == 1


def test_structured_tool_loop_records_native_messages(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="echo_value",
        description="echo",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        handler=lambda args: {"echo": args["value"]},
    ))
    llm = FakeToolLLM([
        AgentModelResponse(tool_calls=[ToolCall("call-1", "echo_value", {"value": "ok"})]),
        AgentModelResponse(content="done"),
    ])
    orchestrator = _orchestrator(tmp_path, llm, registry)

    asyncio.run(orchestrator.process_user_input_async("run", session_id="s1"))

    messages = orchestrator.conversation.get_messages()
    assert any(message.get("tool_calls") for message in messages)
    assert any(message.get("role") == "tool" and message.get("tool_call_id") == "call-1" for message in messages)
    assert messages[-1]["content"] == "done"
    assert orchestrator.run["status"] == "completed"


def test_runtime_rejects_model_adapter_without_function_calling(tmp_path):
    class TextOnlyLLM:
        model = "text-only"

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="noop",
        description="noop",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args: None,
    ))
    orchestrator = _orchestrator(tmp_path, TextOnlyLLM(), registry)

    events = asyncio.run(_collect(orchestrator.process_user_input_stream_async(
        "run", session_id="unsupported"
    )))

    assert any(event.get("type") == "error" and event.get("stage") == "capability" for event in events)
    assert orchestrator.run["status"] == "failed"


def test_approval_checkpoint_can_resume(tmp_path):
    executed = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="dangerous_action",
        description="danger",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args: executed.append("yes") or {"ok": True},
        requires_confirmation=True,
        risk_level="high",
    ))
    llm = FakeToolLLM([
        AgentModelResponse(tool_calls=[ToolCall("call-danger", "dangerous_action", {})]),
        AgentModelResponse(content="approved and done"),
    ])
    orchestrator = _orchestrator(tmp_path, llm, registry)

    events = asyncio.run(_collect(orchestrator.process_user_input_stream_async("run", session_id="s1")))
    approval = next(event for event in events if event["type"] == "approval_required")
    assert executed == []
    assert orchestrator.run["status"] == "waiting_approval"

    resumed = asyncio.run(_collect(orchestrator.resume_after_approval_stream_async(
        approval["run_id"], approval["approval_token"], approved=True
    )))
    assert executed == ["yes"]
    assert orchestrator.run["status"] == "completed"
    assert resumed[-1]["type"] == "done"


def test_step_budget_stops_non_terminating_agent(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="noop",
        description="noop",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args: None,
    ))
    llm = FakeToolLLM([
        AgentModelResponse(tool_calls=[ToolCall("c1", "noop", {})]),
        AgentModelResponse(tool_calls=[ToolCall("c2", "noop", {})]),
    ])
    orchestrator = _orchestrator(tmp_path, llm, registry, max_steps=2)

    asyncio.run(orchestrator.process_user_input_async("loop", session_id="s1"))

    assert orchestrator.run["status"] == "budget_exceeded"
    assert "执行预算已用尽" in orchestrator.conversation.get_messages()[-1]["content"]


def test_builtin_write_and_mutating_shell_require_approval(tmp_path):
    files = tmp_path / "files"
    executor = CommandExecutor(cwd=files, generated_files_dir=files)
    registry = build_tool_registry(
        project_root=tmp_path,
        generated_files_dir=files,
        executor=executor,
    )

    created = asyncio.run(registry.invoke(ToolCall(
        "create", "file_write", {"path": "a.txt", "content": "one"}
    )))
    assert created.success is True
    try:
        asyncio.run(registry.invoke(ToolCall(
            "overwrite", "file_write", {"path": "a.txt", "content": "two", "mode": "overwrite"}
        )))
    except ToolApprovalRequired:
        pass
    else:
        raise AssertionError("overwrite should require approval")

    try:
        asyncio.run(registry.invoke(ToolCall(
            "shell", "shell_execute", {"command": "printf x > b.txt"}
        )))
    except ToolApprovalRequired:
        pass
    else:
        raise AssertionError("mutating shell should require approval")


def test_home_assistant_tools_expose_only_configured_whitelist(tmp_path):
    files = tmp_path / "files"
    executor = CommandExecutor(cwd=files, generated_files_dir=files)
    service = HomeAssistantService(
        base_url="http://home-assistant.local:8123",
        token="test-token",
        allowed_entities="switch.desk_lamp|书桌灯, sensor.temperature|室温",
    )

    registry = build_tool_registry(
        project_root=tmp_path,
        generated_files_dir=files,
        executor=executor,
        home_assistant_service=service,
    )

    state_tool = registry.get("home_assistant_get_state")
    power_tool = registry.get("home_assistant_turn_on")
    assert state_tool is not None
    assert state_tool.input_schema["properties"]["entity_id"]["enum"] == [
        "sensor.temperature", "switch.desk_lamp"
    ]
    assert power_tool is not None
    assert power_tool.input_schema["properties"]["entity_id"]["enum"] == ["switch.desk_lamp"]
    assert "general public weather" in state_tool.description


def test_unconfigured_home_assistant_tools_are_not_registered(tmp_path):
    files = tmp_path / "files"
    registry = build_tool_registry(
        project_root=tmp_path,
        generated_files_dir=files,
        executor=CommandExecutor(cwd=files, generated_files_dir=files),
        home_assistant_service=HomeAssistantService(
            allowed_entities="switch.desk_lamp|书桌灯",
        ),
    )

    assert registry.get("home_assistant_get_state") is None


def test_interrupted_run_resumes_missing_tool_call(tmp_path):
    executed = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="resume_tool",
        description="resume",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args: executed.append("run") or {"ok": True},
    ))
    llm = FakeToolLLM([AgentModelResponse(content="resumed")])
    orchestrator = _orchestrator(tmp_path, llm, registry)
    run = orchestrator.run_store.create(
        session_id="s1", goal="resume", max_steps=8, max_runtime_seconds=180
    )
    run = orchestrator.run_store.append_step(run, {
        "kind": "model",
        "content": "",
        "tool_calls": [ToolCall("resume-call", "resume_tool", {}).as_dict()],
    })
    orchestrator.run_store.update(run, status="interrupted")
    orchestrator.conversation.add_user_message("resume")
    orchestrator.conversation.add_assistant_message(
        "", tool_calls=[ToolCall("resume-call", "resume_tool", {}).as_openai()]
    )

    events = asyncio.run(_collect(orchestrator.resume_run_stream_async(run["id"])))

    assert executed == ["run"]
    assert orchestrator.run["status"] == "completed"
    assert events[-1]["type"] == "done"


async def _collect(iterator):
    return [event async for event in iterator]
