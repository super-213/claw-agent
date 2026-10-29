"""Budgets, cancellation and loop-safety primitives for Agent runs."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from threading import Event
from typing import Any

from .models import ToolCall


@dataclass(frozen=True)
class RunLimits:
    max_steps: int = 0
    max_runtime_seconds: int = 0
    max_tokens: int = 0
    max_cost: float = 0.0
    max_tool_output_chars: int = 12_000
    max_repeated_calls: int = 3
    max_empty_turns: int = 2


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


def argument_hash(name: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"name": name, "arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class LoopGuard:
    max_repeated_calls: int = 3
    max_empty_turns: int = 2
    _last_fingerprint: str = ""
    _repeat_count: int = 0
    _empty_turns: int = 0

    def observe_calls(self, calls: list[ToolCall]) -> bool:
        fingerprint = hashlib.sha256(
            "|".join(argument_hash(call.name, call.arguments) for call in calls).encode("utf-8")
        ).hexdigest()
        if fingerprint == self._last_fingerprint:
            self._repeat_count += 1
        else:
            self._last_fingerprint = fingerprint
            self._repeat_count = 1
        self._empty_turns = 0
        return self._repeat_count >= self.max_repeated_calls

    def observe_empty(self) -> bool:
        self._empty_turns += 1
        return self._empty_turns >= self.max_empty_turns

    def observe_final(self) -> None:
        self._empty_turns = 0
        self._repeat_count = 0
