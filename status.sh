#!/usr/bin/env bash
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$PROJECT_DIR/log"
STATE_FILE="$LOG_DIR/service.env"
BACKEND_PID_FILE="$LOG_DIR/backend.pid"
FRONTEND_PID_FILE="$LOG_DIR/frontend.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
LOG_LINES="${STATUS_LOG_LINES:-30}"

is_number() {
  [[ "${1:-}" =~ ^[0-9]+$ ]]
}

pid_exists() {
  local pid="$1"
  is_number "$pid" && kill -0 "$pid" >/dev/null 2>&1
}

pid_command() {
  local pid="$1"
  ps -p "$pid" -o command= 2>/dev/null || true
}

pid_cwd() {
  local pid="$1"

  if command -v lsof >/dev/null 2>&1; then
    lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1
  fi
}

pid_matches_project() {
  local pid="$1"
  local command
  local cwd

  command="$(pid_command "$pid")"
  cwd="$(pid_cwd "$pid")"

  [[ "$command" == *"$PROJECT_DIR"* ]] && return 0
  [[ "$cwd" == "$PROJECT_DIR" ]] && return 0
  [[ "$cwd" == "$PROJECT_DIR/"* ]] && return 0

  return 1
}

read_pid_file() {
  local file="$1"

  if [[ -f "$file" ]]; then
    tr -d '[:space:]' <"$file"
  fi
}

fallback_backend_pids() {
  if command -v pgrep >/dev/null 2>&1; then
    pgrep -f "web_app.py" 2>/dev/null || true
  fi
}

fallback_frontend_pids() {
  if command -v pgrep >/dev/null 2>&1; then
    pgrep -f "npm.*web-react.*run dev" 2>/dev/null || true
    pgrep -f "vite.*--strictPort" 2>/dev/null || true
  fi
}

first_project_pid() {
  local pid

  while read -r pid; do
    if [[ -n "$pid" && "$pid" != "$$" ]] && pid_exists "$pid" && pid_matches_project "$pid"; then
      printf "%s\n" "$pid"
      return 0
    fi
  done
}

listening_ports_for_pid() {
  local pid="$1"

  if ! pid_exists "$pid"; then
    return 0
  fi

  if command -v lsof >/dev/null 2>&1; then
    lsof -a -nP -p "$pid" -iTCP -sTCP:LISTEN 2>/dev/null \
      | awk 'NR > 1 {print $9}' \
      | sed -n 's/.*:\([0-9][0-9]*\)$/\1/p' \
      | sort -n -u \
      | paste -sd "," -
  fi
}

http_status() {
  local url="$1"

  if ! command -v curl >/dev/null 2>&1; then
    printf "未检查：缺少 curl"
    return 2
  fi

  local code
  code="$(curl -sS -m 3 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || true)"
  if [[ "$code" =~ ^2|3 ]]; then
    printf "正常：HTTP %s" "$code"
    return 0
  fi
  if [[ -n "$code" && "$code" != "000" ]]; then
    printf "异常：HTTP %s" "$code"
    return 1
  fi

  printf "异常：无法连接"
  return 1
}

print_service() {
  local name="$1"
  local pid="$2"
  local port="$3"
  local url="$4"
  local inferred_ports

  printf "\n[%s]\n" "$name"

  if pid_exists "$pid"; then
    if pid_matches_project "$pid"; then
      printf "进程：运行中，PID=%s\n" "$pid"
    else
      printf "进程：PID=%s 存在，但不是当前项目进程\n" "$pid"
    fi
  else
    printf "进程：未运行"
    if [[ -n "${pid:-}" ]]; then
      printf "，记录 PID=%s" "$pid"
    fi
    printf "\n"
  fi

  if [[ -n "${port:-}" ]]; then
    printf "端口：%s\n" "$port"
  elif pid_exists "$pid"; then
    inferred_ports="$(listening_ports_for_pid "$pid")"
    if [[ -n "$inferred_ports" ]]; then
      printf "端口：%s（从进程监听推断）\n" "$inferred_ports"
    else
      printf "端口：未知\n"
    fi
  else
    printf "端口：未知\n"
  fi

  if [[ -n "$url" ]]; then
    printf "健康检查：%s\n" "$(http_status "$url")"
  else
    printf "健康检查：未检查，缺少端口\n"
  fi
}

print_log_tail() {
  local label="$1"
  local file="$2"

  printf "\n[%s 最近 %s 行]\n" "$label" "$LOG_LINES"
  if [[ -f "$file" ]]; then
    tail -n "$LOG_LINES" "$file"
  else
    printf "暂无日志文件：%s\n" "$file"
  fi
}

if [[ -f "$STATE_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$STATE_FILE"
  STATE_STATUS="存在：$STATE_FILE"
else
  STATE_STATUS="不存在，尝试按当前项目进程兜底检查"
fi

BACKEND_PID="${BACKEND_PID:-$(read_pid_file "$BACKEND_PID_FILE")}"
FRONTEND_PID="${FRONTEND_PID:-$(read_pid_file "$FRONTEND_PID_FILE")}"

if [[ -z "${BACKEND_PID:-}" ]]; then
  BACKEND_PID="$(fallback_backend_pids | first_project_pid)"
fi

if [[ -z "${FRONTEND_PID:-}" ]]; then
  FRONTEND_PID="$(fallback_frontend_pids | first_project_pid)"
fi

BACKEND_PORT="${BACKEND_PORT:-}"
FRONTEND_PORT="${FRONTEND_PORT:-}"

BACKEND_URL=""
FRONTEND_URL=""
if [[ -n "$BACKEND_PORT" ]]; then
  BACKEND_URL="http://127.0.0.1:$BACKEND_PORT/"
fi
if [[ -n "$FRONTEND_PORT" ]]; then
  FRONTEND_URL="http://127.0.0.1:$FRONTEND_PORT/"
fi

printf "项目目录：%s\n" "$PROJECT_DIR"
printf "状态文件：%s\n" "$STATE_STATUS"

print_service "后端 API" "${BACKEND_PID:-}" "$BACKEND_PORT" "$BACKEND_URL"
print_service "前端 Vite" "${FRONTEND_PID:-}" "$FRONTEND_PORT" "$FRONTEND_URL"

print_log_tail "后端日志" "$BACKEND_LOG"
print_log_tail "前端日志" "$FRONTEND_LOG"
