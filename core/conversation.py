"""对话管理器"""
from typing import List, Dict


class ConversationManager:
    """管理对话历史和消息构建"""
    
    def __init__(self, system_prompt: str):
        self._messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]

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
    
    def clear_history(self, keep_system: bool = True):
        """清空历史（可选保留系统提示）"""
        if keep_system:
            self._messages = [self._messages[0]]
        else:
            self._messages = []
