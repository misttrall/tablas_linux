# Guía de Despliegue en Docker para VM Linux de Cliente

Esta guía describe el procedimiento operativo estándar para instalar, configurar y operar la plataforma **Novus ETL + Dashboard** en una máquina virtual Linux (on-premise o cloud) de la empresa cliente.

---

## 1. Requisitos de la Máquina Virtual (VM)

### Especificaciones Mínimas Recomendadas:
- **Sistema Operativo:** Ubuntu 22.04 / 24.04 LTS, Debian 12, RHEL 9 o Rocky Linux 9.
- **CPU:** 2 vCPU o superior.
- **Memoria RAM:** 4 GB RAM (mínimo 2 GB libres).
- **Disco:** 20 GB de espacio en disco (SSD recomendado).
- **Software:**
  - Docker Engine >= 24.0
  - Docker Compose v2 (`docker compose`)

### Conectividad y Puertos de Red:
- **Entrante (Inbound):**
  - Puerto `8000` TCP (HTTP/S para acceso de usuarios al Dashboard Web).
- **Saliente (Outbound):**
  - Puerto `3300` / `3200` / `8000` (según SAP Gateway / Dispatcher para extracción RFC).
  - Puerto `1433` (SQL Server) o `5432` (PostgreSQL) hacia la base de datos destino del cliente.
  - Puerto `443` HTTPS hacia `https://lic.novusit.cl` (para validación periódica de licencia Novus).

---

## 2. Estructura de Archivos en la VM

Se recomienda desplegar en el directorio `/opt/novus/etl/`:

```
/opt/novus/etl/
├── config.json              # Configuración corporativa (SAP, DB, Licencia)
├── docker-compose.yml       # Orquestador Docker Compose
├── deploy/                  # Scripts de instalación y Dockerfile
│   ├── Dockerfile
│   ├── docker-entrypoint.sh
│   └── etl-docker.sh
├── data/                    # Volumen persistente: BD interna y caché de licencia
├── logs/                    # Volumen persistente: Logs de sincronización
└── output/                  # Volumen persistente: Entregables Excel / Parquet / CSV
```

---

## 3. Procedimiento de Instalación Paso a Paso

### Paso 1: Copiar el Entregable a la VM
```bash
sudo mkdir -p /opt/novus/etl
sudo chown -R $USER:$USER /opt/novus/etl
cd /opt/novus/etl
# Descomprimir o clonar el código entregado por Novus en este directorio
```

---

### Paso 2: Configurar `config.json`
Crear o editar `config.json` en la raíz con los datos de la empresa:

```json
{
  "environment": "prd",
  "source": {
    "type": "sap",
    "config": {
      "ashost": "sap-server.empresa.local",
      "sysnr": "00",
      "client": "100",
      "user": "RFC_ETL_USER",
      "passwd": "PasswordSegura123",
      "lang": "ES"
    }
  },
  "database": {
    "dialect": "sqlserver",
    "host": "dwh-server.empresa.local",
    "port": 1433,
    "database": "Novus_DWH",
    "user": "dwh_writer",
    "password": "PasswordDWH123"
  },
  "tables": [
    {"source": "MARA", "target": "Mara_Data", "keys": ["MATNR"]},
    {"source": "MARD", "target": "Mard_Data", "keys": ["MANDT", "MATNR", "WERKS", "LGORT"]},
    {"source": "MBEW", "target": "Mbew_Data", "keys": ["MATNR", "BWKEY"]},
    {"source": "MAKT", "target": "Makt_Data", "keys": ["MANDT", "MATNR", "SPRAS"]},
    {"source": "T001L", "target": "T001L_Data", "keys": ["WERKS", "LGORT"]}
  ],
  "license": {
    "server": "https://lic.novusit.cl",
    "customer_id": "empresa_cliente_001",
    "api_key": "api-key-provista-por-novus",
    "cache_path": "/var/lib/etl/license_cache.json"
  }
}
```

---

### Paso 3: Instalar el SDK de SAP (Solo si se usa extracción RFC directa)
Si el cliente extrae datos directamente de SAP RFC:
1. Descargar **SAP NetWeaver RFC SDK 7.50 para Linux x86_64** (desde SAP Launchpad).
2. Descomprimir en `/opt/sap/nwrfcsdk`:
   ```bash
   sudo mkdir -p /opt/sap
   sudo tar -xzf nwrfc750X_XX-XXXXXX.sar -C /opt/sap/
   sudo chmod -R 755 /opt/sap/nwrfcsdk
   ```

---

### Paso 4: Construir y Levantar el Contenedor

Puedes usar `docker compose` o el lanzador `./deploy/etl-docker.sh`:

```bash
# Opción 1: Usando Docker Compose estándar
docker compose build
docker compose up -d

# Opción 2: Usando el script de control
./deploy/etl-docker.sh build
./deploy/etl-docker.sh up
```

---

### Paso 5: Verificar el Estado y Acceso Web

1. **Verificar estado de los servicios:**
   ```bash
   ./deploy/etl-docker.sh status
   ```
2. **Acceder al Dashboard Web:**
   - Abre en el navegador: `http://<IP-DE-LA-VM>:8000`
   - **Usuario inicial:** `admin`
   - **Contraseña inicial:** `extractor` (el sistema solicitará el cambio obligatorio en el primer ingreso).

---

## 4. Comandos de Operación y Mantenimiento

El script `./deploy/etl-docker.sh` incluye accesos directos para todas las operaciones:

| Comando | Acción |
|:---|:---|
| `./deploy/etl-docker.sh status` | Muestra el estado del contenedor y del scheduler systemd. |
| `./deploy/etl-docker.sh logs` | Muestra los logs en tiempo real del Dashboard y del ETL. |
| `./deploy/etl-docker.sh sync` | Dispara manualmente una corrida completa de sincronización ETL. |
| `./deploy/etl-docker.sh report` | Genera los reportes Excel de inventario y vistas derivadas. |
| `./deploy/etl-docker.sh bi` | Genera los entregables Parquet y CSV para Power BI en `./output/`. |
| `./deploy/etl-docker.sh inspect` | Inspecciona la vigencia, límites y módulos activos de la licencia. |
| `./deploy/etl-docker.sh users` | Lista los usuarios registrados en el panel. |
| `./deploy/etl-docker.sh shell` | Abre una terminal interactiva `bash` dentro del contenedor. |
| `./deploy/etl-docker.sh down` | Detiene y apaga el contenedor. |

---

## 5. Estrategia de Respaldo y Recuperación (Disaster Recovery)

Todos los datos críticos residen **fuera del contenedor** en el host:
1. `./config.json`: Configuración y credenciales.
2. `./data/`: Base de datos interna SQLite (`db.sqlite`) con usuarios, historial de ejecuciones y caché de licencia.
3. `./output/`: Archivos generados para BI.

Para respaldar la plataforma, basta con programar un tarball o snapshot de la carpeta `/opt/novus/etl/`:
```bash
tar -czvf /backup/novus_backup_$(date +%Y%m%d).tar.gz /opt/novus/etl/config.json /opt/novus/etl/data
```
