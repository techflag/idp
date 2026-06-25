#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RUNTIME_DIR="${RUNTIME_DATA_DIR:-$SCRIPT_DIR/.runtime}"
PID_DIR="$RUNTIME_DIR/run"
LOG_DIR="$RUNTIME_DIR/logs"
PID_FILE="$PID_DIR/backend.pid"
LOG_FILE="$LOG_DIR/backend.log"
APP_PORT="${PORT:-5006}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${APP_PORT}/api/health}"
SCREEN_NAME="${SCREEN_NAME:-techflag-backend}"
export BACKEND_DEBUG="${BACKEND_DEBUG:-true}"
export LOG_LEVEL="${LOG_LEVEL:-debug}"

mkdir -p "$PID_DIR" "$LOG_DIR"

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

health_ok() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$HEALTH_URL" >/dev/null 2>&1
    return
  fi
  [[ -n "$(list_port_pids "$APP_PORT" | head -n 1)" ]]
}

screen_session_exists() {
  command -v screen >/dev/null 2>&1 && screen -list 2>/dev/null | grep -q "[.]${SCREEN_NAME}[[:space:]]"
}

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${EXISTING_PID:-}" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    if health_ok; then
      echo "backend is already running, pid=$EXISTING_PID"
      exit 0
    fi
    echo "stale backend pid=$EXISTING_PID found without healthy service; stopping it"
    kill "$EXISTING_PID" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
fi

PORT_PIDS="$(list_port_pids "$APP_PORT" | tr '\n' ' ' | xargs || true)"
if [[ -n "${PORT_PIDS:-}" ]]; then
  if health_ok; then
    echo "$PORT_PIDS" | awk '{print $1}' >"$PID_FILE"
    echo "backend is already running, pid(s): $PORT_PIDS"
    exit 0
  fi
  echo "port $APP_PORT is already in use by unhealthy pid(s): $PORT_PIDS"
  echo "run ./stop.sh first, or kill the process using port $APP_PORT"
  exit 1
fi

if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi
AUTO_MIGRATE="${AUTO_MIGRATE:-true}"

auto_migrate_enabled() {
  local normalized
  normalized="$(printf '%s' "$AUTO_MIGRATE" | tr '[:upper:]' '[:lower:]')"
  case "$normalized" in
    0|false|no|off) return 1 ;;
    *) return 0 ;;
  esac
}

run_database_migrations() {
  if ! auto_migrate_enabled; then
    echo "database auto migration skipped: AUTO_MIGRATE=$AUTO_MIGRATE"
    return
  fi
  echo "running database migrations..."
  "$PYTHON_BIN" -m alembic -c alembic.ini upgrade head
}

if screen_session_exists; then
  echo "stopping stale screen session: $SCREEN_NAME"
  screen -S "$SCREEN_NAME" -X quit >/dev/null 2>&1 || true
  sleep 1
fi

run_database_migrations

printf -v Q_SCRIPT_DIR '%q' "$SCRIPT_DIR"
printf -v Q_APP_PORT '%q' "$APP_PORT"
printf -v Q_BACKEND_DEBUG '%q' "$BACKEND_DEBUG"
printf -v Q_LOG_LEVEL '%q' "$LOG_LEVEL"
printf -v Q_PYTHON_BIN '%q' "$PYTHON_BIN"
printf -v Q_LOG_FILE '%q' "$LOG_FILE"

if command -v screen >/dev/null 2>&1; then
  screen -dmS "$SCREEN_NAME" zsh -lc "cd $Q_SCRIPT_DIR; PORT=$Q_APP_PORT BACKEND_DEBUG=$Q_BACKEND_DEBUG LOG_LEVEL=$Q_LOG_LEVEL exec $Q_PYTHON_BIN -m app.main >> $Q_LOG_FILE 2>&1"
else
  nohup "$PYTHON_BIN" -m app.main </dev/null >>"$LOG_FILE" 2>&1 &
fi

for _ in {1..40}; do
  if health_ok; then
    APP_PID="$(list_port_pids "$APP_PORT" | head -n 1 || true)"
    echo "$APP_PID" >"$PID_FILE"
    echo "backend started, pid=$APP_PID"
    echo "debug mode: $BACKEND_DEBUG"
    echo "log file: $LOG_FILE"
    exit 0
  fi
  sleep 0.5
done

echo "backend failed health check: $HEALTH_URL"
echo "log file: $LOG_FILE"
tail -n 40 "$LOG_FILE" || true
rm -f "$PID_FILE"
exit 1
