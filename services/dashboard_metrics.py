"""Dashboard metric aggregation for stored conversations."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import re
import shlex
from typing import Any, Iterable


RANGE_DAYS = {
    "today": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
}

STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "you", "your",
    "are", "was", "were", "will", "have", "has", "had", "not", "but",
    "can", "all", "out", "use", "using", "into", "then", "than", "about",
    "http", "https", "com", "www",
    "一个", "这个", "那个", "需要", "进行", "可以", "我们", "你们", "他们",
    "以及", "或者", "如果", "没有", "已经", "当前", "这里", "然后", "因为",
    "所以", "就是", "还是", "通过", "相关", "内容", "回复", "执行", "命令",
    "完成", "系统", "用户", "助手", "消息", "文件", "代码", "数据",
}

READ_COMMANDS = {
    "awk", "cat", "du", "find", "grep", "head", "jq", "ls", "nl", "pwd",
    "rg", "sed", "tail", "tree", "wc",
}
WRITE_COMMANDS = {
    "cp", "mkdir", "mv", "tee", "touch", "truncate",
}
TEST_COMMANDS = {
    "cargo", "go", "gradle", "jest", "mvn", "npm", "pnpm", "pytest",
    "swift", "uv", "xcodebuild", "yarn",
}
NETWORK_COMMANDS = {"curl", "pip", "wget"}
SERVER_COMMANDS = {"fastapi", "flask", "gunicorn", "uvicorn"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _range_start(range_value: str | None, now: datetime | None = None) -> datetime | None:
    value = (range_value or "all").lower()
    if value == "all":
        return None
    now = now or _now_utc()
    if value == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    days = RANGE_DAYS.get(value)
    if days is None and value.endswith("d"):
        try:
            days = max(1, int(value[:-1]))
        except ValueError:
            days = 30
    if days is None:
        days = 30
    return now - timedelta(days=days)


def _in_range(value: Any, start: datetime | None) -> bool:
    if start is None:
        return True
    dt = _parse_dt(value)
    return dt is not None and dt >= start


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _message_usage(message: dict[str, Any]) -> dict[str, Any]:
    usage = message.get("usage")
    return usage if isinstance(usage, dict) else {}


def _message_category(message: dict[str, Any]) -> str:
    role = message.get("role", "")
    content = (message.get("content") or "").lstrip()
    if role == "system":
        return "skill" if content.startswith("## 激活技能：") else "system_prompt"
    if message.get("tool_calls"):
        return "tool_call"
    if role == "tool":
        return "tool_result"
    usage = _message_usage(message)
    category = usage.get("category")
    if category:
        return str(category)
    return str(role or "message")


def _native_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function") or {}
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (TypeError, json.JSONDecodeError):
                arguments = {"raw": arguments}
        calls.append({
            "id": str(raw.get("id") or ""),
            "name": str(function.get("name") or "unknown_tool"),
            "arguments": arguments if isinstance(arguments, dict) else {},
        })
    return calls


def _tool_text(call: dict[str, Any]) -> str:
    arguments = json.dumps(call.get("arguments") or {}, ensure_ascii=False, sort_keys=True)
    return f"{call.get('name') or 'unknown_tool'} {arguments}"


def _strip_heredoc_body(command: str) -> str:
    lines = command.splitlines()
    if len(lines) <= 1:
        return command
    first = lines[0]
    match = re.search(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", first)
    if not match:
        return command
    return first


def _command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(_strip_heredoc_body(command), posix=True)
    except ValueError:
        return command.split()


def _command_program(command: str) -> str:
    tokens = _command_tokens(command)
    if not tokens:
        return "unknown"
    return Path(tokens[0]).name.lower()


def _command_label(command: str) -> str:
    tokens = _command_tokens(command)
    if not tokens:
        return "unknown"
    program = Path(tokens[0]).name.lower()
    if program in {"python", "python3"} and len(tokens) > 1:
        if tokens[1] == "-m" and len(tokens) > 2:
            return f"{program} -m {tokens[2]}"
        if tokens[1] == "-c":
            return f"{program} -c"
    if program in {"npm", "pnpm", "yarn"} and len(tokens) > 1:
        return f"{program} {tokens[1]}"
    if program == "git" and len(tokens) > 1:
        return f"git {tokens[1]}"
    return program


def _command_category(command: str, result_text: str = "") -> str:
    lowered = command.lower()
    result_lowered = result_text.lower()
    program = _command_program(command)
    tokens = _command_tokens(command)

    if "拒绝执行危险命令" in result_text or "blocked" in result_lowered:
        return "blocked"
    if program == "git":
        return "git"
    if program in NETWORK_COMMANDS:
        return "network"
    if program in SERVER_COMMANDS:
        return "server"
    if program in TEST_COMMANDS:
        if program in {"npm", "pnpm", "yarn"} and "test" not in tokens:
            if "install" in tokens:
                return "network"
            if "run" in tokens and any(word in tokens for word in {"dev", "start", "serve"}):
                return "server"
        if program in {"cargo", "go", "swift", "uv"} and "test" not in tokens:
            return "shell_write" if _looks_like_write(lowered) else "unknown"
        return "test"
    if program in READ_COMMANDS:
        return "shell_read"
    if program in WRITE_COMMANDS or _looks_like_write(lowered):
        return "shell_write"
    return "unknown"


def _tool_category(call: dict[str, Any], result_text: str = "") -> str:
    name = str(call.get("name") or "unknown_tool")
    arguments = call.get("arguments") or {}
    if name == "shell_execute":
        return _command_category(str(arguments.get("command") or ""), result_text)
    if name == "http_request":
        return "network"
    if name in {"file_read", "file_write", "datetime_now"}:
        return name
    if name.startswith("home_assistant_"):
        return "home_assistant"
    return "tool"


def _tool_label(call: dict[str, Any]) -> str:
    if call.get("name") == "shell_execute":
        return _command_label(str((call.get("arguments") or {}).get("command") or ""))
    return str(call.get("name") or "unknown_tool")


def _looks_like_write(command: str) -> bool:
    return bool(
        re.search(r"(^|\s)(>|>>|1>|1>>|2>|2>>|&>|&>>)\s*\S+", command)
        or " cat >" in f" {command}"
        or " tee " in f" {command} "
        or "open(" in command
        or ".write(" in command
    )


def _parse_tool_result(message: dict[str, Any] | None) -> dict[str, Any]:
    if not message:
        return {
            "success": None,
            "status": "unknown",
            "return_code": None,
            "output_chars": 0,
            "output_preview": "",
            "token_usage": 0,
        }
    content = message.get("content") or ""
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        payload = {"status": "unknown", "output": content}
    status = str(payload.get("status") or "unknown")
    success = status == "success"
    value = payload.get("output") if success else payload.get("error") or payload.get("output")
    output = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return_code = None
    if isinstance(payload.get("output"), dict) and "return_code" in payload["output"]:
        return_code = _safe_int(payload["output"].get("return_code"))
    return {
        "success": success,
        "status": status,
        "return_code": return_code,
        "output_chars": len(output),
        "output_preview": output[:240],
        "token_usage": _safe_int(_message_usage(message).get("total_tokens")),
    }


def _date_key(value: Any) -> str:
    dt = _parse_dt(value) or _now_utc()
    return dt.date().isoformat()


def _session_timestamp(session: dict[str, Any], message: dict[str, Any] | None = None) -> str:
    if message and message.get("ts"):
        return str(message.get("ts"))
    return str(session.get("updated_at") or session.get("created_at") or "")


def _active_in_range(session: dict[str, Any], start: datetime | None) -> bool:
    if start is None:
        return True
    if _in_range(session.get("updated_at") or session.get("created_at"), start):
        return True
    return any(_in_range(message.get("ts"), start) for message in session.get("messages", []))


def _branch_metrics(session: dict[str, Any]) -> dict[str, int]:
    messages = session.get("messages", [])
    nodes = [m for m in messages if m.get("node_id")]
    children: dict[str, list[str]] = defaultdict(list)
    parent_by_id = {}
    for message in nodes:
        node_id = message.get("node_id")
        parent_id = message.get("parent_id")
        if not node_id:
            continue
        parent_by_id[node_id] = parent_id
        if parent_id:
            children[parent_id].append(node_id)

    def depth(node_id: str, seen: set[str] | None = None) -> int:
        seen = seen or set()
        if node_id in seen:
            return 0
        seen.add(node_id)
        parent_id = parent_by_id.get(node_id)
        if not parent_id:
            return 1
        return 1 + depth(parent_id, seen)

    node_ids = [m.get("node_id") for m in nodes if m.get("node_id")]
    active_node_id = session.get("active_node_id")
    active_depth = depth(active_node_id) if active_node_id else 0
    return {
        "node_count": len(nodes),
        "branch_points": sum(1 for child_ids in children.values() if len(child_ids) > 1),
        "leaf_count": sum(1 for node_id in node_ids if not children.get(node_id)),
        "max_depth": max((depth(node_id) for node_id in node_ids), default=0),
        "active_path_length": active_depth,
        "summarized_nodes": len(session.get("summarized_nodes") or []),
    }


def _health_score(
    token_total: int,
    tool_calls: int,
    tool_failures: int,
    branch_points: int,
    summary_tokens: int,
) -> int:
    score = 100
    if token_total > 80000:
        score -= 25
    elif token_total > 40000:
        score -= 14
    elif token_total > 20000:
        score -= 7
    if tool_calls:
        failure_rate = tool_failures / tool_calls
        score -= min(30, round(failure_rate * 40))
    if branch_points > 5:
        score -= 12
    elif branch_points > 2:
        score -= 6
    if summary_tokens > 6000:
        score -= 8
    return max(0, min(100, score))


def _tokens_from_usage(messages: Iterable[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "total": 0,
        "system": 0,
        "skill": 0,
        "conversation": 0,
        "user": 0,
        "assistant": 0,
        "tool": 0,
        "tool_call": 0,
        "tool_result": 0,
    }
    for message in messages:
        usage = _message_usage(message)
        category = _message_category(message)
        tokens = _safe_int(usage.get("total_tokens"))
        totals["total"] += tokens
        if category == "system_prompt":
            totals["system"] += tokens
        elif category == "skill":
            totals["skill"] += tokens
        else:
            totals["conversation"] += tokens
        role = message.get("role")
        if role == "user":
            totals["user"] += tokens
        elif role == "assistant":
            totals["assistant"] += tokens
        totals["tool"] += _safe_int(usage.get("tool_tokens"))
        totals["tool_call"] += _safe_int(usage.get("tool_call_tokens"))
        totals["tool_result"] += _safe_int(usage.get("tool_result_tokens"))
    return totals


def _bucket_init(key: str) -> dict[str, Any]:
    return {
        "date": key,
        "tokens": 0,
        "messages": 0,
        "tool_calls": 0,
        "tool_failures": 0,
        "sessions": set(),
    }


def _session_word_source(message: dict[str, Any], scope: str) -> bool:
    category = _message_category(message)
    role = message.get("role")
    if category in {"system_prompt", "skill"}:
        return scope == "skill"
    if scope == "all":
        return role in {"user", "assistant"}
    if scope == "user":
        return role == "user" and category != "tool_result"
    if scope == "assistant":
        return role == "assistant" and category != "tool_call"
    if scope in {"tool", "tools"}:
        return category in {"tool_call", "tool_result"}
    return True


def _word_counts(sessions: list[dict[str, Any]], scope: str, limit: int) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    session_sets: dict[str, set[str]] = defaultdict(set)
    for session in sessions:
        session_id = str(session.get("id") or "")
        for message in session.get("messages", []):
            if not _session_word_source(message, scope):
                continue
            content = message.get("content") or ""
            if scope in {"tool", "tools"} and _message_category(message) == "tool_call":
                content = " ".join(_tool_text(call) for call in _native_tool_calls(message))
            for token in _tokenize(content):
                counts[token] += 1
                if session_id:
                    session_sets[token].add(session_id)

    if not counts:
        return []
    max_count = max(counts.values())
    words = []
    for word, count in counts.most_common(max(1, limit)):
        weight = 16 + int(44 * math.sqrt(count / max_count))
        words.append({
            "word": word,
            "count": count,
            "weight": weight,
            "related_session_count": len(session_sets[word]),
        })
    return words


def _tokenize(text: str) -> list[str]:
    text = re.sub(r"https?://\S+", " ", text or "")
    tokens: list[str] = []
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", text):
        lowered = word.lower().strip("_-")
        if lowered and lowered not in STOP_WORDS and not lowered.isdigit():
            tokens.append(lowered)
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if len(chunk) <= 4:
            if chunk not in STOP_WORDS:
                tokens.append(chunk)
            continue
        for index in range(0, len(chunk) - 1):
            token = chunk[index:index + 2]
            if token not in STOP_WORDS:
                tokens.append(token)
    return tokens


class DashboardMetrics:
    """Build dashboard payloads from the current ConversationStore."""

    def __init__(
        self,
        store: Any,
        token_estimator: Any,
        *,
        agent_path: Path,
        agent_prompt: str,
        skills_dir: Path,
    ):
        self.store = store
        self.token_estimator = token_estimator
        self.agent_path = agent_path
        self.agent_prompt = agent_prompt
        self.skills_dir = skills_dir

    def summary(self, range_value: str = "all") -> dict[str, Any]:
        sessions = self._load_sessions()
        start = _range_start(range_value)
        visible_sessions = [s for s in sessions if _active_in_range(s, start)]
        session_rows = self._session_rows(visible_sessions)
        tools = self._tool_events(visible_sessions, start=start)

        total_tokens = sum(row["token_usage"]["total_tokens"] for row in session_rows)
        total_messages = sum(row["message_count"] for row in session_rows)
        tool_failures = sum(1 for item in tools if item["success"] is False)
        resolved_tools = sum(1 for item in tools if item["success"] is not None)
        success_tools = sum(1 for item in tools if item["success"] is True)
        success_rate = round(success_tools / resolved_tools * 100, 1) if resolved_tools else 0
        role_tokens = self._role_tokens(visible_sessions)
        token_breakdown = self._token_breakdown(visible_sessions)
        timeseries = self._timeseries(visible_sessions, tools, start)

        return {
            "range": range_value,
            "generated_at": _now_utc().isoformat(),
            "kpis": {
                "total_sessions": len(visible_sessions),
                "active_sessions": len([s for s in visible_sessions if _in_range(s.get("updated_at"), _range_start("7d"))]),
                "total_messages": total_messages,
                "total_tokens": total_tokens,
                "tool_calls": len(tools),
                "tool_failures": tool_failures,
                "tool_success_rate": success_rate,
                "avg_tokens_per_session": round(total_tokens / len(visible_sessions)) if visible_sessions else 0,
                "avg_messages_per_session": round(total_messages / len(visible_sessions), 1) if visible_sessions else 0,
            },
            "system_prompt": {
                "path": str(self.agent_path),
                "tokens": self.token_estimator.count_text(self.agent_prompt),
                "characters": len(self.agent_prompt),
                "bytes": len(self.agent_prompt.encode("utf-8")),
            },
            "skills": self._skill_summary(),
            "token_breakdown": token_breakdown,
            "role_tokens": role_tokens,
            "top_sessions": sorted(
                session_rows,
                key=lambda row: row["token_usage"]["total_tokens"],
                reverse=True,
            )[:10],
            "tool_summary": self._tool_summary(tools),
            "recent_tool_calls": sorted(
                tools,
                key=lambda item: item.get("timestamp") or "",
                reverse=True,
            )[:12],
            "timeseries": timeseries,
            "word_cloud": _word_counts(visible_sessions, "all", 80),
            "heatmap": self._heatmap(visible_sessions),
            "alerts": self._alerts(session_rows, tools),
        }

    def sessions(self, range_value: str = "all", sort: str = "total_tokens", limit: int = 50) -> dict[str, Any]:
        start = _range_start(range_value)
        sessions = [s for s in self._load_sessions() if _active_in_range(s, start)]
        rows = self._session_rows(sessions)
        sort_map = {
            "total_tokens": lambda row: row["token_usage"]["total_tokens"],
            "tool_calls": lambda row: row["tool_calls"],
            "updated_at": lambda row: row["updated_at"] or "",
            "message_count": lambda row: row["message_count"],
            "health_score": lambda row: row["health_score"],
        }
        sorter = sort_map.get(sort, sort_map["total_tokens"])
        rows = sorted(rows, key=sorter, reverse=True)
        return {
            "range": range_value,
            "sessions": rows[: max(1, min(limit, 500))],
            "total": len(rows),
        }

    def session_detail(self, session_id: str) -> dict[str, Any]:
        try:
            session = self.store.load_session(session_id)
        except KeyError:
            raise
        row = self._session_rows([session])[0]
        tools = self._tool_events([session])
        messages = session.get("messages", [])
        return {
            "session": row,
            "token_curve": [
                {
                    "index": idx,
                    "timestamp": message.get("ts") or session.get("updated_at"),
                    "role": message.get("role"),
                    "tokens": _safe_int(_message_usage(message).get("total_tokens")),
                    "cumulative_tokens": _safe_int(_message_usage(message).get("cumulative_tokens")),
                    "category": _message_category(message),
                }
                for idx, message in enumerate(messages)
            ],
            "role_tokens": self._role_tokens([session]),
            "token_breakdown": self._token_breakdown([session]),
            "tool_calls": tools,
            "word_cloud": _word_counts([session], "all", 80),
            "tool_word_cloud": _word_counts([session], "tool", 60),
            "recent_messages": [
                {
                    "role": message.get("role"),
                    "category": _message_category(message),
                    "timestamp": message.get("ts"),
                    "tokens": _safe_int(_message_usage(message).get("total_tokens")),
                    "preview": (message.get("content") or "")[:220],
                }
                for message in messages[-12:]
            ],
        }

    def tools(self, range_value: str = "all") -> dict[str, Any]:
        start = _range_start(range_value)
        sessions = [s for s in self._load_sessions() if _active_in_range(s, start)]
        tools = self._tool_events(sessions, start=start)
        return {
            "range": range_value,
            "summary": self._tool_summary(tools),
            "tool_calls": sorted(tools, key=lambda item: item.get("timestamp") or "", reverse=True),
        }

    def word_cloud(
        self,
        scope: str = "all",
        session_id: str | None = None,
        limit: int = 120,
    ) -> dict[str, Any]:
        if session_id:
            sessions = [self.store.load_session(session_id)]
        else:
            sessions = self._load_sessions()
        return {
            "scope": scope,
            "session_id": session_id,
            "words": _word_counts(sessions, scope, max(1, min(limit, 300))),
        }

    def timeseries(self, metric: str = "tokens", range_value: str = "30d") -> dict[str, Any]:
        start = _range_start(range_value)
        sessions = [s for s in self._load_sessions() if _active_in_range(s, start)]
        tools = self._tool_events(sessions, start=start)
        rows = self._timeseries(sessions, tools, start)
        return {
            "metric": metric,
            "range": range_value,
            "points": [
                {"date": item["date"], "value": item.get(metric, 0)}
                for item in rows
            ],
        }

    def _load_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for meta in self.store.list_sessions():
            if isinstance(meta, dict):
                session_id = meta.get("id")
            elif hasattr(meta, "id"):
                session_id = meta.id
            else:
                session_id = asdict(meta).get("id")
            if not session_id:
                continue
            try:
                sessions.append(self.store.load_session(session_id))
            except Exception:
                continue
        return sessions

    def _session_rows(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tool_events = self._tool_events(sessions)
        tools_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in tool_events:
            tools_by_session[event["session_id"]].append(event)

        rows = []
        for session in sessions:
            session_id = str(session.get("id") or "")
            messages = session.get("messages", [])
            token_usage = session.get("token_usage") or {}
            tools = tools_by_session.get(session_id, [])
            failures = sum(1 for item in tools if item["success"] is False)
            branch = _branch_metrics(session)
            rows.append({
                "id": session_id,
                "title": session.get("title") or "新对话",
                "created_at": session.get("created_at") or "",
                "updated_at": session.get("updated_at") or "",
                "message_count": len(messages),
                "user_messages": sum(1 for m in messages if m.get("role") == "user" and _message_category(m) != "tool_result"),
                "assistant_messages": sum(1 for m in messages if m.get("role") == "assistant" and _message_category(m) != "tool_call"),
                "tool_calls": len(tools),
                "tool_failures": failures,
                "tool_success_rate": round(
                    (len(tools) - failures) / len(tools) * 100,
                    1,
                ) if tools else 0,
                "branch": branch,
                "token_usage": {
                    "total_tokens": _safe_int(token_usage.get("total_tokens")),
                    "conversation_tokens": _safe_int(token_usage.get("conversation_tokens")),
                    "user_tokens": _safe_int(token_usage.get("user_tokens")),
                    "assistant_tokens": _safe_int(token_usage.get("assistant_tokens")),
                    "tool_tokens": _safe_int(token_usage.get("tool_tokens")),
                    "tool_call_tokens": _safe_int(token_usage.get("tool_call_tokens")),
                    "tool_result_tokens": _safe_int(token_usage.get("tool_result_tokens")),
                    "summary_tokens": _safe_int(token_usage.get("summary_tokens")),
                    "skill_tokens": _safe_int(token_usage.get("skill_tokens")),
                    "system_prompt_tokens": _safe_int(token_usage.get("system_prompt_tokens")),
                },
                "health_score": _health_score(
                    _safe_int(token_usage.get("total_tokens")),
                    len(tools),
                    failures,
                    branch["branch_points"],
                    _safe_int(token_usage.get("summary_tokens")),
                ),
                "last_tool_call": tools[-1]["timestamp"] if tools else "",
            })
        return rows

    def _tool_events(
        self,
        sessions: list[dict[str, Any]],
        *,
        start: datetime | None = None,
    ) -> list[dict[str, Any]]:
        events = []
        for session in sessions:
            session_id = str(session.get("id") or "")
            title = session.get("title") or "新对话"
            messages = session.get("messages", [])
            for index, message in enumerate(messages):
                if _message_category(message) != "tool_call":
                    continue
                if not _in_range(message.get("ts") or session.get("updated_at"), start):
                    continue
                calls = _native_tool_calls(message)
                if not calls:
                    continue
                for call in calls:
                    result_message = self._next_tool_result(messages, index, call.get("id") or "")
                    result = _parse_tool_result(result_message)
                    tool_text = _tool_text(call)
                    category = _tool_category(call, result.get("output_preview", ""))
                    events.append({
                        "id": f"{session_id}:{index}:{len(events)}",
                        "session_id": session_id,
                        "session_title": title,
                        "timestamp": _session_timestamp(session, message),
                        "command": tool_text,
                        "command_preview": tool_text.replace("\n", " ")[:160],
                        "label": _tool_label(call),
                        "category": category,
                        "success": result["success"],
                        "status": result["status"],
                        "return_code": result["return_code"],
                        "output_chars": result["output_chars"],
                        "output_preview": result["output_preview"],
                        "token_usage": _safe_int(_message_usage(message).get("total_tokens")) + result["token_usage"],
                    })
        return events

    @staticmethod
    def _next_tool_result(
        messages: list[dict[str, Any]],
        index: int,
        call_id: str,
    ) -> dict[str, Any] | None:
        for message in messages[index + 1:]:
            if message.get("role") == "tool" and message.get("tool_call_id") == call_id:
                return message
            if message.get("role") in {"user", "assistant"}:
                return None
        return None

    def _role_tokens(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        totals = Counter()
        for session in sessions:
            for message in session.get("messages", []):
                role = str(message.get("role") or "message")
                category = _message_category(message)
                tokens = _safe_int(_message_usage(message).get("total_tokens"))
                if category == "tool_call":
                    totals["tool_call"] += tokens
                elif category == "tool_result":
                    totals["tool_result"] += tokens
                else:
                    totals[role] += tokens
        labels = {
            "system": "系统提示",
            "user": "用户",
            "assistant": "助手",
            "tool_call": "工具调用",
            "tool_result": "工具结果",
        }
        return [
            {"key": key, "label": labels.get(key, key), "tokens": value}
            for key, value in totals.most_common()
        ]

    def _token_breakdown(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        totals = Counter()
        for session in sessions:
            usage = session.get("token_usage") or {}
            totals["系统提示"] += _safe_int(usage.get("system_prompt_tokens"))
            totals["技能上下文"] += _safe_int(usage.get("skill_tokens"))
            totals["用户消息"] += _safe_int(usage.get("user_tokens"))
            totals["助手消息"] += _safe_int(usage.get("assistant_tokens"))
            totals["工具调用"] += _safe_int(usage.get("tool_call_tokens"))
            totals["工具结果"] += _safe_int(usage.get("tool_result_tokens"))
            totals["摘要"] += _safe_int(usage.get("summary_tokens"))
        return [
            {"label": label, "tokens": tokens}
            for label, tokens in totals.items()
            if tokens > 0
        ]

    def _tool_summary(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        by_category = Counter(item["category"] for item in tools)
        by_label = Counter(item["label"] for item in tools)
        failures = [item for item in tools if item["success"] is False]
        resolved = [item for item in tools if item["success"] is not None]
        success = [item for item in tools if item["success"] is True]
        return {
            "total": len(tools),
            "success": len(success),
            "failures": len(failures),
            "unknown": len(tools) - len(resolved),
            "success_rate": round(len(success) / len(resolved) * 100, 1) if resolved else 0,
            "avg_output_chars": round(sum(item["output_chars"] for item in tools) / len(tools)) if tools else 0,
            "by_category": [
                {"category": key, "count": value}
                for key, value in by_category.most_common()
            ],
            "top_commands": [
                {"label": key, "count": value}
                for key, value in by_label.most_common(12)
            ],
            "top_failures": [
                {"label": key, "count": value}
                for key, value in Counter(item["label"] for item in failures).most_common(8)
            ],
        }

    def _timeseries(
        self,
        sessions: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        start: datetime | None,
    ) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = defaultdict(lambda: _bucket_init(""))
        for session in sessions:
            session_id = str(session.get("id") or "")
            for message in session.get("messages", []):
                timestamp = message.get("ts") or session.get("updated_at")
                if not _in_range(timestamp, start):
                    continue
                key = _date_key(timestamp)
                if not buckets[key]["date"]:
                    buckets[key] = _bucket_init(key)
                buckets[key]["tokens"] += _safe_int(_message_usage(message).get("total_tokens"))
                buckets[key]["messages"] += 1
                buckets[key]["sessions"].add(session_id)
        for item in tools:
            key = _date_key(item.get("timestamp"))
            if not buckets[key]["date"]:
                buckets[key] = _bucket_init(key)
            buckets[key]["tool_calls"] += 1
            if item["success"] is False:
                buckets[key]["tool_failures"] += 1
        rows = []
        for key in sorted(buckets):
            item = buckets[key]
            rows.append({
                "date": key,
                "tokens": item["tokens"],
                "messages": item["messages"],
                "tool_calls": item["tool_calls"],
                "tool_failures": item["tool_failures"],
                "sessions": len(item["sessions"]),
            })
        return rows

    def _heatmap(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets = Counter()
        for session in sessions:
            for message in session.get("messages", []):
                dt = _parse_dt(message.get("ts") or session.get("updated_at"))
                if not dt:
                    continue
                key = f"{dt.weekday()}:{dt.hour}"
                buckets[key] += 1
        return [
            {"weekday": int(key.split(":")[0]), "hour": int(key.split(":")[1]), "count": value}
            for key, value in sorted(buckets.items())
        ]

    def _alerts(self, session_rows: list[dict[str, Any]], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        alerts = []
        for row in session_rows:
            tokens = row["token_usage"]["total_tokens"]
            if tokens > 80000:
                alerts.append({
                    "level": "danger",
                    "title": "超长会话",
                    "message": f"{row['title']} 已累计 {tokens} tokens",
                    "session_id": row["id"],
                })
            elif row["tool_calls"] >= 5 and row["tool_success_rate"] < 70:
                alerts.append({
                    "level": "warning",
                    "title": "工具失败率偏高",
                    "message": f"{row['title']} 工具成功率 {row['tool_success_rate']}%",
                    "session_id": row["id"],
                })
        blocked = [item for item in tools if item["category"] == "blocked"]
        if blocked:
            alerts.append({
                "level": "danger",
                "title": "存在被拦截命令",
                "message": f"最近范围内有 {len(blocked)} 次命令被安全策略拦截",
            })
        return alerts[:8]

    def _skill_summary(self) -> dict[str, Any]:
        skill_paths = sorted(
            path
            for suffix in (".md", ".skill")
            for path in self.skills_dir.glob(f"*/*{suffix}")
            if not path.name.startswith("._")
        )
        try:
            return self.token_estimator.summarize_files(skill_paths)
        except Exception:
            return {
                "estimated": True,
                "encoding": getattr(self.token_estimator, "encoding_name", ""),
                "file_count": 0,
                "total_tokens": 0,
                "total_bytes": 0,
                "files": [],
            }
