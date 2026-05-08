"""文件级对话持久化（非数据库）"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, List, Any

from .token_usage import TokenUsageEstimator


@dataclass
class SessionMeta:
    id: str
    title: str
    created_at: str
    updated_at: str
    token_usage: Dict[str, Any] | None = None


class ConversationStore:
    """基于 JSON 文件的对话存储

    支持多会话并发：每个 session 拥有独立写锁，不同会话的读写互不阻塞。
    单个会话的写入通过 tmp 文件 + os.replace 保证原子性，避免读到半写入状态。
    """

    def __init__(
        self,
        root_dir: str | Path,
        token_estimator: TokenUsageEstimator | None = None,
    ):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        # 管理 session 级锁自身的锁；只在获取/释放 session 锁时短暂持有
        self._locks_guard = Lock()
        self._session_locks: Dict[str, Lock] = {}
        self.token_estimator = token_estimator or TokenUsageEstimator()

    def _session_lock(self, session_id: str) -> Lock:
        with self._locks_guard:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = Lock()
                self._session_locks[session_id] = lock
            return lock

    def _drop_session_lock(self, session_id: str) -> None:
        with self._locks_guard:
            self._session_locks.pop(session_id, None)

    def list_sessions(self) -> List[SessionMeta]:
        sessions: List[SessionMeta] = []
        for path in self.root_dir.glob("*.json"):
            # 跳过原子写留下的临时文件以及 macOS 的 ._ 元数据文件
            if path.name.startswith(".") or path.name.endswith(".tmp"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            session_id = data.get("id") or path.stem
            sessions.append(
                SessionMeta(
                    id=session_id,
                    title=data.get("title", "新对话"),
                    created_at=data.get("created_at", ""),
                    updated_at=data.get("updated_at", ""),
                    token_usage=data.get("token_usage"),
                )
            )
        sessions.sort(key=lambda s: s.updated_at or s.created_at, reverse=True)
        return sessions

    def create_session(self, system_prompt: str, title: str | None = None) -> Dict[str, Any]:
        session_id = uuid.uuid4().hex
        now = self._now_iso()
        session = {
            "id": session_id,
            "title": title or "新对话",
            "created_at": now,
            "updated_at": now,
            "messages": [
                {"role": "system", "content": system_prompt, "ts": now},
            ],
            "summary": "",
            "summarized_until": 1,
        }
        self._annotate_session_usage(session)
        with self._session_lock(session_id):
            self._write_session(session_id, session)
        return session

    def load_session(self, session_id: str) -> Dict[str, Any]:
        path = self._path(session_id)
        if not path.exists():
            raise KeyError(f"Session not found: {session_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return self._with_usage(data)

    def delete_session(self, session_id: str) -> None:
        lock = self._session_lock(session_id)
        with lock:
            path = self._path(session_id)
            if not path.exists():
                self._drop_session_lock(session_id)
                raise KeyError(f"Session not found: {session_id}")
            path.unlink()
        self._drop_session_lock(session_id)

    def clone_session(self, session_id: str) -> Dict[str, Any]:
        # 只锁源会话读取；目标会话是新 id，独立锁。
        with self._session_lock(session_id):
            source = self.load_session(session_id)
        new_id = uuid.uuid4().hex
        now = self._now_iso()
        cloned = {
            **source,
            "id": new_id,
            "title": f"{source.get('title') or '新对话'} 副本",
            "created_at": now,
            "updated_at": now,
            "messages": [
                {**message, "ts": message.get("ts", now)}
                for message in source.get("messages", [])
            ],
            "summary": source.get("summary", ""),
            "summarized_until": source.get("summarized_until", 1),
        }
        self._annotate_session_usage(cloned)
        with self._session_lock(new_id):
            self._write_session(new_id, cloned)
        return cloned

    def save_messages(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        summary: str | None = None,
        summarized_until: int | None = None,
    ) -> Dict[str, Any]:
        with self._session_lock(session_id):
            data = self.load_session(session_id)
            stored = data.get("messages", [])
            now = self._now_iso()
            new_messages: List[Dict[str, Any]] = []

            for idx, msg in enumerate(messages):
                message_payload = self._message_payload(msg)
                if (
                    idx < len(stored)
                    and self._message_payload(stored[idx]) == message_payload
                ):
                    stored_message = {
                        key: value
                        for key, value in stored[idx].items()
                        if key != "usage"
                    }
                    new_messages.append(stored_message)
                else:
                    new_messages.append({**message_payload, "ts": now})

            data["messages"] = new_messages
            if summary is not None:
                data["summary"] = summary
            if summarized_until is not None:
                data["summarized_until"] = max(1, min(summarized_until, len(new_messages)))
            data["updated_at"] = now

            if (not data.get("title") or data["title"] == "新对话"):
                first_user = next(
                    (m for m in new_messages if m.get("role") == "user"),
                    None,
                )
                if first_user and first_user.get("content"):
                    data["title"] = first_user["content"].strip()[:20]

            self._annotate_session_usage(data)
            self._write_session(session_id, data)
            return data

    def refresh_usage(self) -> List[str]:
        """为已有会话文件补齐 token 用量，返回更新过的 session id"""
        updated: List[str] = []
        # 先列出当前全部会话 id，再逐个按 session 锁处理，
        # 避免持有全局锁时阻塞所有会话写入。
        session_ids = [path.stem for path in self.root_dir.glob("*.json")]
        for session_id in session_ids:
            path = self._path(session_id)
            with self._session_lock(session_id):
                if not path.exists():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                session_id = data.get("id") or session_id
                self._annotate_session_usage(data)
                self._write_session(session_id, data)
                updated.append(session_id)
        return updated

    def _path(self, session_id: str) -> Path:
        return self.root_dir / f"{session_id}.json"

    def _write_session(self, session_id: str, data: Dict[str, Any]):
        path = self._path(session_id)
        # 原子写入：先写 .tmp 再 rename，避免并发读到半写文件
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)

    @staticmethod
    def _message_payload(message: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "role": message.get("role", ""),
            "content": message.get("content", ""),
        }
        if message.get("attachments"):
            payload["attachments"] = message["attachments"]
        if message.get("images"):
            payload["images"] = message["images"]
        return payload

    def _with_usage(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not data.get("messages"):
            data["messages"] = []
        self._annotate_session_usage(data)
        return data

    def _annotate_session_usage(self, data: Dict[str, Any]) -> None:
        messages = data.get("messages", [])
        annotated = self.token_estimator.annotate_messages(messages)
        data["messages"] = annotated
        data["token_usage"] = self.token_estimator.summarize_session(
            annotated,
            summary=data.get("summary", ""),
        )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
