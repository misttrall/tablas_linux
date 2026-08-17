#!/usr/bin/env bash
# Arranca el license server Novus.
# Requiere: NOVUS_LICENSE_SERVER_SECRET (pepper) y haber corrido `keygen`.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"
export NOVUS_LICENSE_SERVER_SECRET="${NOVUS_LICENSE_SERVER_SECRET:-}"
if [ -z "$NOVUS_LICENSE_SERVER_SECRET" ]; then
  echo "Define NOVUS_LICENSE_SERVER_SECRET" >&2
  exit 1
fi

exec .venv/bin/uvicorn license_server.app:app --host "$HOST" --port "$PORT"
