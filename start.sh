#!/usr/bin/env bash
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$PROJECT_DIR/log"
STATE_FILE="$LOG_DIR/service.env"

mkdir -p "$LOG_DIR"

is_valid_port() {
  local port="$1"
  [[ "$port" =~ ^[0-9]+$ ]] && ((port >= 1 && port <= 65535))
}

port_in_use() {
  local port="$1"

  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi

  if command -v ss >/dev/null 2>&1; then
    ss -ltn | awk '{print $4}' | grep -Eq "[:.]${port}$"
    return $?
  fi

  if command -v netstat >/dev/null 2>&1; then
    netstat -an | grep -E "LISTEN|LISTENING" | grep -Eq "[:.]${port}[[:space:]]"
    return $?
  fi

  return 1
}

ask_port() {
  local label="$1"
  local default_port="$2"
  local reserved_port="${3:-}"
  local port

  while true; do
    printf "%s [%s]: " "$label" "$default_port" >&2
    read -r port
    port="${port:-$default_port}"

    if ! is_valid_port "$port"; then
      printf "端口必须是 1-65535 之间的数字，请重新输入。\n" >&2
      continue
    fi

    if [[ -n "$reserved_port" && "$port" == "$reserved_port" ]]; then
      printf "端口 %s 已用于另一个服务，请重新输入。\n" "$port" >&2
      continue
    fi

    if port_in_use "$port"; then
      printf "端口 %s 已被占用，请重新选择。\n" "$port" >&2
      continue
    fi

    printf "%s\n" "$port"
    return 0
  done
}

require_command() {
  local name="$1"

  if ! command -v "$name" >/dev/null 2>&1; then
    printf "未找到命令：%s\n" "$name" >&2
    exit 1
  fi
}

require_command python
require_command npm

BACKEND_PORT="$(ask_port "请输入后端 API 端口" "8000")"
FRONTEND_PORT="$(ask_port "请输入前端访问端口" "5173" "$BACKEND_PORT")"

BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_PID_FILE="$LOG_DIR/backend.pid"
FRONTEND_PID_FILE="$LOG_DIR/frontend.pid"

cd "$PROJECT_DIR" || exit 1

printf "启动后端 API，端口：%s\n" "$BACKEND_PORT"
nohup env PORT="$BACKEND_PORT" python web_app.py >>"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!
printf "%s\n" "$BACKEND_PID" >"$BACKEND_PID_FILE"

sleep 1
if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
  printf "后端启动失败，请查看日志：%s\n" "$BACKEND_LOG" >&2
  exit 1
fi

printf "启动前端 Vite，端口：%s\n" "$FRONTEND_PORT"
nohup env VITE_API_TARGET="http://127.0.0.1:$BACKEND_PORT" npm --prefix web-react run dev -- --port "$FRONTEND_PORT" --strictPort >>"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
printf "%s\n" "$FRONTEND_PID" >"$FRONTEND_PID_FILE"

sleep 1
if ! kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
  printf "前端启动失败，请查看日志：%s\n" "$FRONTEND_LOG" >&2
  if kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  exit 1
fi

printf "\n启动完成。\n"
printf "前端地址：http://localhost:%s\n" "$FRONTEND_PORT"
printf "后端 API：http://localhost:%s\n" "$BACKEND_PORT"
printf "后端文档：http://localhost:%s/docs\n" "$BACKEND_PORT"
printf "后端日志：%s\n" "$BACKEND_LOG"
printf "前端日志：%s\n" "$FRONTEND_LOG"

{
  printf "BACKEND_PORT=%s\n" "$BACKEND_PORT"
  printf "FRONTEND_PORT=%s\n" "$FRONTEND_PORT"
  printf "BACKEND_PID=%s\n" "$BACKEND_PID"
  printf "FRONTEND_PID=%s\n" "$FRONTEND_PID"
} >"$STATE_FILE"
printf "启动状态：%s\n" "$STATE_FILE"
