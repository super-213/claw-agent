#!/usr/bin/env bash
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$PROJECT_DIR/log"
STATE_FILE="$LOG_DIR/service.env"
BACKEND_PID_FILE="$LOG_DIR/backend.pid"
FRONTEND_PID_FILE="$LOG_DIR/frontend.pid"

STOPPED=0
FOUND=0
HAD_STATE=0

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

pids_for_port() {
  local port="$1"

  if ! is_number "$port"; then
    return 0
  fi

  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
  fi
}

wait_for_exit() {
  local pid="$1"
  local i

  for i in 1 2 3 4 5; do
    if ! pid_exists "$pid"; then
      return 0
    fi
    sleep 1
  done

  return 1
}

stop_pid() {
  local pid="$1"
  local label="$2"

  if ! is_number "$pid"; then
    return 0
  fi

  if ! pid_exists "$pid"; then
    return 0
  fi

  FOUND=1
  if ! pid_matches_project "$pid"; then
    printf "跳过 %s PID %s：不是当前项目启动的进程。\n" "$label" "$pid"
    return 0
  fi

  printf "关闭 %s PID %s...\n" "$label" "$pid"
  kill "$pid" >/dev/null 2>&1 || true
  if wait_for_exit "$pid"; then
    STOPPED=1
    return 0
  fi

  printf "%s PID %s 未正常退出，尝试强制结束。\n" "$label" "$pid"
  kill -9 "$pid" >/dev/null 2>&1 || true
  STOPPED=1
}

stop_port() {
  local port="$1"
  local label="$2"
  local pid

  if ! is_number "$port"; then
    return 0
  fi

  while read -r pid; do
    if [[ -n "$pid" ]]; then
      stop_pid "$pid" "$label 端口 $port"
    fi
  done < <(pids_for_port "$port")
}

read_pid_file() {
  local file="$1"

  if [[ -f "$file" ]]; then
    tr -d '[:space:]' <"$file"
  fi
}

fallback_project_pids() {
  if ! command -v pgrep >/dev/null 2>&1; then
    return 0
  fi

  pgrep -f "web_app.py" 2>/dev/null || true
  pgrep -f "npm.*web-react.*run dev" 2>/dev/null || true
  pgrep -f "vite.*--strictPort" 2>/dev/null || true
}

if [[ -f "$STATE_FILE" || -f "$BACKEND_PID_FILE" || -f "$FRONTEND_PID_FILE" ]]; then
  HAD_STATE=1
fi

if [[ -f "$STATE_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$STATE_FILE"
fi

BACKEND_PID="${BACKEND_PID:-$(read_pid_file "$BACKEND_PID_FILE")}"
FRONTEND_PID="${FRONTEND_PID:-$(read_pid_file "$FRONTEND_PID_FILE")}"
BACKEND_PORT="${BACKEND_PORT:-}"
FRONTEND_PORT="${FRONTEND_PORT:-}"

stop_pid "${FRONTEND_PID:-}" "前端"
stop_pid "${BACKEND_PID:-}" "后端"
stop_port "$FRONTEND_PORT" "前端"
stop_port "$BACKEND_PORT" "后端"

if [[ "$FOUND" -eq 0 ]]; then
  while read -r pid; do
    if [[ -n "$pid" && "$pid" != "$$" ]]; then
      stop_pid "$pid" "项目服务"
    fi
  done < <(fallback_project_pids | sort -u)
fi

if [[ "$STOPPED" -eq 1 ]]; then
  rm -f "$STATE_FILE" "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"
  printf "已关闭当前项目服务。\n"
else
  if [[ "$HAD_STATE" -eq 1 ]]; then
    rm -f "$STATE_FILE" "$BACKEND_PID_FILE" "$FRONTEND_PID_FILE"
    printf "未发现运行中的当前项目服务，已清理过期状态文件。\n"
    exit 0
  fi
  printf "未发现由 start.sh 启动的当前项目服务，无需关闭。\n"
fi
