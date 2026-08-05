"""Tests for orchestrator sync wrappers over the async implementation."""
from core.conversation import ConversationManager
from core.orchestrator import AgentOrchestrator
from agent_runtime import AgentModelResponse, ToolDefinition, ToolRegistry
from skills.registry import SkillRegistry


class FakeAsyncLLM:
    model = "fake-model"

    async def achat_with_tools(self, messages, tools):
        return AgentModelResponse(content="sync bridge ok")

    async def astream_with_tools(self, messages, tools):
        response = AgentModelResponse(content="stream bridge ok")
        yield {"type": "content_delta", "delta": response.content}
        yield {"type": "done", "response": response}


def _orchestrator(tmp_path):
    skills_dir = tmp_path / "skills"
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="noop",
        description="noop",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args: None,
    ))
    return AgentOrchestrator(
        llm_client=FakeAsyncLLM(),
        conversation=ConversationManager("System prompt"),
        skill_registry=SkillRegistry(str(skills_dir)),
        tool_registry=registry,
    )


def test_sync_process_user_input_uses_async_main_flow(tmp_path):
    orchestrator = _orchestrator(tmp_path)

    should_continue = orchestrator.process_user_input("hello")

    messages = orchestrator.conversation.get_messages()
    assert should_continue is False
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "sync bridge ok"


def test_sync_stream_process_user_input_uses_async_main_flow(tmp_path):
    orchestrator = _orchestrator(tmp_path)

    events = list(orchestrator.process_user_input_stream("hello"))

    assert any(event.get("type") == "model_delta" for event in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["should_continue"] is False


def test_realtime_question_auto_loads_search_skill(tmp_path):
    skills_dir = tmp_path / "skills"
    search_dir = skills_dir / "search"
    search_dir.mkdir(parents=True)
    (search_dir / "search.md").write_text("# search\nfallback search rules", encoding="utf-8")
    orchestrator = _orchestrator(tmp_path)

    accepted, events = orchestrator._prepare_user_input(
        "上海今天天气怎么样",
        emit_events=True,
    )

    messages = orchestrator.conversation.get_messages()
    assert accepted is True
    assert any(
        message["role"] == "system"
        and message["content"].startswith("## 激活技能：search")
        for message in messages
    )
    assert any(
        message["role"] == "system"
        and "切换到同类备用来源重试" in message["content"]
        for message in messages
    )
    assert any(event.get("stage") == "skill_loaded" for event in events)
