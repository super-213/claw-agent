"""LLM 客户端封装"""
import asyncio
import json
import time
from openai import AsyncOpenAI, OpenAI
from typing import Any, AsyncIterator, Dict, Iterator, List

from agent_runtime.models import AgentModelResponse, ToolCall
from services.model_providers import ModelProvider, provider_for


class LLMClient:
    """OpenAI 客户端适配器"""
    
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int = 30,
        max_retries: int = 2,
        provider: str | ModelProvider | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.provider = provider if isinstance(provider, ModelProvider) else provider_for(base_url, provider)
        self.last_request_metrics: Dict[str, Any] = {}
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self._async_client: AsyncOpenAI | None = None

    @property
    def context_window(self) -> int:
        return self.provider.context_window(self.model)

    @property
    def async_client(self) -> AsyncOpenAI:
        """Lazy async client so CLI-only usage does not need async cleanup."""
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._async_client
    
    def chat(self, messages: List[Dict[str, Any]]) -> str:
        """发送聊天请求"""
        response = self._retry_sync(lambda: self.client.chat.completions.create(
            model=self.model, messages=self._chat_messages(messages), timeout=self.timeout
        ))
        return response.choices[0].message.content

    def stream_chat(self, messages: List[Dict[str, Any]]) -> Iterator[str]:
        """流式发送聊天请求，逐段返回模型输出。"""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=self._chat_messages(messages),
            timeout=self.timeout,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield content

    async def achat(self, messages: List[Dict[str, Any]]) -> str:
        """异步发送聊天请求。"""
        response = await self._retry_async(lambda: self.async_client.chat.completions.create(
            model=self.model, messages=self._chat_messages(messages), timeout=self.timeout
        ))
        return response.choices[0].message.content

    def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> AgentModelResponse:
        """Request one structured Agent turn using native function calling."""
        started = time.monotonic()
        response = self._retry_sync(lambda: self.client.chat.completions.create(
            model=self.model,
            messages=self._chat_messages(messages),
            tools=self.provider.prepare_tools(tools),
            tool_choice="auto",
            timeout=self.timeout,
            **self.provider.extra_request_options(streaming=False),
        ))
        parsed = self.provider.parse_choice(
            response.choices[0], usage=getattr(response, "usage", None),
            request_id=getattr(response, "id", None),
        )
        parsed.latency_ms = int((time.monotonic() - started) * 1000)
        parsed.retry_count = int(self.last_request_metrics.get("retry_count") or 0)
        return parsed

    async def achat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> AgentModelResponse:
        """Async structured Agent turn using native function calling."""
        started = time.monotonic()
        response = await self._retry_async(lambda: self.async_client.chat.completions.create(
            model=self.model,
            messages=self._chat_messages(messages),
            tools=self.provider.prepare_tools(tools),
            tool_choice="auto",
            timeout=self.timeout,
            **self.provider.extra_request_options(streaming=False),
        ))
        parsed = self.provider.parse_choice(
            response.choices[0], usage=getattr(response, "usage", None),
            request_id=getattr(response, "id", None),
        )
        parsed.latency_ms = int((time.monotonic() - started) * 1000)
        parsed.retry_count = int(self.last_request_metrics.get("retry_count") or 0)
        return parsed

    async def astream_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield content deltas followed by a final structured Agent response."""
        started = time.monotonic()
        stream = await self._retry_async(lambda: self.async_client.chat.completions.create(
            model=self.model,
            messages=self._chat_messages(messages),
            tools=self.provider.prepare_tools(tools),
            tool_choice="auto",
            timeout=self.timeout,
            stream=True,
            **self.provider.extra_request_options(streaming=True),
        ))
        content_parts: List[str] = []
        calls: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            delta = choice.delta
            content = getattr(delta, "content", None)
            if content:
                content_parts.append(content)
                yield {"type": "content_delta", "delta": content}
            for raw_call in getattr(delta, "tool_calls", None) or []:
                index = int(getattr(raw_call, "index", 0) or 0)
                current = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if getattr(raw_call, "id", None):
                    current["id"] += raw_call.id
                function = getattr(raw_call, "function", None)
                if function is not None:
                    current["name"] += getattr(function, "name", None) or ""
                    current["arguments"] += getattr(function, "arguments", None) or ""
        tool_calls = [
            ToolCall(
                id=value["id"] or f"call_{index}",
                name=value["name"],
                arguments=self._parse_arguments(value["arguments"]),
            )
            for index, value in sorted(calls.items())
        ]
        yield {
            "type": "done",
            "response": AgentModelResponse(
                content="".join(content_parts),
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                provider=self.provider.name,
                latency_ms=int((time.monotonic() - started) * 1000),
                retry_count=int(self.last_request_metrics.get("retry_count") or 0),
            ),
        }

    async def astream_chat(self, messages: List[Dict[str, Any]]) -> AsyncIterator[str]:
        """异步流式发送聊天请求，逐段返回模型输出。"""
        stream = await self.async_client.chat.completions.create(
            model=self.model,
            messages=self._chat_messages(messages),
            timeout=self.timeout,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield content

    @staticmethod
    def _chat_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize stored messages while preserving native tool-call fields."""
        normalized: List[Dict[str, Any]] = []
        for message in messages:
            row: Dict[str, Any] = {
                "role": message.get("role", ""),
                "content": LLMClient._content_with_media(message),
            }
            if message.get("tool_calls"):
                row["tool_calls"] = message["tool_calls"]
            if message.get("tool_call_id"):
                row["tool_call_id"] = message["tool_call_id"]
            if message.get("name") and message.get("role") == "tool":
                row["name"] = message["name"]
            normalized.append(row)
        return normalized

    @classmethod
    def _agent_response(cls, choice: Any) -> AgentModelResponse:
        from services.model_providers import OtherCompatibleAdapter
        return OtherCompatibleAdapter().parse_choice(choice)

    @staticmethod
    def _parse_arguments(raw: str) -> Dict[str, Any]:
        return ModelProvider.parse_arguments(raw)

    def _retry_sync(self, operation):
        started = time.monotonic()
        for attempt in range(self.max_retries + 1):
            try:
                value = operation()
                self.last_request_metrics = {
                    "retry_count": attempt,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
                return value
            except Exception as exc:
                if attempt >= self.max_retries:
                    self.last_request_metrics = {
                        "retry_count": attempt,
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "error": str(exc),
                    }
                    raise
                time.sleep(min(0.5 * (2 ** attempt), 4.0))

    async def _retry_async(self, operation):
        started = time.monotonic()
        for attempt in range(self.max_retries + 1):
            try:
                value = await operation()
                self.last_request_metrics = {
                    "retry_count": attempt,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
                return value
            except Exception as exc:
                if attempt >= self.max_retries:
                    self.last_request_metrics = {
                        "retry_count": attempt,
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "error": str(exc),
                    }
                    raise
                await asyncio.sleep(min(0.5 * (2 ** attempt), 4.0))

    @staticmethod
    def _content_with_media(message: Dict[str, Any]) -> str:
        content = str(message.get("content") or "")
        media_lines = LLMClient._media_lines("图片", message.get("images"))
        media_lines.extend(LLMClient._media_lines("附件", message.get("attachments")))
        if not media_lines:
            return content
        media_text = "\n".join(["[上传内容]", *media_lines])
        return f"{content}\n\n{media_text}".strip()

    @staticmethod
    def _media_lines(label: str, items: Any) -> List[str]:
        if not isinstance(items, list):
            return []
        lines: List[str] = []
        for item in items:
            if isinstance(item, str):
                source = item.strip()
                name = source.rsplit("/", 1)[-1] or source
                mime = ""
            elif isinstance(item, dict):
                source = str(item.get("path") or item.get("url") or item.get("src") or "").strip()
                name = str(item.get("name") or item.get("alt") or item.get("title") or source.rsplit("/", 1)[-1]).strip()
                mime = str(item.get("type") or item.get("mime_type") or item.get("mimeType") or "").strip()
            else:
                continue
            if not source:
                continue
            suffix = f", {mime}" if mime else ""
            lines.append(f"- {label}: {name} ({source}{suffix})")
        return lines
    
    def close(self):
        """关闭客户端"""
        self.client.close()
        if self._async_client is not None:
            async_client = self._async_client
            self._async_client = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(async_client.close())
            else:
                loop.create_task(async_client.close())

    async def aclose(self):
        """关闭同步和异步客户端。"""
        self.client.close()
        if self._async_client is not None:
            await self._async_client.close()
            self._async_client = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()
