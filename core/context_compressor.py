"""上下文压缩器"""
from __future__ import annotations

from typing import Dict, Iterable, List

from services.llm_client import LLMClient


class ContextCompressor:
    """在保留完整历史的前提下，为模型请求构造压缩后的上下文"""

    def __init__(
        self,
        llm_client: LLMClient,
        max_context_chars: int = 60000,
        recent_messages: int = 12,
        summary_target_chars: int = 6000,
        summary_input_chars: int = 30000,
    ):
        self.llm_client = llm_client
        self.max_context_chars = max_context_chars
        self.recent_messages = max(2, recent_messages)
        self.summary_target_chars = summary_target_chars
        self.summary_input_chars = summary_input_chars

    def build_messages(self, conversation) -> List[Dict[str, str]]:
        """返回发给模型的消息列表，必要时先增量压缩旧历史"""
        messages = conversation.get_messages()
        if len(messages) <= 1:
            return messages

        summarized_until = self._normalized_until(
            conversation.get_summarized_until(),
            len(messages),
        )
        prompt_messages = self._build_prompt_messages(
            messages,
            conversation.get_summary(),
            summarized_until,
        )
        if self._count_chars(prompt_messages) <= self.max_context_chars:
            return prompt_messages

        self._compress_old_messages(conversation, messages, summarized_until)

        updated_messages = conversation.get_messages()
        updated_until = self._normalized_until(
            conversation.get_summarized_until(),
            len(updated_messages),
        )
        prompt_messages = self._build_prompt_messages(
            updated_messages,
            conversation.get_summary(),
            updated_until,
        )
        if self._count_chars(prompt_messages) <= self.max_context_chars:
            return prompt_messages

        return self._trim_recent_overflow(prompt_messages)

    def _compress_old_messages(
        self,
        conversation,
        messages: List[Dict[str, str]],
        summarized_until: int,
    ) -> None:
        keep_from = max(1, len(messages) - self.recent_messages)
        if keep_from <= summarized_until:
            return

        summary = conversation.get_summary()
        for batch in self._message_batches(messages[summarized_until:keep_from]):
            summary = self._summarize_batch(summary, batch)

        conversation.set_summary(summary, keep_from)

    def _summarize_batch(
        self,
        existing_summary: str,
        messages: List[Dict[str, str]],
    ) -> str:
        formatted_history = self._format_messages(messages)
        summary_messages = [
            {
                "role": "system",
                "content": (
                    "你是对话历史压缩器。请把历史对话压缩成可继续对话的长期记忆，"
                    "保留用户目标、关键约束、已做决策、文件路径、命令结果、错误、"
                    "未完成事项和后续必须记住的事实。不要编造，不要输出无关解释。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"现有摘要：\n{existing_summary or '无'}\n\n"
                    f"新增历史：\n{formatted_history}\n\n"
                    f"请输出更新后的中文摘要，控制在 {self.summary_target_chars} 字符以内。"
                ),
            },
        ]
        try:
            summary = self.llm_client.chat(summary_messages).strip()
        except Exception as exc:
            print(f"[上下文压缩警告] 摘要生成失败，使用本地回退摘要: {exc}")
            summary = self._fallback_summary(existing_summary, messages)

        if len(summary) > self.summary_target_chars:
            summary = summary[: self.summary_target_chars].rstrip()
        return summary

    def _build_prompt_messages(
        self,
        messages: List[Dict[str, str]],
        summary: str,
        summarized_until: int,
    ) -> List[Dict[str, str]]:
        prompt_messages = [messages[0]]
        if summary:
            prompt_messages.append(
                {
                    "role": "system",
                    "content": f"## 历史对话摘要\n{summary}",
                }
            )
        prompt_messages.extend(messages[summarized_until:])
        return prompt_messages

    def _trim_recent_overflow(
        self,
        messages: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        """最近消息本身过大时的兜底：保留 system/summary 和能放下的最新消息"""
        if self._count_chars(messages) <= self.max_context_chars:
            return messages

        head: List[Dict[str, str]] = []
        tail: List[Dict[str, str]] = []
        for msg in messages:
            if msg.get("role") == "system":
                head.append(msg)
            else:
                tail.append(msg)

        budget = max(0, self.max_context_chars - self._count_chars(head))
        selected: List[Dict[str, str]] = []
        used = 0
        for msg in reversed(tail):
            msg_chars = self._count_chars([msg])
            if selected and used + msg_chars > budget:
                break
            selected.append(msg)
            used += msg_chars

        selected.reverse()
        return head + selected

    def _message_batches(
        self,
        messages: Iterable[Dict[str, str]],
    ) -> Iterable[List[Dict[str, str]]]:
        batch: List[Dict[str, str]] = []
        batch_chars = 0
        for msg in messages:
            normalized = self._normalize_for_summary(msg)
            msg_chars = self._count_chars([normalized])
            if batch and batch_chars + msg_chars > self.summary_input_chars:
                yield batch
                batch = []
                batch_chars = 0
            batch.append(normalized)
            batch_chars += msg_chars
        if batch:
            yield batch

    def _normalize_for_summary(self, message: Dict[str, str]) -> Dict[str, str]:
        content = message.get("content", "")
        max_single = max(1000, self.summary_input_chars // 3)
        if len(content) <= max_single:
            return {"role": message.get("role", ""), "content": content}

        half = max_single // 2
        trimmed = (
            content[:half].rstrip()
            + "\n...[内容过长，已截断中间部分]...\n"
            + content[-half:].lstrip()
        )
        return {"role": message.get("role", ""), "content": trimmed}

    @staticmethod
    def _format_messages(messages: List[Dict[str, str]]) -> str:
        parts = []
        for idx, msg in enumerate(messages, start=1):
            role = msg.get("role", "")
            content = msg.get("content", "")
            parts.append(f"{idx}. {role}:\n{content}")
        return "\n\n".join(parts)

    def _fallback_summary(
        self,
        existing_summary: str,
        messages: List[Dict[str, str]],
    ) -> str:
        text = self._format_messages(messages)
        combined = (
            f"{existing_summary}\n\n[未能调用模型生成摘要，以下为原始历史片段]\n{text}"
            if existing_summary
            else f"[未能调用模型生成摘要，以下为原始历史片段]\n{text}"
        )
        return combined[: self.summary_target_chars].rstrip()

    @staticmethod
    def _count_chars(messages: List[Dict[str, str]]) -> int:
        return sum(
            len(msg.get("role", "")) + len(msg.get("content", "")) + 8
            for msg in messages
        )

    @staticmethod
    def _normalized_until(value: int, message_count: int) -> int:
        return max(1, min(value or 1, message_count))
