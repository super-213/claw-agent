"""Tool discovery, argument validation, approval gating and execution."""
from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

from .models import ToolCall, ToolDefinition, ToolResult


class ToolApprovalRequired(Exception):
    def __init__(self, call: ToolCall, definition: ToolDefinition):
        super().__init__(f"工具 {call.name} 需要用户确认")
        self.call = call
        self.definition = definition


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        name = (definition.name or "").strip()
        if not name:
            raise ValueError("工具名称不能为空")
        if name in self._tools:
            raise ValueError(f"工具已注册：{name}")
        self._tools[name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list(self) -> list[ToolDefinition]:
        return [self._tools[name] for name in sorted(self._tools)]

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self.list()]

    async def invoke(self, call: ToolCall, *, approved: bool = False) -> ToolResult:
        definition = self.get(call.name)
        if definition is None:
            return ToolResult(call.id, call.name, "error", error="unknown_tool")

        errors = self._validate_schema(call.arguments, definition.input_schema, path="arguments")
        if errors:
            return ToolResult(call.id, call.name, "error", error="; ".join(errors))
        if definition.needs_approval(call.arguments) and not approved:
            raise ToolApprovalRequired(call, definition)

        started = time.monotonic()
        attempts = 0
        last_error = ""
        max_attempts = 1 + (definition.max_retries if definition.idempotent else 0)
        while attempts < max_attempts:
            attempts += 1
            try:
                if inspect.iscoroutinefunction(definition.handler):
                    value = await asyncio.wait_for(
                        definition.handler(call.arguments),
                        timeout=definition.timeout,
                    )
                else:
                    value = await asyncio.wait_for(
                        asyncio.to_thread(definition.handler, call.arguments),
                        timeout=definition.timeout,
                    )
                duration = int((time.monotonic() - started) * 1000)
                return ToolResult(
                    call.id,
                    call.name,
                    "success",
                    output=value,
                    attempts=attempts,
                    duration_ms=duration,
                )
            except Exception as exc:
                last_error = str(exc)
                # Invalid arguments, denied access and missing resources are
                # deterministic failures. Retrying them only duplicates work
                # and makes the trace look as if a transient failure occurred.
                if isinstance(exc, (ValueError, PermissionError, FileNotFoundError)):
                    break
                if attempts >= max_attempts:
                    break
                await asyncio.sleep(min(0.25 * (2 ** (attempts - 1)), 2.0))
        duration = int((time.monotonic() - started) * 1000)
        return ToolResult(
            call.id,
            call.name,
            "error",
            error=last_error or "tool_execution_failed",
            attempts=attempts,
            duration_ms=duration,
        )

    @classmethod
    def _validate_schema(
        cls,
        value: Any,
        schema: dict[str, Any],
        *,
        path: str,
    ) -> list[str]:
        """Validate the JSON-Schema subset used by bundled tools."""
        errors: list[str] = []
        expected = schema.get("type")
        type_map = {
            "object": dict,
            "array": list,
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
        }
        python_type = type_map.get(expected)
        if python_type is not None:
            valid = isinstance(value, python_type)
            if expected in {"integer", "number"} and isinstance(value, bool):
                valid = False
            if not valid:
                return [f"{path} 应为 {expected}"]

        if isinstance(value, dict):
            properties = schema.get("properties") or {}
            for required in schema.get("required") or []:
                if required not in value:
                    errors.append(f"{path}.{required} 为必填参数")
            if schema.get("additionalProperties") is False:
                for key in value:
                    if key not in properties:
                        errors.append(f"{path}.{key} 不是允许的参数")
            for key, child in value.items():
                if key in properties:
                    errors.extend(cls._validate_schema(child, properties[key], path=f"{path}.{key}"))
        elif isinstance(value, list) and isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(cls._validate_schema(item, schema["items"], path=f"{path}[{index}]"))

        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{path} 必须是 {schema['enum']} 之一")
        if isinstance(value, str):
            if "minLength" in schema and len(value) < int(schema["minLength"]):
                errors.append(f"{path} 长度不能小于 {schema['minLength']}")
            if "maxLength" in schema and len(value) > int(schema["maxLength"]):
                errors.append(f"{path} 长度不能超过 {schema['maxLength']}")
        return errors
