#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${RUNTIME_DATA_DIR:-$SCRIPT_DIR/.runtime}"
PID_FILE="$RUNTIME_DIR/run/backend.pid"
APP_PORT="${PORT:-5006}"
SCREEN_NAME="${SCREEN_NAME:-techflag-backend}"
PIDS_TO_STOP=""
STOPPED_COUNT=0

list_port_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
    return
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | awk -v port=":$port" '$4 ~ port "$" {print $0}' | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u
    return
  fi
  if command -v fuser >/dev/null 2>&1; then
    fuser "$port"/tcp 2>/dev/null | tr ' ' '\n' | sed '/^$/d'
  fi
}

add_pid() {
  local pid="$1"
  if [[ -z "${pid:-}" ]]; then
    return
  fi
  case " $PIDS_TO_STOP " in
    *" $pid "*) ;;
    *) PIDS_TO_STOP="$PIDS_TO_STOP $pid" ;;
  esac
}

stop_pid() {
  local pid="$1"
  local label="$2"
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "$label process $pid not found"
    return
  fi

  echo "stopping $label pid=$pid"
  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "$label stopped"
      STOPPED_COUNT=$((STOPPED_COUNT + 1))
      return
    fi
    sleep 1
  done

  kill -9 "$pid" 2>/dev/null || true
  echo "$label stopped forcefully"
  STOPPED_COUNT=$((STOPPED_COUNT + 1))
}

if [[ -f "$PID_FILE" ]]; then
  APP_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${APP_PID:-}" ]]; then
    add_pid "$APP_PID"
  else
    echo "pid file is empty, removing stale pid file"
  fi
  rm -f "$PID_FILE"
fi

for PORT_PID in $(list_port_pids "$APP_PORT"); do
  add_pid "$PORT_PID"
done

for PID in $PIDS_TO_STOP; do
  stop_pid "$PID" "backend"
done

if command -v screen >/dev/null 2>&1 && screen -list 2>/dev/null | grep -q "[.]${SCREEN_NAME}[[:space:]]"; then
  echo "stopping backend screen session=$SCREEN_NAME"
  screen -S "$SCREEN_NAME" -X quit >/dev/null 2>&1 || true
  STOPPED_COUNT=$((STOPPED_COUNT + 1))
fi

rm -f "$PID_FILE"

if [[ "$STOPPED_COUNT" -eq 0 ]]; then
  echo "backend is not running"
else
  echo "backend stopped"
fi
