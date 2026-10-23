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
        self._aliases: dict[str, str] = {}
        self.router = ToolRouter(self)
        self.executor = ToolExecutor(self.router)

    def register(self, definition: ToolDefinition) -> None:
        name = (definition.name or "").strip()
        if not name:
            raise ValueError("工具名称不能为空")
        if name in self._tools:
            raise ValueError(f"工具已注册：{name}")
        self._tools[name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(self._aliases.get(name, name))

    def register_alias(self, alias: str, target: str) -> None:
        if alias in self._tools or alias in self._aliases:
            raise ValueError(f"工具别名已注册：{alias}")
        if target not in self._tools:
            raise ValueError(f"工具不存在：{target}")
        self._aliases[alias] = target

    def aliases(self) -> dict[str, str]:
        return dict(self._aliases)

    def resolve_name(self, name: str) -> str:
        return self._aliases.get(name, name)

    def list(self) -> list[ToolDefinition]:
        return [self._tools[name] for name in sorted(self._tools)]

    def schemas(self, *, allowed_tools: set[str] | None = None) -> list[dict[str, Any]]:
        tools = self.list()
        if allowed_tools is not None:
            normalized = {self._aliases.get(name, name) for name in allowed_tools}
            tools = [tool for tool in tools if tool.name in normalized]
        return [tool.openai_schema() for tool in tools]

    async def invoke(self, call: ToolCall, *, approved: bool = False) -> ToolResult:
        return await self.executor.execute(call, approved=approved)

    @classmethod
    def _validate_schema(cls, value: Any, schema: dict[str, Any], *, path: str) -> list[str]:
        return ToolRouter.validate_schema(value, schema, path=path)


class ToolRouter:
    """Resolve a model-selected tool and validate its arguments."""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def route(self, call: ToolCall) -> tuple[ToolDefinition | None, list[str]]:
        definition = self.registry.get(call.name)
        if definition is None:
            return None, ["unknown_tool"]
        return definition, self.validate_schema(
            call.arguments, definition.input_schema, path="arguments"
        )

    @classmethod
    def validate_schema(
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
        if isinstance(expected, list):
            if value is None and 'null' in expected:
                return []
            alternatives = [cls.validate_schema(value, {**schema, 'type': t}, path=path) for t in expected if t != 'null']
            return [] if any(not errors for errors in alternatives) else [f'{path} 类型无效']
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
                    errors.extend(cls.validate_schema(child, properties[key], path=f"{path}.{key}"))
        elif isinstance(value, list) and isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(cls.validate_schema(item, schema["items"], path=f"{path}[{index}]"))

        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{path} 必须是 {schema['enum']} 之一")
        if isinstance(value, str):
            if "minLength" in schema and len(value) < int(schema["minLength"]):
                errors.append(f"{path} 长度不能小于 {schema['minLength']}")
            if "maxLength" in schema and len(value) > int(schema["maxLength"]):
                errors.append(f"{path} 长度不能超过 {schema['maxLength']}")
        return errors


class ToolExecutor:
    """Apply approval, timeout and retry policy to a routed tool call."""

    def __init__(self, router: ToolRouter):
        self.router = router

    async def execute(
        self,
        call: ToolCall,
        *,
        approved: bool = False,
        timeout_override: float | None = None,
    ) -> ToolResult:
        definition, errors = self.router.route(call)
        if definition is None:
            return ToolResult(call.id, call.name, "error", error="unknown_tool")
        if errors:
            return ToolResult(call.id, call.name, "error", error="; ".join(errors))
        if definition.needs_approval(call.arguments) and not approved:
            raise ToolApprovalRequired(call, definition)
        started = time.monotonic()
        attempts = 0
        last_error = ""
        retry_errors: list[str] = []
        max_attempts = 1 + (definition.max_retries if definition.idempotent else 0)
        while attempts < max_attempts:
            attempts += 1
            try:
                if inspect.iscoroutinefunction(definition.handler):
                    value = await asyncio.wait_for(
                        definition.handler(call.arguments),
                        timeout=min(definition.timeout, timeout_override) if timeout_override else definition.timeout,
                    )
                else:
                    value = await asyncio.wait_for(
                        asyncio.to_thread(definition.handler, call.arguments),
                        timeout=min(definition.timeout, timeout_override) if timeout_override else definition.timeout,
                    )
                duration = int((time.monotonic() - started) * 1000)
                return ToolResult(
                    call.id,
                    call.name,
                    "success",
                    output=value,
                    attempts=attempts,
                    duration_ms=duration,
                    metadata={"retry_errors": retry_errors},
                )
            except Exception as exc:
                from services.task_store import TaskError
                if isinstance(exc, TaskError):
                    return ToolResult(call.id, call.name, 'error', output=exc.payload(), error=exc.code,
                                      attempts=attempts, duration_ms=int((time.monotonic() - started) * 1000))
                last_error = str(exc)
                retry_errors.append(last_error)
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
            metadata={"retry_errors": retry_errors},
        )
