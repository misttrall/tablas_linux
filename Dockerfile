FROM python:3.12-slim

WORKDIR /opt/etl

# Instalar dependencias del sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario sin privilegios para ejecución segura
RUN useradd -m -u 1001 -s /bin/bash etlapp

# Copiar requirements completos
COPY requirements-base.txt requirements-etl.txt requirements-web.txt requirements-ci.txt ./
RUN pip install --no-cache-dir -r requirements-ci.txt

COPY cli.py etl_runner.py config.example.json ./
COPY db ./db
COPY sources ./sources
COPY derived ./derived
COPY utils ./utils
COPY migrations ./migrations
COPY dashboard ./dashboard
COPY licensing ./licensing
COPY bi ./bi
COPY schemas ./schemas

# Asignar permisos al usuario etlapp
RUN chown -R etlapp:etlapp /opt/etl /tmp

USER etlapp

ENV ETL_CONFIG=/opt/etl/config.json \
    ETL_LIVE_FILE=/tmp/etl_live.json \
    TZ=America/Santiago \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "dashboard.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
