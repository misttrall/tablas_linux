#!/usr/bin/env bash
# Arranque del demo del dashboard white-label (Novus / Invertec BI).
#
#   scripts/run_demo.sh start|stop|status|log [--port 8001]
#
# Variables opcionales: PORT, HOST, ETL_SECRET, PID_FILE, LOG_FILE.
# El puerto 8000 y cualquier otra instancia ajena quedan intactos.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8001}"
HOST="${HOST:-0.0.0.0}"
SECRET="${ETL_SECRET:-demo-secret-para-desarrollo}"
PID_FILE="${PID_FILE:-/tmp/uvicorn8001.pid}"
LOG_FILE="${LOG_FILE:-/tmp/uvicorn8001.log}"

venv_py="$ROOT/.venv/bin/python"
if [[ ! -x "$venv_py" ]]; then
  venv_py="$(command -v python3 || command -v python || true)"
fi
if [[ -z "$venv_py" ]]; then
  echo "[error] No hay intérprete Python disponible" >&2
  exit 1
fi

require_config() {
  if [[ ! -f "$ROOT/config.json" ]]; then
    echo "[error] No existe $ROOT/config.json" >&2
    exit 1
  fi
}

port_busy() {
  "$venv_py" -c "import socket,sys
try:
    socket.create_connection(('127.0.0.1', $PORT), timeout=1).close()
except OSError:
    sys.exit(1)
sys.exit(0)"
}

running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

start() {
  require_config
  if running; then
    echo "[ok] Ya está corriendo (pid $(cat "$PID_FILE"))"
    return 0
  fi
  if port_busy; then
    echo "[error] Puerto $PORT está en uso (instancia ajena); no se toca" >&2
    exit 1
  fi
  ETL_SECRET="$SECRET" nohup "$venv_py" -m uvicorn dashboard.app:app \
    --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 2
  if running; then
    echo "[ok] Demo en http://$HOST:$PORT (pid $(cat "$PID_FILE"), log $LOG_FILE)"
  else
    echo "[error] No arrancó; revisa $LOG_FILE" >&2
    exit 1
  fi
}

stop() {
  if running; then
    kill "$(cat "$PID_FILE")"
    rm -f "$PID_FILE"
    echo "[ok] Detenido"
  else
    rm -f "$PID_FILE"
    echo "[ok] No estaba corriendo"
  fi
}

status() {
  if running; then
    echo "[ok] Corriendo (pid $(cat "$PID_FILE"), log $LOG_FILE)"
  else
    echo "[info] Detenido"
  fi
}

log() {
  tail -50 "$LOG_FILE" 2>/dev/null || echo "[info] Sin log en $LOG_FILE"
}

case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  log) log ;;
  *) echo "Uso: $0 {start|stop|status|log}" >&2; exit 1 ;;
esac
