# 需求文档：会话分支

## 简介

为对话式 AI Agent 系统添加"会话分支"功能。用户可以在任意对话位置创建分支，形成树状对话结构。前端以树状图展示分支关系，并在对话时高亮显示大模型实际使用的历史上下文路径。该功能是对现有"复制会话"的升级——从全量复制进化为精确的节点级分支。

## 术语表

- **Branch_Engine**：后端分支管理引擎，负责创建、存储和查询分支关系
- **Tree_Renderer**：前端树状图渲染组件，负责可视化展示会话的分支结构
- **Context_Highlighter**：前端上下文路径高亮组件，负责标记大模型选择的历史对话路径
- **Conversation_Store**：现有的 JSON 文件级对话持久化服务
- **Branch_Node**：分支树中的一个节点，对应对话中的一条消息
- **Branch_Point**：用户选择创建分支的消息位置
- **Active_Path**：从根节点到当前活跃叶节点的完整消息路径
- **Context_Path**：大模型在一次请求中实际使用的历史消息序列

## 需求

### 需求 1：分支创建

**用户故事：** 作为用户，我想在对话的任意消息位置创建分支，以便从该位置探索不同的对话方向。

#### 验收标准

1. WHEN 用户在某条消息上触发"创建分支"操作, THE Branch_Engine SHALL 以该消息为分支点创建一个新的分支，新分支继承从根节点到该分支点的所有消息
2. WHEN 分支创建成功, THE Branch_Engine SHALL 返回新分支的唯一标识符和完整的祖先消息路径
3. THE Branch_Engine SHALL 支持在同一分支点创建多个分支
4. WHEN 用户在已有分支的消息上再次创建分支, THE Branch_Engine SHALL 将新分支作为该分支点的另一个子分支添加
5. IF 指定的分支点消息不存在, THEN THE Branch_Engine SHALL 返回明确的错误信息，包含无效的消息标识符

### 需求 2：分支数据模型

**用户故事：** 作为开发者，我想要一个清晰的树状数据结构来存储分支关系，以便高效地查询和遍历分支。

#### 验收标准

1. THE Branch_Engine SHALL 为每条消息分配唯一的节点标识符（node_id）
2. THE Branch_Engine SHALL 为每条消息记录其父节点标识符（parent_id），根节点的 parent_id 为 null
3. THE Branch_Engine SHALL 在会话数据中维护一个 branches 字段，记录所有分支点及其子分支列表
4. WHEN 会话数据被持久化, THE Conversation_Store SHALL 将分支树结构与消息数据一同保存到 JSON 文件中
5. THE Branch_Engine SHALL 支持通过任意节点标识符查询从根节点到该节点的完整路径

### 需求 3：分支导航与切换

**用户故事：** 作为用户，我想在不同分支之间自由切换，以便对比不同对话方向的结果。

#### 验收标准

1. WHEN 用户选择切换到某个分支, THE Branch_Engine SHALL 将该分支设为当前活跃路径，并返回该路径上的所有消息
2. WHEN 分支切换完成, THE Tree_Renderer SHALL 更新树状图中的活跃路径高亮
3. THE Branch_Engine SHALL 在切换分支时保留所有分支的消息数据，不丢失任何历史内容
4. WHEN 用户在某个分支上继续对话, THE Branch_Engine SHALL 将新消息追加到当前活跃分支的末端

### 需求 4：树状图可视化

**用户故事：** 作为用户，我想通过树状图清晰地看到会话的分支结构，以便了解对话的整体脉络和分支关系。

#### 验收标准

1. THE Tree_Renderer SHALL 以树状图形式展示会话的完整分支结构，每个节点显示对应消息的摘要文本
2. THE Tree_Renderer SHALL 用视觉连线表示节点之间的父子关系
3. THE Tree_Renderer SHALL 用区别于其他节点的样式标记当前活跃路径上的节点
4. WHEN 用户点击树状图中的某个节点, THE Tree_Renderer SHALL 触发分支切换操作，将对话视图切换到该节点所在的路径
5. WHEN 会话的分支结构发生变化, THE Tree_Renderer SHALL 在 500 毫秒内更新树状图显示
6. THE Tree_Renderer SHALL 在节点数量超过 200 时仍保持流畅的交互响应

### 需求 5：上下文路径高亮

**用户故事：** 作为用户，我想在对话时看到大模型实际使用了哪些历史消息作为上下文，以便理解模型的回复依据。

#### 验收标准

1. WHEN 大模型完成一次回复, THE Context_Highlighter SHALL 在对话视图中高亮标记本次请求中实际发送给模型的所有历史消息
2. THE Context_Highlighter SHALL 使用与活跃路径高亮不同的视觉样式来标记上下文路径
3. WHEN 会话存在上下文压缩（摘要）, THE Context_Highlighter SHALL 标记哪些消息被压缩为摘要、哪些消息被完整发送
4. WHEN 用户切换分支, THE Context_Highlighter SHALL 清除前一个分支的上下文高亮，并在新分支产生回复后重新标记

### 需求 6：与现有"复制会话"功能的兼容

**用户故事：** 作为用户，我想让现有的"复制会话"功能与新的分支系统协调工作，以便平滑过渡到新功能。

#### 验收标准

1. THE Branch_Engine SHALL 将现有的"复制会话"操作视为在根节点创建一个完整的独立会话副本，不纳入分支树结构
2. WHEN 用户对一个包含分支的会话执行"复制会话", THE Conversation_Store SHALL 复制完整的分支树结构到新会话中
3. THE Branch_Engine SHALL 为不含分支数据的历史会话文件提供向后兼容，将其视为只有单一主干路径的会话

### 需求 7：分支删除

**用户故事：** 作为用户，我想删除不再需要的分支，以便保持对话结构的整洁。

#### 验收标准

1. WHEN 用户删除某个分支, THE Branch_Engine SHALL 移除该分支及其所有子分支的消息数据
2. IF 用户尝试删除当前活跃分支, THEN THE Branch_Engine SHALL 拒绝操作并提示用户先切换到其他分支
3. IF 用户尝试删除主干路径（根到第一个分支点的路径）, THEN THE Branch_Engine SHALL 拒绝操作并返回错误信息
4. WHEN 分支删除成功, THE Tree_Renderer SHALL 立即从树状图中移除对应的节点和连线

### 需求 8：分支上下文构建

**用户故事：** 作为开发者，我想确保大模型在分支对话中收到正确的历史上下文，以便模型能基于正确的对话路径生成回复。

#### 验收标准

1. WHEN 用户在某个分支上发送消息, THE Branch_Engine SHALL 构建从根节点到当前分支末端的完整消息序列作为模型上下文
2. THE Branch_Engine SHALL 确保构建的上下文路径中不包含其他分支的消息
3. WHEN 上下文压缩被触发, THE Branch_Engine SHALL 仅对当前活跃路径上的消息执行压缩，不影响其他分支的消息完整性
4. THE Branch_Engine SHALL 在每次模型请求后记录实际使用的上下文消息节点列表，供 Context_Highlighter 使用

