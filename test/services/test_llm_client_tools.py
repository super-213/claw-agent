from types import SimpleNamespace

from services.llm_client import LLMClient


def test_agent_response_extracts_native_tool_calls():
    function = SimpleNamespace(name="file_read", arguments='{"path":"README.md"}')
    raw_call = SimpleNamespace(id="call-1", function=function)
    message = SimpleNamespace(content=None, tool_calls=[raw_call])
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")

    response = LLMClient._agent_response(choice)

    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].name == "file_read"
    assert response.tool_calls[0].arguments == {"path": "README.md"}


def test_chat_messages_preserve_tool_protocol_fields():
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call-1",
                "type": "function",
                "function": {"name": "datetime_now", "arguments": "{}"},
            }],
        },
        {
            "role": "tool",
            "content": '{"status":"success"}',
            "tool_call_id": "call-1",
            "name": "datetime_now",
        },
    ]

    normalized = LLMClient._chat_messages(messages)

    assert normalized[0]["tool_calls"][0]["id"] == "call-1"
    assert normalized[1]["role"] == "tool"
    assert normalized[1]["tool_call_id"] == "call-1"
