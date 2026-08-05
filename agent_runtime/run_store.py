"""Atomic JSON checkpoints for resumable Agent runs."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
from threading import Lock
from typing import Any
import uuid
import secrets
from datetime import datetime, timezone


class RunStore:
    TERMINAL_STATUSES = {"completed", "failed", "cancelled", "budget_exceeded"}

    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def create(
        self,
        *,
        session_id: str,
        goal: str,
        max_steps: int,
        max_runtime_seconds: int,
    ) -> dict[str, Any]:
        now = self._now()
        run = {
            "id": uuid.uuid4().hex,
            "session_id": session_id,
            "goal": goal,
            "status": "running",
            "step_count": 0,
            "max_steps": max_steps,
            "max_runtime_seconds": max_runtime_seconds,
            "pending_approval": None,
            "steps": [],
            "created_at": now,
            "updated_at": now,
        }
        self.save(run)
        return run

    def load(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id)
        if not path.exists():
            raise KeyError(f"Run not found: {run_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, run: dict[str, Any]) -> dict[str, Any]:
        run = dict(run)
        run["updated_at"] = self._now()
        path = self._path(str(run["id"]))
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        with self._lock:
            tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, path)
        return run

    def append_step(self, run: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
        run.setdefault("steps", []).append({**step, "recorded_at": self._now()})
        run["step_count"] = len(run["steps"])
        return self.save(run)

    def update(self, run: dict[str, Any], **changes: Any) -> dict[str, Any]:
        run.update(changes)
        return self.save(run)

    def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        rows = []
        for path in self.root_dir.glob("*.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if row.get("session_id") == session_id:
                rows.append(row)
        return sorted(rows, key=lambda row: row.get("updated_at") or "", reverse=True)

    def rotate_approval_token(self, run_id: str) -> str:
        run = self.load(run_id)
        pending = dict(run.get("pending_approval") or {})
        if run.get("status") != "waiting_approval" or not pending:
            raise ValueError("run_is_not_waiting_for_approval")
        token = secrets.token_urlsafe(24)
        pending["token_hash"] = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self.update(run, pending_approval=pending)
        return token

    def _path(self, run_id: str) -> Path:
        if not run_id or any(char not in "0123456789abcdef" for char in run_id.lower()):
            raise KeyError(f"Invalid run id: {run_id}")
        return self.root_dir / f"{run_id}.json"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
