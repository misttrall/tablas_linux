# ETL + Dashboard + scheduler systemd en un solo contenedor.
# Uso: docker compose -f deploy/docker-compose.yml up --build -d
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        systemd systemd-sysv \
        python3 python3-venv \
        openssl rsync curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements-base.txt requirements-etl.txt requirements-web.txt ./
COPY deploy/wheels/ ./deploy/wheels/

RUN python3 -m venv /opt/etl/tablas_linux/venv \
    && /opt/etl/tablas_linux/venv/bin/pip install --no-cache-dir -r requirements-web.txt \
    && /opt/etl/tablas_linux/venv/bin/pip install --no-cache-dir ./deploy/wheels/pyrfc-3.3.1-cp312-cp312-linux_x86_64.whl

# .dockerignore excluye config.json/.env/*.sqlite/deploy/wheels: las
# credenciales SAP y el wheel se montan o copian en runtime/build explícito.
COPY . /opt/etl/tablas_linux/
RUN rm -rf /opt/etl/tablas_linux/.git \
    && find /opt/etl/tablas_linux -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && mkdir -p /var/lib/etl/logs /var/lib/etl/output \
    && useradd -r -s /usr/sbin/nologin -d /opt/etl/tablas_linux etl \
    && chown -R etl:etl /opt/etl/tablas_linux /var/lib/etl

COPY deploy/etl-dashboard.service deploy/etl-sync.service deploy/etl-sync.timer /etc/systemd/system/
COPY deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && systemctl enable etl-dashboard.service etl-sync.timer

STOPSIGNAL SIGRTMIN+3

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/sbin/init"]
