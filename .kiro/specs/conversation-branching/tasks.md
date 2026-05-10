# 任务清单：会话分支

## 第 1 阶段：后端数据模型与分支引擎

- [x] 1.1 创建 `core/branch_engine.py`，实现 `BranchEngine` 类的基础结构（节点索引、子节点映射）
- [x] 1.2 实现 `migrate_linear()` 方法：将线性消息列表转换为带 `node_id`/`parent_id` 的树结构
- [x] 1.3 实现 `get_path_to_node()` 方法：从根到指定节点的路径查询
- [x] 1.4 实现 `create_branch()` 方法：在指定节点创建新分支
- [x] 1.5 实现 `delete_branch()` 方法：删除指定节点及其所有后代
- [x] 1.6 实现 `build_context()` 方法：构建当前路径的模型上下文
- [x] 1.7 实现 `append_message()` 方法：在指定父节点下追加消息
- [x] 1.8 实现 `get_tree_summary()` 方法：生成树结构摘要供前端使用
- [x] 1.9 为 BranchEngine 编写属性测试（路径完整性、分支创建不变量、上下文隔离、删除一致性、迁移 round-trip）

## 第 2 阶段：持久化层改造

- [x] 2.1 修改 `ConversationStore.create_session()`：新会话的 system 消息带 `node_id`，设置 `active_node_id`
- [x] 2.2 修改 `ConversationStore.load_session()`：加载时检测旧格式并自动调用 `migrate_linear()` 迁移
- [x] 2.3 修改 `ConversationStore.save_messages()`：支持保存扁平节点列表（含 node_id/parent_id）和 `active_node_id`
- [x] 2.4 修改 `ConversationStore.clone_session()`：复制时保留完整分支树结构
- [x] 2.5 为持久化 round-trip 编写属性测试（保存后加载得到等价树结构）

## 第 3 阶段：ConversationManager 集成

- [x] 3.1 修改 `ConversationManager`：集成 `BranchEngine`，`load_messages` 时构建树索引
- [x] 3.2 修改 `ConversationManager.get_messages()`：返回当前活跃路径的消息序列
- [x] 3.3 新增 `ConversationManager.switch_branch(node_id)` 方法
- [x] 3.4 新增 `ConversationManager.create_branch(node_id)` 方法
- [x] 3.5 修改 `Orchestrator`：使用 `BranchEngine.build_context()` 构建上下文，回复后记录 `context_nodes`

## 第 4 阶段：API 端点

- [x] 4.1 新增 `POST /api/sessions/<id>/branch` 端点：创建分支
- [x] 4.2 新增 `POST /api/sessions/<id>/switch` 端点：切换活跃路径
- [x] 4.3 新增 `GET /api/sessions/<id>/tree` 端点：获取树结构摘要
- [x] 4.4 新增 `DELETE /api/sessions/<id>/branch/<node_id>` 端点：删除分支
- [X] 4.5 修改 `POST /api/chat/stream`：响应中包含 `context_nodes` 信息
- [x] 4.6 修改 `GET /api/sessions/<id>`：响应中包含 `active_node_id` 和节点的 `node_id`/`parent_id`

## 第 5 阶段：前端树状图

- [x] 5.1 创建 `web/js/branch-tree.js`：树状图模块基础结构（SVG 容器、布局计算）
- [x] 5.2 实现 Reingold-Tilford 树布局算法
- [x] 5.3 实现节点渲染（圆形节点 + 消息摘要 tooltip + 角色颜色区分）
- [x] 5.4 实现连线渲染（贝塞尔曲线连接父子节点）
- [x] 5.5 实现活跃路径高亮（不同颜色标记当前路径上的节点和连线）
- [x] 5.6 实现节点点击交互：点击节点调用 switch API 切换分支
- [x] 5.7 实现缩放和平移交互（鼠标滚轮缩放、拖拽平移）
- [x] 5.8 添加树状图面板的 UI 布局（桌面端右侧面板、移动端底部抽屉）

## 第 6 阶段：前端上下文高亮

- [x] 6.1 创建 `web/js/context-highlight.js`：上下文高亮模块
- [x] 6.2 修改 `messages.js`：消息 DOM 元素添加 `data-node-id` 属性
- [x] 6.3 实现上下文路径高亮逻辑：根据 `context_nodes` 为消息添加高亮 CSS 类
- [x] 6.4 实现压缩状态标记：区分"完整发送"和"已压缩为摘要"的消息样式
- [x] 6.5 实现分支切换时清除旧高亮并在新回复后重新标记

## 第 7 阶段：前端交互集成

- [x] 7.1 修改 `messages.js`：消息右键菜单/操作按钮增加"从此处创建分支"选项
- [x] 7.2 修改 `sessions.js`：`openSession` 时加载树结构并渲染树状图
- [x] 7.3 修改 `sessions.js`：流式响应完成后更新树状图（追加新节点）
- [x] 7.4 修改 `sessions.js`：分支切换后重新渲染消息列表
- [x] 7.5 添加分支删除的前端交互（树状图节点右键菜单）
- [x] 7.6 添加相关 CSS 样式（高亮色、树状图面板、节点样式、响应式布局）

## 第 8 阶段：兼容性与收尾

- [x] 8.1 确保"复制会话"功能正常工作：复制包含分支的会话保留完整树结构
- [x] 8.2 确保历史会话文件（无 node_id）加载时自动迁移且功能正常
- [x] 8.3 更新 README.md：添加会话分支功能说明和 API 文档
- [x] 8.4 端到端测试：创建分支 → 切换 → 对话 → 高亮 → 删除的完整流程验证

