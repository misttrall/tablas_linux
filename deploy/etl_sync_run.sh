#!/bin/bash
# Disparado por etl-sync.timer (OnCalendar=*-*-* *:45:00).
#
# Ejecuta el pipeline ETL de forma programada. Si el ETL ya está en marcha
# (botón "Sincronizar" del dashboard o una corrida que aún no termina), sale
# con 42 ("pospuesta") sin reintentar, para no pisar la corrida activa.
#
# Códigos de salida:
#   42  Corrida pospuesta: ya hay una ejecución activa (lock local o BD).
#   1   La corrida intentó ejecutarse y falló.
#   0   La corrida terminó OK.

set -u

ETL_DIR=${ETL_DIR:-/opt/etl/tablas_linux}
export ETL_CONFIG=${ETL_CONFIG:-"$ETL_DIR/config.json"}
export ETL_LIVE_FILE=${ETL_LIVE_FILE:-/tmp/etl_live.json}
export SAPNWRFC_HOME=${SAPNWRFC_HOME:-/opt/sap/nwrfcsdk}

if [ -n "${SAPNWRFC_HOME:-}" ] && [ -d "$SAPNWRFC_HOME/lib" ]; then
  export LD_LIBRARY_PATH="$SAPNWRFC_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

PYTHON=${PYTHON:-"$ETL_DIR/venv/bin/python"}
LOCK_FILE=/tmp/etl_sap.lock
LOCK_STALE_SECONDS=3600

# 1) Chequeo barato: lock local sin vencer.
if [ -f "$LOCK_FILE" ]; then
  age=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0)))
  if [ "$age" -lt "$LOCK_STALE_SECONDS" ]; then
    echo "etl_sync_run: ETL ya en ejecución (lock local); corrida pospuesta"
    exit 42
  fi
fi

# 2) Chequeo autoritativo: fila 'running' no vencida en la BD destino.
"$PYTHON" - "$ETL_CONFIG" <<'PY'
import sys
from db.control import DEFAULT_STALE_MINUTES
from db.db_connection import get_engine
from db.sinks import get_sink
from utils.config_loader import load_config

config = load_config(sys.argv[1])
engine = get_engine(config)
sink = get_sink(engine)
with engine.connect() as conn:
    active = sink.get_active_run(conn, DEFAULT_STALE_MINUTES * 60)
    sys.exit(0 if active is not None else 3)
PY
rc=$?
if [ "$rc" = "0" ]; then
  echo "etl_sync_run: ETL ya en ejecución (BD); corrida pospuesta"
  exit 42
fi

# 3) Corrida programada. `cli run` no lee ETL_CONFIG: se pasa --config explícito.
cd "$ETL_DIR" || { echo "etl_sync_run: no existe $ETL_DIR"; exit 1; }
exec "$PYTHON" -m cli run --config "$ETL_CONFIG"
