# macOS 交互式部署与 Cloudflare Tunnel

在 Mac 上的项目根目录运行：

```bash
bash deploy/mac.sh
```

选择 `1` 首次部署 / 更新。脚本会询问网站端口（默认 `8080`）、API 端口（默认 `8000`）、是否仅使用 HTTPS 登录，以及缺少时的 DashScope API Key（输入不回显）。本地先调试时，HTTPS 登录选 `N`。先打开 `http://127.0.0.1:8080` 创建管理员并验证聊天，再连接公网。

需要已安装 [Homebrew](https://brew.sh)、已登录 Mac 桌面的普通用户和网络连接。支持 Apple Silicon 和 Intel Mac；使用系统 Bash 3.2 即可，不要用 `sudo bash`。脚本在安装缺少的 Homebrew 依赖前询问，使用 `python@3.12`、`node@24` 和 `nginx`，Python 包安装在项目 `.venv`，前端用 `npm ci` 和生产构建。已有 `.venv` 会复用（要求 Python 3.10+）；不要从 Linux 复制虚拟环境。

脚本使用独立 Nginx 配置，不修改 Homebrew 全局站点，不运行 `brew services start nginx`。后端和网站都仅监听 `127.0.0.1`，适合同机 cloudflared，不直接提供局域网访问。网站端口和后端端口必须不同且大于等于 1024。

```text
浏览器 https://agent.example.com
  → Cloudflare Tunnel → Mac cloudflared
  → http://127.0.0.1:8080（独立 Nginx）
      ├── React 生产网页 / PWA
      └── /api/、/files/、/generated/ → FastAPI 127.0.0.1:8000
```

## 后台运行和日常管理

部署会注册当前用户的两个 LaunchAgent：

- `~/Library/LaunchAgents/com.claw-agent.api.plist`
- `~/Library/LaunchAgents/com.claw-agent.web.plist`

它们在用户登录时自动启动，进程异常退出后由 launchd 重启；关闭终端不会停止服务。**这是登录后自动启动**，重启后尚未登录、注销、Mac 休眠或项目所在外接磁盘未挂载时不能保证访问。长期运行请在 macOS 系统设置中按需配置接通电源时防止自动睡眠。FileVault 开启时，重启后也需要先解锁磁盘。

每个用户管理一套部署。不要在部署后直接移动项目；如需移动，先在原目录停止、移除这两个 plist，再在新目录重新部署。路径支持空格，但不支持换行或 `$`。外接磁盘上的项目需确保登录时已挂载；项目尽量放在稳定的本机目录。

```bash
bash deploy/mac.sh status
bash deploy/mac.sh stop
bash deploy/mac.sh start
bash deploy/mac.sh restart
bash deploy/mac.sh logs
```

`stop` 只停止当前运行，下次登录仍会启动。永久取消自动启动时，先运行 `stop`，再删除上面两个 plist；保留项目数据即可随时重新部署。

配置保存在 `.data/deploy-mac/`，日志保存在 `log/mac/`。日志持续追加，需要自行按使用量清理或轮转。脚本不自动同步代码；更新代码后重新选择 `1`，重新安装需要的依赖并构建，配置检查通过后重启。更新前备份 `.env`、`.data`、`files`、`.webui_secret_key` 和自定义技能；脚本保留这些文件，但不会自动创建版本回滚备份。前端构建期间网页可能短暂不可用，依赖安装也会修改已有虚拟环境，建议在维护时段部署。

## 后续接入自己的公网域名

网站本地验证完成后，可随时选择菜单 `6`，或：

```bash
bash deploy/mac.sh tunnel
```

这个入口可选安装 `cloudflared` 并显示实际源站地址；不会创建 Tunnel、处理 Token 或修改已有连接器。Tunnel 独立于项目部署管理。

1. 准备 Cloudflare 账号，以及已接入该账号并激活的自有域名。
2. 在 [Cloudflare 控制台](https://dash.cloudflare.com/) 的 **Networking → Tunnels** 创建 Tunnel，例如 `mac-claw-agent`。
3. 选择 macOS 和本机架构（`uname -m`：`arm64` 是 Apple Silicon，`x86_64` 是 Intel），按控制台当前提供的安装和运行指令启动连接器。已通过菜单安装 cloudflared 时无需重复安装。
4. 等待 Tunnel 显示 **Healthy**，添加 **Routes → Add route → Published application**：

| 配置 | 示例 |
| --- | --- |
| 主机名 | `agent.example.com`，替换为自己的子域名 |
| Path | 留空 |
| 服务类型 | HTTP |
| 服务地址 | `127.0.0.1:8080`，使用部署时实际选择的网站端口 |

完整 Service URL 输入框填写 `http://127.0.0.1:8080`。**不要指向后端 8000**，它不托管 React 页面。上述地址要求 cloudflared 直接运行在这台 Mac 上，容器或其他机器需要单独配置网络。

5. 在浏览器打开 `https://agent.example.com`，用手机移动网络验证登录、上传、聊天流式输出。前端与 API 共用域名，无需另设前端 API 地址或 CORS。无需路由器入站端口映射。
6. 正式只通过公网 HTTPS 登录后，重新运行部署并在“启用 Secure Cookie”选择 `y`。此设置由 LaunchAgent 的环境变量控制，优先于 `.env`；之后本地 HTTP 登录可能不能保持会话，改用公网 HTTPS。部署前仍可通过本地页面完成初始化。

Token 是连接凭证，不要写入代码、文档或提交到 Git。连接器的常驻运行方式使用控制台提供的指令；macOS 官方支持登录时运行的 LaunchAgent 和开机运行的 LaunchDaemon。项目使用登录时启动，因此即使 Tunnel 开机即启动，也需要用户登录后网站才能恢复。已有其他 Tunnel 时请先确认用途，避免卸载或覆盖。

来源：[Cloudflare 创建 Tunnel 与公开应用路由](https://developers.cloudflare.com/tunnel/get-started/)、[macOS 服务运行方式](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/as-a-service/macos/)。

## 排查

- 公网 `502`：先检查 `bash deploy/mac.sh status`，再确认 Tunnel 的服务地址是本机网站端口和 `HTTP`。
- 错误 `1033`：检查连接器是否运行，以及控制台 Tunnel 是否 Healthy。
- 页面正常但 API 不通：查看 `log/mac/api.log` 和 `log/mac/nginx-error.log`。
- 登录异常：确认是否在启用 Secure Cookie 后仍访问 HTTP。启用 Passkey 时，另按 `config/.env.example` 配置固定公网域名的 `PASSKEY_RP_ID` 和 `PASSKEY_ORIGIN`。
- 端口已被占用：选择其他端口；脚本不会终止其他应用。改网站端口后，记得同步更新 Tunnel 源站地址。
- `Operation not permitted` 或启动失败：检查项目磁盘挂载及 macOS 对后台进程访问该目录的权限，详细原因在日志中。
