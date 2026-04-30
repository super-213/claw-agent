"""对话管理器"""
from typing import List, Dict


class ConversationManager:
    """管理对话历史和消息构建"""
    
    def __init__(self, system_prompt: str):
        self._messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]
        self._summary = ""
        self._summarized_until = 1

    def get_system_prompt(self) -> str:
        """获取系统提示词"""
        if self._messages and self._messages[0].get("role") == "system":
            return self._messages[0].get("content", "")
        return ""
    
    def add_user_message(self, content: str):
        """添加用户消息"""
        self._messages.append({"role": "user", "content": content})
    
    def add_assistant_message(self, content: str):
        """添加助手消息"""
        self._messages.append({"role": "assistant", "content": content})
    
    def add_system_message(self, content: str):
        """添加系统消息（用于技能注入）"""
        self._messages.append({"role": "system", "content": content})
    
    def inject_skill_context(self, skill_name: str, skill_content: str):
        """注入技能上下文"""
        self.add_system_message(f"## 激活技能：{skill_name}\n{skill_content}")
    
    def get_messages(self) -> List[Dict[str, str]]:
        """获取消息列表副本"""
        return self._messages.copy()

    def get_summary(self) -> str:
        """获取已压缩的历史摘要"""
        return self._summary

    def get_summarized_until(self) -> int:
        """获取已摘要到的消息下标"""
        return self._summarized_until

    def set_summary(self, summary: str, summarized_until: int):
        """更新历史摘要元数据"""
        self._summary = summary or ""
        self._summarized_until = max(1, min(summarized_until, len(self._messages)))

    def load_messages(self, messages: List[Dict[str, str]]):
        """加载历史消息（仅保留 role/content）"""
        cleaned: List[Dict[str, str]] = []
        for msg in messages:
            cleaned.append(
                {
                    "role": msg.get("role", ""),
                    "content": msg.get("content", ""),
                }
            )
        self._messages = cleaned
        self._summarized_until = max(1, min(self._summarized_until, len(self._messages)))

    def load_summary(self, summary: str = "", summarized_until: int = 1):
        """加载历史摘要元数据"""
        self.set_summary(summary, summarized_until)
    
    def clear_history(self, keep_system: bool = True):
        """清空历史（可选保留系统提示）"""
        if keep_system:
            self._messages = [self._messages[0]]
        else:
            self._messages = []
        self._summary = ""
        self._summarized_until = 1
