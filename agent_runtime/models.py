"""Typed values shared by model adapters, tools and the runtime loop."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any]], Any]
ApprovalPolicy = Callable[[dict[str, Any]], bool]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler = field(repr=False, compare=False)
    risk_level: str = "low"
    requires_confirmation: bool = False
    approval_policy: ApprovalPolicy | None = field(default=None, repr=False, compare=False)
    timeout: float = 30.0
    max_retries: int = 0
    idempotent: bool = False

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def needs_approval(self, arguments: dict[str, Any]) -> bool:
        if self.approval_policy is not None:
            return bool(self.approval_policy(arguments))
        return self.requires_confirmation


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def as_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ToolCall":
        return cls(
            id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            arguments=dict(payload.get("arguments") or {}),
        )


@dataclass
class ToolResult:
    call_id: str
    name: str
    status: str
    output: Any = None
    error: str | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 1
    duration_ms: int = 0

    @property
    def success(self) -> bool:
        return self.status == "success"

    def as_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "artifacts": self.artifacts,
            "attempts": self.attempts,
            "duration_ms": self.duration_ms,
        }

    def model_content(self, max_chars: int = 12000) -> str:
        text = json.dumps(self.as_dict(), ensure_ascii=False, default=str)
        if len(text) <= max_chars:
            return text
        omitted = len(text) - max_chars
        return f"{text[:max_chars]}\n...[工具输出截断 {omitted} 字符]"


@dataclass
class AgentModelResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)
