"""Home Assistant control client with whitelist enforcement."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


POWER_DOMAINS = {"switch", "light", "fan", "input_boolean"}
TOOL_NAMES = {
    "ha_list_devices": "home_assistant.list_devices",
    "home_assistant.list_devices": "home_assistant.list_devices",
    "ha_get_state": "home_assistant.get_state",
    "home_assistant.get_state": "home_assistant.get_state",
    "ha_turn_on": "home_assistant.turn_on",
    "home_assistant.turn_on": "home_assistant.turn_on",
    "ha_turn_off": "home_assistant.turn_off",
    "home_assistant.turn_off": "home_assistant.turn_off",
}


@dataclass(frozen=True)
class HomeAssistantEntityRule:
    entity_id: str
    aliases: tuple[str, ...] = ()

    def public_payload(self) -> dict[str, Any]:
        domain, _, name = self.entity_id.partition(".")
        return {
            "entity_id": self.entity_id,
            "domain": domain,
            "name": name,
            "aliases": list(self.aliases),
            "power_control": domain in POWER_DOMAINS,
        }


class HomeAssistantService:
    """Safe Home Assistant REST API wrapper.

    The model and UI should call this service instead of calling Home Assistant
    directly. Every operation validates the entity whitelist first.
    """

    def __init__(
        self,
        *,
        base_url: str = "",
        token: str = "",
        allowed_entities: str | list[str] | None = None,
        request_timeout: int = 10,
        root_dir: str | Path | None = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.allowed_entities_raw = self._normalize_allowed_raw(allowed_entities)
        self.request_timeout = max(1, int(request_timeout or 10))
        self.root_dir = Path(root_dir) if root_dir else None
        self._lock = Lock()
        if self.root_dir:
            self.root_dir.mkdir(parents=True, exist_ok=True)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    @property
    def rules(self) -> dict[str, HomeAssistantEntityRule]:
        return {
            rule.entity_id: rule
            for rule in self.parse_allowed_entities(self.allowed_entities_raw)
        }

    def update_runtime(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        allowed_entities: str | list[str] | None = None,
        request_timeout: int | None = None,
    ) -> None:
        with self._lock:
            if base_url is not None:
                self.base_url = base_url.rstrip("/")
            if token is not None:
                self.token = token
            if allowed_entities is not None:
                self.allowed_entities_raw = self._normalize_allowed_raw(allowed_entities)
            if request_timeout is not None:
                self.request_timeout = max(1, int(request_timeout))

    def public_config(self, *, mask_secret) -> dict[str, Any]:
        config_error = None
        try:
            rules = [rule.public_payload() for rule in self.rules.values()]
        except ValueError as exc:
            rules = []
            config_error = str(exc)
        return {
            "base_url": self.base_url,
            "token_set": bool(self.token),
            "token_masked": mask_secret(self.token),
            "allowed_entities": self.allowed_entities_raw,
            "allowed_entity_count": len(rules),
            "allowed_entity_rules": rules,
            "request_timeout": self.request_timeout,
            "configured": self.configured,
            "tools": self.tools_schema(),
            "config_error": config_error,
        }

    def list_allowed_entities(self, *, include_states: bool = False) -> dict[str, Any]:
        rows = [rule.public_payload() for rule in self.rules.values()]
        if include_states:
            for row in rows:
                try:
                    row["state"] = self.get_state(row["entity_id"])["state"]
                except ValueError as exc:
                    row["state_error"] = str(exc)
        return {
            "configured": self.configured,
            "entities": rows,
        }

    def get_state(self, entity_id: str) -> dict[str, Any]:
        rule = self._require_allowed(entity_id)
        self._require_configured()
        data = self._request("GET", f"/api/states/{quote(rule.entity_id, safe='')}")
        return {
            "entity_id": rule.entity_id,
            "state": data.get("state") if isinstance(data, dict) else None,
            "attributes": data.get("attributes", {}) if isinstance(data, dict) else {},
            "last_changed": data.get("last_changed") if isinstance(data, dict) else None,
            "last_updated": data.get("last_updated") if isinstance(data, dict) else None,
        }

    def set_power(self, entity_id: str, turn_on: bool, *, actor: dict[str, Any] | None = None) -> dict[str, Any]:
        rule = self._require_allowed(entity_id)
        self._require_configured()
        domain = rule.entity_id.split(".", 1)[0]
        if domain not in POWER_DOMAINS:
            raise ValueError(f"unsupported_power_domain:{domain}")

        service = "turn_on" if turn_on else "turn_off"
        try:
            result = self._request(
                "POST",
                f"/api/services/{domain}/{service}",
                {"entity_id": rule.entity_id},
            )
            payload = {
                "ok": True,
                "entity_id": rule.entity_id,
                "service": f"{domain}.{service}",
                "home_assistant_result": result,
            }
            self._activity(f"power.{service}", rule.entity_id, actor, ok=True)
            return payload
        except Exception as exc:
            self._activity(f"power.{service}", rule.entity_id, actor, ok=False, error=str(exc))
            raise

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None, *, actor: dict[str, Any] | None = None) -> dict[str, Any]:
        canonical_name = TOOL_NAMES.get((name or "").strip())
        if not canonical_name:
            raise ValueError("unknown_home_assistant_tool")
        args = arguments or {}
        if canonical_name == "home_assistant.list_devices":
            result = self.list_allowed_entities(include_states=bool(args.get("include_states")))
        elif canonical_name == "home_assistant.get_state":
            result = self.get_state(str(args.get("entity_id") or ""))
        elif canonical_name == "home_assistant.turn_on":
            result = self.set_power(str(args.get("entity_id") or ""), True, actor=actor)
        elif canonical_name == "home_assistant.turn_off":
            result = self.set_power(str(args.get("entity_id") or ""), False, actor=actor)
        else:
            raise ValueError("unknown_home_assistant_tool")
        self._activity(f"tool.{canonical_name.rsplit('.', 1)[-1]}", str(args.get("entity_id") or ""), actor, ok=True)
        return {"ok": True, "tool": canonical_name, "result": result}

    def handle_chat_intent(self, text: str, actor: dict[str, Any] | None = None) -> str | None:
        entity_id = self._match_entity(text)
        if not entity_id:
            return None
        try:
            if self._is_turn_on_text(text):
                result = self.set_power(entity_id, True, actor=actor)
                return f"已调用 Home Assistant：{result['entity_id']} 已执行 {result['service']}。"
            if self._is_turn_off_text(text):
                result = self.set_power(entity_id, False, actor=actor)
                return f"已调用 Home Assistant：{result['entity_id']} 已执行 {result['service']}。"
            if self._is_state_text(text):
                state = self.get_state(entity_id)
                return f"{state['entity_id']} 当前状态是 {state.get('state') or 'unknown'}。"
        except ValueError as exc:
            return f"Home Assistant 调用失败：{exc}"
        return None

    def activity_log(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.root_dir:
            return []
        path = self.root_dir / "activity.jsonl"
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows[-max(1, min(limit, 500)) :]

    @staticmethod
    def tools_schema() -> list[dict[str, Any]]:
        return [
            {
                "name": "home_assistant.list_devices",
                "description": "List Home Assistant entities allowed by the server whitelist.",
                "parameters": {
                    "type": "object",
                    "properties": {"include_states": {"type": "boolean"}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "home_assistant.get_state",
                "description": "Read the state of a whitelisted Home Assistant entity.",
                "parameters": {
                    "type": "object",
                    "properties": {"entity_id": {"type": "string"}},
                    "required": ["entity_id"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "home_assistant.turn_on",
                "description": "Turn on a whitelisted switch/light/fan/input_boolean entity.",
                "parameters": {
                    "type": "object",
                    "properties": {"entity_id": {"type": "string"}},
                    "required": ["entity_id"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "home_assistant.turn_off",
                "description": "Turn off a whitelisted switch/light/fan/input_boolean entity.",
                "parameters": {
                    "type": "object",
                    "properties": {"entity_id": {"type": "string"}},
                    "required": ["entity_id"],
                    "additionalProperties": False,
                },
            },
        ]

    @staticmethod
    def parse_allowed_entities(value: str | list[str] | None) -> list[HomeAssistantEntityRule]:
        raw_entries = HomeAssistantService._entries(value)
        rules: list[HomeAssistantEntityRule] = []
        seen: set[str] = set()
        for raw_entry in raw_entries:
            parts = [part.strip() for part in raw_entry.split("|") if part.strip()]
            if not parts:
                continue
            entity_id = parts[0]
            HomeAssistantService._validate_entity_id(entity_id)
            if entity_id in seen:
                continue
            seen.add(entity_id)
            rules.append(HomeAssistantEntityRule(entity_id=entity_id, aliases=tuple(parts[1:])))
        return rules

    @staticmethod
    def _entries(value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).replace("\n", ",").split(",") if item.strip()]

    @staticmethod
    def _normalize_allowed_raw(value: str | list[str] | None) -> str:
        return "\n".join(HomeAssistantService._entries(value))

    @staticmethod
    def _validate_entity_id(entity_id: str) -> None:
        if not entity_id or "." not in entity_id:
            raise ValueError("invalid_entity_id")
        domain, name = entity_id.split(".", 1)
        allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
        if not domain or not name or any(char not in allowed_chars for char in domain + name):
            raise ValueError("invalid_entity_id")

    def _require_allowed(self, entity_id: str) -> HomeAssistantEntityRule:
        entity_id = (entity_id or "").strip()
        self._validate_entity_id(entity_id)
        rule = self.rules.get(entity_id)
        if not rule:
            raise ValueError("entity_not_allowed")
        return rule

    def _require_configured(self) -> None:
        if not self.configured:
            raise ValueError("home_assistant_not_configured")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.request_timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"home_assistant_http_{exc.code}:{detail}") from exc
        except URLError as exc:
            raise ValueError(f"home_assistant_connection_error:{exc.reason}") from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def _match_entity(self, text: str) -> str | None:
        normalized = text or ""
        for rule in self.rules.values():
            if rule.entity_id in normalized:
                return rule.entity_id
            for alias in rule.aliases:
                if alias and alias in normalized:
                    return rule.entity_id
        return None

    @staticmethod
    def _is_turn_on_text(text: str) -> bool:
        return any(word in text for word in ("打开", "开启", "启动", "开一下", "turn on"))

    @staticmethod
    def _is_turn_off_text(text: str) -> bool:
        return any(word in text for word in ("关闭", "关掉", "停止", "关一下", "turn off"))

    @staticmethod
    def _is_state_text(text: str) -> bool:
        return any(word in text for word in ("状态", "查询", "看看", "开着", "关着", "state"))

    def _activity(
        self,
        action: str,
        entity_id: str,
        actor: dict[str, Any] | None,
        *,
        ok: bool,
        error: str | None = None,
    ) -> None:
        if not self.root_dir:
            return
        entry = {
            "at": datetime.now().astimezone().isoformat(),
            "action": action,
            "entity_id": entity_id,
            "ok": ok,
            "actor_id": (actor or {}).get("id"),
            "actor_username": (actor or {}).get("username"),
        }
        if error:
            entry["error"] = error
        path = self.root_dir / "activity.jsonl"
        with self._lock:
            with path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(entry, ensure_ascii=False) + "\n")
