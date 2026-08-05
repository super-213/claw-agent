"""Provider capability and response normalization for native function calling."""
from __future__ import annotations

from abc import ABC
import json
from typing import Any
from urllib.parse import urlparse

from agent_runtime.models import AgentModelResponse, ToolCall


class ModelProvider(ABC):
    name = "compatible"
    supports_function_calling = True
    supports_streaming_tools = True
    default_context_window = 32_768

    def prepare_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return tools

    def extra_request_options(self, *, streaming: bool = False) -> dict[str, Any]:
        return {}

    def context_window(self, model: str) -> int:
        return self.default_context_window

    def parse_choice(
        self,
        choice: Any,
        *,
        usage: Any = None,
        request_id: str | None = None,
    ) -> AgentModelResponse:
        message = choice.message
        calls: list[ToolCall] = []
        for index, raw_call in enumerate(getattr(message, "tool_calls", None) or []):
            function = raw_call.function
            calls.append(ToolCall(
                id=str(getattr(raw_call, "id", None) or f"call_{index}"),
                name=str(getattr(function, "name", None) or ""),
                arguments=self.parse_arguments(getattr(function, "arguments", None) or ""),
            ))
        return AgentModelResponse(
            content=getattr(message, "content", None) or "",
            tool_calls=calls,
            finish_reason=getattr(choice, "finish_reason", None),
            usage=self.normalize_usage(usage),
            provider=self.name,
            request_id=request_id,
        )

    @staticmethod
    def parse_arguments(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {"__invalid_json__": raw}
        return value if isinstance(value, dict) else {"__invalid_arguments__": value}

    @staticmethod
    def normalize_usage(usage: Any) -> dict[str, int]:
        if usage is None:
            return {}
        def read(name: str, fallback: str | None = None) -> int:
            value = getattr(usage, name, None)
            if value is None and isinstance(usage, dict):
                value = usage.get(name)
            if value is None and fallback:
                value = getattr(usage, fallback, None)
                if value is None and isinstance(usage, dict):
                    value = usage.get(fallback)
            return int(value or 0)
        prompt = read("prompt_tokens", "input_tokens")
        completion = read("completion_tokens", "output_tokens")
        total = read("total_tokens") or prompt + completion
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        }


class OpenAIAdapter(ModelProvider):
    name = "openai"
    default_context_window = 128_000


class DashScopeAdapter(ModelProvider):
    name = "dashscope"
    default_context_window = 131_072


class OtherCompatibleAdapter(ModelProvider):
    name = "openai-compatible"


def provider_for(base_url: str, explicit: str | None = None) -> ModelProvider:
    requested = (explicit or "").strip().lower()
    if requested in {"openai", "official"}:
        return OpenAIAdapter()
    if requested in {"dashscope", "qwen", "aliyun"}:
        return DashScopeAdapter()
    hostname = (urlparse(base_url).hostname or "").lower()
    if hostname.endswith("openai.com"):
        return OpenAIAdapter()
    if "dashscope" in hostname or hostname.endswith("aliyuncs.com"):
        return DashScopeAdapter()
    return OtherCompatibleAdapter()
