#!/bin/bash

# Para que el botón "Sincronizar" pueda ejecutar `cli run` bajo demanda,
# este proceso debe heredar el SDK SAP (SAPNWRFC_HOME / LD_LIBRARY_PATH) y
# acceso a la red corporativa. Si no, el trigger devuelve error visible.

cd /opt/etl/tablas_linux

export ETL_CONFIG=${ETL_CONFIG:-/opt/etl/tablas_linux/config.json}
export ETL_LIVE_FILE=${ETL_LIVE_FILE:-/tmp/etl_live.json}

exec /opt/etl/tablas_linux/venv/bin/python -m uvicorn dashboard.app:app \
  --host 0.0.0.0 --port 8000 "$@"
