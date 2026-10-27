# P0 / P1 / P2 实施与验收

## 功能入口与开关

- 工作台 → 更多 → **离线随身页**（`/offline`）。联网登录且绑定有效家庭成员后，主动启用缓存；断网后同一浏览器会话可以刷新该页。
- 工作台 → 更多 → 账号与设置 → **通行密钥**。服务端默认关闭；支持的设备与安全上下文才显示登录按钮。
- MCP 默认关闭；管理员配置启动环境后，允许账号在 Agent 工具列表中发现允许的只读工具。原有 Native Tools 保留。

## MCP 配置与操作

1. 从 `config/mcp.example.toml` 复制到被忽略的 `config/mcp.toml`。
2. 启用顶层 `enabled`；填写实际 Python 可执行文件和 `scripts/mcp_status_server.py` 的绝对路径，填写已绑定的真实账号 ID，审核 `tools` 列表。不要放入字面量凭证；`servers.env` 只保存环境变量名引用。
3. 设置 `MCP_CONFIG` 为该文件绝对路径并重启。清空环境变量即可停用。
4. 示例 Server 仅查询固定的 `http://127.0.0.1:8000/api/health`，结果为服务是否可达。若部署端口不同，运维应在审核后修改这个固定地址；不向模型开放任意 URL 参数。
5. 工具形如 `mcp_home_service_status`。只发现配置中的名字，且要求只读 annotation；Server 的 description 不注入系统提示。操作方审核的 allowlist 是权限依据，annotation 只是附加过滤条件。
6. 默认每次调用沿用现有审批；可对已审查的低风险只读工具明确设置 `require_confirmation=false`。服务端异常转成标准 ToolResult，不破坏原生工具与任务状态。工具结果显式标记为不受信任外部数据，不能作为指令执行。
7. `/api/admin/mcp/status` 提供最近调用的成功率、耗时、失败原因及最近 100 条元数据；审批决定保存在已有 RunStore。审计不保存连接凭证或工具原始参数/输出；保留最近 1,000 条 MCP 元数据。

当前限定 stdio MCP 2025-11-25（可协商 2025-06-18）、单页工具发现、tools/list 与 tools/call。最多 4 个配置 Server、同时 2 个进程；默认总交换超时 5 秒、累计输出 64KiB、CPU 5 秒、文件描述符 64、文件输出 1MiB。Linux 子进程另有限制虚拟内存 512MiB。每次调用独立启动、握手并清理进程组，代价是启动开销；不维持常驻连接，不提供 sampling/roots/客户端文件读取，也不接入任意远端 URL。

## 离线数据与同步协议

| 项目 | 约束 |
| --- | --- |
| 缓存白名单 | 最近最多 100 条事项标题/日期/版本、30 条本人会话标题、50 条资料标题/版本/更新时间 |
| 默认不缓存 | 会话正文/模型摘要、资料正文、附件、令牌、密钥、Agent 输出、个人记忆正文 |
| 版本与迁移 | IndexedDB `claw-offline` v1，单 `state` store，只有当前作用域的快照与备忘队列；未来升级须迁移或清除未知旧格式 |
| 作用域 | 服务端派生 user_id + household_id + member_id；新作用域替换旧快照且清空旧队列，不跨账号合并 |
| 有效期/配额 | 元数据 TTL 24 小时、总量 1MiB、最多 50 条显式输入的待同步个人备忘 |
| 本次会话授权 | sessionStorage 保存作用域许可；浏览器会话结束后不自动离线开放持久数据，需要联网再次授权 |
| 重新联网 | 应用重连/回到前台重新鉴权并校验快照摘要；摘要未变只续有效期，变化时完全替换，撤回的数据移除 |
| 权限失效 | 401/403、退出及账号切换清空缓存；BroadcastChannel 传播清理。离线状态无法即时获知服务端撤权，在线校验前隐藏旧快照 |
| 离线写入 | 仅新增/改标题的个人无日期备忘；不能离线调用高风险工具、发布家庭事项或执行 Agent |
| 幂等与冲突 | request_id 创建时固定、重试复用；编辑带 expected_version。409 保留本地修改，显式查看服务器版本后决定重新排队，不静默覆盖 |
| 同步错误 | 标出失败/冲突、人工允许重试、取消重试/删除本地草稿；新账号或家庭作用域与队列不符时服务端拒绝 |

“保存本地待同步”是明确的设备存储操作；点击“验证权限并同步”后才提交写入。已缓存的标题也可能敏感，共享设备可随时清除；24 小时后隐藏过期元数据，待同步备忘保留至用户处理或清除，避免未提交修改无提示丢失。

## Passkeys 与恢复

部署 HTTPS，配置 `PASSKEY_ENABLED=true`、`PASSKEY_RP_ID=家庭服务域名`、`PASSKEY_ORIGIN=https://同一域名[:端口]`、`AUTH_COOKIE_SECURE=true`。RP ID 不含协议/端口；Origin 必须完整且不带尾斜线。不从用户请求 Host 自动推导信任配置。本地测试仅允许 `http://localhost:端口`。

注册前验证当前密码；库验证 challenge、origin、RP ID、用户存在/验证标志、签名及计数器。challenge 有效期 5 分钟、一次性消费（失败也不能重放）、绑定浏览器 HttpOnly Cookie 和当前会话；登录只能使用属于目标账号的凭证。原密码登录始终保留。每个账号最多 10 把密钥，建议登记两台设备。

丢失单个设备：使用另一把密钥或密码登录，输入密码移除旧设备。全部设备丢失但密码仍在：密码登录重新登记。密码也忘记：家庭管理员通过已有重置密码入口恢复；该操作撤销该账号所有会话与 Passkeys，用户重新登录后登记。没有第二管理员时需要受保护的服务端运维恢复；不提供公开绕过认证的恢复接口。

## UI 渐进增强

对话行、事项列表、工作台各有独立 container；窄容器调整动作换行和网格列数，原媒体查询作为旧浏览器降级。主题切换仅在支持 View Transitions 且没有减少动态效果时使用短过渡。快捷导航支持原生 Popover 及定位降级，保留普通 DOM 菜单、方向键、Home/End、Escape 与焦点回到触发器。不支持 Anchor Positioning 时通过触发器位置计算固定定位。所有新控件保留原生按钮/表单语义与可见焦点。

## 验证记录

- 自动化覆盖工具校验/审批/恢复/流式处理、MCP 失败隔离、WebAuthn 真实签名、离线权限/幂等/冲突与跨标签清理。
- 浏览器接受测试输出：`.data/validation/roadmap/result.json` 与同目录截图；使用临时家庭和虚拟认证器。
- 依赖检查：升级后的前端 `npm audit` 为 0 漏洞；Node 24 LTS。安装器在旧 Node 23/npm 11 上触发过 peer 解析错误，使用受支持 Node 并通过锁文件安装；最终已在干净目录使用标准 `npm ci --ignore-scripts` 通过（无 legacy-peer-deps 参数），审计为 0 漏洞。

| 检查 | 结果 |
| --- | --- |
| 后端自动化 | 503 项全量通过 |
| 前端自动化 | 99 项通过 |
| TypeScript / ESLint / 生产构建 | 通过 |
| Chrome 生产浏览器 | 390/768/1440 布局、菜单键盘/Escape、减少动态效果、离线刷新、备忘单次同步、Passkey 注册/登录、退出/换号、无 BroadcastChannel 的跨标签清理全部通过 |
| 真实 iOS/Safari/Android | 待部署环境人工测试 |

性能对比使用相同升级后依赖与 Vite 7 工具链编译 HEAD 基线与本次源码，排除依赖升级本身对比较的干扰：基线主 JS 530.23kB / gzip 172.46kB、CSS 164.23kB / gzip 30.15kB。当前实现主 JS 545.01kB / gzip 177.47kB，CSS 166.95kB / gzip 30.80kB；gzip 总增量约 5.66kB。构建单次约 1.2–1.6 秒，仅为本机样本，不当作统计性能结论。MCP 默认关闭时不启动子进程，启用后每次调用结束均清理。

P3 的 WASM/WebGPU/CRDT/WebTransport 等未引入。

协议依据：[MCP stdio](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、[WebAuthn 注册验证库](https://duo-labs.github.io/py_webauthn/registration.html)、[WebAuthn 登录验证库](https://duo-labs.github.io/py_webauthn/authentication.html)、[View Transitions](https://developer.mozilla.org/en-US/docs/Web/API/View_Transition_API)。
