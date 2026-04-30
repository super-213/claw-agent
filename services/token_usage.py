"""Token 用量近似估算"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

import tiktoken


DEFAULT_ENCODING = "cl100k_base"
MESSAGE_OVERHEAD_TOKENS = 4
SESSION_PRIMER_TOKENS = 3


@dataclass(frozen=True)
class TokenUsageEstimator:
    """基于 tiktoken 的近似 token 估算器"""

    encoding_name: str = DEFAULT_ENCODING

    def __post_init__(self):
        object.__setattr__(self, "_encoding", self._load_encoding(self.encoding_name))

    def count_text(self, text: str) -> int:
        return len(self._encoding.encode(text or "", disallowed_special=()))

    def estimate_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        role = message.get("role", "")
        content = message.get("content", "")
        role_tokens = self.count_text(role)
        content_tokens = self.count_text(content)
        total_tokens = role_tokens + content_tokens + MESSAGE_OVERHEAD_TOKENS
        category = self.classify_message(message)

        usage = {
            "estimated": True,
            "encoding": self.encoding_name,
            "category": category,
            "role_tokens": role_tokens,
            "content_tokens": content_tokens,
            "message_overhead_tokens": MESSAGE_OVERHEAD_TOKENS,
            "total_tokens": total_tokens,
            "tool_tokens": total_tokens if category in {"tool_call", "tool_result"} else 0,
        }

        if category == "tool_call":
            usage["tool_call_tokens"] = total_tokens
            usage["tool_result_tokens"] = 0
        elif category == "tool_result":
            usage["tool_call_tokens"] = 0
            usage["tool_result_tokens"] = total_tokens
        else:
            usage["tool_call_tokens"] = 0
            usage["tool_result_tokens"] = 0

        return usage

    def annotate_messages(self, messages: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        annotated: List[Dict[str, Any]] = []
        cumulative_tokens = SESSION_PRIMER_TOKENS

        for message in messages:
            updated = dict(message)
            usage = self.estimate_message(updated)
            cumulative_tokens += usage["total_tokens"]
            usage["cumulative_tokens"] = cumulative_tokens
            updated["usage"] = usage
            annotated.append(updated)

        return annotated

    def summarize_session(
        self,
        messages: Iterable[Dict[str, Any]],
        summary: str = "",
    ) -> Dict[str, Any]:
        totals = {
            "estimated": True,
            "encoding": self.encoding_name,
            "message_count": 0,
            "total_tokens": SESSION_PRIMER_TOKENS,
            "session_primer_tokens": SESSION_PRIMER_TOKENS,
            "system_prompt_tokens": 0,
            "skill_tokens": 0,
            "summary_tokens": self.count_text(summary),
            "conversation_tokens": 0,
            "user_tokens": 0,
            "assistant_tokens": 0,
            "tool_tokens": 0,
            "tool_call_tokens": 0,
            "tool_result_tokens": 0,
        }

        totals["total_tokens"] += totals["summary_tokens"]

        for message in messages:
            usage = message.get("usage") or self.estimate_message(message)
            role = message.get("role", "")
            category = usage.get("category") or self.classify_message(message)
            tokens = int(usage.get("total_tokens", 0))

            totals["message_count"] += 1
            totals["total_tokens"] += tokens

            if category == "system_prompt":
                totals["system_prompt_tokens"] += tokens
            elif category == "skill":
                totals["skill_tokens"] += tokens
            else:
                totals["conversation_tokens"] += tokens

            if role == "user":
                totals["user_tokens"] += tokens
            elif role == "assistant":
                totals["assistant_tokens"] += tokens

            totals["tool_tokens"] += int(usage.get("tool_tokens", 0))
            totals["tool_call_tokens"] += int(usage.get("tool_call_tokens", 0))
            totals["tool_result_tokens"] += int(usage.get("tool_result_tokens", 0))

        return totals

    def summarize_files(self, paths: Iterable[Path]) -> Dict[str, Any]:
        files = []
        total_tokens = 0
        total_bytes = 0

        for path in paths:
            text = path.read_text(encoding="utf-8")
            tokens = self.count_text(text)
            byte_count = len(text.encode("utf-8"))
            files.append(
                {
                    "path": str(path),
                    "tokens": tokens,
                    "bytes": byte_count,
                    "characters": len(text),
                }
            )
            total_tokens += tokens
            total_bytes += byte_count

        return {
            "estimated": True,
            "encoding": self.encoding_name,
            "file_count": len(files),
            "total_tokens": total_tokens,
            "total_bytes": total_bytes,
            "files": files,
        }

    @staticmethod
    def classify_message(message: Dict[str, Any]) -> str:
        role = message.get("role", "")
        content = (message.get("content") or "").lstrip()

        if role == "system":
            return "skill" if content.startswith("## 激活技能：") else "system_prompt"
        if content.startswith("[命令]") or content.startswith("［命令］"):
            return "tool_call"
        if content.startswith("[执行完成]") or content.startswith("［执行完成］"):
            return "tool_result"
        return role or "message"

    @staticmethod
    def _load_encoding(encoding_name: str):
        try:
            return tiktoken.get_encoding(encoding_name)
        except Exception:
            return tiktoken.get_encoding(DEFAULT_ENCODING)
