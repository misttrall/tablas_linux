#!/bin/bash
# Bootstrap del contenedor antes de arrancar systemd (PID 1).
# - Reconstruye /opt/etl/tablas_linux/config.json con el destino apuntando al
#   volumen persistente /var/lib/etl/db.sqlite, a partir del config montado
#   (con credenciales SAP) en /etc/etl/config.json.
# - Genera ETL_SECRET en .env si no existe.
# - Migraciones y usuarios por defecto (idempotente).
set -eu

ETL_DIR=/opt/etl/tablas_linux
CONFIG_SRC=/etc/etl/config.json
DB_DIR=/var/lib/etl

cd "$ETL_DIR"

if [ ! -f "$CONFIG_SRC" ]; then
  echo "docker-entrypoint: falta $CONFIG_SRC (montar el config.json con credenciales SAP)" >&2
  exit 1
fi

"$ETL_DIR/venv/bin/python" - "$CONFIG_SRC" "$ETL_DIR/config.json" <<'PY'
import json, sys

cfg = json.load(open(sys.argv[1]))
db = cfg.setdefault("database", {})
# Si es SQLite o no se especificó ruta, asegurar persistencia en /var/lib/etl
if db.get("dialect", "sqlite") == "sqlite":
    if not db.get("database") or db.get("database") == "db.sqlite":
        db["database"] = "/var/lib/etl/db.sqlite"

# Si hay bloque license, asegurar que el caché se guarde en volumen persistente
if "license" in cfg and isinstance(cfg["license"], dict):
    if not cfg["license"].get("cache_path"):
        cfg["license"]["cache_path"] = "/var/lib/etl/license_cache.json"

json.dump(cfg, open(sys.argv[2], "w"), indent=2, ensure_ascii=False)
print("docker-entrypoint: config.json procesado (persistencia en /var/lib/etl)")
PY

ENV_FILE="$ETL_DIR/.env"
if [ ! -f "$ENV_FILE" ] || ! grep -q '^ETL_SECRET=' "$ENV_FILE"; then
  umask 077
  SECRET=$(openssl rand -hex 32)
  printf 'ETL_SECRET=%s\n' "$SECRET" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "docker-entrypoint: ETL_SECRET generado (64 caracteres hex)"
fi

mkdir -p /var/lib/etl/logs /var/lib/etl/output /var/lib/etl/bi
chown -R etl:etl "$ETL_DIR" "$DB_DIR"

PY="$ETL_DIR/venv/bin/python"
CONFIG="$ETL_DIR/config.json"

runuser -u etl -- "$PY" -m cli migrate --config "$CONFIG" >/dev/null 2>&1 || true

# Crear usuarios por defecto si no existen
runuser -u etl -- "$PY" -c "
from sqlalchemy import create_engine, text
from utils.config_loader import load_config
from db.db_connection import _connection_string
from dashboard.auth import security

config = load_config('$CONFIG')
engine = create_engine(_connection_string(config['database']))
with engine.begin() as conn:
    row = conn.execute(text(\"SELECT id FROM app_users WHERE username='admin'\")).fetchone()
    if not row:
        h = security.hash_password('extractor')
        conn.execute(text(\"INSERT INTO app_users (username, password_hash, role, is_root, must_change_password, active) VALUES ('admin', :h, 'admin', 1, 1, 1)\"), {'h': h})
        print('docker-entrypoint: usuario admin creado')
    row_user = conn.execute(text(\"SELECT id FROM app_users WHERE username='extractor'\")).fetchone()
    if not row_user:
        h2 = security.hash_password('extractor')
        conn.execute(text(\"INSERT INTO app_users (username, password_hash, role, is_root, must_change_password, active) VALUES ('extractor', :h, 'user', 0, 0, 1)\"), {'h': h2})
        print('docker-entrypoint: usuario extractor creado')
" 2>/dev/null || true

echo "docker-entrypoint: arrancando systemd (PID 1)"
exec "$@"
