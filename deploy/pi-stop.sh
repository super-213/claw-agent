#!/usr/bin/env bash
set -euo pipefail

SITE_LINK="/etc/nginx/sites-enabled/claw-agent"

if [[ "$(id -u)" -eq 0 ]]; then
  echo "请用普通用户运行；脚本会按需调用 sudo。" >&2
  exit 1
fi

echo "停止并禁用 Claw Agent 后端…"
sudo systemctl disable --now claw-agent.service

if [[ -L "$SITE_LINK" ]]; then
  echo "停用 Claw Agent 的 Nginx 站点…"
  sudo unlink "$SITE_LINK"
  sudo nginx -t
  if systemctl is-active --quiet nginx; then
    sudo systemctl reload nginx
  fi
elif [[ -e "$SITE_LINK" ]]; then
  echo "Nginx 站点不是符号链接，未改动：$SITE_LINK" >&2
  exit 1
fi

echo "Claw Agent 已关闭。重新启动：bash ~/claw-agent/deploy/pi-start.sh"
