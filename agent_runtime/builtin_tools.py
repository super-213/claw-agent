"""Bundled structured tools and their security boundaries."""
from __future__ import annotations

from datetime import datetime
import ipaddress
import json
from pathlib import Path
import re
import shlex
import socket
from typing import Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services.executor import CommandExecutor
from services.home_assistant_service import HomeAssistantService, POWER_DOMAINS

from .models import ToolDefinition
from .registry import ToolRegistry


READ_ONLY_SHELL_COMMANDS = {
    "pwd", "ls", "cat", "head", "tail", "wc", "rg", "grep", "stat", "file",
    "du", "df", "which", "find", "sed", "test", "true", "false", "date",
}


def build_tool_registry(
    *,
    project_root: str | Path,
    generated_files_dir: str | Path,
    executor: CommandExecutor,
    home_assistant_service: HomeAssistantService | None = None,
) -> ToolRegistry:
    project = Path(project_root).resolve()
    generated = Path(generated_files_dir).resolve()
    registry = ToolRegistry()

    registry.register(ToolDefinition(
        name="datetime_now",
        description="Return the current date and time in an IANA timezone.",
        input_schema={
            "type": "object",
            "properties": {"timezone": {"type": "string", "maxLength": 100}},
            "additionalProperties": False,
        },
        handler=_datetime_now,
        idempotent=True,
        max_retries=1,
    ))
    registry.register(ToolDefinition(
        name="file_read",
        description="Read a UTF-8 text file from the project or generated-files directory.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 1024},
                "max_chars": {"type": "integer"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=lambda args: _file_read(args, (project, generated)),
        idempotent=True,
        max_retries=1,
    ))
    registry.register(ToolDefinition(
        name="file_write",
        description="Write UTF-8 text inside the generated-files directory.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 1024},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["create", "overwrite", "append"]},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        handler=lambda args: _file_write(args, generated),
        risk_level="medium",
        approval_policy=lambda args: _file_write_needs_approval(args, generated),
    ))
    registry.register(ToolDefinition(
        name="http_request",
        description="Perform a public HTTP GET or HEAD request and return a bounded text response.",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "minLength": 1, "maxLength": 4096},
                "method": {"type": "string", "enum": ["GET", "HEAD"]},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "max_chars": {"type": "integer"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        handler=_http_request,
        timeout=20,
        idempotent=True,
        max_retries=2,
    ))
    registry.register(ToolDefinition(
        name="shell_execute",
        description=(
            "Execute one non-interactive shell command in the generated-files directory. "
            "Prefer dedicated datetime, file and HTTP tools when available."
        ),
        input_schema={
            "type": "object",
            "properties": {"command": {"type": "string", "minLength": 1, "maxLength": 20000}},
            "required": ["command"],
            "additionalProperties": False,
        },
        handler=lambda args: _shell_execute(args, executor),
        risk_level="high",
        approval_policy=_shell_needs_approval,
        timeout=max(1, executor.timeout + 2),
    ))

    if (
        home_assistant_service is not None
        and home_assistant_service.configured
        and home_assistant_service.rules
    ):
        _register_home_assistant(registry, home_assistant_service)
    return registry


def _datetime_now(args: dict[str, Any]) -> dict[str, Any]:
    timezone = str(args.get("timezone") or "Asia/Shanghai")
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown_timezone:{timezone}") from exc
    now = datetime.now(zone)
    return {"iso": now.isoformat(), "date": now.date().isoformat(), "timezone": timezone}


def _resolve_path(path_value: str, roots: tuple[Path, ...], *, default_root: Path) -> Path:
    raw = Path(path_value).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (default_root / raw).resolve()
    if not any(_is_relative_to(candidate, root) for root in roots):
        raise PermissionError("path_outside_allowed_roots")
    return candidate


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _file_read(args: dict[str, Any], roots: tuple[Path, ...]) -> dict[str, Any]:
    path = _resolve_path(str(args["path"]), roots, default_root=roots[0])
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    max_chars = max(1, min(int(args.get("max_chars") or 20000), 100000))
    text = path.read_text(encoding="utf-8")
    truncated = len(text) > max_chars
    return {
        "path": str(path),
        "content": text[:max_chars],
        "characters": len(text),
        "truncated": truncated,
    }


def _file_write_needs_approval(args: dict[str, Any], root: Path) -> bool:
    try:
        path = _resolve_path(str(args.get("path") or ""), (root,), default_root=root)
    except Exception:
        return True
    mode = str(args.get("mode") or "create")
    return path.exists() or mode in {"overwrite", "append"}


def _file_write(args: dict[str, Any], root: Path) -> dict[str, Any]:
    path = _resolve_path(str(args["path"]), (root,), default_root=root)
    mode = str(args.get("mode") or "create")
    if mode == "create" and path.exists():
        raise FileExistsError("file_exists_use_overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if mode == "append" else "w", encoding="utf-8") as handle:
        handle.write(str(args.get("content") or ""))
    return {"path": str(path), "bytes": path.stat().st_size, "mode": mode}


def _http_request(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args["url"])
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only_http_https_urls_are_allowed")
    _reject_private_host(parsed.hostname)
    method = str(args.get("method") or "GET").upper()
    headers = {str(k): str(v) for k, v in dict(args.get("headers") or {}).items()}
    headers.setdefault("User-Agent", "Claw-Agent-Runtime/1.0")
    request = Request(url, method=method, headers=headers)
    max_chars = max(1, min(int(args.get("max_chars") or 20000), 100000))
    opener = build_opener(_NoRedirectHandler())
    with opener.open(request, timeout=15) as response:
        body = response.read(max_chars * 4 + 1)
        content_type = response.headers.get("Content-Type", "")
        charset = response.headers.get_content_charset() or "utf-8"
        text = body.decode(charset, errors="replace")
        return {
            "url": response.geturl(),
            "status": response.status,
            "content_type": content_type,
            "body": text[:max_chars],
            "truncated": len(text) > max_chars or len(body) > max_chars * 4,
        }


def _reject_private_host(hostname: str) -> None:
    try:
        addresses = {row[4][0] for row in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as exc:
        raise ValueError("host_resolution_failed") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise PermissionError("private_network_requests_are_not_allowed")


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _shell_needs_approval(args: dict[str, Any]) -> bool:
    command = str(args.get("command") or "")
    if not command or re.search(r"[;&`]|\$\(", command):
        return True
    if any(operator in command for operator in (">", "<", "\n")):
        return True
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return True
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token == "|":
            segments.append([])
        else:
            segments[-1].append(token)
    for segment in segments:
        if not segment:
            return True
        program = Path(segment[0]).name
        if program == "git":
            if len(segment) < 2 or segment[1] not in {"status", "diff", "log", "show", "rev-parse", "ls-files"}:
                return True
            continue
        if program not in READ_ONLY_SHELL_COMMANDS:
            return True
        if program == "find" and any(item in {"-delete", "-exec", "-execdir", "-ok", "-okdir"} for item in segment):
            return True
        if program == "sed" and any(item == "-i" or item.startswith("-i") for item in segment[1:]):
            return True
    return False


def _shell_execute(args: dict[str, Any], executor: CommandExecutor) -> dict[str, Any]:
    result = executor.execute(str(args["command"]))
    payload = {
        "success": result.success,
        "return_code": result.return_code,
        "output": result.output,
        "error": result.error,
        "is_timeout": result.is_timeout,
    }
    if not result.success:
        raise RuntimeError(json.dumps(payload, ensure_ascii=False))
    return payload


def _register_home_assistant(registry: ToolRegistry, service: HomeAssistantService) -> None:
    descriptions = {row["name"]: row for row in service.tools_schema()}
    allowed_ids = sorted(service.rules)
    power_ids = [
        entity_id
        for entity_id in allowed_ids
        if entity_id.split(".", 1)[0] in POWER_DOMAINS
    ]
    name_map = {
        "home_assistant_list_devices": "home_assistant.list_devices",
        "home_assistant_get_state": "home_assistant.get_state",
        "home_assistant_turn_on": "home_assistant.turn_on",
        "home_assistant_turn_off": "home_assistant.turn_off",
    }
    for public_name, service_name in name_map.items():
        schema = descriptions[service_name]
        if service_name.endswith(("turn_on", "turn_off")) and not power_ids:
            continue
        input_schema = dict(schema["parameters"])
        input_schema["properties"] = dict(input_schema.get("properties") or {})
        if "entity_id" in input_schema["properties"]:
            entity_ids = power_ids if service_name.endswith(("turn_on", "turn_off")) else allowed_ids
            input_schema["properties"]["entity_id"] = {
                "type": "string",
                "enum": entity_ids,
            }
        description = schema["description"]
        if service_name.endswith("get_state"):
            description += (
                " Use this only for the listed smart-home entities, never for a "
                "general public weather or web query."
            )
        registry.register(ToolDefinition(
            name=public_name,
            description=description,
            input_schema=input_schema,
            handler=lambda args, name=service_name: _call_home_assistant(service, name, args),
            risk_level="high" if service_name.endswith(("turn_on", "turn_off")) else "low",
            requires_confirmation=service_name.endswith(("turn_on", "turn_off")),
            timeout=max(2, service.request_timeout + 2),
            idempotent=service_name.endswith(("list_devices", "get_state")),
            max_retries=1,
        ))


def _call_home_assistant(
    service: HomeAssistantService,
    name: str,
    args: dict[str, Any],
) -> Any:
    if name == "home_assistant.turn_on":
        return service.set_power(str(args.get("entity_id") or ""), True, confirmed=True)
    if name == "home_assistant.turn_off":
        return service.set_power(str(args.get("entity_id") or ""), False, confirmed=True)
    return service.call_tool(name, args)
