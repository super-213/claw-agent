#!/usr/bin/env bash
# Replace ~/claw-agent with ~/claw-agent-new while preserving runtime state.
set -Eeuo pipefail

OLD_DIR="$HOME/claw-agent"
NEW_DIR="$HOME/claw-agent-new"
BACKUP_DIR="$HOME/claw-agent-backup-$(date +%Y%m%d-%H%M%S)-$$"
OLD_RENAMED=false
NEW_INSTALLED=false
WAS_ACTIVE=false
MOVED_STATE=()

if [[ "$(id -u)" -eq 0 ]]; then
  echo "请用普通用户运行；脚本会按需调用 sudo。" >&2
  exit 1
fi
if [[ ! -d "$OLD_DIR" || ! -f "$OLD_DIR/web_app.py" ]]; then
  echo "找不到旧版本：$OLD_DIR" >&2
  exit 1
fi
if [[ ! -d "$NEW_DIR" || ! -f "$NEW_DIR/web_app.py" || ! -f "$NEW_DIR/web-react/dist/index.html" || ! -f "$NEW_DIR/deploy/pi-start.sh" || ! -f "$NEW_DIR/deploy/pi-nginx.sh" || ! -f "$NEW_DIR/deploy/claw-agent.conf" ]]; then
  echo "新版本目录不完整：$NEW_DIR" >&2
  exit 1
fi
if [[ -e "$BACKUP_DIR" ]]; then
  echo "备份目录已存在：$BACKUP_DIR" >&2
  exit 1
fi

STATE_PATHS=(.env .data files .venv log config/.env)
for relative in "${STATE_PATHS[@]}"; do
  if [[ -e "$OLD_DIR/$relative" && -e "$NEW_DIR/$relative" ]]; then
    echo "新旧目录都包含运行数据，拒绝覆盖：$relative" >&2
    exit 1
  fi
done

rollback() {
  local original_error="$1"
  trap - ERR
  set +e
  echo "更新失败，正在恢复旧版本…" >&2
  sudo systemctl stop claw-agent.service >/dev/null 2>&1
  if [[ "$NEW_INSTALLED" == true && -d "$OLD_DIR" ]]; then
    for relative in "${MOVED_STATE[@]}"; do
      if [[ -e "$OLD_DIR/$relative" ]]; then
        mkdir -p "$(dirname "$BACKUP_DIR/$relative")"
        mv "$OLD_DIR/$relative" "$BACKUP_DIR/$relative"
      fi
    done
    if [[ ! -e "$NEW_DIR" ]]; then
      mv "$OLD_DIR" "$NEW_DIR"
    fi
  fi
  if [[ "$OLD_RENAMED" == true && -d "$BACKUP_DIR" && ! -e "$OLD_DIR" ]]; then
    mv "$BACKUP_DIR" "$OLD_DIR"
  fi
  if [[ "$WAS_ACTIVE" == true ]]; then
    if [[ -f "$OLD_DIR/deploy/pi-start.sh" ]]; then
      bash "$OLD_DIR/deploy/pi-start.sh" || echo "旧服务自动重启失败，请检查 systemd 日志。" >&2
    else
      sudo systemctl restart claw-agent.service || echo "旧服务自动重启失败，请检查 systemd 日志。" >&2
    fi
  fi
  echo "旧版本目录：${OLD_DIR}；新版本目录：$NEW_DIR" >&2
  exit "$original_error"
}
trap 'rollback "$?"' ERR

if systemctl is-active --quiet claw-agent.service; then
  WAS_ACTIVE=true
fi
echo "停止旧后端…"
sudo systemctl stop claw-agent.service

echo "备份旧代码并切换新代码…"
mv "$OLD_DIR" "$BACKUP_DIR"
OLD_RENAMED=true
mv "$NEW_DIR" "$OLD_DIR"
NEW_INSTALLED=true

for relative in "${STATE_PATHS[@]}"; do
  if [[ -e "$BACKUP_DIR/$relative" ]]; then
    mkdir -p "$(dirname "$OLD_DIR/$relative")"
    mv "$BACKUP_DIR/$relative" "$OLD_DIR/$relative"
    MOVED_STATE+=("$relative")
  fi
done

# Skills added through the UI are user data. Keep only names absent from the new release.
for old_skill in "$BACKUP_DIR"/skills/*; do
  [[ -d "$old_skill" ]] || continue
  skill_name="$(basename "$old_skill")"
  if [[ ! -e "$OLD_DIR/skills/$skill_name" ]]; then
    cp -a "$old_skill" "$OLD_DIR/skills/$skill_name"
  fi
done

echo "启动新版本并检查服务…"
bash "$OLD_DIR/deploy/pi-start.sh"
trap - ERR
echo "更新完成。旧代码备份：$BACKUP_DIR"
echo "运行状态：bash $OLD_DIR/deploy/pi-status.sh"
