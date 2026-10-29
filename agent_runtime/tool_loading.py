"""Per-run tool discovery. Registration and execution permissions stay separate."""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable

from .models import ToolDefinition
from .registry import ToolRegistry


GROUPS = {
    "public_web": "公网查询、搜索、网页、天气、新闻 / public web HTTP search",
    "files": "读取文本、生成文件、命令 / files documents shell",
    "time": "日期、时间、时区 / date time timezone",
    "knowledge": "保存和检索资料、说明书、事实、偏好、记忆 / knowledge memory",
    "tasks": "日程、备忘、提醒、清单、完成、周期 / tasks calendar reminders",
    "board": "家庭留言板、便笺、接收人 / board notes recipients",
    "home_assistant": "智能家居设备与状态 / home automation devices",
    "external": "已连接外部服务 / MCP external services",
    "other": "其他已注册能力 / other capabilities",
}


def group_for(name: str) -> str:
    if name == "http_request" or name.startswith("browser_"):
        return "public_web"
    for prefix, group in (("knowledge_", "knowledge"), ("family_board_", "board"),
                          ("family_", "tasks"), ("home_assistant_", "home_assistant"),
                          ("mcp_", "external"), ("file_", "files"), ("shell_", "files"),
                          ("datetime_", "time")):
        if name.startswith(prefix):
            return group
    return "other"


def tool_group(tool: ToolDefinition) -> str:
    return tool.group or group_for(tool.name)


def terms(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(phrase[i:i + 2] for i in range(len(phrase) - 1))
        if len(phrase) == 1:
            words.add(phrase)
    return words


class ToolLoadingSession:
    def __init__(self, registry: ToolRegistry, allowed: Callable[[], set[str] | None]):
        if registry.get("tool_load") is not None:
            raise ValueError("tool_load is reserved for per-run tool discovery")
        self.registry = registry
        self.allowed = allowed
        self.loaded: list[str] = []
        # Never register per-run handlers on the application's shared registry.
        self.controls = ToolRegistry()
        self.controls.register(ToolDefinition(
            name="tool_load",
            description="按任务查找并加载相关工具，下一轮提供完整参数；不执行业务操作。用 query 描述目标、group 缩小范围，或 names 指定已知名称。返回全部匹配工具，找不到时换查询，不猜参数。",
            input_schema={"type": "object", "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 500},
                "group": {"type": "string", "enum": list(GROUPS)},
                "offset": {"type": "integer", "minimum": 0},
                "names": {"type": "array",
                          "items": {"type": "string", "minLength": 1, "maxLength": 200}},
            }, "additionalProperties": False},
            handler=self.discover, idempotent=True,
        ))

    def eligible(self) -> list[ToolDefinition]:
        allowed = self.allowed()
        canonical = {self.registry.resolve_name(name) for name in allowed} if allowed is not None else None
        return [tool for tool in self.registry.list()
                if tool.name != "skill_load" and (canonical is None or tool.name in canonical)]

    def catalog(self) -> str:
        counts = Counter(tool_group(tool) for tool in self.eligible())
        return "\n".join(f"- {group}: {GROUPS.get(group, group)}（{count} 项）" for group, count in sorted(counts.items()))

    def load(self, names: list[str]) -> list[str]:
        canonical = list(dict.fromkeys(self.registry.resolve_name(name) for name in names))
        eligible = {tool.name for tool in self.eligible()}
        if any(name not in eligible for name in canonical):
            raise ValueError("tool_unavailable_or_not_allowed")
        self.loaded = [name for name in self.loaded if name in eligible and name not in canonical]
        self.loaded += canonical
        return canonical

    def restore(self, names) -> None:
        eligible = {tool.name for tool in self.eligible()}
        self.loaded = list(dict.fromkeys(
            self.registry.resolve_name(name) for name in names if isinstance(name, str)
        ))
        self.loaded = [name for name in self.loaded if name in eligible]

    def discover(self, args: dict) -> dict:
        names = args.get("names")
        group = args.get("group")
        query = str(args.get("query") or "").strip().lower()
        offset = args.get("offset", 0)
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset 必须为非负整数")
        if names:
            selected = self.load(names)
        else:
            if not query and not group:
                raise ValueError("请提供 query、group 或 names，以便按任务加载工具")
            candidates = [tool for tool in self.eligible() if not group or tool_group(tool) == group]
            query_terms = terms(query)
            ranked = []
            for tool in candidates:
                # Exact names and aliases work even when descriptions are in another language.
                exact = query == tool.name.lower() or self.registry.resolve_name(query) == tool.name
                direct = len(query_terms & terms(tool.name + " " + tool.description + " " + " ".join(tool.keywords)))
                category = len(query_terms & terms(GROUPS.get(tool_group(tool), tool_group(tool))))
                score = 1000 * exact + 10 * direct + category
                if score or (group and not query):
                    ranked.append((score, tool))
            ranked.sort(key=lambda row: (-row[0], row[1].name))
            # Keep offset for old checkpoints/calls, without imposing a page size.
            selected = self.load([tool.name for _, tool in ranked[offset:]])
        return {
            "loaded": [{"name": name, "description": self.registry.get(name).description[:180]}
                       for name in selected],
            "active_tools": list(self.loaded),
            "next_offset": None,
            "notice": "完整参数定义将在下一轮 tools 中提供，再调用具体工具执行。" if selected
                      else "未找到相关工具，请用目录中的 group 或具体操作名称重试。",
        }

    def schemas(self) -> list[dict]:
        eligible = {tool.name for tool in self.eligible()}
        active = set(self.loaded) & eligible
        controls = self.controls.schemas()
        controls[0]["function"]["parameters"]["properties"]["group"]["enum"] = sorted(
            set(GROUPS) | {tool_group(tool) for tool in self.eligible()})
        return controls + self.registry.schemas(allowed_tools=active | {"skill_load"})
