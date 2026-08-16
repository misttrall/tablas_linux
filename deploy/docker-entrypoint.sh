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
db["dialect"] = "sqlite"
db["database"] = "/var/lib/etl/db.sqlite"
json.dump(cfg, open(sys.argv[2], "w"), indent=2, ensure_ascii=False)
print("docker-entrypoint: config.json generado (destino sqlite en /var/lib/etl)")
PY

ENV_FILE="$ETL_DIR/.env"
if [ ! -f "$ENV_FILE" ] || ! grep -q '^ETL_SECRET=' "$ENV_FILE"; then
  umask 077
  SECRET=$(openssl rand -hex 32)
  printf 'ETL_SECRET=%s\n' "$SECRET" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "docker-entrypoint: ETL_SECRET generado"
fi

chown -R etl:etl "$ETL_DIR" "$DB_DIR"

PY="$ETL_DIR/venv/bin/python"
CONFIG="$ETL_DIR/config.json"

runuser -u etl -- "$PY" -m cli migrate --config "$CONFIG" >/dev/null 2>&1 || true
if ! runuser -u etl -- "$PY" -m cli users list --config "$CONFIG" 2>/dev/null | grep -q .; then
  runuser -u etl -- "$PY" -m cli users add --username admin --password extractor --role admin --root --no-force-password-change --config "$CONFIG" >/dev/null
  runuser -u etl -- "$PY" -m cli users add --username extractor --password extractor --role user --no-force-password-change --config "$CONFIG" >/dev/null
  echo "docker-entrypoint: usuarios admin/extractor creados"
fi

echo "docker-entrypoint: arrancando systemd (PID 1)"
exec "$@"
