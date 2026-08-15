FROM python:3.12-slim

WORKDIR /opt/etl

# El run contra SAP requiere el SDK NW RFC (licenciado), que NO se incluye en
# la imagen; se monta en runtime en /opt/sap/nwrfcsdk y se expone via env vars.
ENV SAPNWRFC_HOME=/opt/sap/nwrfcsdk \
    LD_LIBRARY_PATH=/opt/sap/nwrfcsdk/lib

COPY requirements-ci.txt /opt/etl/requirements-ci.txt
RUN pip install --no-cache-dir -r /opt/etl/requirements-ci.txt

COPY cli.py /opt/etl/cli.py
COPY etl_runner.py /opt/etl/etl_runner.py
COPY db /opt/etl/db
COPY sources /opt/etl/sources
COPY derived /opt/etl/derived
COPY utils /opt/etl/utils
COPY migrations /opt/etl/migrations
COPY dashboard /opt/etl/dashboard
COPY config.example.json /opt/etl/config.example.json

# La config real (con credenciales) se monta en runtime; no se copia al image.
ENV ETL_CONFIG=/opt/etl/config.json \
    ETL_LIVE_FILE=/tmp/etl_live.json

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health', timeout=5).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "dashboard.app:app", "--host", "0.0.0.0", "--port", "8000"]
