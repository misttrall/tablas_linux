#!/bin/bash
# ETL + Dashboard + scheduler systemd en un contenedor (pruebas locales).
#
# Nota: systemd dentro del contenedor sobre cgroup v2 requiere
# `--cgroupns=host` + cgroup montado rw + --privileged. Docker Compose
# (v5.3.1) no expone `cgroupns_mode`, por eso este lanzador.
#
# Uso:
#   etl-docker.sh build        Construye la imagen etl-sap:test
#   etl-docker.sh up           Levanta el contenedor etl-sap-test
#   etl-docker.sh down         Lo detiene y elimina
#   etl-docker.sh logs         Sigue los logs del contenedor
#   etl-docker.sh status       Estado del contenedor y de systemd
#   etl-docker.sh shell        Bash interactivo dentro del contenedor
#
# Variables:
#   SAP_SDK     SDK NW RFC del host (default: /home/mist/sap/nwrfcsdk)
#   CONFIG_JSON config.json con credenciales SAP (default: ./config.json)
set -eu

IMAGE=etl-sap:test
NAME=etl-sap-test
VOLUME=etl-data
SAP_SDK=${SAP_SDK:-/home/mist/sap/nwrfcsdk}
CONFIG_JSON=${CONFIG_JSON:-config.json}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
CONFIG_JSON=$(realpath "${CONFIG_JSON:-$SCRIPT_DIR/config.json}")

[ -f "$CONFIG_JSON" ] || { echo "etl-docker: falta $CONFIG_JSON (config con credenciales SAP)" >&2; exit 1; }

ACTION=${1:-up}

case "$ACTION" in
  build)
    docker build --network host -f "$SCRIPT_DIR/Dockerfile" -t "$IMAGE" "$SCRIPT_DIR/.."
    ;;
  up)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker run -d --name "$NAME" \
      --restart unless-stopped \
      --privileged --cgroupns=host --network host \
      -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
      -v "$SAP_SDK:/opt/sap/nwrfcsdk:ro" \
      -v "$CONFIG_JSON:/etc/etl/config.json:ro" \
      -v "$VOLUME:/var/lib/etl" \
      "$IMAGE"
    echo "etl-docker: $NAME levantado"
    ;;
  down)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    echo "etl-docker: $NAME eliminado"
    ;;
  logs)
    docker logs -f "$NAME"
    ;;
  status)
    docker ps --filter name="$NAME" --format '{{.Names}}: {{.Status}}'
    docker exec "$NAME" systemctl is-system-running 2>/dev/null || echo "(systemd no accesible)"
    ;;
  shell)
    docker exec -it "$NAME" bash
    ;;
  *)
    echo "uso: $0 {build|up|down|logs|status|shell}" >&2
    exit 1
    ;;
esac
