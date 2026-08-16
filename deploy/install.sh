#!/bin/bash
# Instalador del motor ETL + dashboard para Linux con systemd (solo systemd;
# Windows/otras distros se evalúan en otra iteración).
#
# Uso:
#   sudo ./deploy/install.sh [--etl-dir /opt/etl/tablas_linux] [--user etl]
#                            [--python python3.12] [--with-sap] [--no-start]
#
# Qué hace:
#   1. Copia el código a ETL_DIR (origen: el repo donde vive este script).
#   2. Crea el usuario de servicio (por defecto: etl) si no existe.
#   3. Crea el venv e instala requirements-{base,etl,web}.txt.
#      Con --with-sap intenta además requirements-sap.txt (pyrfc, wheel de SAP).
#   4. Genera ETL_SECRET (openssl rand -hex 32) en $ETL_DIR/.env (modo 600).
#   5. Si falta config.json, copia config.example.json y avisa que hay que editarlo.
#   6. Aplica las migraciones (incluye app_users).
#   7. Crea el admin raíz admin/extractor con cambio de password obligatorio
#      en el primer login (solo si aún no existe ningún usuario).
#   8. Instala etl-dashboard.service, etl-sync.service y etl-sync.timer
#      (scheduler a las :45; exit 42 = pospuesta) y los arranca.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ETL_DIR="${ETL_DIR:-/opt/etl/tablas_linux}"
SVC_USER="${SVC_USER:-etl}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
START=1
WITH_SAP=0

for arg in "$@"; do
  case "$arg" in
    --etl-dir=*) ETL_DIR="${arg#*=}" ;;
    --user=*)    SVC_USER="${arg#*=}" ;;
    --python=*)  PYTHON_BIN="${arg#*=}" ;;
    --no-start)  START=0 ;;
    --with-sap)  WITH_SAP=1 ;;
    -h|--help)
      grep '^#   ' "$0" | sed 's/^#   //'
      exit 0
      ;;
    *) echo "[error] argumento desconocido: $arg" >&2; exit 1 ;;
  esac
done

log() { echo "[install] $*"; }
die() { echo "[install] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 0) Precondiciones
# ---------------------------------------------------------------------------
[ "$(id -u)" -eq 0 ] || die "ejecutar como root (sudo)."
command -v systemctl >/dev/null 2>&1 || die "no se encontró systemd (systemctl)."
command -v runuser >/dev/null 2>&1 || die "falta runuser (paquete util-linux)."
command -v openssl >/dev/null 2>&1 || die "falta openssl."
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "no se encontró $PYTHON_BIN (necesitas Python >= 3.10)."
[ -d "$SRC_DIR/dashboard" ] || die "no parece un repo ETL: falta $SRC_DIR/dashboard"

run_as() { ( cd "$ETL_DIR" && runuser -u "$SVC_USER" -- "$@" ); }

# ---------------------------------------------------------------------------
# 1) Código
# ---------------------------------------------------------------------------
log "copiando código a $ETL_DIR"
install -d -o "$SVC_USER" -g "$SVC_USER" "$ETL_DIR" 2>/dev/null || true
if [ "$SRC_DIR" != "$ETL_DIR" ]; then
  # .env y config.json no vienen del repo: se preservan entre instalaciones.
  rsync -a --delete \
    --exclude '.git' --exclude 'venv' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude 'logs' --exclude 'output' --exclude '.env' --exclude 'config.json' \
    "$SRC_DIR"/ "$ETL_DIR"/
fi

# ---------------------------------------------------------------------------
# 2) Usuario de servicio
# ---------------------------------------------------------------------------
if ! id "$SVC_USER" >/dev/null 2>&1; then
  log "creando usuario de servicio $SVC_USER"
  useradd --system --home-dir "$ETL_DIR" --shell /usr/sbin/nologin "$SVC_USER"
fi

# ---------------------------------------------------------------------------
# 3) Entorno Python
# ---------------------------------------------------------------------------
if [ ! -x "$ETL_DIR/venv/bin/python" ]; then
  log "creando venv con $PYTHON_BIN"
  "$PYTHON_BIN" -m venv "$ETL_DIR/venv"
fi
log "instalando dependencias"
"$ETL_DIR/venv/bin/pip" install --upgrade pip -q
"$ETL_DIR/venv/bin/pip" install -q \
  -r "$ETL_DIR/requirements-base.txt" \
  -r "$ETL_DIR/requirements-etl.txt" \
  -r "$ETL_DIR/requirements-web.txt"

if [ "$WITH_SAP" = "1" ]; then
  log "instalando binding SAP (pyrfc; requiere el wheel de SAP)"
  "$ETL_DIR/venv/bin/pip" install -q -r "$ETL_DIR/requirements-sap.txt" \
    || die "falló pyrfc: montar el SDK NW RFC y proveer el wheel de SAP, o re-ejecutar sin --with-sap"
fi

# ---------------------------------------------------------------------------
# 4) Secretos (modo 600, propiedad del usuario de servicio)
# ---------------------------------------------------------------------------
ENV_FILE="$ETL_DIR/.env"
if [ ! -f "$ENV_FILE" ] || ! grep -q '^ETL_SECRET=' "$ENV_FILE"; then
  SECRET="$(openssl rand -hex 32)"
  log "generando ETL_SECRET en $ENV_FILE"
  umask 077
  {
    echo "# Generado por deploy/install.sh. No compartir."
    echo "ETL_SECRET=$SECRET"
    echo "ETL_TOKEN_TTL_HOURS=12"
    echo "SAPNWRFC_HOME=/opt/sap/nwrfcsdk"
    echo "LD_LIBRARY_PATH=/opt/sap/nwrfcsdk/lib"
  } > "$ENV_FILE"
  chown "$SVC_USER":"$SVC_USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

# ---------------------------------------------------------------------------
# 5) Configuración del cliente
# ---------------------------------------------------------------------------
if [ ! -f "$ETL_DIR/config.json" ]; then
  cp "$ETL_DIR/config.example.json" "$ETL_DIR/config.json"
  chown "$SVC_USER":"$SVC_USER" "$ETL_DIR/config.json"
  log "config.json creado desde el ejemplo; EDITAR antes del primer uso"
fi

# ---------------------------------------------------------------------------
# 6) Migraciones
# ---------------------------------------------------------------------------
log "aplicando migraciones (incluye app_users)"
MIGRATE_OK=0
if run_as "$ETL_DIR/venv/bin/python" -m cli migrate \
  --config "$ETL_DIR/config.json"; then
  MIGRATE_OK=1
else
  log "migraciones fallaron; revisar config.json (¿BD destino accesible?)"
fi

# ---------------------------------------------------------------------------
# 7) Admin raíz (idempotente; solo si las migraciones dejaron app_users)
# ---------------------------------------------------------------------------
if [ "$MIGRATE_OK" = "1" ]; then
  if ! run_as "$ETL_DIR/venv/bin/python" -m cli users list \
    --config "$ETL_DIR/config.json" | grep -q .; then
    log "creando admin raíz 'admin' (password inicial: extractor; se pedirá cambiarla)"
    run_as "$ETL_DIR/venv/bin/python" -m cli users add \
      --config "$ETL_DIR/config.json" \
      --username admin --password extractor --root
  fi
else
  log "se omite el alta del admin raíz hasta que las migraciones funcionen"
fi

# ---------------------------------------------------------------------------
# 8) Unidades systemd
# ---------------------------------------------------------------------------
chown -R "$SVC_USER":"$SVC_USER" "$ETL_DIR"
log "instalando unidades systemd"
for unit in etl-dashboard.service etl-sync.service etl-sync.timer; do
  sed \
    -e "s#/opt/etl/tablas_linux#$ETL_DIR#g" \
    -e "s/^User=.*/User=$SVC_USER/" \
    -e "s/^Group=.*/Group=$SVC_USER/" \
    "$SRC_DIR/deploy/$unit" > "/etc/systemd/system/$unit"
done
systemctl daemon-reload

if [ "$START" = "1" ]; then
  log "arrancando dashboard y timer de sincronización"
  systemctl enable --now etl-dashboard.service || log "aviso: no se pudo arrancar el dashboard (revisar config.json/.env)"
  systemctl enable --now etl-sync.timer || log "aviso: no se pudo arrancar el timer"
fi

# ---------------------------------------------------------------------------
log "instalación completada."
log "  - Código/venv:   $ETL_DIR"
log "  - Usuario:       $SVC_USER"
log "  - Dashboard:     http://<host>:8000/login"
log "  - Usuario raíz:  admin / extractor (cambiar en el primer login)"
log "  - Scheduler:     systemctl list-timers etl-sync.timer"
log "  - Logs:          journalctl -u etl-dashboard -u etl-sync -f"
[ "$START" = "1" ] || log "  (no se arrancaron los servicios: usar systemctl start)"
