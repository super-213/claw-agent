# Swift 原生前端 App 需求文档

## 1. 结论

可以做到。

当前系统后端已经以 FastAPI 提供完整业务 API，React 前端本质上是一个 API 消费端。可以用 Swift 编写一个原生 iOS App 作为新的前端，App 只负责界面、状态管理、文件选择、流式响应展示和本地配置，不承载 Agent 编排、会话持久化、模型调用、用户管理等后端职责。

推荐路线是：保留现有 FastAPI 后端不变，新增一个 SwiftUI iOS App，通过 `URLSession` 访问 `/api/*`、`/generated/*`、`/files/*`。首期不使用 WebView，不复用 React 页面，而是按现有苹果风视觉目标重写原生界面。

## 2. 背景

当前 React 前端已经按 `frontend-apple-style-redesign-requirements.md` 调整为接近 Apple 软件的视觉风格，但移动端仍然需要用户打开浏览器访问前端。浏览器访问在移动端存在几个天然问题：

- 入口不够像独立应用，需要记住地址或添加到主屏幕。
- Safari 地址栏、刷新、缩放和键盘行为会干扰沉浸式聊天体验。
- 文件选择、分享、通知、会话切换等操作不如原生 App 顺手。
- 局域网访问后端时，普通用户需要理解 IP、端口和前端代理。
- PWA 可以改善一部分问题，但在登录态、通知、文件、后台行为和原生质感上仍有限制。

因此新增 Swift 原生 App 的目标是让移动端用户直接打开 App 使用同一套后端能力，获得更稳定的触控体验和系统级入口。

## 3. 产品定位

Swift App 是 Claw Agent 的原生移动前端。

它不是新的后端，不保存权威业务数据，不直接调用模型 API，不执行命令，不管理本地 Agent 文件。它只通过现有后端 API 完成：

- 登录和用户身份识别；
- 会话列表、会话详情、分支树；
- 聊天消息发送和流式响应展示；
- 图片、附件上传与展示；
- 技能、模型配置、用户管理和共享设置；
- Dashboard 和家庭事务数据展示；
- 本地 App 设置，例如后端地址、主题、登录保存策略。

## 4. 总体目标

### 4.1 核心目标

- 提供 iPhone 优先的原生 SwiftUI 前端，后续自然扩展 iPad。
- 直接访问现有 FastAPI 后端，尽量不改后端 API。
- 覆盖 React 前端的核心业务能力，优先保证聊天、会话、分支树和登录完整可用。
- 延续苹果风视觉方向，使用系统导航、列表、表单、sheet、toolbar、material 和 SF Symbols。
- 支持局域网后端地址配置，例如 `http://192.168.1.10:8000`。
- 支持 NDJSON 流式响应，消息逐步展示，而不是等待一次性完成。
- 支持图片和文件上传，保留后端 25MB 限制和元数据结构。
- 支持登录态持久化，用户重新打开 App 后可继续使用。

### 4.2 体验目标

- 用户打开 App 后直接进入最近会话或登录页。
- 聊天输入、附件、发送、流式输出和错误恢复都符合 iOS 使用习惯。
- 会话列表和分支树在小屏幕上通过导航层级或 sheet 展示，不挤压主聊天。
- 管理类页面保留完整能力，但首期可降低视觉优先级。
- 网络失败、后端未启动、未登录、权限不足等状态必须有清楚提示。

## 5. 非目标

首期不包含：

- 不重写 FastAPI 后端；
- 不把模型 API Key 放入 iOS App 直接调用模型服务；
- 不在 App 内执行 shell 命令；
- 不在 App 内保存权威会话 JSON；
- 不用 WebView 简单包一层现有 React 页面作为最终方案；
- 不引入复杂离线编辑和本地同步冲突处理；
- 不首期发布 App Store，先面向本地安装、TestFlight 或企业/个人签名；
- 不首期实现 APNs 原生推送，除非后端新增 APNs 支持。

## 6. 目标平台

### 6.1 首期平台

- iOS 17 及以上；
- iPhone 作为主目标；
- iPad 以自适应布局兼容，但首期不要求完整桌面级多栏体验。

### 6.2 后续平台

- iPadOS：补齐三栏工作台、外接键盘快捷键、拖拽附件；
- macOS：可用 SwiftUI 复用大部分代码，但不作为首期目标；
- visionOS：不纳入规划。

## 7. 推荐技术方案

### 7.1 App 架构

推荐采用 SwiftUI + MVVM + Service 层：

```text
Swift App
├── App
│   ├── ClawAgentApp
│   ├── AppRouter
│   └── AppEnvironment
├── Core
│   ├── APIClient
│   ├── AuthSession
│   ├── Models
│   ├── StreamParser
│   └── KeychainStore
├── Features
│   ├── Auth
│   ├── Chat
│   ├── Sessions
│   ├── BranchTree
│   ├── Skills
│   ├── Settings
│   ├── Users
│   ├── Dashboard
│   └── Home
└── SharedUI
    ├── Buttons
    ├── EmptyStates
    ├── ErrorViews
    ├── MarkdownView
    └── LoadingViews
```

### 7.2 技术选型

- UI：SwiftUI。
- 网络：`URLSession`，使用 async/await。
- JSON：`Codable`，对后端宽松字段使用可选字段或 `AnyCodable` 风格结构。
- 流式响应：`URLSession.bytes(for:)` 读取 NDJSON，每行解析为 `ChatStreamEvent`。
- 登录态：优先使用后端 Cookie，App 端通过自定义 `URLSessionConfiguration` 和 `HTTPCookieStorage` 保持。
- 敏感本地配置：Keychain 保存后端地址、登录偏好和必要 token/cookie 辅助信息。
- 图片选择：`PhotosPicker`。
- 文件选择：`UIDocumentPickerViewController` 的 SwiftUI wrapper。
- Markdown：首期可用 `AttributedString(markdown:)` 处理基础 Markdown，复杂代码块和表格后续引入更强 Markdown 渲染组件。
- 图表：Swift Charts。
- 分支树：首期使用 SwiftUI Canvas 或自定义 `Shape` 绘制节点和连线。

## 8. 后端依赖和边界

### 8.1 后端保持职责

后端继续负责：

- 用户、角色、登录态、权限判断；
- 会话创建、删除、复制、共享、分支；
- 会话消息持久化；
- Agent 编排、模型流式输出和命令执行；
- 技能文件读取和热重载；
- 模型配置保存；
- Dashboard 数据聚合；
- 家庭事务数据和 Web Push 相关接口。

### 8.2 App 负责职责

App 负责：

- 渲染原生界面；
- 调用 API；
- 处理输入、附件、图片选择；
- 解析流式事件并增量更新消息；
- 管理本地 UI 状态；
- 保存后端地址和登录状态；
- 将 `/generated/*`、`/files/*` 等相对资源 URL 转换为完整后端 URL；
- 显示错误、权限、空状态和加载状态。

### 8.3 需要确认的后端约束

- 后端需要能被手机访问，监听地址应为 `0.0.0.0`，不能只监听 `127.0.0.1`。
- 手机和后端设备需要在同一网络，或后端需要部署到可访问服务器。
- 如果使用 HTTP 局域网地址，iOS 需要配置 ATS 例外。推荐长期改为 HTTPS。
- Cookie 登录态需要确认 `SameSite`、`Secure`、域名/IP 和过期策略在 App 请求中可稳定工作。
- 原生推送不能直接复用 Web Push。若要系统通知，需要后端新增 APNs 设备 token 注册和推送逻辑。

## 9. API 范围

### 9.1 认证 API

App 需要实现：

- `GET /api/auth/bootstrap-status`
- `GET /api/auth/usernames`
- `POST /api/auth/bootstrap-admin`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

验收要求：

- 首次无管理员时显示初始化管理员页面。
- 已有管理员时显示登录页。
- 登录成功后进入聊天工作台。
- 401 时清理本地登录态并回到登录页。
- `remember_me` 需要映射到 App 登录保存选项。

### 9.2 会话 API

App 需要实现：

- `GET /api/sessions`
- `POST /api/sessions`
- `GET /api/sessions/{session_id}`
- `DELETE /api/sessions/{session_id}`
- `POST /api/sessions/{session_id}/copy`
- `GET /api/sessions/{session_id}/share`
- `PATCH /api/sessions/{session_id}/share`

验收要求：

- 会话列表按更新时间展示。
- 可创建新会话、切换会话、删除会话、复制会话。
- 删除需要二次确认。
- 共享设置仅在有权限时显示。

### 9.3 聊天 API

App 需要实现：

- `POST /api/chat/uploads`
- `POST /api/chat`
- `POST /api/chat/stream`

优先使用 `POST /api/chat/stream`。

验收要求：

- 发送消息时立即显示用户消息和运行状态。
- 能解析 `step`、`model_start`、`model_delta`、`model_done`、`command_start`、`command_result`、`done`、`error`。
- `model_delta` 需要逐步拼接到当前助手消息。
- `command_result` 可折叠显示。
- `done` 后用后端返回的完整 messages 校准本地状态。
- 错误时保留已输入内容或提供重试。
- 上传文件使用 multipart form-data，字段名为 `files`。
- 上传数量和大小遵循后端限制。

### 9.4 分支 API

App 需要实现：

- `GET /api/sessions/{session_id}/tree`
- `POST /api/sessions/{session_id}/branch`
- `POST /api/sessions/{session_id}/switch`
- `DELETE /api/sessions/{session_id}/branch/{node_id}`

验收要求：

- 可从任意消息节点创建分支。
- 分支树能展示节点、父子关系、活跃路径和当前节点。
- 点击节点可切换分支。
- 删除非活跃分支需要确认。
- 小屏幕中分支树通过 sheet 或独立导航页打开。

### 9.5 技能和配置 API

App 需要实现：

- `GET /api/skills`
- `POST /api/skills/reload`
- `POST /api/skills`
- `GET /api/config`
- `POST /api/config`

验收要求：

- 技能列表可查看、刷新、新增。
- 技能可插入到聊天输入框。
- 模型配置可查看和更新。
- API Key 只显示后端返回的脱敏值，App 不显示明文旧值。

### 9.6 用户管理 API

管理员用户需要实现：

- `GET /api/users`
- `GET /api/admin/users`
- `POST /api/admin/users`
- `PATCH /api/admin/users/{user_id}`
- `DELETE /api/admin/users/{user_id}`
- `POST /api/admin/users/{user_id}/reset-password`

验收要求：

- 普通用户不显示管理员入口。
- 管理员可创建、编辑、禁用/删除用户和重置密码。
- 表单校验错误要显示后端返回 message 或 error。

### 9.7 Dashboard API

App P1 阶段实现：

- `GET /api/dashboard/summary`
- `GET /api/dashboard/sessions`
- `GET /api/dashboard/sessions/{session_id}`
- `GET /api/dashboard/tools`
- `GET /api/dashboard/word-cloud`
- `GET /api/dashboard/timeseries`
- `GET /api/dashboard/users`

验收要求：

- 首页展示关键 KPI。
- 支持 `all`、`30d`、`7d`、`today` 范围。
- 图表用 Swift Charts 或简化列表展示。
- 小屏幕优先保证可读性，不强行还原 Web 大屏图表。

### 9.8 家庭事务 API

App P1/P2 阶段实现：

- `GET /api/home/household`
- `PATCH /api/home/household`
- `GET /api/home/activity-log`
- `GET /api/home/inventory/expiring`
- `GET /api/home/inventory`
- `GET /api/home/inventory/{location}`
- `POST /api/home/inventory/{location}/items`
- `PATCH /api/home/inventory/{location}/items/{item_id}`
- `DELETE /api/home/inventory/{location}/items/{item_id}`
- `POST /api/home/inventory/{location}/items/{item_id}/consume`
- `POST /api/home/inventory/{location}/items/{item_id}/restore`
- `GET /api/home/reminders`
- `POST /api/home/reminders`
- `PATCH /api/home/reminders/{reminder_id}`
- `DELETE /api/home/reminders/{reminder_id}`
- `POST /api/home/reminders/{reminder_id}/complete`
- `POST /api/home/reminders/{reminder_id}/snooze`
- `POST /api/home/reminders/{reminder_id}/cancel`
- `GET /api/home/notifications`
- `POST /api/home/notifications/{notification_id}/read`
- `POST /api/home/notifications/read-all`

说明：

- Web Push 接口可暂不在原生 App 中接入。
- 若需要 iOS 系统通知，需要新增 APNs 后端能力，不能只靠现有 `/api/push/*`。

## 10. 页面和功能需求

### 10.1 启动和后端连接

首次启动流程：

1. 读取本地保存的后端地址。
2. 如果没有地址，进入后端连接设置页。
3. 用户输入后端地址，例如 `http://192.168.1.10:8000`。
4. App 调用 `GET /` 或 `GET /api/auth/bootstrap-status` 验证连接。
5. 连接成功后进入初始化管理员或登录流程。

连接设置页要求：

- 支持手动输入 IP/域名和端口。
- 显示最近使用过的后端地址。
- 提供连接测试按钮。
- 明确提示后端未启动、网络不可达、地址格式错误、证书错误。
- 支持后续在设置中切换后端地址。

### 10.2 登录和初始化管理员

页面要求：

- 使用 iOS 标准表单和安全输入框。
- 用户名支持从 `/api/auth/usernames` 加载建议。
- 支持记住登录。
- 首次管理员初始化时要求用户名、显示名、密码。
- 登录失败展示明确错误。

状态要求：

- App 启动时优先调用 `/api/auth/me` 验证登录态。
- 登录过期时回到登录页。
- 退出登录后清理 Cookie 和本地会话状态。

### 10.3 主导航

iPhone 推荐 Tab + NavigationStack：

- 聊天；
- Dashboard；
- 家庭；
- 设置。

聊天页内部包含会话列表入口、当前会话和分支树入口。管理员入口放在设置页中，不占主 Tab。

iPad 后续可升级为 NavigationSplitView：

- 左侧：会话列表；
- 中间：聊天；
- 右侧：分支树或详情。

### 10.4 聊天工作台

聊天页是首期核心。

顶部区域：

- 显示当前会话标题。
- 显示运行状态，例如空闲、准备中、流式输出、执行命令、保存中、失败。
- 提供会话列表按钮、分支树按钮、更多菜单。

消息区：

- 用户消息右侧气泡，系统蓝或浅蓝底。
- 助手消息左侧或全宽阅读块，适合长 Markdown。
- 过程事件默认折叠，可展开查看。
- 命令执行结果默认折叠，失败结果突出显示。
- 图片缩略图可点击预览。
- 附件显示文件名、类型和大小。
- 支持长按复制消息内容。
- 支持滚动到底部按钮。

输入区：

- 多行输入，支持中文输入法。
- 附件按钮打开图片或文件选择。
- 发送按钮在空文本且无附件时禁用。
- 发送中可显示停止或禁用状态，具体取决于后端是否支持取消。
- 发送失败后可重试。

### 10.5 会话列表

要求：

- 显示标题、更新时间、token 简要信息、共享状态。
- 支持下拉刷新。
- 支持搜索或本地过滤。
- 支持新建、复制、删除。
- 正在运行的会话显示状态。
- 空状态提供新建会话入口。

### 10.6 分支树

首期方案：

- 在 iPhone 上通过 full-screen sheet 或独立页面展示。
- 使用可缩放/可滚动画布展示节点和连线。
- 节点展示摘要、角色、活跃状态、子节点数量。
- 活跃路径使用系统蓝，非活跃节点降低透明度。
- 点击节点弹出操作：切换到该节点、从该节点创建分支、删除分支。

验收重点：

- 对小屏幕友好，不能把树挤在聊天页右侧。
- 大树可滚动，不允许节点重叠到不可操作。
- 当前节点进入页面后应自动定位到可见区域。

### 10.7 技能管理

要求：

- 技能列表显示名称、路径、大小、更新时间。
- 支持刷新技能。
- 支持新建技能，包含名称和内容。
- 支持从技能列表插入聊天输入框。

### 10.8 模型配置

要求：

- 显示当前 base URL、model、API Key 脱敏状态。
- 支持更新 base URL、model、API Key。
- API Key 输入为空时表示保留原值。
- 保存前进行基本表单校验。

### 10.9 用户管理

仅管理员可见。

要求：

- 用户列表展示用户名、显示名、角色、状态、创建时间、最近登录。
- 支持创建用户。
- 支持修改显示名、角色、状态。
- 支持重置密码。
- 支持删除或禁用用户。
- 危险操作必须二次确认。

### 10.10 Dashboard

首期可做简化版。

要求：

- 显示全局 KPI。
- 显示 token 趋势、角色分布、工具调用摘要。
- 显示会话排行。
- 支持时间范围切换。
- 支持进入单会话详情。

### 10.11 家庭事务

首期 P1/P2。

要求：

- 显示冰箱/库存列表。
- 支持新增、编辑、删除、消耗、恢复库存。
- 显示即将过期项目。
- 显示提醒和通知。
- 支持完成、稍后提醒、取消提醒。

## 11. 数据模型要求

Swift 模型需要兼容后端宽松字段。后端部分字段可能是可选或未来扩展，因此 App 不应因为未知字段解码失败。

核心模型：

- `User`
- `SessionSummary`
- `SessionDetail`
- `Message`
- `MessageMedia`
- `MessageUsage`
- `BranchTree`
- `BranchApiNode`
- `ChatStreamEvent`
- `Skill`
- `ModelConfig`
- `DashboardSummary`
- `HomeInventoryItem`
- `HomeReminder`
- `HomeNotification`

要求：

- 对 `role`、`status`、`scope` 等枚举保留 unknown case。
- 对消息中的扩展字段允许忽略。
- 日期字段先按 String 保存，UI 层统一格式化，避免后端格式细节导致解码失败。
- 相对 URL 字段在使用前统一通过 `APIClient.resolveURL(_:)` 转换。

## 12. 流式响应要求

`POST /api/chat/stream` 返回 `application/x-ndjson`。App 需要逐字节或逐行读取。

解析规则：

- 以换行切分事件。
- 空行跳过。
- 每行按 JSON 解码为 `ChatStreamEvent`。
- 单个 chunk 可能包含半行，需要缓存未完成内容。
- 解码失败不能直接导致 App 崩溃，应显示流式解析错误。
- `error` 事件或终止错误需要结束运行状态。
- `done` 事件为本轮完成标记。

UI 更新规则：

- `step` 更新运行状态。
- `model_delta` 拼接临时助手消息。
- `command_start` 创建命令执行条目。
- `command_result` 更新命令结果。
- `done` 使用完整 messages 覆盖本地临时消息。

## 13. 文件和图片要求

上传：

- 支持相册选择图片。
- 支持文件选择。
- 使用 multipart form-data，字段名固定为 `files`。
- 上传成功后得到 `media` 数组，再随聊天请求发送。

展示：

- 图片 URL 可能是 `/generated/uploads/...`，App 需要补全后端 base URL。
- 附件需要展示文件名、类型、大小。
- 图片点击后打开预览。
- 下载失败显示占位状态。

限制：

- 后端当前单文件限制为 25MB。
- 一次上传文件数量遵循后端 `MAX_UPLOAD_FILES`。

## 14. 安全要求

- App 不保存模型 API Key 明文，除非用户主动在模型配置页输入并提交给后端。
- 后端地址、登录保存策略和必要会话信息保存到 Keychain 或受保护存储。
- Cookie 不应打印到日志。
- 网络错误日志不得包含密码、API Key、Cookie。
- HTTP 局域网访问仅用于本地开发或可信网络。
- 生产或远程访问推荐 HTTPS。
- 后端暴露到公网前必须启用强密码和访问控制。

## 15. 网络和部署要求

### 15.1 本地局域网模式

后端启动要求：

```bash
WEB_HOST=0.0.0.0 PORT=8000 python web_app.py
```

手机访问地址示例：

```text
http://192.168.1.10:8000
```

要求：

- App 首次配置后端地址。
- 后端机器和手机在同一局域网。
- 防火墙允许 8000 端口。
- iOS ATS 需要为本地 HTTP 配置例外，或使用 HTTPS。

### 15.2 远程部署模式

推荐：

- 后端部署到固定域名；
- 使用 HTTPS；
- 反向代理处理 TLS；
- App 直接配置 `https://agent.example.com`；
- Cookie 设置适配 HTTPS。

## 16. 推送通知说明

现有后端提供 `/api/push/*` Web Push 接口，主要服务浏览器 Service Worker。iOS 原生 App 不能直接复用 Web Push 订阅作为 APNs 推送。

首期处理：

- App 内展示通知列表；
- App 打开时刷新通知；
- 不实现系统级推送。

如需原生推送，后续需要新增：

- App 申请 APNs device token；
- 后端新增 APNs token 注册接口；
- 后端保存用户和 device token 关系；
- 后端使用 APNs 发送通知；
- App 处理通知点击跳转。

## 17. 视觉和交互要求

整体风格延续苹果风改版目标：

- 使用系统背景色、material、分割线和系统蓝。
- 使用 SF Symbols 作为主要图标。
- 使用原生导航栏、toolbar、sheet、confirmation dialog。
- 不使用赛博风、霓虹发光、扫描线、强网格背景。
- 不使用过度卡片堆叠。
- 支持浅色和深色模式。
- 支持 Dynamic Type。
- 支持 VoiceOver 的基础 label。

iPhone 布局原则：

- 聊天是第一优先级。
- 会话列表和分支树通过导航或 sheet 进入。
- 输入区适配 safe area 和键盘。
- 触控目标不低于 44pt。

iPad 布局原则：

- 可使用三栏。
- 分支树可作为右侧 inspector。
- 支持横竖屏切换。

## 18. 可访问性要求

- 所有图标按钮提供可访问性 label。
- 表单错误可被 VoiceOver 读出。
- 颜色不能作为唯一状态表达。
- 支持系统字号。
- 支持系统深色模式。
- loading 和错误状态有明确文本。
- 长列表支持合理的滚动和焦点顺序。

## 19. 性能要求

- 会话列表加载 200 个会话时保持流畅。
- 单会话 1000 条消息可滚动，不明显卡顿。
- 流式输出 UI 更新需要节流，避免每个小 delta 都触发布局重算。
- 图片缩略图需要异步加载和缓存。
- Dashboard 图表数据加载不阻塞聊天页。
- App 冷启动到登录态检查完成目标小于 2 秒，网络慢时显示加载状态。

## 20. 错误处理要求

必须覆盖：

- 后端地址为空；
- 后端未启动；
- 网络超时；
- JSON 解码失败；
- NDJSON 流中断；
- 401 未登录；
- 403 无权限；
- 404 会话不存在；
- 409 首次管理员已存在或状态冲突；
- 413 文件过大；
- 500 后端错误。

错误展示原则：

- 用户可理解；
- 保留技术详情入口，便于调试；
- 提供重试或返回路径；
- 不吞掉后端返回的 `message`。

## 21. 分阶段实施计划

### 阶段 0：技术验证

目标：

- 验证 iOS App 能连接本机或局域网 FastAPI。
- 验证登录 Cookie 可保持。
- 验证 `/api/chat/stream` NDJSON 能实时解析。
- 验证 multipart 上传可用。

交付：

- 一个最小 SwiftUI Demo；
- 后端地址设置页；
- 登录页；
- 简单聊天页；
- 流式输出文本。

验收：

- 手机真机可访问后端；
- 登录后能发送消息；
- 能实时看到模型输出；
- App 重启后登录态按预期保持或重新登录。

### 阶段 1：聊天核心闭环

范围：

- 登录和管理员初始化；
- 会话列表；
- 会话详情；
- 新建、删除、复制会话；
- 聊天发送；
- 流式响应；
- 图片和附件上传；
- Markdown 基础渲染。

验收：

- 移动端可不依赖浏览器完成主要聊天工作流。
- 长对话可阅读。
- 发送中和错误状态清楚。

### 阶段 2：分支和管理能力

范围：

- 分支树展示；
- 创建分支；
- 切换分支；
- 删除分支；
- 技能列表、新建、重载、插入；
- 模型配置；
- 共享设置。

验收：

- React 前端中的核心 Agent 工作台能力在 App 中可用。
- 分支树在手机上可操作。

### 阶段 3：Dashboard、家庭事务和管理员

范围：

- Dashboard KPI 和会话排行；
- 单会话 Dashboard 详情；
- 家庭库存、提醒、通知；
- 用户管理。

验收：

- 管理和辅助页面达到可用水准。
- 管理员和普通用户权限入口正确。

### 阶段 4：iPad 优化和发布准备

范围：

- iPad 三栏布局；
- 深色模式细节；
- Dynamic Type 和 VoiceOver；
- 网络诊断页面；
- TestFlight 或签名分发；
- 应用图标和启动屏。

验收：

- iPad 横屏体验接近桌面工作台。
- 真机回归通过。
- 可交给实际用户安装测试。

## 22. 验收标准

### 22.1 P0 验收

- App 可配置后端地址。
- App 可完成首次管理员初始化。
- App 可登录、退出和恢复登录态。
- App 可加载会话列表。
- App 可创建会话。
- App 可发送聊天消息。
- App 可实时显示流式响应。
- App 可上传图片或附件。
- App 可查看历史消息。
- 后端关闭或网络失败时有明确提示。

### 22.2 P1 验收

- App 可创建、切换、删除分支。
- App 可查看并操作分支树。
- App 可管理技能和模型配置。
- App 可处理共享设置。
- App 可展示 Dashboard 基础数据。
- App 支持深色模式。

### 22.3 P2 验收

- App 支持家庭事务页面。
- App 支持管理员用户管理。
- App 支持 iPad 三栏布局。
- App 通过基础可访问性检查。
- App 完成 TestFlight 或本地签名分发流程。

## 23. 测试要求

单元测试：

- API URL 拼接；
- JSON 模型解码；
- NDJSON 分块解析；
- 登录态状态机；
- 分支树模型转换；
- 错误映射。

集成测试：

- 登录；
- 会话列表；
- 流式聊天；
- 文件上传；
- 分支切换；
- 配置保存。

真机测试：

- iPhone 小屏；
- iPhone 大屏；
- iPad 横屏；
- 局域网 HTTP；
- HTTPS；
- 后端重启；
- 网络切换；
- 长对话滚动；
- 中文输入法和软键盘。

## 24. 风险和取舍

### 24.1 风险

- NDJSON 流式解析比普通 REST 请求复杂，需要重点验证。
- Cookie 在原生 App 中的保存和过期策略需要实测。
- HTTP 局域网访问会受到 iOS ATS 限制。
- 分支树原生绘制有一定工作量。
- Markdown 表格、代码块和附件展示要达到 Web 同等效果需要迭代。
- 原生推送不能直接复用 Web Push。

### 24.2 取舍

- 首期优先做原生 SwiftUI，而不是 WebView 包壳。
- 首期优先聊天闭环，而不是完整复制所有 Dashboard 图表。
- 首期分支树可以先保证可用和清晰，再追求视觉精致。
- 首期通知只做 App 内通知列表，系统推送后续再加 APNs。

## 25. 待确认问题

- App 只做 iOS，还是需要同时做 macOS？
- 首期是否接受只覆盖聊天、会话、分支和设置，Dashboard/Home 后移？
- 后端运行位置是本机局域网，还是会部署到固定服务器？
- 是否需要支持 HTTPS 和远程访问？
- 是否需要 App Store/TestFlight 分发，还是只需要本地安装？
- 是否必须实现系统级推送通知？
- 产品名、图标和 Bundle ID 如何命名？

