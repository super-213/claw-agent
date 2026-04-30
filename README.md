# Claw Agent - 重构版

基于分层架构和插件化设计的智能 Agent 系统。

## 架构特点

- **分层架构**：表现层、应用层、领域层、基础设施层清晰分离
- **责任链模式**：灵活的响应处理机制
- **插件化技能系统**：易于扩展的技能注册表
- **依赖注入**：便于测试和维护
- **安全增强**：命令执行黑名单、超时保护
- **Web UI + API**：内置 Web 界面与会话 API

## 目录结构

```
claw/
├── config/              # 配置管理
│   ├── settings.py      # ConfigManager
│   └── .env.example     # 环境变量示例
├── core/                # 核心业务逻辑
│   ├── orchestrator.py  # Agent 编排器
│   ├── conversation.py  # 对话管理
│   └── context.py       # 执行上下文
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
│   └── conversation_store.py # JSON 对话持久化
├── utils/               # 工具函数
│   └── parser.py        # 输入解析
├── web/                 # Web UI 静态资源
│   └── index.html       # Web UI 页面
├── web_app.py           # Web UI 服务入口
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
```

或创建 `.env` 文件（参考 `config/.env.example`）

### 3. 运行（CLI）

```bash
python main.py
```

CLI 内置技能管理命令：

- `/skills`：列出当前技能
- `/reload-skills`：手动重载技能目录
- `/add-skill <name> [内容]`：添加技能；不传内容时进入多行输入，单独输入 `.` 结束

### Web UI

```bash
python web_app.py
```

默认访问 `http://localhost:8000`。对话历史会保存在 `.data/conversations` 下的 JSON 文件中，可通过 `CONVERSATION_DIR` 修改路径。

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
curl -X POST http://localhost:8000/api/sessions \\
  -H 'Content-Type: application/json' \\
  -d '{\"title\":\"我的新对话\"}'
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
curl -X POST http://localhost:8000/api/skills \\
  -H 'Content-Type: application/json' \\
  -d '{\"name\":\"demo\",\"content\":\"# demo\\n技能说明\"}'
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

7. `POST /api/chat` 发送消息

```bash
curl -X POST http://localhost:8000/api/chat \\
  -H 'Content-Type: application/json' \\
  -d '{\"session_id\":\"d4b4b0...\",\"message\":\"你好\"}'
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
2. 创建 `{skill_name}.md` 文件
3. 系统会热重载并自动发现；也可以通过 CLI 的 `/add-skill` 或 Web 侧边栏的“添加技能”创建

### 添加新的响应处理器

1. 继承 `ResponseHandler` 基类
2. 实现 `can_handle()` 和 `process()` 方法
3. 在 `AgentOrchestrator` 中添加到责任链

## 安全特性

- 危险命令黑名单（rm -rf /、mkfs 等）
- 交互式命令拦截（vi、vim、python 等）
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

## 后续优化方向

- [ ] 添加日志系统
- [ ] 单元测试覆盖
- [ ] 异步执行支持
- [x] Web API 接口（会话/聊天）
- [x] 技能热重载
- [x] 对话历史持久化（JSON 文件）
