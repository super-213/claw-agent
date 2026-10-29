"""Bundled structured tools and their security boundaries."""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path
import re
import shlex
import socket
from typing import Any
from urllib.parse import unquote, urlparse, quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from services.executor import CommandExecutor
from services.media_input import IMAGE_EXTENSIONS
from services.public_http import is_fake_ip, is_public_ip, resolve_fake_ip, pinned_opener

from .registry import ToolRegistry

READ_ONLY_SHELL_COMMANDS = {
    "pwd", "ls", "cat", "head", "tail", "wc", "rg", "grep", "stat", "file",
    "du", "df", "which", "find", "sed", "test", "true", "false", "date",
}


def build_tool_registry(
    *, project_root, generated_files_dir, executor, home_assistant_service=None,
    skill_registry=None, browser_handler=None, app_handler=None,
    allowed_http_domains=(), protected_paths=(), family_mode=False, include_plugins=True,
):
    """Compatibility facade: all schemas and registrations live in plugin packages."""
    from .plugins import PluginManager, ToolBindingContext
    from .plugins.assembly import foundation_services
    registry = ToolRegistry()
    services = foundation_services(registry=registry, project_root=project_root,
        generated_files_dir=generated_files_dir, executor=executor, skill_registry=skill_registry,
        home_assistant_service=home_assistant_service, browser_handler=browser_handler,
        app_handler=app_handler, allowed_http_domains=allowed_http_domains,
        protected_paths=protected_paths, family_mode=family_mode)
    manager = PluginManager.default()
    manager.bind(registry, ToolBindingContext(runtime='web' if family_mode else 'cli', services=services),
                 bundled_only=not include_plugins)
    return registry

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


def _file_read(args: dict[str, Any], roots: tuple[Path, ...], protected_paths=()) -> dict[str, Any]:
    value = str(args["path"])
    if value.startswith(("/generated/", "/files/")):
        # Web routes are aliases for the generated directory, never disk roots.
        relative = unquote(value.split("/", 2)[2])
        path = _resolve_path(relative, (roots[-1],), default_root=roots[-1])
    else:
        path = _resolve_path(value, roots, default_root=roots[0])
    if ((path.name == '.env' or path.name.startswith('.env.')) and path.name != '.env.example'
            or path.name.startswith('.webui_secret_key')):
        raise PermissionError('protected_credentials')
    if any(path == Path(p).resolve() or _is_relative_to(path, Path(p).resolve()) for p in protected_paths):
        raise PermissionError("protected_family_data")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        raise ValueError("image_requires_visual_input: 图片应直接通过消息中的 image_url 观察，file_read 只读取文本；不要把本工具失败解释为无法查看已附图片")
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


def _http_request(
    args: dict[str, Any],
    allowed_domains: tuple[str, ...] = (),
) -> dict[str, Any]:
    url = str(args["url"])
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only_http_https_urls_are_allowed")
    if allowed_domains and not any(
        parsed.hostname == domain or parsed.hostname.endswith(f".{domain}")
        for domain in allowed_domains
    ):
        raise PermissionError("http_domain_not_allowed")
    pinned_addresses = _reject_private_host(parsed.hostname)
    method = str(args.get("method") or "GET").upper()
    headers = {str(k): str(v) for k, v in dict(args.get("headers") or {}).items()}
    headers.setdefault("User-Agent", "Claw-Agent-Runtime/1.0")
    request = Request(quote(url, safe=":/?#[]@!$&'()*+,;=%"), method=method, headers=headers)
    max_chars = max(1, min(int(args.get("max_chars") or 20000), 100000))
    opener = (pinned_opener(pinned_addresses, _NoRedirectHandler()) if pinned_addresses
              else build_opener(_NoRedirectHandler()))
    with opener.open(request, timeout=10) as response:
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


def _reject_private_host(hostname: str) -> tuple[str, ...] | None:
    # Literal private IPs must never take the synthetic-DNS fallback.
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None and not is_public_ip(str(literal)):
        raise PermissionError("private_network_requests_are_not_allowed")
    try:
        addresses = {row[4][0] for row in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as exc:
        raise ValueError("host_resolution_failed") from exc
    if addresses and all(is_fake_ip(address) for address in addresses):
        return resolve_fake_ip(hostname)
    for address in addresses:
        if not is_public_ip(address):
            raise PermissionError("private_network_requests_are_not_allowed")
    return None


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
