# 树莓派安装 Cloudflare Tunnel 并绑定自定义域名

本教程适用于运行 Raspberry Pi OS 或 Debian、使用 systemd 的树莓派。先完成 [Claw Agent 部署](README.md)，再把自己的域名绑定到树莓派上的 Nginx。示例域名为 `agent.example.com`，操作时替换成你自己的域名。

采用 Cloudflare 控制台管理 Tunnel 的方式，`cloudflared` 直接安装在树莓派系统中。完成后可通过 `https://agent.example.com` 从外网访问，树莓派、项目服务和 Tunnel 都需要保持运行。

```text
浏览器 https://agent.example.com
              ↓
         Cloudflare
              ↓ Tunnel
     树莓派 cloudflared
              ↓ http://127.0.0.1:80
        树莓派 Nginx
          ├── React 前端
          └── /api 等请求 → FastAPI 127.0.0.1:8000
```

Tunnel 由树莓派主动连接 Cloudflare，无需公网 IP，也无需在路由器设置入站端口映射。参见 [Cloudflare Tunnel 原理](https://developers.cloudflare.com/tunnel/)。

## 一 准备账号和域名

需要准备：

- 一台可以联网、可以使用 `sudo` 的树莓派。
- 已在局域网正常运行的 Claw Agent。
- Cloudflare 账号和一个自己持有的域名。

在 [Cloudflare 控制台](https://dash.cloudflare.com/) 添加域名，按页面引导检查现有 DNS 记录，然后到域名注册商处把域名的 nameserver 改为 Cloudflare 提供的地址。等 Cloudflare 显示该域名为 Active 后再继续。已有网站或邮件时，应保留它们需要的 DNS 记录。

如果域名已经接入 Cloudflare，跳过这一步。详细操作见 [域名接入指南](https://developers.cloudflare.com/fundamentals/manage-domains/add-site/)。

## 二 确认项目在树莓派正常运行

先在当前电脑终端通过 SSH 登录树莓派：

```bash
ssh pi@192.168.1.100
```

把用户名和 IP 替换为实际值。登录后，本教程其余终端命令均在树莓派执行。检查服务和网页：

```bash
sudo systemctl status claw-agent nginx --no-pager
curl -I http://127.0.0.1:80/
```

两个服务应为 `active (running)`，网页通常返回 `200 OK`。先在局域网浏览器打开 `http://树莓派IP/`，完成首次管理员创建，并确认可以登录、聊天。

如果尚未启动项目：

```bash
bash ~/claw-agent/deploy/pi-start.sh
```

本项目 Nginx 已监听 80 端口并转发 API。Tunnel 的目标应填写 `http://127.0.0.1:80`；8000 端口仅提供后端 API，不能作为整个网站的入口。

## 三 安装 cloudflared

先查看系统架构：

```bash
dpkg --print-architecture
```

常见结果为 `arm64` 或 `armhf`。后续 APT 会选择匹配系统架构的软件包；如果在控制台选择安装平台，也要按这个结果选择 ARM64 或 ARM，不能仅依据树莓派硬件是否支持 64 位来判断。Cloudflare 提供 [ARM 和 ARM64 下载](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/)。

安装下载工具和证书：

```bash
sudo apt-get update
sudo apt-get install -y curl ca-certificates
```

添加 Cloudflare 官方签名密钥和稳定版软件源：

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update
sudo apt-get install -y cloudflared
```

这里使用官方 Debian 通用源 `any`。安装步骤对应 [Cloudflare 官方软件仓库](https://pkg.cloudflare.com/index.html)。

确认安装成功：

```bash
cloudflared --version
```

## 四 在控制台创建 Tunnel

在电脑浏览器操作：

1. 登录 [Cloudflare 控制台](https://dash.cloudflare.com/)。
2. 进入 **Networking → Tunnels**，选择 **Create Tunnel**。
3. 如果需要选择连接器类型，选择 **Cloudflared**。
4. 输入名称，例如 `raspberrypi-claw-agent`，创建 Tunnel。
5. 在安装环境中选择 Debian，以及树莓派对应的 ARM64 或 ARM 架构。
6. 找到安装连接器服务的命令，其中包含这个 Tunnel 的专属 Token。

官方当前入口和流程见 [创建 Tunnel](https://developers.cloudflare.com/tunnel/get-started/)。页面布局可能调整，可在控制台搜索 Tunnels 定位。

## 五 安装连接器服务并设置开机自启

在树莓派执行控制台提供的服务安装命令。前面已经安装了 `cloudflared`，此处只需服务安装部分。命令形式如下：

```bash
sudo cloudflared service install '替换为控制台提供的TunnelToken'
sudo systemctl enable --now cloudflared
```

保留引号，把引号中的说明文字替换为真实 Token。Token 是连接凭证，请勿提交到 Git、写入本教程或发送给其他人。此处不需要再执行 `cloudflared tunnel login` 或手动创建 credentials JSON。

检查连接器：

```bash
sudo systemctl status cloudflared --no-pager
sudo journalctl -u cloudflared -n 50 --no-pager
```

服务应为 `active (running)`。返回 Cloudflare 控制台，等待 Tunnel 显示 Healthy，再继续添加路由。服务安装命令见 [官方安装步骤](https://developers.cloudflare.com/tunnel/get-started/)。

## 六 绑定自己的网址

在该 Tunnel 页面进入 **Routes → Add route → Published application**，填写：

| 配置项 | 示例值 |
| --- | --- |
| Subdomain | `agent` |
| Domain | `example.com`，选择自己的域名 |
| Path | 留空，转发整个网站 |
| Service Type | `HTTP` |
| Service URL | `127.0.0.1:80` |

如果页面只有一个完整 Service URL 输入框，填写 `http://127.0.0.1:80`。这里的 `127.0.0.1` 指运行 cloudflared 的树莓派；本教程不适用于把 cloudflared 放在独立 Docker 容器中的情况。

保存路由。通过控制台添加公开应用路由时，Cloudflare 会自动创建指向 Tunnel 的 DNS 记录。若提示相同主机名已有 A、AAAA 或 CNAME 记录，应先核实其用途；也可以换一个未使用的子域名。参见 [Tunnel 路由与 DNS](https://developers.cloudflare.com/tunnel/concepts/routing/)。

外部访问使用 HTTPS，Tunnel 在本机通过 HTTP 访问 Nginx 即可。当前项目的 Nginx 不需要额外安装 HTTPS 证书，也不需要修改 `server_name _;`。前端和 API 使用同一域名，无需为此次部署修改前端 API 地址或添加 CORS 配置。

## 七 验证公网访问

等待路由和 DNS 生效后，在浏览器打开：

```text
https://agent.example.com
```

换成自己的域名。用手机关闭 Wi-Fi、通过移动数据访问一次，可以确认外网也能访问。应看到登录页，登录后测试一次聊天和流式输出。

也可以检查响应头：

```bash
curl -I https://agent.example.com/
```

登录状态检查可用下面的命令；没有登录 Cookie 时返回 `401` 是正常的：

```bash
curl -i https://agent.example.com/api/auth/me
```

如果额外配置了 Cloudflare Access，可能先收到 Access 登录跳转。

确认开机自启：

```bash
systemctl is-enabled cloudflared nginx claw-agent
```

三个服务应显示 `enabled`。之后树莓派重启，服务会随系统启动；外网访问恢复还取决于网络连接和 Tunnel 重连。

## 八 日常维护

查看、重启和跟踪日志：

```bash
sudo systemctl status cloudflared --no-pager
sudo systemctl restart cloudflared
sudo journalctl -u cloudflared -f
```

查看日志时按 `Ctrl+C` 退出，不会停止服务。

通过安装时添加的 APT 软件源更新：

```bash
sudo apt-get update
sudo apt-get install --only-upgrade cloudflared
sudo systemctl restart cloudflared
cloudflared --version
```

临时停止这个连接器：

```bash
sudo systemctl stop cloudflared
```

恢复连接器：

```bash
sudo systemctl start cloudflared
```

若 Tunnel 只有这一台连接器，停止它后公网域名无法再到达项目；局域网仍可通过树莓派 IP 访问。项目代码更新按 [部署指南](README.md) 操作，cloudflared 是独立系统服务，无需随每次项目更新重新安装。

## 九 常见问题

| 现象 | 排查方向 |
| --- | --- |
| `cloudflared: command not found` | 检查第三步安装是否成功，执行 `apt-cache policy cloudflared` 查看软件源是否提供候选版本。 |
| 显示 `cloudflared service is already installed` | 当前系统已有连接器。先查看服务状态，确认它连接的 Tunnel；正常运行时直接复用，不要重复安装或卸载。 |
| 错误 1033 | Cloudflare 找不到可用连接器。检查树莓派供电、cloudflared 服务、日志和 Tunnel 状态，并确认域名指向正确 Tunnel。 |
| Tunnel 提示无法到达源站并返回 502 | 确认 `curl -I http://127.0.0.1:80/` 正常，路由目标使用 HTTP 和 80 端口。 |
| 网页正常但 API 返回 502 | 检查 `sudo systemctl status claw-agent`，以及 `sudo journalctl -u claw-agent -n 80 --no-pager`。 |
| 域名无法解析或提示 DNS 记录冲突 | 检查域名接入状态、路由主机名和同名 DNS 记录。 |
| 页面显示后端信息，未显示前端 | 检查是否误将服务地址填写成了 8000，应使用 `http://127.0.0.1:80`。 |

错误含义和更详细的处理方法见 [Cloudflare 常见错误](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/troubleshoot-tunnels/common-errors/)。

如果日志持续提示 QUIC 握手超时或 TCP 连接超时，检查网络是否允许访问 Cloudflare 的出站 `7844` 端口：QUIC 使用 UDP，HTTP/2 使用 TCP。两种出站连接都被阻断时，Tunnel 无法工作。这里是树莓派向外连接，不是要求在路由器开放入站端口。参见 [连接故障排查](https://developers.cloudflare.com/tunnel/troubleshooting/)。
