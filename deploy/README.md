# 树莓派部署

本机在项目根目录运行 `./package-pi.sh`。脚本会在需要时安装前端依赖、构建 React，再生成
`release/claw-agent-pi.tar.gz`。压缩包包含后端源码、前端构建产物、技能和部署脚本；
不包含 `.env`、`.data`、`files`、日志、虚拟环境或 `node_modules`。

把压缩包传到树莓派（替换用户名和地址）：

```bash
scp release/claw-agent-pi.tar.gz pi@192.168.1.100:~/
```

在树莓派上执行：

```bash
tar -xzf ~/claw-agent-pi.tar.gz -C ~
cd ~/claw-agent
bash deploy/pi-start.sh
```

首次运行会在树莓派安装 Python 依赖和缺少的 Nginx/Python venv 系统包，
并要求输入 DashScope API Key；因此首次运行需要联网。后续更新使用下方的
`claw-agent-new` 流程。脚本保留树莓派已有的 `.env`、`.data` 和 `files`，
在 systemd 中启动后端，在 Nginx 的
80 端口提供前端并转发 API。已有其他 Nginx 站点时脚本会停止，避免覆盖。
Nginx 的源配置在 `deploy/claw-agent.conf`。`pi-nginx.sh` 比较它与
`/etc/nginx/sites-available/claw-agent` 的内容，仅在变化时更新配置并重载 Nginx；
`pi-start.sh` 会调用它，也可以单独运行 `bash deploy/pi-nginx.sh`。
配置变化时脚本会运行 `nginx -t`，校验失败则恢复原配置。

检查服务：

```bash
sudo systemctl status claw-agent nginx
sudo journalctl -u claw-agent -n 80 --no-pager
```

日常管理：

```bash
bash ~/claw-agent/deploy/pi-status.sh
bash ~/claw-agent/deploy/pi-stop.sh
bash ~/claw-agent/deploy/pi-start.sh
bash ~/claw-agent/deploy/pi-nginx.sh
```

更新时，在树莓派把新包解压到 `~/claw-agent-new`，再运行新版本里的更新脚本：

```bash
mkdir -p ~/claw-agent-new
tar -xzf ~/claw-agent-pi.tar.gz --strip-components=1 -C ~/claw-agent-new
bash ~/claw-agent-new/deploy/pi-update.sh
```

更新脚本将旧代码移到带时间戳的备份目录，把新代码移动到 `~/claw-agent`，
迁移 `.env`、`.data`、`files`、`.venv`、日志及已有自定义技能，随后运行
`pi-start.sh` 并检查服务。如果新版本启动失败，脚本会尝试恢复旧目录并重启旧服务。

注意：本机是 macOS 时，Python 虚拟环境不能打包后在树莓派 Linux ARM 上直接运行。
前端构建产物可以跨平台复制，Python 依赖必须在树莓派上安装。
