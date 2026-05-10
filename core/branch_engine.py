"""分支管理引擎 - 管理会话的树状分支结构"""

import uuid
from typing import Dict, List


class BranchEngine:
    """分支管理引擎

    将扁平的消息列表构建为内存中的树索引，支持分支创建、路径查询、
    上下文构建等操作。每条消息通过 node_id 唯一标识，通过 parent_id
    建立父子关系。
    """

    def __init__(self, messages: List[Dict]):
        """初始化分支引擎，构建内存中的树索引。

        Args:
            messages: 消息列表，每条消息应包含 'node_id' 和 'parent_id' 字段。
                      缺少 'node_id' 的消息将被跳过。
        """
        self._nodes: Dict[str, Dict] = {}  # node_id -> message
        self._children: Dict[str, List[str]] = {}  # node_id -> [child_node_ids]

        for message in messages:
            node_id = message.get("node_id")
            if node_id is None:
                continue

            self._nodes[node_id] = message

            parent_id = message.get("parent_id")
            # 为当前节点初始化子节点列表（如果尚未存在）
            if node_id not in self._children:
                self._children[node_id] = []

            # 将当前节点添加到父节点的子节点列表中
            if parent_id is not None:
                if parent_id not in self._children:
                    self._children[parent_id] = []
                self._children[parent_id].append(node_id)

    def get_path_to_node(self, node_id: str) -> List[Dict]:
        """获取从根到指定节点的消息路径。

        Args:
            node_id: 目标节点的唯一标识符。

        Returns:
            从根节点到目标节点的消息列表（有序）。

        Raises:
            ValueError: 如果指定的 node_id 不存在。
        """
        if node_id not in self._nodes:
            raise ValueError(f"节点不存在: {node_id}")

        path = []
        current_id = node_id

        while current_id is not None:
            node = self._nodes[current_id]
            path.append(node)
            current_id = node.get("parent_id")

        path.reverse()
        return path

    def create_branch(self, branch_point_id: str) -> str:
        """在指定节点创建分支，返回新的叶节点 ID（空占位）。

        Args:
            branch_point_id: 分支点节点的唯一标识符。

        Returns:
            新创建的叶节点 ID。

        Raises:
            ValueError: 如果指定的 branch_point_id 不存在。
        """
        if branch_point_id not in self._nodes:
            raise ValueError(f"分支点不存在: {branch_point_id}")

        new_node_id = str(uuid.uuid4())

        # 创建空占位节点，继承分支点作为父节点
        new_node: Dict = {
            "node_id": new_node_id,
            "parent_id": branch_point_id,
            "role": "user",
            "content": "",
        }

        # 添加到节点索引
        self._nodes[new_node_id] = new_node

        # 初始化新节点的子节点列表
        self._children[new_node_id] = []

        # 将新节点添加到分支点的子节点列表
        if branch_point_id not in self._children:
            self._children[branch_point_id] = []
        self._children[branch_point_id].append(new_node_id)

        return new_node_id

    def delete_branch(self, node_id: str, active_node_id: str) -> int:
        """删除指定节点及其所有后代，返回删除数量。

        Args:
            node_id: 要删除的节点的唯一标识符。
            active_node_id: 当前活跃节点的 ID，用于防止删除活跃分支。

        Returns:
            被删除的节点数量。

        Raises:
            ValueError: 如果 node_id 不存在、是根节点、或在活跃路径上。
        """
        # 1. 检查节点是否存在
        if node_id not in self._nodes:
            raise ValueError(f"节点不存在: {node_id}")

        # 2. 检查是否为根节点（parent_id 为 None）
        if self._nodes[node_id].get("parent_id") is None:
            raise ValueError(f"不能删除根节点: {node_id}")

        # 3. 检查是否在活跃路径上（是 active_node_id 的祖先或就是 active_node_id）
        if active_node_id in self._nodes:
            active_path = self.get_path_to_node(active_node_id)
            active_path_ids = {n["node_id"] for n in active_path}
            if node_id in active_path_ids:
                raise ValueError(
                    f"不能删除活跃路径上的节点: {node_id}，请先切换到其他分支"
                )

        # 4. 收集要删除的节点（BFS 遍历所有后代）
        to_delete = []
        queue = [node_id]
        while queue:
            current = queue.pop(0)
            to_delete.append(current)
            queue.extend(self._children.get(current, []))

        # 5. 从父节点的子节点列表中移除该节点
        parent_id = self._nodes[node_id].get("parent_id")
        if parent_id is not None and parent_id in self._children:
            self._children[parent_id] = [
                child for child in self._children[parent_id] if child != node_id
            ]

        # 6. 从 _nodes 和 _children 中移除所有收集到的节点
        for nid in to_delete:
            del self._nodes[nid]
            if nid in self._children:
                del self._children[nid]

        return len(to_delete)

    def get_tree_summary(self, active_node_id: str) -> List[Dict]:
        """获取树结构摘要（用于前端渲染）。

        Args:
            active_node_id: 当前活跃节点的 ID，用于标记活跃路径。

        Returns:
            节点摘要列表，每个摘要包含 node_id、parent_id、role、summary、
            is_active、child_count 等字段。
        """
        # 计算活跃路径上的节点集合
        active_path_ids: set = set()
        if active_node_id in self._nodes:
            current_id = active_node_id
            while current_id is not None:
                active_path_ids.add(current_id)
                current_id = self._nodes[current_id].get("parent_id")

        # 遍历所有节点，生成摘要
        summaries: List[Dict] = []
        for node_id, node in self._nodes.items():
            content = node.get("content", "") or ""
            if len(content) > 30:
                summary = content[:30] + "..."
            else:
                summary = content

            summaries.append({
                "node_id": node_id,
                "parent_id": node.get("parent_id"),
                "role": node.get("role", ""),
                "summary": summary,
                "is_active": node_id in active_path_ids,
                "child_count": len(self._children.get(node_id, [])),
            })

        return summaries

    def build_context(self, leaf_node_id: str) -> List[Dict]:
        """构建从根到叶节点的上下文消息序列。

        获取从根节点到指定叶节点的完整路径，过滤掉空占位节点
        （如分支创建时产生的空节点），返回可直接用于模型请求的消息序列。

        Args:
            leaf_node_id: 叶节点的唯一标识符。

        Returns:
            从根节点到叶节点路径上的有效消息列表（有序），
            不包含空内容的占位节点。

        Raises:
            ValueError: 如果指定的 leaf_node_id 不存在。
        """
        path = self.get_path_to_node(leaf_node_id)

        # 过滤掉空占位节点（如 create_branch 创建的空节点）
        context = [msg for msg in path if msg.get("content")]

        return context

    def append_message(self, parent_id: str, message: Dict) -> str:
        """在指定父节点下追加消息，返回新 node_id。

        Args:
            parent_id: 父节点的唯一标识符。
            message: 要追加的消息字典（包含 role, content, ts 等字段）。

        Returns:
            新消息的 node_id。

        Raises:
            ValueError: 如果指定的 parent_id 不存在。
        """
        if parent_id not in self._nodes:
            raise ValueError(f"父节点不存在: {parent_id}")

        # 生成新的唯一 node_id
        new_node_id = str(uuid.uuid4())

        # 设置消息的 node_id 和 parent_id
        message["node_id"] = new_node_id
        message["parent_id"] = parent_id

        # 添加到节点索引
        self._nodes[new_node_id] = message

        # 初始化新节点的子节点列表
        self._children[new_node_id] = []

        # 将新节点添加到父节点的子节点列表
        self._children[parent_id].append(new_node_id)

        return new_node_id

    def migrate_linear(self, messages: List[Dict]) -> List[Dict]:
        """将线性消息列表迁移为带 node_id/parent_id 的树结构。

        对于不含 node_id 的历史消息列表，按顺序生成 node_id 并建立
        线性的 parent_id 链。已有 node_id 的消息保持不变。

        Args:
            messages: 线性消息列表（可能不含 node_id/parent_id）。

        Returns:
            带有 node_id 和 parent_id 字段的消息列表。
        """
        migrated: List[Dict] = []
        prev_node_id: str | None = None

        for msg in messages:
            # 创建消息副本以避免修改原始数据
            new_msg = dict(msg)

            # 如果消息已有 node_id，保留它；否则生成新的 UUID
            if "node_id" not in new_msg or new_msg["node_id"] is None:
                new_msg["node_id"] = str(uuid.uuid4())

            # 设置 parent_id：第一条消息为 None，后续指向前一条消息
            new_msg["parent_id"] = prev_node_id

            prev_node_id = new_msg["node_id"]
            migrated.append(new_msg)

        # 更新内部树索引
        self._nodes.clear()
        self._children.clear()
        for msg in migrated:
            node_id = msg["node_id"]
            self._nodes[node_id] = msg
            if node_id not in self._children:
                self._children[node_id] = []
            parent_id = msg.get("parent_id")
            if parent_id is not None:
                if parent_id not in self._children:
                    self._children[parent_id] = []
                self._children[parent_id].append(node_id)

        return migrated
