# RUNBOOK — Motor ETL + Dashboard

Operación y mantenimiento del motor ETL multi-ERP (Linux con systemd) y su
dashboard web con autenticación (JWT + bcrypt).

## Índice

1. [Instalación](#1-instalación)
2. [Primer arranque y acceso](#2-primer-arranque-y-acceso)
3. [Usuarios y roles](#3-usuarios-y-roles)
4. [Sincronización programada y manual](#4-sincronización-programada-y-manual)
5. [Operación del scheduler](#5-operación-del-scheduler)
6. [Actualización (upgrade)](#6-actualización-upgrade)
7. [Backup y restauración](#7-backup-y-restauración)
8. [Solución de problemas](#8-solución-de-problemas)
9. [Configuración](#9-configuración)
10. [Rutas y seguridad](#10-rutas-y-seguridad)
11. [Emitir una licencia para un cliente](#11-emitir-una-licencia-para-un-cliente)

---

## 1. Instalación

Requiere un servidor **Linux con systemd**, Python ≥ 3.10 y acceso a la base
de datos destino. El instalador crea el usuario de servicio, el venv, genera
el secreto de sesión, aplica las migraciones y deja el dashboard + scheduler
corriendo.

> **Extracción SAP**: el binding `pyrfc` no está en PyPI (es un binario
> licenciado por SAP). La instalación base funciona con fuentes CSV/Excel;
> para SAP hay que montar el SDK NW RFC y el wheel de SAP y usar `--with-sap`
> (ver [Configuración](#9-configuración)).

```bash
sudo apt install -y python3 python3-venv openssl rsync
sudo ./deploy/install.sh
```

Opciones:

```bash
sudo ./deploy/install.sh \
  --etl-dir=/opt/etl/tablas_linux \   # directorio de instalación
  --user=etl \                         # usuario de servicio
  --python=python3.12 \                # intérprete para el venv
  --with-sap                           # instalar pyrfc (wheel de SAP)
  --no-start                           # instala pero no arranca servicios
```

Qué hace:

| Paso | Detalle |
|------|---------|
| Código | Copia el repo a `--etl-dir` (excluye `.git`, venv, logs, output) |
| Usuario | Crea el usuario de servicio si no existe y toma posesión del directorio |
| Entorno | Crea `venv/` e instala `requirements-{base,etl,web}.txt` |
| Entorno SAP | Con `--with-sap`, instala `requirements-sap.txt` (pyrfc, wheel de SAP) |
| Secretos | Genera `ETL_SECRET` (32 bytes hex) y `.env` (modo 600) |
| Config | Si falta `config.json`, copia `config.example.json` (¡hay que editarlo!) |
| Migraciones | Ejecuta `cli migrate` (tablas de control, progreso, ejecuciones, `app_users`) |
| Admin raíz | Crea `admin` / `extractor` con cambio de password obligatorio (solo si no hay usuarios) |
| Servicios | Instala y arranca `etl-dashboard.service` y `etl-sync.timer` |

> **Importante**: antes de que las migraciones funcionen, `config.json` debe
> apuntar a la BD destino real (servidor, base, credenciales). Si las
> migraciones fallan, el instalador **no** crea el admin raíz (avisa al final).

## 2. Primer arranque y acceso

1. Editar `config.json` (véase [Configuración](#9-configuración)) si el
   instalador lo creó desde el ejemplo, y reiniciar el dashboard:
   `sudo systemctl restart etl-dashboard`.
2. Abrir `http://<servidor>:8000/login`.
3. Entrar con `admin` / `extractor`. El sistema **obliga a cambiar la
   password** en el primer login (mínimo 8 caracteres).
4. El admin raíz puede crear más usuarios desde `/panel`.

Servicios:

```bash
sudo systemctl status etl-dashboard.service   # dashboard (puerto 8000)
sudo systemctl status etl-sync.timer           # scheduler horario (:45)
sudo systemctl list-timers etl-sync.timer      # próxima ejecución
```

## 3. Usuarios y roles

Roles:

- **`user`**: inventario, estado, botón Sincronizar y última sincronización.
- **`admin`**: además, panel de ejecuciones, progreso, tablas, dashboard de
  agregados y gestión de usuarios.
- **`is_root`**: admin raíz (el creado por el instalador). **No se puede
  borrar ni degradar**; solo root cambia su propia password.

Gestión por CLI (recomendada para el alta inicial o por scripting):

```bash
# Listar usuarios
python -m cli users list --config config.json

# Crear admin raíz (protegido contra borrado)
python -m cli users add --username admin --password '...' --root --config config.json

# Crear un usuario común
python -m cli users add --username operador --password '...' --config config.json

# Sin obligar a cambiar la password en el primer login
python -m cli users add --username aux --password '...' --no-force-password-change

# Cambiar password
python -m cli users set-password --username operador --password 'nueva' --config config.json
```

Desde el panel (`/panel`, solo admin): crear usuarios, asignar rol, activar/
desactivar, resetear password y eliminar.

## 4. Sincronización programada y manual

- **Programada**: el timer `etl-sync.timer` dispara el ETL cada hora en el
  minuto **:45** (`OnCalendar=*-*-* *:45:00`).
- **Manual**: botón **Sincronizar** en el dashboard (vista `/etl` o
  `/inventario`); dispara `cli run --config ...` como subproceso del
  dashboard, heredando el SDK SAP.

Ambos mecanismos usan el **mismo lock** (archivo `/tmp/etl_sap.lock` +
fila `running` en `etl_execution`): nunca corren dos corridas a la vez. Si el
scheduler cae sobre una corrida activa (manual o previa), sale con
**exit 42 = "pospuesta"** y **no** lo reintenta: espera el siguiente slot de
las :45.

## 5. Operación del scheduler

El flujo del script `deploy/etl_sync_run.sh`:

1. Si `/tmp/etl_sap.lock` es reciente (< 60 min) → exit 42.
2. Si hay una fila `running` no vencida en `etl_execution` → exit 42.
3. Ejecuta `python -m cli run --config "$ETL_CONFIG"`.

Códigos de salida:

| Código | Significado | Qué hacer |
|--------|-------------|-----------|
| `0` | Corrida OK | — |
| `42` | Pospuesta (ya había una activa) | Nada; es normal |
| `1` | La corrida falló | Revisar `journalctl -u etl-sync` |

```bash
journalctl -u etl-sync -f                    # logs del scheduler
journalctl -u etl-dashboard -f               # logs del dashboard
sudo systemctl stop etl-sync.timer           # pausar el scheduler
sudo systemctl start etl-sync.timer          # reanudar
```

El dashboard usa `SuccessExitStatus=42`, así que una corrida pospuesta no se
registra como fallo.

## 6. Actualización (upgrade)

```bash
# 1) Desde el repo nuevo
sudo ./deploy/install.sh --etl-dir=/opt/etl/tablas_linux

# 2) Verificar migraciones pendientes (no destructivas)
python -m cli migrate --config config.json

# 3) Reiniciar el dashboard y recargar el timer
sudo systemctl restart etl-dashboard.service
sudo systemctl restart etl-sync.timer

# 4) Comprobar versión/estado
python -m cli status --last 3 --config config.json
```

> El instalador es idempotente: no regenera `.env`, no duplica el admin raíz
> y re-copia el código sobre el destino.

## 7. Backup y restauración

- **BD destino**: incluye las tablas de control (`etl_control`, `etl_progress`,
  `etl_execution`, `etl_execution_table`, `app_users`). Backup según la BD
  (dump de SQL Server / PostgreSQL / MySQL / copia del archivo en SQLite).
- **`config.json`**: contiene credenciales de SAP y BD → respaldar de forma
  segura.
- **`<etl-dir>/.env`**: contiene `ETL_SECRET`. Si se pierde, **todas las
  sesiones se invalidan** y hay que regenerarlo (logout de todos los
  usuarios). La password de los usuarios no depende de él (bcrypt en BD).

## 8. Solución de problemas

| Síntoma | Causa probable | Acción |
|---------|----------------|--------|
| El instalador no creó el admin | Migraciones fallaron (config sin editar) | Arreglar `config.json`, `cli migrate`, luego `cli users add --root ...` |
| Login rechaza usuarios creados | BD de usuarios en otra base/instancia | Verificar que dashboard y `cli` usan el mismo `config.json` |
| "password_actual_incorrecta" al cambiar | Campo actual mal | Usar la password vigente (o resetear por CLI) |
| Trigger "already_running" (409) | Hay una corrida activa o huérfana | Esperar; si es huérfana (>60 min) se marca como failed sola |
| Scheduler pospuesto (42) siempre | La corrida activa es lenta o quedó `running` | Ver `etl_execution.status`; los huérfanos vencen a los 60 min |
| Dashboard no levanta | `ETL_SECRET` ausente o config inválido | `journalctl -u etl-dashboard`; verificar `.env` y `config.json` |
| Botón Sincronizar falla | SDK SAP no heredado por el servicio | `SAPNWRFC_HOME`/`LD_LIBRARY_PATH` en `<etl-dir>/.env`; reiniciar servicio |
| Puerto 8000 ocupado | Otro proceso | Cambiar `--port` en `etl-dashboard.service` |

## 9. Configuración

Variables de entorno (en `<etl-dir>/.env`, modo 600):

| Variable | Default | Descripción |
|----------|---------|-------------|
| `ETL_SECRET` | — (obligatorio) | Clave HMAC de las sesiones JWT; la genera `install.sh` |
| `ETL_TOKEN_TTL_HOURS` | `12` | Vigencia de la sesión |
| `ETL_CONFIG` | `config.json` | Ruta del config del cliente (dashboard y scheduler) |
| `ETL_LIVE_FILE` | `/tmp/etl_live.json` | Estado en vivo compartido runner/dashboard |
| `SAPNWRFC_HOME` | `/opt/sap/nwrfcsdk` | SDK SAP para extracción y para el botón Sincronizar |
| `LD_LIBRARY_PATH` | — | Normalmente `$SAPNWRFC_HOME/lib` |

SDK SAP y `pyrfc` (extracción SAP):

```bash
# 1) Montar/copiar el SDK NW RFC en /opt/sap/nwrfcsdk (licenciado por SAP)
# 2) Instalar el binding en el venv (o con el instalador: --with-sap)
cd /opt/etl/tablas_linux
sudo -u etl ./venv/bin/pip install /ruta/al/wheel/pyrfc-*.whl
# 3) Reiniciar el dashboard para que el botón Sincronizar herede el SDK
sudo systemctl restart etl-dashboard
```

`config.json` (del cliente): fuente (SAP/CSV/Excel), BD destino (sqlite/
mssql/postgresql/mysql), tablas, campos, guard de tablas grandes y visión
derivada. Ver `config.example.json`.

## 10. Rutas y seguridad

Públicas:

- `GET /login` — página de login
- `GET /api/health` — healthcheck
- `GET /api/auth/login` — login (cookie `etl_session`, HttpOnly, SameSite=Lax)
- `GET /static/*` — assets

Requieren sesión (`user`): `/inventario`, `/api/auth/me`,
`/api/auth/password`, `/api/auth/logout`, `/api/last-sync`,
`/api/etl/trigger`, `/api/live`, `/api/inventory*`.

Requieren `admin`: `/etl`, `/panel`, `/api/executions`, `/api/progress`,
`/api/dashboard`, `/api/tables`, `/api/admin/users*`.

Notas de seguridad:

- El secreto `ETL_SECRET` vive en `.env` (modo 600) y jamás se expone.
- Las passwords se guardan con bcrypt (costo 12).
- Root no se borra ni degrada por CLI ni por la API; solo root cambia su
  password (el instalador la obliga en el primer login).
- `ETL_COOKIE_SECURE` puede activarse cuando el dashboard se sirva por HTTPS
  (detrás de un proxy).

## 11. Emitir una licencia para un cliente

Flujo operativo completo para dar de alta un cliente con licencia en el
servidor de Novus. Requiere acceso al servidor donde corre el license server.

### 1. Generar el par de claves ed25519 (una sola vez)

```bash
NOVUS_LICENSE_SERVER_SECRET=<pepper-secreto> \
  .venv/bin/python -m license_server.cli keygen
```

Esto crea `license_server/private_key.pem` (privada, chmod 600) y
`licensing/novus_public.pem` (pública, se copia al cliente).

### 2. Registrar el cliente

```bash
NOVUS_LICENSE_SERVER_SECRET=<pepper-secreto> \
  .venv/bin/python -m license_server.cli customer add \
    --id empresa_001 \
    --name "Mi Empresa" \
    --api-key <clave-api-secreta>
```

### 3. Emitir la licencia

```bash
NOVUS_LICENSE_SERVER_SECRET=<pepper-secreto> \
  .venv/bin/python -m license_server.cli license issue \
    --customer empresa_001 \
    --license-id NOVUS-001 \
    --valid-until 2026-09-01 \
    --modules derived dashboard \
    --limit users=5
```

La CLI imprime el token JWT. Guardarlo de forma segura (el cliente lo
necesita solo si activa manualmente; normalmente se obtiene vía API).

### 4. Arrancar el license server

```bash
NOVUS_LICENSE_SERVER_SECRET=<pepper-secreto> \
  ./scripts/run_license_server.sh
```

Escucha en `127.0.0.1:8080` (configurable con `HOST`/`PORT`).

### 5. Configurar el cliente

En el `config.json` del cliente, agregar el bloque `license`:

```json
{
  "license": {
    "server": "https://licencias.novusit.cl",
    "customer_id": "empresa_001",
    "api_key": "<clave-api-secreta>",
    "public_key": "licensing/novus_public.pem"
  }
}
```

Copiar `licensing/novus_public.pem` al directorio del cliente.

### 6. Verificar en el cliente

```bash
# Estado de la licencia
etl license status

# Forzar activación (si no hay caché aún)
etl license activate
```

### troubleshooting rápido

| Síntoma | Causa | Acción |
|---------|-------|--------|
| `activación rechazada (401)` | API key incorrecta | Verificar `api_key` en config y en el servidor |
| `sin_licencia_activa` | No se emitió licencia para ese cliente | `license issue --customer ...` en el servidor |
| `licencia_vencida` | `valid_until` pasó | Renovar: `license renew --license-id ... --valid-until ...` |
| `modulo_no_contratado` | El módulo no está en `--modules` | Reemitir con los módulos necesarios |
| `no se pudo contactar el servidor` | Servidor caído o firewall | Verificar conectividad; el caché local mantiene el servicio durante `offline_until` |
