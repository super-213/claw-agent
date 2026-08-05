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
from datetime import datetime, timedelta, timezone

from .models import RunStatus


class RunStore:
    STATUSES = {status.value for status in RunStatus}
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
        token_budget: int = 100_000,
        cost_budget: float = 0.0,
        max_tool_output_chars: int = 12_000,
    ) -> dict[str, Any]:
        now = self._now()
        run = {
            "id": uuid.uuid4().hex,
            "session_id": session_id,
            "goal": goal,
            "status": "running",
            "current_step": None,
            "step_count": 0,
            "max_steps": max_steps,
            "max_runtime_seconds": max_runtime_seconds,
            "runtime_elapsed_ms": 0,
            "token_budget": max(0, int(token_budget)),
            "tokens_used": 0,
            "cost_budget": max(0.0, float(cost_budget)),
            "cost_used": 0.0,
            "max_tool_output_chars": max_tool_output_chars,
            "cancel_requested": False,
            "pending_approval": None,
            "tool_ledger": {},
            "steps": [],
            "events": [{
                "type": "state_transition",
                "from": "pending",
                "to": "running",
                "at": now,
            }],
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
            # Cancellation may be requested by another API task while the
            # orchestrator still holds an older in-memory checkpoint. Never
            # let a later stale save erase that durable signal.
            if path.exists():
                try:
                    durable = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    durable = {}
                if durable.get("cancel_requested"):
                    run["cancel_requested"] = True
                    run["cancel_reason"] = durable.get("cancel_reason")
            tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, path)
        return run

    def append_step(self, run: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
        recorded_at = self._now()
        payload = {
            "step_id": step.get("step_id") or uuid.uuid4().hex,
            "reasoning_summary": step.get("reasoning_summary") or "",
            "tool_calls": step.get("tool_calls") or [],
            "observations": step.get("observations") or [],
            "status": step.get("status") or "completed",
            "retry_count": int(step.get("retry_count") or 0),
            **step,
            "recorded_at": recorded_at,
        }
        run.setdefault("steps", []).append(payload)
        run["step_count"] = len(run["steps"])
        run["current_step"] = payload["step_id"]
        return self.save(run)

    def update(self, run: dict[str, Any], **changes: Any) -> dict[str, Any]:
        old_status = run.get("status")
        new_status = changes.get("status", old_status)
        if new_status not in self.STATUSES:
            raise ValueError(f"invalid_run_status:{new_status}")
        run.update(changes)
        if new_status != old_status:
            run.setdefault("events", []).append({
                "type": "state_transition",
                "from": old_status,
                "to": new_status,
                "at": self._now(),
                "reason": changes.get("error") or changes.get("interrupted_reason"),
            })
        return self.save(run)

    def append_event(self, run: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        run.setdefault("events", []).append({**event, "at": event.get("at") or self._now()})
        return self.save(run)

    def request_cancel(self, run_id: str, *, reason: str = "user_requested") -> dict[str, Any]:
        run = self.load(run_id)
        if run.get("status") in self.TERMINAL_STATUSES:
            return run
        return self.update(run, cancel_requested=True, cancel_reason=reason)

    def record_tool_started(
        self,
        run: dict[str, Any],
        *,
        call_id: str,
        fingerprint: str,
        idempotent: bool,
    ) -> dict[str, Any]:
        run.setdefault("tool_ledger", {})[call_id] = {
            "fingerprint": fingerprint,
            "status": "executing",
            "idempotent": bool(idempotent),
            "started_at": self._now(),
        }
        return self.save(run)

    def record_tool_finished(
        self,
        run: dict[str, Any],
        *,
        call_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        entry = dict(run.setdefault("tool_ledger", {}).get(call_id) or {})
        entry.update({"status": "completed", "result": result, "finished_at": self._now()})
        run["tool_ledger"][call_id] = entry
        return self.save(run)

    def resolve_tool_uncertainty(
        self,
        run_id: str,
        *,
        call_id: str,
        action: str,
        output: Any = None,
    ) -> dict[str, Any]:
        run = self.load(run_id)
        if run.get("status") != "waiting_user":
            raise ValueError("run_is_not_waiting_for_user")
        ledger = run.setdefault("tool_ledger", {})
        entry = dict(ledger.get(call_id) or {})
        if entry.get("status") != "executing":
            raise ValueError("tool_call_is_not_uncertain")
        if action == "cancel":
            return self.update(run, status="cancelled", error="user_cancelled_uncertain_tool")
        if action == "retry":
            entry["status"] = "retry_authorized"
            entry["resolved_at"] = self._now()
            ledger[call_id] = entry
        elif action in {"assume_succeeded", "assume_failed"}:
            entry.update({
                "status": "completed",
                "finished_at": self._now(),
                "result": {
                    "call_id": call_id,
                    "name": "",
                    "status": "success" if action == "assume_succeeded" else "error",
                    "output": output,
                    "error": None if action == "assume_succeeded" else "user_marked_failed_after_recovery",
                    "artifacts": [],
                    "attempts": 1,
                    "duration_ms": 0,
                    "metadata": {"recovery_decision": action},
                },
            })
            ledger[call_id] = entry
        else:
            raise ValueError("invalid_recovery_action")
        run.setdefault("events", []).append({
            "type": "recovery_decision", "tool_call_id": call_id,
            "decision": action, "at": self._now(),
        })
        return self.update(run, status="interrupted", error=None)

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
        now = datetime.now(timezone.utc)
        pending["rotated_at"] = now.isoformat()
        pending["expires_at"] = (now + timedelta(minutes=10)).isoformat()
        self.update(run, pending_approval=pending)
        return token

    def _path(self, run_id: str) -> Path:
        if not run_id or any(char not in "0123456789abcdef" for char in run_id.lower()):
            raise KeyError(f"Invalid run id: {run_id}")
        return self.root_dir / f"{run_id}.json"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
