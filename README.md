# Claw Agent - 重构版

基于分层架构和插件化设计的智能 Agent 系统。

## 架构特点

- **分层架构**：表现层、应用层、领域层、基础设施层清晰分离
- **责任链模式**：灵活的响应处理机制
- **插件化技能系统**：易于扩展的技能注册表
- **依赖注入**：便于测试和维护
- **安全增强**：命令执行黑名单、超时保护
- **FastAPI Web UI + API**：内置 Web 界面、会话 API 与 OpenAPI 文档
- **流式输出**：基于 NDJSON 的实时流式响应，前端逐步渲染
- **Token 用量估算**：基于 tiktoken 的 token 统计与分类
- **LLM 调用可视化**：前端展示每轮模型调用的元信息（模型名、轮次、消息数、耗时）
- **响应式布局**：桌面端与移动端自适应显示
- **多会话并发安全**：会话切换时流式事件正确隔离，不会串台
- **会话分支**：树状对话结构，支持在任意消息位置创建分支、切换路径、上下文高亮

## 目录结构

```
claw/
├── config/              # 配置管理
│   ├── settings.py      # ConfigManager
│   └── .env.example     # 环境变量示例
├── core/                # 核心业务逻辑
│   ├── orchestrator.py  # Agent 编排器
│   ├── conversation.py  # 对话管理
│   ├── branch_engine.py # 分支管理引擎
│   ├── context.py       # 执行上下文
│   └── context_compressor.py # 上下文压缩
├── skills/              # 技能系统
│   ├── base.py          # 技能基类
│   ├── registry.py      # 技能注册表
│   └── calculator/      # 示例技能
├── handlers/            # 响应处理器
│   ├── base.py          # 处理器基类
│   ├── command.py       # 命令处理
│   ├── completion.py    # 完成处理
│   └── skill.py         # 技能输出处理
├── services/            # 基础服务
│   ├── llm_client.py    # LLM 客户端
│   ├── executor.py      # 命令执行器
│   ├── conversation_store.py # JSON 对话持久化
│   └── token_usage.py   # Token 用量估算
├── utils/               # 工具函数
│   └── parser.py        # 输入解析
├── web/                 # Web UI 静态资源（模块化）
│   ├── index.html       # 页面入口
│   ├── styles.css       # 样式（响应式布局）
│   └── js/              # 前端 JS 模块
│       ├── app.js       # 应用初始化
│       ├── api.js       # API 请求封装
│       ├── branch-tree.js # 树状图渲染
│       ├── config.js    # 配置面板
│       ├── context-highlight.js # 上下文高亮
│       ├── dom.js       # DOM 工具
│       ├── markdown.js  # Markdown 渲染
│       ├── messages.js  # 消息与流式渲染
│       ├── sessions.js  # 会话管理
│       ├── skills.js    # 技能面板
│       ├── state.js     # 全局状态
│       └── utils.js     # 通用工具
├── files/               # 生成文件目录
├── docs/                # 项目文档
├── web_app.py           # FastAPI Web UI 服务入口
└── main.py              # CLI 入口
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
export DASHSCOPE_API_KEY="your_api_key_here"
export API_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export MODEL_NAME="qwen-plus"
```

或创建 `.env` 文件（参考 `config/.env.example`）

配置优先级：当前进程环境变量 > 项目根 `.env` > `config/.env` > 默认值。

### 3. 运行（CLI）

```bash
python main.py
```

CLI 内置技能管理命令：

- `/skills`：列出当前技能
- `/reload-skills`：手动重载技能目录
- `/add-skill <name> [内容]`：添加技能；不传内容时进入多行输入，单独输入 `.` 结束；默认创建 `.md`，也可用 `<name>.skill` 创建 `.skill` 技能

CLI 内置模型配置命令：

- `/config`：查看当前 API URL、模型名称和脱敏后的 API KEY
- `/config set api_key`：隐藏输入并保存 API KEY
- `/config set api_key <value>`：直接保存 API KEY
- `/config set base_url <url>`：保存 API URL
- `/config set model <name>`：保存模型名称

### Web UI

```bash
python web_app.py
```

默认访问 `http://localhost:8000`。侧边栏的"模型设置"可修改 API URL、API KEY 和模型名称。Web 端只展示脱敏 API KEY；保存时 API KEY 留空会保留原值，不会把完整密钥返回给浏览器。对话历史会保存在 `.data/conversations` 下的 JSON 文件中，可通过 `CONVERSATION_DIR` 修改路径。

服务默认监听 `127.0.0.1:8000`，可通过 `WEB_HOST` 和 `PORT` 覆盖。

后台看板地址：`http://localhost:8000/dashboard`。看板展示全局 token、会话排行、工具调用统计、词云、活跃热力图和单会话详情；旧会话会基于消息内容自动推断工具调用。

FastAPI 自动文档地址：

- Swagger UI：`http://localhost:8000/docs`
- OpenAPI JSON：`http://localhost:8000/openapi.json`

**前端特性：**

- 流式输出：消息逐字渲染，过程步骤实时展示
- LLM 调用卡片：每轮模型请求展示元信息（模型名、轮次、消息数、耗时）
- 过程卡片重建：刷新页面后自动从历史消息重建过程可视化
- 响应式布局：桌面端与移动端自适应，统一显示效果
- 多会话隔离：切换会话时流式事件不会串到其他会话视图
- 图片与附件：支持在消息中展示图片和附件

### Token 用量估算

系统内置基于 tiktoken（`cl100k_base`）的 token 近似估算，可通过 `GET /api/token-usage` 查看：

- 系统提示词 token 数
- 各技能文件 token 数
- 各会话累计 token 用量（按角色、工具调用分类统计）

可通过 `TOKEN_ENCODING` 环境变量切换编码方式。

### 对话持久化

- 默认路径：`.data/conversations`
- 自定义路径：设置 `CONVERSATION_DIR=/absolute/path`
- 长对话会保留完整历史，同时在发给模型前自动压缩旧上下文

### 上下文压缩配置

可通过环境变量调整压缩策略：

- `CONTEXT_MAX_CHARS`：模型请求上下文字符预算，默认 `60000`
- `CONTEXT_RECENT_MESSAGES`：始终保留的最近消息数，默认 `12`
- `SUMMARY_TARGET_CHARS`：历史摘要目标长度，默认 `6000`
- `SUMMARY_INPUT_CHARS`：单次摘要输入字符上限，默认 `30000`

### Web API 说明（接口示例）

基础地址：`http://localhost:8000`

1. `GET /api/sessions` 获取会话列表

```bash
curl http://localhost:8000/api/sessions
```

响应示例：

```json
[
  {
    "id": "d4b4b0...",
    "title": "新对话",
    "created_at": "2026-03-29T08:00:00+00:00",
    "updated_at": "2026-03-29T08:01:00+00:00"
  }
]
```

2. `POST /api/sessions` 新建会话（可选传 `title`）

```bash
curl -X POST http://localhost:8000/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"title":"我的新对话"}'
```

响应示例：

```json
{
  "id": "d4b4b0...",
  "title": "我的新对话",
  "created_at": "2026-03-29T08:00:00+00:00",
  "updated_at": "2026-03-29T08:00:00+00:00",
  "messages": [
    { "role": "system", "content": "...", "ts": "2026-03-29T08:00:00+00:00" }
  ]
}
```

3. `GET /api/skills` 获取技能列表

```bash
curl http://localhost:8000/api/skills
```

4. `POST /api/skills` 添加技能

```bash
curl -X POST http://localhost:8000/api/skills \
  -H 'Content-Type: application/json' \
  -d '{"name":"demo","content":"# demo\n技能说明"}'
```

5. `POST /api/skills/reload` 手动重载技能目录

```bash
curl -X POST http://localhost:8000/api/skills/reload
```

6. `GET /api/sessions/<session_id>` 获取单个会话

```bash
curl http://localhost:8000/api/sessions/d4b4b0...
```

响应示例：

```json
{
  "id": "d4b4b0...",
  "title": "我的新对话",
  "created_at": "2026-03-29T08:00:00+00:00",
  "updated_at": "2026-03-29T08:01:00+00:00",
  "messages": [
    { "role": "system", "content": "...", "ts": "2026-03-29T08:00:00+00:00" },
    { "role": "user", "content": "你好", "ts": "2026-03-29T08:00:10+00:00" },
    { "role": "assistant", "content": "[完成] 你好", "ts": "2026-03-29T08:00:12+00:00" }
  ]
}
```

7. `POST /api/chat` 发送消息（同步）

```bash
curl -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"d4b4b0...","message":"你好"}'
```

响应示例：

```json
{
  "session_id": "d4b4b0...",
  "messages": [
    { "role": "user", "content": "你好" },
    { "role": "assistant", "content": "[完成] 你好" }
  ]
}
```

8. `POST /api/chat/stream` 发送消息（流式）

以 NDJSON（每行一个 JSON 对象）格式返回实时事件流：

```bash
curl -X POST http://localhost:8000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"d4b4b0...","message":"你好"}'
```

事件类型：

| type | 说明 |
|------|------|
| `step` | 过程步骤（stage: request/save） |
| `llm_call` | 模型调用开始，含 model、round、message_count |
| `content` | 流式文本片段 |
| `tool_call` | 工具/命令调用 |
| `tool_result` | 工具执行结果 |
| `done` | 响应完成，含最终 messages |
| `error` | 错误信息 |

9. `GET /api/token-usage` 获取 Token 用量估算

```bash
curl http://localhost:8000/api/token-usage
```

返回系统提示词、技能文件、各会话的 token 统计。

10. `GET /api/config` / `POST /api/config` 查看/修改模型配置

```bash
curl http://localhost:8000/api/config
curl -X POST http://localhost:8000/api/config \
  -H 'Content-Type: application/json' \
  -d '{"base_url":"...","model":"qwen-max","api_key":"..."}'
```

也可以在消息中附带图片或附件元数据；本地生成文件会统一放在 `files/`（可通过 `GENERATED_FILES_DIR` 修改），通过 `/generated/<文件名>` 或 `/files/<文件名>` 访问：

```bash
curl -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id":"d4b4b0...",
    "message":"请看这张图",
    "images":[{"url":"/generated/example.png","alt":"example"}],
    "attachments":[{"name":"原图","url":"https://example.com/a.png","type":"image/png"}]
  }'
```

## 会话分支

会话分支功能允许用户在对话的任意消息位置创建分支，形成树状对话结构。这是对"复制会话"的升级——从全量复制进化为精确的节点级分支。

**核心能力：**

- 在任意消息位置创建分支，探索不同对话方向
- 树状图可视化展示完整分支结构
- 上下文高亮：标记大模型实际使用的历史消息路径
- 分支切换保留所有分支数据，不丢失历史内容
- 向后兼容：历史线性会话自动迁移为树结构

**数据模型：**

每条消息作为树节点，包含 `node_id`（唯一标识）和 `parent_id`（父节点标识）。会话维护 `active_node_id` 指向当前活跃叶节点。所有分支的消息以扁平列表存储在同一个 JSON 文件中。

**前端交互：**

- 消息右键菜单可选择"从此处创建分支"
- 右侧面板（桌面端）或底部抽屉（移动端）展示树状图
- 点击树状图节点切换到对应分支
- 活跃路径和上下文路径用不同颜色区分

### 分支 API

11. `POST /api/sessions/<id>/branch` 在指定消息处创建分支

```bash
curl -X POST http://localhost:8000/api/sessions/d4b4b0.../branch \
  -H 'Content-Type: application/json' \
  -d '{"branch_point_node_id":"node-uuid"}'
```

响应示例：

```json
{
  "ok": true,
  "branch_node_id": "new-leaf-uuid",
  "ancestor_path": ["root", "n1", "n2"]
}
```

12. `POST /api/sessions/<id>/switch` 切换到指定节点的路径

```bash
curl -X POST http://localhost:8000/api/sessions/d4b4b0.../switch \
  -H 'Content-Type: application/json' \
  -d '{"target_node_id":"node-uuid"}'
```

响应示例：

```json
{
  "ok": true,
  "active_node_id": "node-uuid",
  "messages": [
    {"node_id": "root", "role": "system", "content": "..."},
    {"node_id": "n1", "role": "user", "content": "..."},
    {"node_id": "n2", "role": "assistant", "content": "..."}
  ]
}
```

13. `GET /api/sessions/<id>/tree` 获取会话的树结构摘要

```bash
curl http://localhost:8000/api/sessions/d4b4b0.../tree
```

响应示例：

```json
{
  "nodes": [
    {
      "node_id": "root",
      "parent_id": null,
      "role": "system",
      "summary": "你是一个智能助手...",
      "is_active": true,
      "child_count": 1
    },
    {
      "node_id": "n1",
      "parent_id": "root",
      "role": "user",
      "summary": "你好，请帮我写一段代码...",
      "is_active": true,
      "child_count": 2
    }
  ],
  "active_node_id": "n3"
}
```

14. `DELETE /api/sessions/<id>/branch/<node_id>` 删除指定分支

```bash
curl -X DELETE http://localhost:8000/api/sessions/d4b4b0.../branch/node-uuid
```

响应示例：

```json
{
  "ok": true,
  "removed_count": 5
}
```

**注意事项：**

- 不能删除当前活跃分支，需先切换到其他分支
- 不能删除主干路径（根到第一个分支点的路径）
- 删除操作会移除目标节点及其所有子节点

### 流式响应中的分支信息

`POST /api/chat/stream` 的 `done` 事件中包含 `context_nodes` 字段，记录本次请求实际使用的上下文消息节点列表：

```json
{"type": "done", "messages": [...], "context_nodes": ["root", "n1", "n2", "n3"]}
```

### 会话详情中的分支信息

`GET /api/sessions/<id>` 响应中包含分支相关字段：

```json
{
  "id": "d4b4b0...",
  "active_node_id": "n3",
  "messages": [
    {"node_id": "root", "parent_id": null, "role": "system", "content": "..."},
    {"node_id": "n1", "parent_id": "root", "role": "user", "content": "..."}
  ]
}
```

## 使用示例

### 执行系统命令
```
User: 查看当前目录
AI: [命令] ls -la
[执行结果]: ...
AI: [完成] 当前目录共有 5 个文件
```

### 调用技能
```
User: 调用 calculator skill 计算 2+3*4
AI: [计算] 2+3*4 = 14
```

### 直接回答
```
User: Python 如何定义函数？
AI: [完成] 使用 def 关键字：def 函数名(参数): 代码块
```

## 扩展指南

### 添加新技能

1. 在 `skills/` 下创建技能目录
2. 创建 `{skill_name}.md` 或 `{skill_name}.skill` 文件
3. 系统会热重载并自动发现；也可以通过 CLI 的 `/add-skill` 或 Web 侧边栏的"添加技能"创建

### 添加新的响应处理器

1. 继承 `ResponseHandler` 基类
2. 实现 `can_handle()` 和 `process()` 方法
3. 在 `AgentOrchestrator` 中添加到责任链

## 安全特性

- 危险命令黑名单（rm -rf /、mkfs 等）
- 交互式 REPL/编辑器拦截（vi、vim、裸 python 等），允许 python -c / python -m / 脚本等一次性命令
- 命令执行超时保护
- 环境变量管理 API Key

## 与原版对比

| 特性 | 原版 | 重构版 |
|------|------|--------|
| 架构 | 单文件单函数 | 分层模块化 |
| 配置 | 硬编码 | 环境变量 + 配置类 |
| 技能系统 | 函数式 | 插件化注册表 |
| 响应处理 | if-elif 链 | 责任链模式 |
| 命令执行 | 无保护 | 安全检查 + 超时 |
| 可测试性 | 困难 | 依赖注入 |
| 扩展性 | 需修改核心 | 插件式扩展 |
| 输出方式 | 同步阻塞 | 流式 NDJSON |
| Token 统计 | 无 | tiktoken 估算 |
| 前端架构 | 单文件 | 模块化 JS |

## 后续优化方向

- [ ] 添加日志系统
- [ ] 单元测试覆盖
- [ ] 异步执行支持（asyncio）
- [x] Web API 接口（会话/聊天）
- [x] 技能热重载
- [x] 对话历史持久化（JSON 文件）
- [x] 流式输出（NDJSON SSE）
- [x] Token 用量估算
- [x] 前端模块化拆分
- [x] 响应式布局（桌面/移动端）
- [x] 多会话并发安全
- [x] LLM 调用过程可视化
- [x] 图片与附件支持
- [x] 会话分支（树状对话结构）
