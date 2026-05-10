# 设计文档：会话分支

## 概述

本设计为对话式 AI Agent 系统引入树状分支结构，替代现有的线性消息列表。核心思路是：将每条消息建模为树节点（带 `node_id` 和 `parent_id`），在后端维护完整的分支树，前端通过树状图可视化并支持路径切换和上下文高亮。

## 架构决策

### 数据存储方案：扁平节点列表 + 邻接表

选择在现有 JSON 文件中扩展字段，而非引入数据库：
- 每条消息增加 `node_id`（UUID）和 `parent_id` 字段
- 会话顶层增加 `active_path`（当前活跃叶节点的 node_id）
- 保持单文件存储，与现有 `ConversationStore` 架构一致

**理由**：项目当前使用 JSON 文件持久化，引入数据库会增加部署复杂度。树的规模（通常 < 1000 节点）在 JSON 中完全可控。

### 前端树状图：Canvas/SVG 自绘

使用轻量级 SVG 渲染树状图，不引入重型图形库：
- 节点用圆形/矩形表示，连线用 SVG path
- 支持缩放和平移
- 活跃路径和上下文路径用不同颜色区分

**理由**：项目前端是原生 JS 模块化架构，不使用框架。SVG 方案轻量且与现有架构一致。

## 数据模型设计

### 消息节点结构

```python
{
    "node_id": "uuid-string",       # 唯一节点标识
    "parent_id": "uuid-string|null", # 父节点标识，根节点为 null
    "role": "user|assistant|system",
    "content": "...",
    "ts": "ISO-8601",
    "attachments": [...],
    "images": [...],
    # 仅 assistant 消息
    "context_nodes": ["node_id_1", "node_id_2", ...]  # 本次请求使用的上下文节点
}
```

### 会话文件结构扩展

```python
{
    "id": "session-uuid",
    "title": "...",
    "created_at": "...",
    "updated_at": "...",
    "active_node_id": "uuid-of-current-leaf",  # 当前活跃叶节点
    "messages": [
        # 扁平列表，所有分支的消息都在这里
        {"node_id": "root", "parent_id": null, "role": "system", ...},
        {"node_id": "n1", "parent_id": "root", "role": "user", ...},
        {"node_id": "n2", "parent_id": "n1", "role": "assistant", ...},
        {"node_id": "n3", "parent_id": "n1", "role": "user", ...},  # 分支
        ...
    ],
    "summary": "...",
    "summarized_until": 1,  # 保留用于兼容，分支模式下改用 summarized_nodes
    "summarized_nodes": ["node_id_1", ...],  # 已被压缩的节点列表
    "token_usage": {...}
}
```

### 向后兼容

对于不含 `node_id` 的历史会话文件，加载时自动补充：
- 按消息顺序生成 `node_id`
- 设置线性的 `parent_id` 链
- 设置 `active_node_id` 为最后一条消息

## API 设计

### 新增接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/sessions/<id>/branch` | 在指定消息处创建分支 |
| POST | `/api/sessions/<id>/switch` | 切换到指定节点的路径 |
| GET | `/api/sessions/<id>/tree` | 获取会话的树结构摘要 |
| DELETE | `/api/sessions/<id>/branch/<node_id>` | 删除指定分支 |

### POST /api/sessions/<id>/branch

请求体：
```json
{
    "branch_point_node_id": "node-uuid"
}
```

响应：
```json
{
    "ok": true,
    "branch_node_id": "new-leaf-uuid",
    "ancestor_path": ["root", "n1", "n2", ...]
}
```

### POST /api/sessions/<id>/switch

请求体：
```json
{
    "target_node_id": "node-uuid"
}
```

响应：
```json
{
    "ok": true,
    "active_node_id": "node-uuid",
    "messages": [...]  // 从根到目标节点的消息序列
}
```

### GET /api/sessions/<id>/tree

响应：
```json
{
    "nodes": [
        {
            "node_id": "...",
            "parent_id": "...",
            "role": "user|assistant|system",
            "summary": "消息前30字...",
            "is_active": true,
            "child_count": 2
        }
    ],
    "active_node_id": "..."
}
```

### DELETE /api/sessions/<id>/branch/<node_id>

响应：
```json
{
    "ok": true,
    "removed_count": 5
}
```

## 后端模块设计

### BranchEngine 类

```python
class BranchEngine:
    """分支管理引擎"""

    def __init__(self, messages: List[Dict]):
        # 构建内存中的树索引
        self._nodes: Dict[str, Dict] = {}  # node_id -> message
        self._children: Dict[str, List[str]] = {}  # node_id -> [child_node_ids]

    def get_path_to_node(self, node_id: str) -> List[Dict]:
        """获取从根到指定节点的消息路径"""

    def create_branch(self, branch_point_id: str) -> str:
        """在指定节点创建分支，返回新的叶节点 ID（空占位）"""

    def delete_branch(self, node_id: str, active_node_id: str) -> int:
        """删除指定节点及其所有后代，返回删除数量"""

    def get_tree_summary(self, active_node_id: str) -> List[Dict]:
        """获取树结构摘要（用于前端渲染）"""

    def build_context(self, leaf_node_id: str) -> List[Dict]:
        """构建从根到叶节点的上下文消息序列"""

    def append_message(self, parent_id: str, message: Dict) -> str:
        """在指定父节点下追加消息，返回新 node_id"""

    def migrate_linear(self, messages: List[Dict]) -> List[Dict]:
        """将线性消息列表迁移为带 node_id/parent_id 的树结构"""
```

### 修改 ConversationManager

在 `ConversationManager` 中集成 `BranchEngine`：
- `load_messages` 时构建树索引
- `get_messages` 返回当前活跃路径的消息
- 新增 `switch_branch(node_id)` 方法
- 新增 `create_branch(node_id)` 方法

### 修改 ConversationStore

- `save_messages` 支持保存扁平节点列表（含 node_id/parent_id）
- `load_session` 时自动迁移旧格式
- `clone_session` 保留完整分支树

### 修改 Orchestrator

- 在 `process_user_input` 中使用 `BranchEngine.build_context()` 构建上下文
- 模型回复后记录 `context_nodes` 到 assistant 消息中

## 前端模块设计

### 新增 js/branch-tree.js

负责树状图的 SVG 渲染：
- 布局算法：Reingold-Tilford 树布局
- 节点渲染：圆形节点 + 消息摘要 tooltip
- 连线渲染：贝塞尔曲线
- 交互：点击节点切换分支、缩放平移

### 新增 js/context-highlight.js

负责上下文路径高亮：
- 从 assistant 消息的 `context_nodes` 字段读取
- 在消息列表中为对应消息添加高亮 CSS 类
- 区分"完整发送"和"已压缩"两种状态

### 修改 js/messages.js

- 在每条消息 DOM 上添加 `data-node-id` 属性
- 支持高亮/取消高亮指定节点
- 消息右键菜单增加"从此处创建分支"选项

### 修改 js/sessions.js

- `openSession` 时加载树结构并渲染树状图
- 分支切换后重新渲染消息列表
- 流式响应完成后更新树状图

### UI 布局

树状图面板作为可折叠的侧面板或底部面板：
- 桌面端：右侧面板，可拖拽调整宽度
- 移动端：底部抽屉，上滑展开

## 正确性属性

### 属性 1：路径完整性（不变量）

对于树中任意节点 N，`get_path_to_node(N)` 返回的路径满足：
- 路径第一个元素的 `parent_id` 为 null（根节点）
- 路径最后一个元素的 `node_id` 等于 N
- 路径中相邻元素满足 `path[i+1].parent_id == path[i].node_id`

### 属性 2：分支创建保持树完整性（不变量）

创建分支前后：
- 原有所有节点的 `node_id` 和 `parent_id` 不变
- 原有所有路径仍然可达
- 新分支点的子节点数量增加 1

### 属性 3：上下文隔离（不变量）

对于任意活跃路径 P，`build_context(P.leaf)` 返回的消息集合：
- 是从根到叶节点路径上节点的子集（考虑压缩）
- 不包含任何不在该路径上的节点

### 属性 4：持久化 Round-Trip

对于任意会话树结构 T：
- `save(T)` 后 `load()` 得到的树结构与 T 等价
- 等价定义：所有节点的 node_id、parent_id、content 相同，active_node_id 相同

### 属性 5：删除后树一致性（不变量）

删除节点 N 后：
- N 及其所有后代不在消息列表中
- 剩余节点的 parent_id 仍指向存在的节点（或 null）
- 树仍然连通（从根可达所有剩余节点）

### 属性 6：向后兼容迁移（Round-Trip）

对于任意线性消息列表 L：
- `migrate_linear(L)` 产生的树结构中，`get_path_to_node(leaf)` 返回的消息内容序列与 L 相同
- 迁移后的树只有一条路径（无分支）

### 属性 7：分支切换幂等性

对于同一个目标节点，连续两次 `switch_branch(node_id)` 返回相同的消息序列。

## 性能考量

- 树索引在内存中构建，O(n) 初始化，O(depth) 路径查询
- 前端树状图使用虚拟化，仅渲染可视区域内的节点
- 大型会话（>200 节点）时树状图支持折叠子树
- JSON 文件大小随分支增长，但单会话通常不超过几 MB

## 测试策略

- **属性测试**：使用 Hypothesis 对 BranchEngine 的核心方法进行属性测试（路径完整性、分支创建不变量、上下文隔离、持久化 round-trip）
- **单元测试**：API 端点的请求/响应验证
- **集成测试**：前后端联调，验证分支创建→切换→对话的完整流程
- **性能测试**：200+ 节点的树状图渲染性能

