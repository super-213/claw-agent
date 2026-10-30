#!/bin/bash
# Interactive production deployment for macOS; compatible with system Bash 3.2.
set -euo pipefail
umask 077
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUNTIME="$APP_DIR/.data/deploy-mac"
LOG_DIR="$APP_DIR/log/mac"
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"

fail() { printf '%s\n' "$*" >&2; exit 1; }
ask() { read -r -p "$1 [$2]: " REPLY; REPLY="${REPLY:-$2}"; }
yes() { ask "$1 (y/N)" N; [[ "$REPLY" == y || "$REPLY" == Y ]]; }
label() { printf 'com.claw-agent.%s' "$1"; }

init() {
  [[ "$(uname -s)" == Darwin ]] || fail '本脚本仅适用于 macOS。'
  [[ "$(id -u)" != 0 ]] || fail '请用登录桌面的普通用户运行，不要使用 sudo。'
  [[ "$APP_DIR" != *$'\n'* && "$APP_DIR" != *$'\r'* && "$APP_DIR" != *'$'* ]] || fail '项目路径不能包含换行或 $。'
  launchctl print "$DOMAIN" >/dev/null 2>&1 || fail '未找到用户桌面会话，请登录 Mac 桌面后在终端运行。'
  # A fixed pair of labels manages one installation per user. Never replace another checkout.
  local kind file
  for kind in api web; do
    file="$AGENTS/$(label "$kind").plist"
    if [[ -e "$file" ]]; then
      [[ "$(/usr/libexec/PlistBuddy -c 'Print :WorkingDirectory' "$file")" == "$APP_DIR" ]] || fail "已有其他目录的部署：$file。请先在原目录停止并移除对应 plist。"
    fi
  done
}

brew_setup() {
  if ! command -v brew >/dev/null 2>&1; then
    if [[ -x /opt/homebrew/bin/brew ]]; then
      eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then
      eval "$(/usr/local/bin/brew shellenv)"
    else
      fail '请先从 https://brew.sh 安装 Homebrew，再运行本脚本。'
    fi
  fi
}
install_formula() {
  yes "安装缺少的 Homebrew 依赖 $1？" || fail "请手动安装 $1 后重试。"
  brew install "$1"
}

stop_jobs() {
  local kind service
  for kind in web api; do
    service="$DOMAIN/$(label "$kind")"
    if launchctl print "$service" >/dev/null 2>&1; then
      launchctl bootout "$service"
    fi
  done
}

start_jobs() {
  [[ -f "$RUNTIME/config.json" ]] || fail '尚未部署，请先选择首次部署 / 更新。'
  local kind file
  for kind in api web; do
    file="$AGENTS/$(label "$kind").plist"
    [[ -f "$file" ]] || fail "缺少 $file，请重新部署。"
    launchctl enable "$DOMAIN/$(label "$kind")"
    if ! launchctl print "$DOMAIN/$(label "$kind")" >/dev/null 2>&1; then
      launchctl bootstrap "$DOMAIN" "$file"
    fi
  done
}

read_config() {
  WEB_PORT="$(/usr/bin/plutil -extract web_port raw -o - "$RUNTIME/config.json")"
  API_PORT="$(/usr/bin/plutil -extract api_port raw -o - "$RUNTIME/config.json")"
}

check_health() {
  read_config
  local attempt
  for attempt in {1..30}; do
    if curl --noproxy '*' -fsS --max-time 2 "http://127.0.0.1:$WEB_PORT/" >/dev/null 2>&1 &&
       curl --noproxy '*' -fsS --max-time 2 "http://127.0.0.1:$WEB_PORT/api/health" >/dev/null 2>&1; then
      printf '\n服务已就绪：http://127.0.0.1:%s\nTunnel 源站地址：http://127.0.0.1:%s\n' "$WEB_PORT" "$WEB_PORT"
      return
    fi
    sleep 1
  done
  fail "启动检查失败。请查看 $LOG_DIR/api.log 和 $LOG_DIR/nginx-error.log，或运行 bash deploy/mac.sh status。"
}

ask_port() {
  local title="$1" default="$2" kind="$3" port owner pids pid foreign
  while true; do
    ask "$title" "$default"; port="$REPLY"
    if [[ ! "$port" =~ ^[1-9][0-9]{3,4}$ ]] || ((port < 1024 || port > 65535)); then
      echo '请输入 1024-65535 端口。'; continue
    fi
    # An existing listener is allowed only when owned by this launchd job.
    owner="$(launchctl print "$DOMAIN/$(label "$kind")" 2>/dev/null | awk '/^[[:space:]]*pid = / {print $3}' || true)"
    pids="$(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    foreign=false
    for pid in $pids; do
      # Nginx workers inherit the master's socket.
      if [[ "$pid" != "$owner" && "$(ps -o ppid= -p "$pid" | tr -d ' ')" != "$owner" ]]; then foreign=true; fi
    done
    if [[ "$foreign" == true ]]; then echo "端口 $port 已被其他服务占用。"; continue; fi
    REPLY="$port"; return
  done
}

deploy() {
  [[ -t 0 ]] || fail '部署需要交互式终端。'
  brew_setup
  [[ -f "$APP_DIR/requirements.txt" && -f "$APP_DIR/web-react/package-lock.json" ]] || fail '项目文件不完整。'
  local py nginx_bin node_bin npm_bin default_web=8080 default_api=8000 secure=false
  local web_port api_port requirements_hash key stage
  # Pin deployment Python independently of Conda/system Python.
  py="$(brew --prefix)/opt/python@3.12/bin/python3.12"
  [[ -x "$py" ]] || install_formula python@3.12
  nginx_bin="$(brew --prefix)/bin/nginx"
  [[ -x "$nginx_bin" ]] || install_formula nginx
  node_bin="$(brew --prefix)/opt/node@24/bin/node"
  [[ -x "$node_bin" ]] || install_formula node@24
  export PATH="$(dirname "$node_bin"):$(brew --prefix)/bin:$PATH"
  npm_bin="$(dirname "$node_bin")/npm"
  [[ -x "$npm_bin" ]] || fail '找不到 node@24 的 npm。'
  if [[ -f "$RUNTIME/config.json" ]]; then
    read_config; default_web="$WEB_PORT"; default_api="$API_PORT"
  fi
  ask_port '网站入口端口' "$default_web" web; web_port="$REPLY"
  while true; do
    ask_port '后端 API 端口' "$default_api" api; api_port="$REPLY"
    [[ "$web_port" != "$api_port" ]] && break
    echo '网站和 API 端口不能相同。'
  done
  echo '本地 HTTP 调试请选择 N；以后正式只使用公网 HTTPS 时，可重新部署并选择 y。'
  if yes '只使用 HTTPS 登录（启用 Secure Cookie）？'; then secure=true; fi

  cd "$APP_DIR"
  if [[ ! -x .venv/bin/python ]]; then "$py" -m venv .venv; fi
  .venv/bin/python -c 'import sys; assert sys.version_info >= (3, 10), "需要 Python 3.10+，请另行备份并重建 .venv"'
  requirements_hash="$(shasum -a 256 requirements.txt | awk '{print $1}')"
  if [[ ! -f .venv/.requirements.sha256 ]] || [[ "$(cat .venv/.requirements.sha256)" != "$requirements_hash" ]]; then
    .venv/bin/python -m pip install -r requirements.txt
    printf '%s\n' "$requirements_hash" > .venv/.requirements.sha256
  fi
  # launchd does not inherit this terminal's exported credentials.
  if ! env -u DASHSCOPE_API_KEY .venv/bin/python - <<'PY'
from dotenv import dotenv_values
values = dict(dotenv_values('config/.env'))
values.update(dotenv_values('.env'))
key = (values.get('DASHSCOPE_API_KEY') or '').strip()
raise SystemExit(0 if key and key != 'your_api_key_here' else 1)
PY
  then
    read -r -s -p '请输入 DASHSCOPE_API_KEY（不回显）：' key; printf '\n'
    [[ -n "$key" && "$key" != *$'\r'* ]] || fail 'API Key 不能为空或包含回车。'
    # Single-quote dotenv encoding avoids interpolation; never echo the credential.
    printf '%s' "$key" | .venv/bin/python -c 'import sys; from dotenv import set_key; set_key(".env", "DASHSCOPE_API_KEY", sys.stdin.read(), quote_mode="always", encoding="utf-8")'
    chmod 600 .env
    unset key
  fi

  echo '安装前端依赖并构建生产网页…'
  "$npm_bin" --prefix web-react ci
  "$npm_bin" --prefix web-react run build
  mkdir -p "$RUNTIME" "$LOG_DIR" "$AGENTS"
  cp "$(brew --prefix)/etc/nginx/mime.types" "$RUNTIME/mime.types"
  stage="$(mktemp -d "$RUNTIME/config.XXXXXX")"
  local secure_flag=""
  if [[ "$secure" == true ]]; then secure_flag=--secure; fi
  .venv/bin/python deploy/mac-config.py --app "$APP_DIR" --runtime "$RUNTIME" --output "$stage" \
    --python "$APP_DIR/.venv/bin/python" --nginx "$nginx_bin" \
    --web-port "$web_port" --api-port "$api_port" ${secure_flag:+"$secure_flag"}
  "$nginx_bin" -e "$LOG_DIR/nginx-error.log" -t -p "$RUNTIME/" -c "$stage/nginx.conf"
  /usr/bin/plutil -lint "$stage"/*.plist
  stop_jobs
  cp "$stage/nginx.conf" "$stage/config.json" "$RUNTIME/"
  cp "$stage"/*.plist "$AGENTS/"
  rm -rf "$stage"
  start_jobs
  check_health
  echo '请先在本机打开网站创建管理员，再接入公网。后台服务会在当前用户登录时自动启动。'
  echo '更新代码后再次选择部署；脚本保留 .env、.data、files 和自定义技能。'
}

status() {
  local kind
  for kind in api web; do
    printf '\n%s\n' "$(label "$kind")"
    launchctl print "$DOMAIN/$(label "$kind")" 2>/dev/null | awk '/state = |pid = |last exit code = /' || true
  done
  if [[ -f "$RUNTIME/config.json" ]]; then
    read_config
    curl --noproxy '*' -sS --max-time 3 -o /dev/null -w '网站 HTTP %{http_code}\n' "http://127.0.0.1:$WEB_PORT/" || true
    curl --noproxy '*' -sS --max-time 3 -o /dev/null -w 'API HTTP %{http_code}\n' "http://127.0.0.1:$WEB_PORT/api/health" || true
  fi
  printf '日志目录：%s\n' "$LOG_DIR"
}

tunnel() {
  [[ -f "$RUNTIME/config.json" ]] || fail '请先部署项目。'
  brew_setup
  if ! command -v cloudflared >/dev/null 2>&1; then
    if yes '现在安装 cloudflared？'; then brew install cloudflared; fi
  fi
  read_config
  printf '\n在 Cloudflare 控制台创建 Tunnel，按 macOS 安装指引运行连接器。\n'
  printf '添加 Published application 路由：你的子域名 → http://127.0.0.1:%s\n' "$WEB_PORT"
  printf '详细步骤：%s/deploy/MACOS.md\n' "$APP_DIR"
  printf '官方指引：https://developers.cloudflare.com/tunnel/get-started/\n'
}

main() {
  case "${1:-menu}" in
    --help|-h) echo '用法：bash deploy/mac.sh [menu|deploy|start|restart|stop|status|logs|tunnel]'; return ;;
  esac
  init
  local action="${1:-menu}"
  if [[ "$action" == menu ]]; then
    [[ -t 0 ]] || fail '请在交互式终端运行，或指定 status/start/stop 等子命令。'
    printf '\nHome Agent · macOS 部署\n1) 首次部署 / 更新（安装依赖并构建）\n2) 启动 / 重启\n3) 停止\n4) 状态\n5) 查看最近日志\n6) Cloudflare Tunnel 接入\n0) 退出\n'
    ask '请选择' 4
    case "$REPLY" in 1) action=deploy;; 2) action=restart;; 3) action=stop;; 4) action=status;; 5) action=logs;; 6) action=tunnel;; 0) return;; *) fail '无效选项。';; esac
  fi
  case "$action" in
    deploy) deploy;;
    start) start_jobs; check_health;;
    restart) stop_jobs; start_jobs; check_health;;
    stop) stop_jobs; echo '已停止；下次用户登录时仍会自动启动。';;
    status) status;;
    logs) local file; for file in api.log web.log nginx-error.log; do
      printf '\n%s\n' "$LOG_DIR/$file"
      if [[ -f "$LOG_DIR/$file" ]]; then tail -n 60 "$LOG_DIR/$file"; fi
      done;;
    tunnel) tunnel;;
    *) fail '未知命令，请运行 bash deploy/mac.sh --help。';;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
