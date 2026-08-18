#!/usr/bin/env bash
# Sandbox Aislado de Licenciamiento y ETL Dashboard (Novus).
#
#   scripts/run_license_sandbox.sh start|stop|status|scenario|log|clean
#
# Puertos aislados por defecto:
#   - Servidor de Licencias: 8082
#   - Dashboard de Pruebas:  8083
#
# No interfiere con puerto 8000 (producción) ni 8001 (demo).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX_DIR="${SANDBOX_DIR:-/tmp/etl_sandbox}"
LICENSE_PORT="${LICENSE_PORT:-8082}"
DASHBOARD_PORT="${DASHBOARD_PORT:-8083}"
HOST="${HOST:-127.0.0.1}"

SERVER_PID_FILE="$SANDBOX_DIR/license_server.pid"
DASHBOARD_PID_FILE="$SANDBOX_DIR/dashboard.pid"
SERVER_LOG="$SANDBOX_DIR/license_server.log"
DASHBOARD_LOG="$SANDBOX_DIR/dashboard.log"

venv_py="$ROOT/.venv/bin/python"
if [[ ! -x "$venv_py" ]]; then
  venv_py="$(command -v python3 || command -v python || true)"
fi
if [[ -z "$venv_py" ]]; then
  echo "[error] No hay intérprete Python disponible" >&2
  exit 1
fi

setup_sandbox_data() {
  mkdir -p "$SANDBOX_DIR/csv" "$SANDBOX_DIR/output"

  # 1. Generar claves si no existen
  if [[ ! -f "$SANDBOX_DIR/private_key.pem" || ! -f "$SANDBOX_DIR/novus_public.pem" ]]; then
    "$venv_py" -c "
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from pathlib import Path

priv = ed25519.Ed25519PrivateKey.generate()
priv_bytes = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
pub_bytes = priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

Path('$SANDBOX_DIR/private_key.pem').write_bytes(priv_bytes)
Path('$SANDBOX_DIR/novus_public.pem').write_bytes(pub_bytes)
"
  fi

  # 2. Generar CSV sintéticos para simular ERP (MARA, MARD, MBEW, MAKT, T001L)
  cat << 'EOF' > "$SANDBOX_DIR/csv/MARA.csv"
MATNR,MTART,MATKL,XCHPF,MEINS
MAT-100,ROH,RAW,X,UN
MAT-200,FERT,PROD,,KG
MAT-300,HALB,SEMI,,UN
EOF

  cat << 'EOF' > "$SANDBOX_DIR/csv/MARD.csv"
MANDT,MATNR,WERKS,LGORT,LABST,LMINB
100,MAT-100,P100,A001,450.0,50.0
100,MAT-200,P100,A001,20.0,100.0
100,MAT-300,P100,A001,800.0,200.0
EOF

  cat << 'EOF' > "$SANDBOX_DIR/csv/MBEW.csv"
MATNR,BWKEY,LBKUM,SALK3,VPRSV,STPRS,VERPR
MAT-100,P100,450.0,45000.0,V,0.0,100.0
MAT-200,P100,20.0,10000.0,V,0.0,500.0
MAT-300,P100,800.0,20000.0,V,0.0,25.0
EOF

  cat << 'EOF' > "$SANDBOX_DIR/csv/MAKT.csv"
MANDT,MATNR,SPRAS,MAKTX,MAKTG
100,MAT-100,ES,Caja de Cartón Reforzada,CAJA CARTON
100,MAT-200,ES,Materia Prima Grano A,GRANO A
100,MAT-300,ES,Film Plástico Transparente,FILM PLASTICO
EOF

  cat << 'EOF' > "$SANDBOX_DIR/csv/T001L.csv"
WERKS,LGORT,LGOBE
P100,A001,Bodega Principal Central
EOF

  # 3. Crear config.sandbox.json
  cat << EOF > "$SANDBOX_DIR/config.sandbox.json"
{
  "environment": "qa",
  "source": {
    "type": "csv",
    "config": {
      "directory": "$SANDBOX_DIR/csv"
    }
  },
  "database": {
    "dialect": "sqlite",
    "database": "$SANDBOX_DIR/sandbox_db.sqlite"
  },
  "tables": [
    {"source": "MARA", "target": "Mara_Data", "keys": ["MATNR"]},
    {"source": "MARD", "target": "Mard_Data", "keys": ["MANDT", "MATNR", "WERKS", "LGORT"]},
    {"source": "MBEW", "target": "Mbew_Data", "keys": ["MATNR", "BWKEY"]},
    {"source": "MAKT", "target": "Makt_Data", "keys": ["MANDT", "MATNR", "SPRAS"]},
    {"source": "T001L", "target": "T001L_Data", "keys": ["WERKS", "LGORT"]}
  ],
  "fields": {
    "MARA": ["MATNR", "MTART", "MATKL", "XCHPF", "MEINS"],
    "MARD": ["MANDT", "MATNR", "WERKS", "LGORT", "LABST", "LMINB"],
    "MBEW": ["MATNR", "BWKEY", "LBKUM", "SALK3", "VPRSV", "STPRS", "VERPR"],
    "MAKT": ["MANDT", "MATNR", "SPRAS", "MAKTX", "MAKTG"],
    "T001L": ["WERKS", "LGORT", "LGOBE"]
  },
  "derived": {
    "name": "inv_bodega",
    "text_lang": "ES",
    "tab": "Inventario",
    "row_label": "MATNR",
    "dominio": {
      "filters": [
        {"field": "WERKS", "op": "eq", "value": "P100"},
        {"field": "LGORT", "op": "eq", "value": "A001"}
      ]
    },
    "precio": {"field": "VERPR"},
    "valor": {"field": "VERPR"},
    "keys": ["MATNR", "WERKS", "LGORT"],
    "inventory": {
      "filters": {"centro": "Centro", "almacen": "Almacen"}
    },
    "columns": [
      {"as": "MATNR", "source": "MATNR", "label": "Material"},
      {"as": "Descripcion", "source": "MAKTX", "label": "Descripción"},
      {"as": "Centro", "source": "WERKS", "label": "Centro"},
      {"as": "Almacen", "source": "LGORT", "label": "Almacén", "hide": true},
      {"as": "AlmacenDesc", "source": "LGOBE", "label": "Almacén", "fallback": "Almacen"},
      {"as": "StockLibre", "source": "LABST", "label": "Stock", "fallback": "Stock"},
      {"as": "UMB", "source": "MEINS", "label": "UMB", "hide": true},
      {"as": "Precio", "source": "VERPR", "label": "Precio", "hide": true},
      {"as": "ValorTotal", "compute": "LABST * VERPR", "label": "Valor"}
    ],
    "excel": {
      "path": "$SANDBOX_DIR/output/inventario.xlsx",
      "sheet": "Stock",
      "alerts_sheet": "StockBajo"
    }
  },
  "dashboard": {
    "title": "Novus Data Platform",
    "logo": "/static/novus-logo.png",
    "color": "#EA7222",
    "footer": "© 2026 Novus Technologies · Datos e Inteligencia de Negocios"
  },
  "license": {
    "server": "http://$HOST:$LICENSE_PORT",
    "customer_id": "empresa_sandbox",
    "api_key": "sandbox-api-key",
    "public_key": "$SANDBOX_DIR/novus_public.pem",
    "cache_path": "$SANDBOX_DIR/license_cache.json",
    "refresh_minutes": 720
  }
}
EOF

  # 4. Inicializar base de datos del License Server si no existe
  if [[ ! -f "$SANDBOX_DIR/server.db" ]]; then
    NOVUS_LICENSE_DB="$SANDBOX_DIR/server.db" \
    NOVUS_LICENSE_SERVER_SECRET="sandbox-pepper-secret" \
    "$venv_py" -c "
from sqlalchemy import create_engine
from license_server import db as ldb
import time

engine = create_engine('sqlite:///$SANDBOX_DIR/server.db')
ldb.init_db(engine)
h = ldb.hash_api_key('sandbox-pepper-secret', 'sandbox-api-key')
ldb.create_customer(engine, 'empresa_sandbox', 'Cliente Sandbox', h)
now = int(time.time())
ldb.issue_license(
    engine, 'empresa_sandbox', 'NOVUS-SBX-001',
    valid_from=now - 86400, valid_until=now + 30*86400, grace_days=7,
    modules={'derived': True, 'dashboard': True, 'bi': True},
    limits={'users': 5}
)
"
  fi

  # 5. Generar caché inicial de licencia (E01) si no existe
  if [[ ! -f "$SANDBOX_DIR/license_cache.json" ]]; then
    "$venv_py" "$ROOT/scripts/simulate_licensing.py" scenario E01 --config "$SANDBOX_DIR/config.sandbox.json" > /dev/null 2>&1 || true
  fi

  # 6. Inicializar base de datos de control, migraciones y usuario admin
  if [[ ! -f "$SANDBOX_DIR/sandbox_db.sqlite" ]]; then
    echo "[info] Inicializando base de datos SQLite y migraciones sandbox..."
    "$venv_py" -m cli migrate --config "$SANDBOX_DIR/config.sandbox.json" > /dev/null 2>&1 || true
    "$venv_py" -m cli run --config "$SANDBOX_DIR/config.sandbox.json" > /dev/null 2>&1 || true
  fi

  # Asegurar que el usuario admin existe siempre en sandbox_db.sqlite
  "$venv_py" -c "
from sqlalchemy import create_engine, text
from dashboard.auth import security
import os

engine = create_engine('sqlite:///$SANDBOX_DIR/sandbox_db.sqlite')
with engine.begin() as conn:
    row = conn.execute(text(\"SELECT id FROM app_users WHERE username='admin'\")).fetchone()
    if not row:
        h = security.hash_password('admin')
        conn.execute(text(\"INSERT INTO app_users (username, password_hash, role, is_root, must_change_password, active) VALUES ('admin', :h, 'admin', 1, 0, 1)\"), {'h': h})
        print('[info] Usuario admin creado en el sandbox')
" 2>/dev/null || true
}

is_running() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

start_server() {
  if is_running "$SERVER_PID_FILE"; then
    echo "[ok] License server ya está corriendo en http://$HOST:$LICENSE_PORT (pid $(cat "$SERVER_PID_FILE"))"
  else
    NOVUS_LICENSE_DB="$SANDBOX_DIR/server.db" \
    NOVUS_LICENSE_SERVER_SECRET="sandbox-pepper-secret" \
    NOVUS_LICENSE_PRIVATE_KEY="$SANDBOX_DIR/private_key.pem" \
    setsid "$venv_py" -m uvicorn license_server.app:app \
      --host "$HOST" --port "$LICENSE_PORT" < /dev/null > "$SERVER_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$SERVER_PID_FILE"
    disown "$pid" 2>/dev/null || true
    sleep 1
    if is_running "$SERVER_PID_FILE"; then
      echo "[ok] License server iniciado en http://$HOST:$LICENSE_PORT (pid $(cat "$SERVER_PID_FILE"))"
    else
      echo "[error] License server no arrancó; revisa $SERVER_LOG" >&2
    fi
  fi
}

start_dashboard() {
  if is_running "$DASHBOARD_PID_FILE"; then
    echo "[ok] Dashboard sandbox ya está corriendo en http://$HOST:$DASHBOARD_PORT (pid $(cat "$DASHBOARD_PID_FILE"))"
  else
    ETL_SECRET="sandbox-dashboard-secret-key-12345" \
    ETL_CONFIG="$SANDBOX_DIR/config.sandbox.json" \
    setsid "$venv_py" -m uvicorn dashboard.app:app \
      --host "$HOST" --port "$DASHBOARD_PORT" < /dev/null > "$DASHBOARD_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$DASHBOARD_PID_FILE"
    disown "$pid" 2>/dev/null || true
    sleep 1
    if is_running "$DASHBOARD_PID_FILE"; then
      echo "[ok] Dashboard sandbox iniciado en http://$HOST:$DASHBOARD_PORT (pid $(cat "$DASHBOARD_PID_FILE"))"
    else
      echo "[error] Dashboard sandbox no arrancó; revisa $DASHBOARD_LOG" >&2
    fi
  fi
}

stop_process() {
  local name="$1"
  local pid_file="$2"
  if is_running "$pid_file"; then
    local pid
    pid="$(cat "$pid_file")"
    kill "$pid" 2>/dev/null || true
    rm -f "$pid_file"
    echo "[ok] $name detenido (pid $pid)"
  else
    rm -f "$pid_file"
    echo "[info] $name no estaba corriendo"
  fi
}

start() {
  setup_sandbox_data
  start_server
  echo ""
  echo "══════════════════════════════════════════════════════════════════════"
  echo "  SERVIDOR DE LICENCIAS Y PLATAFORMA UNIFICADA NOVUS"
  echo "══════════════════════════════════════════════════════════════════════"
  echo "  • Frontend Unificado: http://$HOST:8001"
  echo "  • License Server:     http://$HOST:$LICENSE_PORT"
  echo "  • Usuario / Clave:    admin / admin"
  echo ""
  echo "  Comandos rápidos para simular estados de licencia en vivo:"
  echo "    $0 scenario E05       # Aplicar período de gracia (Grace Period)"
  echo "    $0 scenario E07       # Aplicar suspensión de servicio"
  echo "    $0 scenario E01       # Restaurar licencia activa"
  echo "    $0 status             # Ver estado de la licencia y servidor"
  echo "    $0 stop               # Detener license server"
  echo "══════════════════════════════════════════════════════════════════════"
}

stop() {
  stop_process "License server" "$SERVER_PID_FILE"
}

status() {
  echo "--- Estado de Servicios ---"
  if is_running "$SERVER_PID_FILE"; then
    echo "[ok] License server:     CORRIENDO (pid $(cat "$SERVER_PID_FILE"), puerto $LICENSE_PORT)"
  else
    echo "[info] License server:   DETENIDO"
  fi
  if [[ -f "$ROOT/config.json" ]]; then
    echo ""
    echo "--- Estado de Licencia (config.json) ---"
    "$venv_py" -m cli license status --config "$ROOT/config.json" || true
  fi
}

scenario() {
  local sc_id="${1:-}"
  if [[ -z "$sc_id" ]]; then
    echo "Uso: $0 scenario <E01..E12>"
    exit 1
  fi
  setup_sandbox_data
  "$venv_py" "$ROOT/scripts/simulate_licensing.py" scenario "$sc_id" --config "$SANDBOX_DIR/config.sandbox.json"
  if [[ -f "$SANDBOX_DIR/license_cache.json" ]]; then
    mkdir -p "$ROOT/data"
    cp "$SANDBOX_DIR/license_cache.json" "$ROOT/data/license_cache.json"
    if [[ -f "$SANDBOX_DIR/novus_public.pem" ]]; then
      cp "$SANDBOX_DIR/novus_public.pem" "$ROOT/data/novus_public.pem"
    fi
  fi
  echo ""
  echo "[info] Estado resultante de la licencia:"
  "$venv_py" -m cli license status --config "$ROOT/config.json" 2>/dev/null || "$venv_py" -m cli license status --config "$SANDBOX_DIR/config.sandbox.json"
}

log() {
  local target="${1:-server}"
  echo "=== License Server Log ($SERVER_LOG) ==="
  tail -30 "$SERVER_LOG" 2>/dev/null || echo "(sin logs)"
}

clean() {
  stop
  rm -rf "$SANDBOX_DIR"
  echo "[ok] Directorio sandbox $SANDBOX_DIR eliminado"
}

case "${1:-status}" in
  start)    start ;;
  stop)     stop ;;
  restart)  stop; sleep 1; start ;;
  status)   status ;;
  scenario) scenario "${2:-}" ;;
  log)      log "${2:-all}" ;;
  clean)    clean ;;
  *)        echo "Uso: $0 {start|stop|restart|status|scenario <E01..E12>|log|clean}" >&2; exit 1 ;;
esac
