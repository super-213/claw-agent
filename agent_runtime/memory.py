"""Source-aware session and user memory with explicit long-term authorization."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any
import uuid


class MemoryStore:
    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def save(
        self,
        *,
        content: str,
        scope: str,
        owner_id: str,
        source: str,
        confidence: float = 1.0,
        user_authorized: bool = False,
    ) -> dict[str, Any]:
        if scope not in {"session", "user"}:
            raise ValueError("invalid_memory_scope")
        if scope == "user" and not user_authorized:
            raise PermissionError("long_term_memory_requires_user_authorization")
        content = content.strip()
        if not content:
            raise ValueError("memory_content_required")
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": uuid.uuid4().hex,
            "scope": scope,
            "owner_id": owner_id,
            "content": content[:20_000],
            "source": source,
            "confidence": max(0.0, min(float(confidence), 1.0)),
            "created_at": now,
            "updated_at": now,
        }
        rows = self._load(scope, owner_id)
        rows.append(record)
        self._save(scope, owner_id, rows)
        return record

    def search(self, query: str, *, scopes: list[tuple[str, str]], limit: int = 8) -> list[dict[str, Any]]:
        terms = {term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]+", query) if len(term) > 1}
        candidates: list[tuple[float, dict[str, Any]]] = []
        for scope, owner_id in scopes:
            for row in self._load(scope, owner_id):
                text = str(row.get("content") or "").lower()
                overlap = sum(1 for term in terms if term in text)
                if terms and not overlap:
                    continue
                score = overlap + float(row.get("confidence") or 0)
                candidates.append((score, row))
        candidates.sort(key=lambda item: (item[0], item[1].get("updated_at") or ""), reverse=True)
        return [row for _, row in candidates[:max(1, min(limit, 50))]]

    def delete(self, memory_id: str, *, scope: str, owner_id: str) -> bool:
        rows = self._load(scope, owner_id)
        kept = [row for row in rows if row.get("id") != memory_id]
        if len(kept) == len(rows):
            return False
        self._save(scope, owner_id, kept)
        return True

    def correct(
        self,
        memory_id: str,
        *,
        scope: str,
        owner_id: str,
        content: str,
        source: str,
    ) -> dict[str, Any]:
        rows = self._load(scope, owner_id)
        for row in rows:
            if row.get("id") == memory_id:
                row["content"] = content.strip()[:20_000]
                row["source"] = source
                row["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._save(scope, owner_id, rows)
                return row
        raise KeyError("memory_not_found")

    def _path(self, scope: str, owner_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", owner_id)[:128]
        return self.root_dir / f"{scope}-{safe}.json"

    def _load(self, scope: str, owner_id: str) -> list[dict[str, Any]]:
        path = self._path(scope, owner_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return payload if isinstance(payload, list) else []

    def _save(self, scope: str, owner_id: str, rows: list[dict[str, Any]]) -> None:
        path = self._path(scope, owner_id)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        with self._lock:
            tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
