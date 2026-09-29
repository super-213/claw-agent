#!/usr/bin/env bash
# Run after extracting claw-agent-pi.tar.gz on Raspberry Pi OS / Debian.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
APP_USER="$(id -un)"
SERVICE_NAME="claw-agent"

if [[ "$(id -u)" -eq 0 ]]; then
  echo "请用普通用户运行本脚本；需要时脚本会调用 sudo。" >&2
  exit 1
fi
if [[ "$APP_DIR" == *[[:space:]]* ]]; then
  echo "项目路径不能包含空格或换行：$APP_DIR" >&2
  exit 1
fi
if [[ ! -f "$APP_DIR/requirements.txt" || ! -f "$APP_DIR/web-react/dist/index.html" || ! -f "$APP_DIR/deploy/claw-agent.conf" || ! -f "$APP_DIR/deploy/pi-nginx.sh" ]]; then
  echo "压缩包不完整：缺少 Python 依赖清单、已构建的前端或 Nginx 部署文件。" >&2
  exit 1
fi
for command in sudo apt-get systemctl python3 sha256sum; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "缺少命令：${command}（本脚本适用于 Raspberry Pi OS / Debian）。" >&2
    exit 1
  fi
done

cd "$APP_DIR"

if [[ ! -x .venv/bin/python ]]; then
  if ! python3 -m venv .venv; then
    echo "安装 python3-venv 后重试…"
    sudo apt-get update
    sudo apt-get install -y python3-venv
    python3 -m venv .venv
  fi
fi

requirements_hash="$(sha256sum requirements.txt | cut -d ' ' -f 1)"
if [[ ! -f .venv/.requirements.sha256 ]] || [[ "$(cat .venv/.requirements.sha256)" != "$requirements_hash" ]]; then
  .venv/bin/python -m pip install -r requirements.txt
  printf '%s\n' "$requirements_hash" > .venv/.requirements.sha256
fi

has_api_key=false
for env_file in .env config/.env; do
  if [[ -f "$env_file" ]] && grep -Eq '^DASHSCOPE_API_KEY=.+$' "$env_file"; then
    has_api_key=true
    break
  fi
done
if [[ "$has_api_key" == false ]]; then
  if [[ ! -t 0 ]]; then
    echo "缺少 API Key。请在 $APP_DIR/.env 中设置 DASHSCOPE_API_KEY 后重试。" >&2
    exit 1
  fi
  read -r -s -p "首次运行，请输入 DASHSCOPE_API_KEY：" api_key
  printf '\n'
  if [[ -z "$api_key" || "$api_key" == *$'\n'* ]]; then
    echo "API Key 不能为空或包含换行。" >&2
    exit 1
  fi
  (umask 077; printf 'DASHSCOPE_API_KEY=%s\n' "$api_key" >> .env)
  chmod 600 .env
  unset api_key
fi

echo "配置 systemd 后端服务…"
sudo tee "/etc/systemd/system/$SERVICE_NAME.service" >/dev/null <<EOF
[Unit]
Description=Claw Agent API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=WEB_HOST=127.0.0.1
Environment=PORT=8000
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/web_app.py
Restart=on-failure
RestartSec=3
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME.service"
sudo systemctl restart "$SERVICE_NAME.service"

bash "$APP_DIR/deploy/pi-nginx.sh"

echo "检查服务…"
for attempt in 1 2 3 4 5; do
  if .venv/bin/python -c 'from urllib.request import urlopen; urlopen("http://127.0.0.1:8000/", timeout=2).close()' >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 5 ]]; then
    echo "后端尚未就绪。请检查：sudo journalctl -u claw-agent -n 80 --no-pager" >&2
    exit 1
  fi
  sleep 1
done
if ! .venv/bin/python -c 'from urllib.request import urlopen; urlopen("http://127.0.0.1/", timeout=3).close()' >/dev/null 2>&1; then
  echo "Nginx 80 端口检查失败。请检查：sudo journalctl -u nginx -n 80 --no-pager" >&2
  exit 1
fi

echo "部署完成。局域网地址：http://$(hostname -I | awk '{print $1}')/"
echo "后端状态：sudo systemctl status claw-agent"
echo "后端日志：sudo journalctl -u claw-agent -f"
