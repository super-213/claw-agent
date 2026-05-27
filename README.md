# Claw Agent

基于 FastAPI、分层架构和插件化技能系统的本地智能 Agent。项目当前同时提供 CLI、Vite + React + TypeScript Web UI、后台数据看板、会话分支树、流式响应、文件级持久化、token 估算和命令执行安全控制。

## 核心能力

- **分层架构**：`core`、`services`、`handlers`、`skills`、`web-react` 边界清晰，便于扩展和测试。
- **异步 Agent 编排**：同步入口保留兼容，Web 聊天走 async 主流程，支持模型流式输出和命令执行循环。
- **插件化技能系统**：支持 `.md` 和 `.skill` 技能文件，CLI/Web 均可添加和热重载技能。
- **FastAPI API + Vite Web UI**：FastAPI 提供 API、文件访问和 OpenAPI 文档；React 前端由 Vite 开发服务器或独立静态服务承载。
- **NDJSON 流式响应**：前端逐步渲染解析、模型输出、命令执行、保存和完成事件。
- **会话分支树**：每条消息有 `node_id`/`parent_id`，支持任意节点创建分支、切换路径、删除非活跃分支和上下文高亮。
- **会话复制与迁移**：旧线性会话自动迁移为树结构，复制会话时保留完整分支树。
- **文件级持久化**：会话保存到 JSON 文件，按 session 加锁，并通过临时文件 + `os.replace` 原子写入。
- **Token 与看板分析**：基于 `tiktoken` 估算系统提示词、技能、会话、工具调用、摘要等 token，并提供使用趋势、词云、热力图和工具统计。
- **图片与附件元数据**：聊天 API 支持 `images` 与 `attachments`，生成文件统一通过 `/generated/*` 或 `/files/*` 访问。
- **安全执行**：命令黑名单、交互式命令拦截、超时保护、连续失败中止、API Key 脱敏展示。

## 目录结构

```text
.
├── Agent.md                         # Agent 系统指令
├── main.py                          # CLI 入口
├── web_app.py                       # FastAPI Web 服务入口
├── config/
│   ├── settings.py                  # 配置加载、校验、.env 写入
│   └── .env.example                 # 环境变量示例
├── core/
│   ├── orchestrator.py              # Agent 编排、流式事件、命令循环
│   ├── conversation.py              # 对话管理和分支状态
│   ├── branch_engine.py             # 树状分支索引与操作
│   ├── context.py                   # 执行上下文
│   └── context_compressor.py        # 长上下文压缩
├── handlers/
│   ├── command.py                   # [命令] 输出处理
│   ├── completion.py                # [完成] 输出处理
│   └── skill.py                     # 技能输出处理
├── services/
│   ├── chat_runner.py               # Web 聊天运行器与 session 级运行锁
│   ├── conversation_store.py        # JSON 会话持久化、复制、迁移、token 标注
│   ├── branch_service.py            # 分支 API 服务层
│   ├── dashboard_metrics.py         # 看板指标聚合
│   ├── executor.py                  # 命令执行与安全控制
│   ├── llm_client.py                # OpenAI-compatible LLM 客户端
│   ├── message_media.py             # 图片/附件请求归一化
│   ├── session_state.py             # 会话加载与保存辅助
│   └── token_usage.py               # token 估算与分类
├── skills/
│   ├── registry.py                  # 技能注册表
│   └── */*.md|*.skill               # 技能定义
├── web/
│   └── ...                          # 旧版原生 HTML/CSS/JS 前端，短期保留用于回滚参考
├── web-react/
│   ├── index.html                   # Vite HTML shell
│   ├── package.json                 # React/Vite/TypeScript 前端工程
│   ├── vite.config.ts               # Vite dev proxy 与生产构建配置
│   └── src/
│       ├── api/                     # 类型化 API client、NDJSON stream 解析
│       ├── app/                     # Provider、Router、App 根组件
│       ├── features/                # auth/chat/sessions/branch-tree/dashboard 等业务模块
│       ├── stores/                  # Zustand 客户端状态
│       ├── styles/                  # 复用现有 CSS 并承载 React 增量样式
│       └── utils/                   # Markdown、格式化、消息视图工具
├── docs/                            # 设计与需求文档
├── files/                           # 生成文件目录
└── test/                            # Python、前端模块与 React 单元测试
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

前端依赖分为根目录 Node 辅助依赖和 `web-react/` React 工程依赖；缺依赖时执行：

```bash
npm install
npm --prefix web-react install
```

### 2. 配置环境变量

```bash
export DASHSCOPE_API_KEY="your_api_key_here"
export API_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export MODEL_NAME="qwen-plus"
```

也可以创建 `.env` 或 `config/.env`，参考 `config/.env.example`。配置优先级为：

```text
当前进程环境变量 > 项目根 .env > config/.env > 默认值
```

常用配置项：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | 无 | 必填，OpenAI-compatible API Key |
| `API_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 模型 API 地址 |
| `MODEL_NAME` | `qwen-plus` | 模型名称 |
| `AGENT_FILE` | `Agent.md` | Agent 系统指令文件 |
| `SKILLS_DIR` | `skills` | 技能目录 |
| `CONVERSATION_DIR` | `.data/conversations` | 会话 JSON 保存目录 |
| `GENERATED_FILES_DIR` | `files` | 生成文件目录 |
| `WEB_HOST` | `0.0.0.0` | Web 服务监听地址 |
| `PORT` | `8000` | Web 服务端口 |
| `TIMEOUT` | `30` | 命令与模型客户端超时 |
| `TOKEN_ENCODING` | `cl100k_base` | token 估算编码 |

长上下文压缩配置：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CONTEXT_MAX_CHARS` | `60000` | 模型请求上下文字符预算 |
| `CONTEXT_RECENT_MESSAGES` | `12` | 始终保留的最近消息数 |
| `SUMMARY_TARGET_CHARS` | `6000` | 历史摘要目标长度 |
| `SUMMARY_INPUT_CHARS` | `30000` | 单次摘要输入字符上限 |

### 3. 启动 CLI

```bash
python main.py
```

CLI 内置命令：

- `/skills`：列出当前技能。
- `/reload-skills`：手动重载技能目录。
- `/add-skill <name> [内容]`：添加技能；不传内容时进入多行输入，单独输入 `.` 结束。
- `/config`：查看当前 API URL、模型名称和脱敏 API Key。
- `/config set api_key`：隐藏输入并保存 API Key。
- `/config set api_key <value>`：直接保存 API Key。
- `/config set base_url <url>`：保存 API URL。
- `/config set model <name>`：保存模型名称。

### 4. 启动后端 API 与 Web UI

```bash
python web_app.py
```

后端默认端口为 `8000`：

- API 状态：`http://localhost:8000/`
- Swagger UI：`http://localhost:8000/docs`
- OpenAPI JSON：`http://localhost:8000/openapi.json`

React 前端开发模式：

```bash
python web_app.py
npm run web:dev
```

Vite 默认运行在 `http://localhost:5173`，并通过 proxy 转发 `/api`、`/files`、`/generated` 到 `http://127.0.0.1:8000`。如后端端口不同，可设置：

```bash
VITE_API_TARGET=http://127.0.0.1:8001 npm run web:dev
```

生产构建：

```bash
npm run web:typecheck
npm run web:lint
npm run web:test
npm run web:build
npm --prefix web-react run preview
```

`npm run web:build` 会输出到 `web-react/dist`。FastAPI 的 `8000` 端口只提供后端 API，不托管前端页面；生产前端请用 Vite preview、Nginx 或其他静态服务承载，并把 API 目标指向后端地址。

前端常用命令：

| 命令 | 说明 |
| --- | --- |
| `npm run web:dev` | 启动 Vite dev server，默认 `5173`，代理到 FastAPI |
| `npm run web:typecheck` | 执行 TypeScript strict 类型检查 |
| `npm run web:lint` | 执行 ESLint |
| `npm run web:test` | 执行 Vitest 单元测试 |
| `npm run web:build` | 生成 `web-react/dist` 生产静态资源 |
| `npm --prefix web-react run preview` | 本地预览 Vite 构建产物 |

Web 端的“模型设置”可修改 API URL、API Key 和模型名称。API Key 只脱敏展示；保存时留空会保留原值，不会把完整密钥返回给浏览器。

## Web UI 功能

当前默认生产前端已迁移到 Vite + React + TypeScript，并保留旧版原生前端代码作为短期回滚参考。React 前端按 `api/`、`app/`、`features/`、`stores/`、`utils/` 分层，API 请求、权限状态、流式解析和树布局逻辑集中管理。

- 消息逐步渲染，模型输出以流式文本增量展示。
- 过程事件展示解析输入、技能加载、上下文构建、模型调用、命令执行和保存状态。
- 支持多会话创建、删除、复制、切换。
- 支持登录、退出、首次管理员初始化、管理员用户管理和普通用户/管理员入口隔离。
- 支持会话共享设置和共享用户选择。
- 支持会话分支树，在任意消息处创建分支，切换活跃路径，删除非活跃分支。
- 支持上下文路径高亮，标记本轮模型实际使用的历史节点。
- 支持技能列表、技能新增、技能重载和技能快速插入输入框。
- 支持模型 API URL、API Key、模型名称配置。
- 支持图片与附件元数据展示。
- 桌面端与移动端响应式布局；移动端分支树以抽屉形式展示。
- React 构建产物使用 Vite 内容哈希；`/assets/*` 使用长期缓存，其余 HTML/CSS/JS 开发回退资源仍禁用缓存。

## 前端架构

React 前端位于 `web-react/`：

- `src/api/`：统一 JSON request、NDJSON stream request、API 类型定义和各业务 API 封装。
- `src/app/`：React Query Provider、路由表和受保护路由入口。
- `src/features/auth/`：登录、首次管理员初始化和登录态守卫。
- `src/features/chat/`：会话工作台、消息渲染、输入框和流式事件状态转换。
- `src/features/sessions/`：会话侧栏、复制、删除、共享设置。
- `src/features/branch-tree/`：分支树 React 渲染，以及纯函数树模型/布局算法。
- `src/features/dashboard/`：后台看板页面、KPI、图表、词云、会话详情抽屉。
- `src/features/plugins/`、`settings/`、`users/`：技能、模型配置和用户管理弹窗。
- `src/stores/`：Zustand 客户端状态，包括当前用户、会话、技能、模型配置、消息和运行中流式状态。

关键前端测试覆盖：

- `test/web-react/api/stream.test.ts`：NDJSON 分块解析。
- `test/web-react/branch-tree/model/build.test.ts`：分支树展示模型构建。

## 后台看板

后台看板基于 `.data/conversations/*.json` 实时聚合，不依赖数据库。当前指标包括：

- 全局 KPI：会话数、消息数、token 总量、工具调用数、失败数、成功率、平均 token。
- Token 结构：系统提示词、技能上下文、用户消息、助手消息、工具调用、工具结果、摘要。
- 会话排行：按 token、工具调用、消息数、健康分、更新时间排序。
- 单会话详情：累计 token 曲线、角色分布、工具调用、最近消息、词云。
- 工具分析：命令分类、Top 命令、失败命令、输出长度、危险命令拦截。
- 趋势与热力图：按日期聚合 token、消息、工具调用、失败次数和活跃时段。
- 词云：支持全部、用户、助手、工具、单会话范围。

看板接口统一使用 `/api/dashboard/*`，具体见下方 API。

## 会话与持久化

- 默认会话目录：`.data/conversations`
- 每个会话一个 JSON 文件。
- `ConversationStore` 对每个 session 使用独立锁，避免同一会话并发写冲突。
- 写入时先写临时文件，再使用 `os.replace` 原子替换，避免读到半写入文件。
- 会话加载时会自动跳过 `.tmp` 和 macOS `._*` 元数据文件。
- 旧格式线性会话会在加载时自动补齐 `node_id`/`parent_id` 并持久化迁移。
- 会话保存时会重新标注每条消息的 token 用量和会话汇总。

## 会话分支

分支数据模型采用扁平消息列表 + 父子节点指针：

```json
{
  "active_node_id": "node-3",
  "messages": [
    {"node_id": "node-1", "parent_id": null, "role": "system", "content": "..."},
    {"node_id": "node-2", "parent_id": "node-1", "role": "user", "content": "方案 A"},
    {"node_id": "node-3", "parent_id": "node-2", "role": "assistant", "content": "..."}
  ]
}
```

核心规则：

- `active_node_id` 指向当前活跃路径的叶子或占位节点。
- 发给模型的上下文来自根节点到 `active_node_id` 的路径。
- 创建分支时会在分支点下生成一个空占位节点并切换到该节点。
- 新消息会追加到当前活跃节点下，并推进 `active_node_id`。
- 删除分支会删除目标节点及其所有后代。
- 不能删除根节点，也不能删除当前活跃路径上的节点。

## API 概览

基础地址：`http://localhost:8000`

### 会话 API

```bash
curl http://localhost:8000/api/sessions
```

```bash
curl -X POST http://localhost:8000/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"title":"我的新对话"}'
```

```bash
curl http://localhost:8000/api/sessions/<session_id>
```

```bash
curl -X DELETE http://localhost:8000/api/sessions/<session_id>
```

```bash
curl -X POST http://localhost:8000/api/sessions/<session_id>/copy
```

复制会话会保留完整消息、分支树、`active_node_id`、摘要和已摘要节点信息。

### 聊天 API

同步聊天：

```bash
curl -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"<session_id>","message":"你好"}'
```

流式聊天：

```bash
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"<session_id>","message":"你好"}'
```

流式响应为 NDJSON，每行一个 JSON 对象，`Content-Type` 为 `application/x-ndjson`。

常见事件类型：

| type | 说明 |
| --- | --- |
| `step` | 流程状态，例如 `request`、`parse`、`skill`、`context`、`handler`、`save`、`complete` |
| `model_start` | 模型请求开始，包含 `model`、`iteration`、`message_count` |
| `model_delta` | 模型流式增量文本，字段为 `delta` |
| `model_done` | 模型输出完成，包含完整 `content` |
| `command_start` | 检测到 `[命令]` 并开始执行 |
| `command_result` | 命令执行结果，包含 `success`、`return_code`、`output` |
| `done` | 本次请求完成，包含新增 `messages`、`session_id`、`active_node_id`、`context_nodes` |
| `error` | 处理失败，包含错误信息 |

携带图片和附件：

```bash
curl -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id":"<session_id>",
    "message":"请看这张图",
    "images":[{"url":"/generated/example.png","alt":"example"}],
    "attachments":[{"name":"原图","url":"https://example.com/a.png","type":"image/png"}]
  }'
```

`images` 支持字符串 URL 或对象；`attachments` 支持字符串 URL 或包含 `name`、`url`、`path`、`type`、`size` 等字段的对象。单次最多处理 32 个媒体项，文本字段会截断到安全长度。

### 技能与配置 API

```bash
curl http://localhost:8000/api/skills
```

```bash
curl -X POST http://localhost:8000/api/skills \
  -H 'Content-Type: application/json' \
  -d '{"name":"demo","content":"# demo\n技能说明"}'
```

```bash
curl -X POST http://localhost:8000/api/skills/reload
```

```bash
curl http://localhost:8000/api/config
```

```bash
curl -X POST http://localhost:8000/api/config \
  -H 'Content-Type: application/json' \
  -d '{"base_url":"https://example.com/v1","model":"qwen-max","api_key":"sk-..."}'
```

`POST /api/config` 会写入优先级最高的现有 `.env`；如果不存在，则写入 `config/.env` 并尽量设置权限为 `0600`。

### Token 与看板 API

```bash
curl http://localhost:8000/api/token-usage
```

```bash
curl 'http://localhost:8000/api/dashboard/summary?range=30d'
curl 'http://localhost:8000/api/dashboard/sessions?range=30d&sort=total_tokens&limit=50'
curl http://localhost:8000/api/dashboard/sessions/<session_id>
curl 'http://localhost:8000/api/dashboard/tools?range=7d'
curl 'http://localhost:8000/api/dashboard/word-cloud?scope=user&limit=120'
curl 'http://localhost:8000/api/dashboard/timeseries?metric=tokens&range=30d'
```

支持的常用范围：`all`、`today`、`7d`、`30d`、`90d`，也支持类似 `14d` 的天数格式。

### 分支 API

创建分支：

```bash
curl -X POST http://localhost:8000/api/sessions/<session_id>/branch \
  -H 'Content-Type: application/json' \
  -d '{"branch_point_node_id":"<node_id>"}'
```

切换活跃路径：

```bash
curl -X POST http://localhost:8000/api/sessions/<session_id>/switch \
  -H 'Content-Type: application/json' \
  -d '{"target_node_id":"<node_id>"}'
```

获取树摘要：

```bash
curl http://localhost:8000/api/sessions/<session_id>/tree
```

删除分支：

```bash
curl -X DELETE http://localhost:8000/api/sessions/<session_id>/branch/<node_id>
```

## 技能扩展

添加技能有三种方式：

1. 在 `skills/<skill_name>/` 下创建 `<skill_name>.md` 或 `<skill_name>.skill`。
2. 使用 CLI：`/add-skill <name> [内容]`。
3. 使用 Web 侧边栏或 `POST /api/skills`。

用户输入包含 `调用 <技能名> skill ...` 时，系统会加载对应技能内容并注入模型上下文。

## 命令执行协议

Agent 通过 `Agent.md` 约束模型输出协议：

```text
[命令] ls -la
[完成] 任务已完成
```

处理规则：

- `[命令]` 优先于 `[完成]`，避免同一回复中同时出现时跳过命令执行。
- 命令结果会以 `[执行完成]` 写回上下文，模型继续下一轮。
- 命令失败会统计连续失败次数，达到上限后写入 `[执行中止]` 并停止自动重试。
- 交互式命令和危险命令会被拦截。
- 命令执行工作目录固定为 `GENERATED_FILES_DIR`，默认 `files/`。

## 测试

运行 Python 测试：

```bash
pytest -q test
```

运行 React 单元测试：

```bash
npm --prefix web-react run test
```

当前测试覆盖重点包括：

- 分支引擎创建、切换、删除、属性测试。
- 会话持久化、复制和旧格式迁移。
- Web API：会话、聊天并发、分支、删除、看板。
- Orchestrator async/sync 兼容。
- 前端分支树布局、边渲染、上下文高亮和模块导入。

## 安全与边界

- API Key 不会在 Web API 中明文返回。
- 生成文件只允许写入 `GENERATED_FILES_DIR`，并通过安全路径检查提供访问。
- `/generated/{filename}` 和 `/files/{filename}` 会拒绝目录穿越。
- 静态资源缓存默认关闭，适合开发环境；生产部署时可按需调整缓存策略。
- Token 统计为本地估算，不等同于模型服务返回的真实计费 usage。

## 后续方向

- 保存模型服务返回的真实 usage 与耗时，替代或补充本地估算。
- 为后台看板补充模型调用耗时、轮次、上下文消息数等更细粒度指标。
- 增加认证或访问控制，避免 Web API 暴露在不可信网络。
- 扩展技能市场/技能模板和更多工具处理器。
- 增加生产环境缓存、日志和可观测性配置。
