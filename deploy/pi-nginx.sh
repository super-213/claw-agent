#!/usr/bin/env bash
# Install static assets and update the Nginx site only when its config changes.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SOURCE_CONF="$APP_DIR/deploy/claw-agent.conf"
SITE_CONF="/etc/nginx/sites-available/claw-agent"
SITE_LINK="/etc/nginx/sites-enabled/claw-agent"
DEFAULT_LINK="/etc/nginx/sites-enabled/default"
WEB_ROOT="/var/www/claw-agent"

if [[ "$(id -u)" -eq 0 ]]; then
  echo "请用普通用户运行；脚本会按需调用 sudo。" >&2
  exit 1
fi
if [[ ! -f "$SOURCE_CONF" || ! -f "$APP_DIR/web-react/dist/index.html" ]]; then
  echo "缺少 Nginx 配置或前端构建产物。" >&2
  exit 1
fi
for command in sudo apt-get systemctl cmp; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "缺少命令：$command" >&2
    exit 1
  fi
done

if ! command -v nginx >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y nginx
fi
if [[ ! -d /etc/nginx/sites-available || ! -d /etc/nginx/sites-enabled ]]; then
  echo "未找到 Debian 风格的 Nginx sites-available/sites-enabled 目录。" >&2
  exit 1
fi
for site in /etc/nginx/sites-enabled/*; do
  [[ -e "$site" || -L "$site" ]] || continue
  case "$(basename "$site")" in
    default|claw-agent) ;;
    *) echo "已有其他站点：${site}。请先检查 Nginx 配置。" >&2; exit 1 ;;
  esac
done
if [[ -e "$SITE_LINK" && ! -L "$SITE_LINK" ]]; then
  echo "已有非符号链接的 Claw Agent 站点：$SITE_LINK" >&2
  exit 1
fi
if [[ -L "$SITE_LINK" && "$(readlink -f "$SITE_LINK")" != "$SITE_CONF" ]]; then
  echo "Claw Agent 站点链接指向其他配置：$SITE_LINK" >&2
  exit 1
fi
if [[ -e "$DEFAULT_LINK" && ! -L "$DEFAULT_LINK" ]]; then
  echo "已有非符号链接的 default 站点：$DEFAULT_LINK" >&2
  exit 1
fi

config_changed=false
site_link_changed=false
default_removed=false
default_target=""
backup_conf=""
if [[ ! -f "$SITE_CONF" ]] || ! sudo cmp -s "$SOURCE_CONF" "$SITE_CONF"; then
  config_changed=true
  if [[ -f "$SITE_CONF" ]]; then
    backup_conf="${SITE_CONF}.backup.$$"
    sudo cp -p "$SITE_CONF" "$backup_conf"
  fi
  sudo install -m 644 "$SOURCE_CONF" "$SITE_CONF"
  echo "Nginx 配置已更新。"
else
  echo "Nginx 配置内容未变化。"
fi

if [[ -L "$DEFAULT_LINK" ]]; then
  default_target="$(readlink "$DEFAULT_LINK")"
  sudo unlink "$DEFAULT_LINK"
  default_removed=true
fi
if [[ ! -L "$SITE_LINK" ]]; then
  sudo ln -s "$SITE_CONF" "$SITE_LINK"
  site_link_changed=true
fi

restore_config() {
  if [[ -n "$backup_conf" ]]; then
    sudo cp -p "$backup_conf" "$SITE_CONF"
    sudo rm -f "$backup_conf"
  elif [[ "$config_changed" == true ]]; then
    sudo rm -f "$SITE_CONF"
  fi
  if [[ "$site_link_changed" == true ]]; then
    sudo unlink "$SITE_LINK"
  fi
  if [[ "$default_removed" == true ]]; then
    sudo ln -s "$default_target" "$DEFAULT_LINK"
  fi
}

if [[ "$config_changed" == true || "$site_link_changed" == true || "$default_removed" == true ]]; then
  if ! sudo nginx -t; then
    echo "Nginx 配置检查失败，恢复原配置…" >&2
    restore_config
    exit 1
  fi
  if ! sudo systemctl enable nginx; then
    echo "无法启用 Nginx，恢复原配置…" >&2
    restore_config
    exit 1
  fi
  if systemctl is-active --quiet nginx; then
    if ! sudo systemctl reload nginx; then
      echo "Nginx 重载失败，恢复原配置…" >&2
      restore_config
      sudo systemctl reload nginx || true
      exit 1
    fi
  elif ! sudo systemctl start nginx; then
    echo "Nginx 启动失败，恢复原配置…" >&2
    restore_config
    exit 1
  fi
  if [[ -n "$backup_conf" ]]; then
    sudo rm -f "$backup_conf"
  fi
else
  if ! systemctl is-active --quiet nginx; then
    sudo systemctl enable --now nginx
  fi
  echo "Nginx 配置无需更新。"
fi

echo "同步前端静态文件…"
sudo install -d -m 755 "$WEB_ROOT"
sudo cp -R "$APP_DIR/web-react/dist/." "$WEB_ROOT/"
sudo chmod -R a+rX "$WEB_ROOT"
