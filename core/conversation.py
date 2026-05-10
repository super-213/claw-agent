"""对话管理器"""
from typing import Any, Dict, List, Optional

from core.branch_engine import BranchEngine


class ConversationManager:
    """管理对话历史和消息构建"""
    
    def __init__(self, system_prompt: str):
        self._messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        self._summary = ""
        self._summarized_until = 1
        self.branch_engine: Optional[BranchEngine] = None
        self.active_node_id: Optional[str] = None

    def get_system_prompt(self) -> str:
        """获取系统提示词"""
        if self._messages and self._messages[0].get("role") == "system":
            return self._messages[0].get("content", "")
        return ""
    
    def add_user_message(
        self,
        content: str,
        attachments: List[Dict[str, Any]] | None = None,
        images: List[Dict[str, Any]] | None = None,
    ):
        """添加用户消息"""
        msg = self._build_message("user", content, attachments, images)
        if self.branch_engine is not None and self.active_node_id is not None:
            new_node_id = self.branch_engine.append_message(self.active_node_id, msg)
            self.active_node_id = new_node_id
        self._messages.append(msg)
    
    def add_assistant_message(
        self,
        content: str,
        attachments: List[Dict[str, Any]] | None = None,
        images: List[Dict[str, Any]] | None = None,
    ):
        """添加助手消息"""
        msg = self._build_message("assistant", content, attachments, images)
        if self.branch_engine is not None and self.active_node_id is not None:
            new_node_id = self.branch_engine.append_message(self.active_node_id, msg)
            self.active_node_id = new_node_id
        self._messages.append(msg)
    
    def add_system_message(self, content: str):
        """添加系统消息（用于技能注入）"""
        self._messages.append({"role": "system", "content": content})
    
    def inject_skill_context(self, skill_name: str, skill_content: str):
        """注入技能上下文"""
        self.add_system_message(f"## 激活技能：{skill_name}\n{skill_content}")
    
    def switch_branch(self, node_id: str) -> List[Dict[str, Any]]:
        """切换活跃路径到指定节点。

        更新 active_node_id 并返回从根节点到目标节点的消息序列。

        Args:
            node_id: 目标节点的唯一标识符。

        Returns:
            从根节点到目标节点的消息列表（有序）。

        Raises:
            ValueError: 如果 BranchEngine 未初始化或 node_id 不存在。
        """
        if self.branch_engine is None:
            raise ValueError("BranchEngine 未初始化，无法切换分支")

        # get_path_to_node will raise ValueError if node_id doesn't exist
        path = self.branch_engine.get_path_to_node(node_id)

        # Update the active node
        self.active_node_id = node_id

        return path

    def create_branch(self, node_id: str) -> Dict[str, Any]:
        """在指定节点创建分支。

        调用 BranchEngine.create_branch() 创建新分支，更新 active_node_id
        为新分支节点，并返回新分支节点 ID 和祖先路径。

        Args:
            node_id: 分支点节点的唯一标识符。

        Returns:
            包含以下字段的字典：
            - branch_node_id: 新创建的分支节点 ID
            - ancestor_path: 从根节点到新分支节点的节点 ID 列表

        Raises:
            ValueError: 如果 BranchEngine 未初始化或 node_id 不存在。
        """
        if self.branch_engine is None:
            raise ValueError("BranchEngine 未初始化，无法创建分支")

        # Create the branch via BranchEngine (raises ValueError if node_id doesn't exist)
        new_node_id = self.branch_engine.create_branch(node_id)

        # Update active_node_id to the new branch node
        self.active_node_id = new_node_id

        # Get the ancestor path from root to the new branch node
        path = self.branch_engine.get_path_to_node(new_node_id)
        ancestor_path = [msg["node_id"] for msg in path]

        return {
            "branch_node_id": new_node_id,
            "ancestor_path": ancestor_path,
        }

    def get_messages(self) -> List[Dict[str, Any]]:
        """获取当前活跃路径的消息序列。

        如果 BranchEngine 可用且 active_node_id 已设置，则返回从根节点到
        active_node_id 的路径消息（通过 BranchEngine.get_path_to_node()）。
        否则回退到返回完整消息列表副本（兼容无分支的旧会话）。
        """
        if self.branch_engine is not None and self.active_node_id is not None:
            try:
                return self.branch_engine.get_path_to_node(self.active_node_id)
            except ValueError:
                # active_node_id 无效时回退到完整列表
                pass
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

    def load_messages(self, messages: List[Dict[str, Any]], active_node_id: Optional[str] = None):
        """加载历史消息并构建分支树索引。

        保留前端可展示的附件元数据以及分支相关的 node_id/parent_id 字段。
        如果消息不含 node_id/parent_id（旧格式），则通过 BranchEngine.migrate_linear()
        自动迁移为树结构。

        Args:
            messages: 历史消息列表。
            active_node_id: 当前活跃节点的 ID。如果未提供，默认使用最后一条消息的 node_id。
        """
        cleaned: List[Dict[str, Any]] = []
        for msg in messages:
            built = self._build_message(
                msg.get("role", ""),
                msg.get("content", ""),
                msg.get("attachments"),
                msg.get("images"),
            )
            # 保留分支相关字段
            if "node_id" in msg:
                built["node_id"] = msg["node_id"]
            if "parent_id" in msg:
                built["parent_id"] = msg["parent_id"]
            if "context_nodes" in msg:
                built["context_nodes"] = msg["context_nodes"]
            cleaned.append(built)
        self._messages = cleaned
        self._summarized_until = max(1, min(self._summarized_until, len(self._messages)))

        # 构建分支树索引
        has_node_ids = any("node_id" in msg for msg in self._messages)
        if has_node_ids:
            # 消息已有 node_id/parent_id，直接构建树索引
            self.branch_engine = BranchEngine(self._messages)
        else:
            # 旧格式消息，通过 migrate_linear 迁移并构建树索引
            self.branch_engine = BranchEngine([])
            self._messages = self.branch_engine.migrate_linear(self._messages)

        # 设置 active_node_id
        if active_node_id is not None:
            self.active_node_id = active_node_id
        elif self._messages:
            # 默认使用最后一条消息的 node_id（兼容线性会话）
            last_node_id = self._messages[-1].get("node_id")
            if last_node_id:
                self.active_node_id = last_node_id

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

    @staticmethod
    def _build_message(
        role: str,
        content: str,
        attachments: List[Dict[str, Any]] | None = None,
        images: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        message: Dict[str, Any] = {
            "role": role or "",
            "content": content or "",
        }
        if attachments:
            message["attachments"] = attachments
        if images:
            message["images"] = images
        return message
