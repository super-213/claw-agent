"""LLM 客户端封装"""
from openai import OpenAI
from typing import Any, Dict, List


class LLMClient:
    """OpenAI 客户端适配器"""
    
    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 30):
        self.model = model
        self.timeout = timeout
        self.client = OpenAI(api_key=api_key, base_url=base_url)
    
    def chat(self, messages: List[Dict[str, Any]]) -> str:
        """发送聊天请求"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self._chat_messages(messages),
            timeout=self.timeout
        )
        return response.choices[0].message.content

    @staticmethod
    def _chat_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """OpenAI Chat Completions 只接收 role/content，附件仅用于本地展示。"""
        return [
            {
                "role": message.get("role", ""),
                "content": str(message.get("content") or ""),
            }
            for message in messages
        ]
    
    def close(self):
        """关闭客户端"""
        self.client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
