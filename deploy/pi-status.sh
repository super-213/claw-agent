#!/usr/bin/env bash
set -u

APP_DIR="$HOME/claw-agent"
SITE_LINK="/etc/nginx/sites-enabled/claw-agent"

echo "Home Agent 状态"
echo "项目目录：$APP_DIR"
if [[ -d "$APP_DIR" ]]; then
  echo "代码：已安装"
else
  echo "代码：未安装"
fi

for service in claw-agent nginx; do
  if command -v systemctl >/dev/null 2>&1; then
    active="$(systemctl is-active "$service" 2>/dev/null || true)"
    enabled="$(systemctl is-enabled "$service" 2>/dev/null || true)"
    echo "${service}：${active:-未知}（开机启动：${enabled:-未知}）"
  else
    echo "${service}：无法检查，缺少 systemctl"
  fi
done

if [[ -L "$SITE_LINK" ]]; then
  echo "Nginx 站点：已启用"
else
  echo "Nginx 站点：未启用"
fi
if [[ -f "$APP_DIR/deploy/claw-agent.conf" && -f /etc/nginx/sites-available/claw-agent ]]; then
  if cmp -s "$APP_DIR/deploy/claw-agent.conf" /etc/nginx/sites-available/claw-agent; then
    echo "Nginx 配置：最新"
  else
    echo "Nginx 配置：待更新"
  fi
fi

python3 - <<'PY'
from urllib.request import urlopen

for label, url in (
    ("后端 8000", "http://127.0.0.1:8000/"),
    ("网站 80", "http://127.0.0.1/"),
):
    try:
        with urlopen(url, timeout=2) as response:
            print(f"{label}：HTTP {response.status}")
    except Exception as exc:
        print(f"{label}：无法访问（{exc}）")
PY

if command -v hostname >/dev/null 2>&1; then
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [[ -n "$ip" ]]; then
    echo "局域网地址：http://$ip/"
  fi
fi
