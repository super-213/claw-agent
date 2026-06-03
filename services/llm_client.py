"""LLM 客户端封装"""
import asyncio
from openai import AsyncOpenAI, OpenAI
from typing import Any, AsyncIterator, Dict, Iterator, List


class LLMClient:
    """OpenAI 客户端适配器"""
    
    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 30):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self._async_client: AsyncOpenAI | None = None

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
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self._chat_messages(messages),
            timeout=self.timeout
        )
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
        response = await self.async_client.chat.completions.create(
            model=self.model,
            messages=self._chat_messages(messages),
            timeout=self.timeout,
        )
        return response.choices[0].message.content

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
    def _chat_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """OpenAI Chat Completions receives text, so expose media as readable paths."""
        return [
            {
                "role": message.get("role", ""),
                "content": LLMClient._content_with_media(message),
            }
            for message in messages
        ]

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
