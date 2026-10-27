# 当前架构与安全基线（2026-10-27）

范围：本地可达 Git 历史、FastAPI/Agent Runtime、React/PWA。未访问远端托管后台，未使用真实账号调用模型或外部家庭设备。

## 核查结论与发布门槛

**代码实现已覆盖 P0/P1/P2；P0 的历史数据事故处置尚未关闭，不应将本次代码通过测试解释为可以直接公开发布。**

| 核查项 | 证据与处置 |
| --- | --- |
| 当前密钥/数据跟踪 | `git ls-files` 未发现 `.data` 或 `.webui_secret_key`；不是根据目录存在推断 |
| 历史敏感数据 | 本地可达 refs 包含 60 个会话数据 blob、17 个用户文件 blob（含密码哈希）、1 个旧 WebUI 密钥 blob |
| 当前凭证影响 | 旧密钥与本地一致，已轮换并设为 0600；当前 FastAPI 不引用该旧密钥。2 个本地账号密码哈希仍匹配历史版本，需停服后交互设置新密码 |
| 依赖跟踪 | 1,606 个 `node_modules` 文件已从索引移除，本地依赖保留；`.gitignore` 与提交前检查已补齐 |
| 配置 | 示例保留；实际 `.env`、`config/mcp.toml`、本地数据不提交。移除笼统 `*.json`/`docs/` 忽略，允许依赖锁、测试数据和文档正常版本管理 |
| HTTP 缓存 | `/api/`、`/files/`、`/generated/` 返回 no-store；保留既有 private,no-store。静态哈希资源可长期缓存，SW 仅预缓存公开应用文件 |
| 访问边界 | 管理员不再自动拥有其他成员私有会话读写/删除权限；只有会话所有者可改变共享。家庭事项和资料继续使用原服务授权；库存读写补齐有效成员绑定校验 |
| 本地持久化 | 用户密码与持久会话写入 0600；密码库损坏时拒绝开放初始化入口。TaskStore 保留锁、原子替换和版本校验 |
| 浏览器写入 | 在执行写操作前拒绝不匹配的 Origin；HTTPS 部署应设置 `AUTH_COOKIE_SECURE=true`，反向代理保留 Host（含端口）和正确协议 |
| 通知 | 原 ChatNotifications 已将订阅绑定到用户及会话哈希，发送前校验有效会话；退出撤销服务端订阅并清理本地通知。新增离线数据清理接入退出、401/403 与跨标签消息 |
| 依赖公告 | 升级 Vite 7、Vitest 4、PWA 插件 1、React Router 7 与受影响间接依赖；锁文件审计为 0 已报告漏洞。React/TS/FastAPI/PWA 主架构保留 |

报告不包含密钥、密码哈希、真实会话正文。历史路径/对象的详细指纹可由运维运行 `python3 scripts/audit_repository.py` 生成到受保护的本地文件。

## 身份与权限

- `UserStore` 管理账号、管理员角色、active/disabled/deleted 状态。Cookie 是随机不透明 token，服务端按 SHA-256 索引；密码使用 PBKDF2。非 remember 会话不落盘。
- 管理员负责账号及成员绑定；不会因为技术管理员角色而获得其他成员私有会话、个人事项或资料的访问权。管理员重置密码是显式的账号恢复操作，会撤销该账号会话与全部 Passkeys。
- `FamilyMemberService` 将账号明确绑定到当前家庭的成员 ID；家庭数据的授权由绑定与当前有效状态决定。部署模型仍为单家庭实例，新增离线作用域也包含家庭 ID，不能把这当成多家庭 SaaS 租户隔离已实现。
- 私有会话按 owner、共享范围和 read/write 权限授权；共享修改仅 owner。个人事项按参与者、资料按 owner/明确家庭共享授权；管理员不能直接读取其他成员的私人事项。
- Agent 执行者绑定实际登录账号，家庭/知识工具读取当前账号和分支执行上下文。审批由已有 run API 检查会话权限、参数摘要、一次性 token 和有效期；MCP 使用相同 ToolDefinition/Registry 与 run 审批、步骤审计。

## 运行架构

React/TypeScript SPA → FastAPI Cookie 鉴权 → 业务服务（事项/留言板/知识）及 AgentOrchestrator → 统一 ToolRegistry → 原生工具或受信任只读 MCP stdio 子进程。

已有 NDJSON 消费端处理跨 chunk、UTF-8、尾行、错误与无终止事件断线；RunStore/checkpoint、工具调用指纹和幂等账本支持审批后继续与中断恢复。新增 MCP 不复用历史工具结果来替代当前权限检查。

新增模块：

- `agent_runtime/mcp_adapter.py` / `mcp_launcher.py`：显式白名单、工具发现、完整 JSON Schema 校验、既有审批、无继承密钥环境、超时/输出/并发/CPU 限制、进程组清理、元数据审计。
- `services/offline_api.py` 与前端 `features/offline`：显式启用的元数据快照、作用域隔离的 IndexedDB、个人备忘同步与人工冲突处理。
- `services/passkeys.py` 与前端认证模块：密码确认后的注册、浏览器和会话绑定的一次性 challenge、WebAuthn 验证库、设备管理和密码后备。
- Container Queries 改善对话卡片、事项行与工作台；主题切换选择性使用 View Transitions；快捷菜单使用 Popover，保留原浏览器降级、方向键与 Escape。

## 历史事故处置（待运维完成）

1. 停服并备份受保护的数据；执行 `python3 scripts/security_recovery.py` 查看受影响账号数量，再执行 `python3 scripts/security_recovery.py --apply`，逐个交互设置新的至少 12 位密码。脚本不输出或保存明文密码，同时撤销持久会话/Passkeys。重启丢弃内存会话。
2. 对已使用过同一密码的其他服务分别更换密码；核查远端公开范围、日志、fork、镜像、发布包和备份。仅本地 Git 无法证明远端未被下载。
3. 在专门的镜像克隆中评审并执行历史移除：`.data/`、`.webui_secret_key`、根与前端 `node_modules/`。可使用 `git filter-repo --invert-paths --path .data/ --path .webui_secret_key --path node_modules/ --path web-react/node_modules/`。先验证所有分支/标签结果，再由仓库维护者协调受保护分支、远端强推与协作者重新克隆；本次未改写或强推共享历史。
4. 仓库维护者通知受影响协作者，申请托管平台清理缓存/不可达对象并记录完成证据。该步骤涉及对外消息，本次未代发。
5. 完成以上步骤后重新运行审计，再关闭路线图 P0 的“有效凭证/私人资料不再公开跟踪”验收项。

本仓库 `.githooks/pre-commit` 已在当前 checkout 通过 `core.hooksPath` 启用。新克隆运行 `git config core.hooksPath .githooks`；它检查索引中的已知敏感路径和生成目录，不是通用秘密扫描器。

## 验证与限制

可重复命令：

```sh
python3 scripts/audit_repository.py --check-index
python3 -m pytest test -q --ignore=test/browser --ignore=test/web-react
npm run web:typecheck
npm run web:lint
npm run web:test
npm run web:build
npm --prefix web-react audit
python3 scripts/validate_roadmap.py
```

使用 requirements.txt 的依赖环境与 Node 24 LTS；本次 Python 新依赖安装到临时目录，未改动全局 Python 环境。浏览器脚本使用临时家庭账号和 Chrome 虚拟认证器，不使用真实家庭资料。

测试结果和性能记录见 [实施与验收](claw-agent-web-upgrade.md)。仍需实际家庭设备上的 iOS/Safari、Android 和恢复演练；虚拟认证器不能替代硬件丢失/同步密钥平台的真实演练。

已知部署边界：服务端数据未新增静态加密；运维需要磁盘/备份加密和文件访问控制。MCP 只运行已审查的受信任程序，资源限制不等于操作系统安全沙箱；macOS 不保证虚拟内存硬上限。对真正不受信任的 Server 应另行使用隔离容器。
