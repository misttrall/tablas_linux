# Licenciamiento / product: módulos opt-in, servidor de licencias y gracia offline

Fecha: 2026-08-16 · Estado: aprobado · Rama: dev · Espec hijo: `2026-08-15-entregable-bi-white-label-design.md`

## Decisión de negocio (contexto)

Novus es una plataforma de integración y explotación de datos. La arquitectura separa:

- **Core/ETL**: extracción, carga y mantenimiento de datos (nunca se deja de actualizar).
- **Derived/Data**: transformación de datos en información de valor (DWH, vistas, Excel).
- **Dashboard**: visualización web white-label.
- **BI**: integración y entregables para Power BI.
- **Licensing**: control centralizado de módulos, vigencia y capacidades contratadas.

Cada cliente contrata solo las capacidades que necesita, con un único motor Novus.
El Core/ETL **no se licencia individualmente** (evita que un dashboard quede desactualizado
por una dependencia de licencia ETL); `derived`, `dashboard` y `bi` son **módulos opt-in**.
La arquitectura debe soportar licenciar ETL en el futuro sin tocar el motor.

Decisión tomada en brainstorming (2026-08-16):

1. **Activación online**: el engine activa contra un servidor de licencias por HTTPS.
2. **Servidor construido en este repo**: `license_server/` (FastAPI + BD propia).
3. **Gracia offline**: token firmado cacheado con `valid_until` + `offline_until`;
   sin internet se opera hasta el vencimiento y se revalida al reconectar.
4. **Catálogo**: núcleo incluido (`etl`, `users`) + opt-in `derived`, `dashboard`, `bi`.
5. **Identidad**: `customer_id` + `api_key` (secreto por cliente) contra el servidor.
6. **Límites**: solo `users` se enforcea en esta fase; la API soporta `sources`/`refreshes`/`dashboards` a futuro.
7. **Estructura**: se añade `licensing/` y `license_server/` **sin reescructurar** el repo plano actual.
8. **Sin bloque `license` en config** → modo sin licenciar: todos los módulos habilitados
   (desarrollo/CI; no bloquea la suite existente).

## Alcance (Fase 2)

- **`license_server/`**: servidor que emite y valida licencias firmadas (JWT ed25519),
  con BD SQLite (customers, licenses, license_modules, license_limits, license_events),
  endpoint `POST /api/activate` y CLI de gestión interna.
- **`licensing/`**: cliente embebido (activación, caché firmada, estados, enforcement
  de módulos y del límite de usuarios).
- **Enforcement**: `derived` (reporte, bootstrap `--with-derived`, materialización en
  `etl_runner`), `dashboard` (páginas/endpoints del panel web), `bi` (`cli bi`),
  límite `users` (creación en `cli users add` y `POST /api/admin/users`).
- **CLI**: `cli license {status|activate|validate|clear-cache}`.
- **Config**: bloque `license` opcional en `config.schema.json` y `config.example.json`.

Fuera de alcance: enforcement de `sources`/`refreshes`/`dashboards`, protección contra
manipulación de reloj, API admin REST (solo CLI), servidor multi-DB, provisionamiento automático.

## Principio rector

**El ETL mantiene los datos. Derived crea el valor. Dashboard y BI entregan ese valor.
Licensing determina qué capacidades puede utilizar cada cliente.** El bloqueo nunca
elimina ni daña datos existentes: un módulo bloqueado conserva la información ya generada.

## Arquitectura

```
license_server/ (NOVUS)            NOVUS ENGINE (cliente)
┌─────────────────────────┐        ┌──────────────────────────────┐
│ FastAPI /api/activate   │ HTTPS  │ licensing/                    │
│ License DB (SQLite)     │◄──────►│  - client.py (activación)     │
│ ed25519 privada         │  JWT   │  - validator.py (pub PEM)     │
│ license_server/cli.py   │        │  - cache.py  (~/.novus/...)   │
└─────────────────────────┘        └──────┬───────────────────────┘
                                          │ gates
                                          ▼
                 cli run (core) · reporte/derived · dashboard · cli bi
```

## Estados de licencia

| Estado | Condición |
|---|---|
| **ACTIVE** | `now <= valid_until` y firma válida (online u offline) |
| **GRACE** | `valid_until < now <= offline_until` y sin conexión (cache firma válida) |
| **EXPIRED** | `now > offline_until`, o el servidor responde expirada al reconectar |
| **SUSPENDED / REVOKED** | el servidor responde así al activar (solo se sabe online) |
| **NO_LICENSE** | sin bloque `license` en config (modo dev: todo habilitado) |

`offline_until = valid_until + grace_days` (lo calcula el servidor; `grace_days`
configurable por licencia, default 7). El engine re-activa si el cache está vencido o
tiene más de `license.refresh_minutes` (default 720). Falla de red + cache válido →
ACTIVE/GRACE. Falla + sin gracia → bloquea los módulos.

## Módulos y gating

| Operación | Módulo |
|---|---|
| `cli run` (extracción+carga) | — (core, incluido) |
| `cli reporte`, `bootstrap --with-derived`, materialización en `etl_runner` | **derived** |
| Páginas `/derivadas` + `/api/derived-views` + `/api/derived/*` + `/api/inventory*` | **dashboard** |
| `cli bi manifest\|export\|guide` | **bi** |
| `/etl`, `/panel`, `/api/admin/users` (gestión) | — (herramienta interna Novus) |
| `cli users add`, `POST /api/admin/users` (crear) | límite **users** |

- Módulo bloqueado en CLI → `LicenseError` con mensaje accionable, exit≠0.
- En dashboard → página de aviso / 403, banner global persistente; los datos se conservan.
- `etl_runner` omite la materialización con warning si `derived` no está contratado
  (el run core sigue teniendo éxito).

## Firmas y seguridad

- **JWT EdDSA (ed25519)** vía PyJWT (`algorithm="EdDSA"`, backend `cryptography`).
- Clave privada solo en `license_server` (generada con `license_server/cli.py keygen`,
  PEM en `license_server/private_key.pem`, gitignored). El engine embebe la pública
  (`licensing/novus_public.pem` bundled; `license.public_key` permite reemplazarla).
- Claims: `customer_id`, `license_id`, `status`, `valid_from`, `valid_until`,
  `offline_until`, `modules` (dict), `limits` (dict), `iat`, `exp` (= `offline_until`).
- `api_key` del cliente guardada en el servidor como HMAC-SHA256 + pepper
  (`NOVUS_LICENSE_SERVER_SECRET`); comparación con `hmac.compare_digest`.
- El engine no modifica `valid_until`/`modules`/`limits`: cualquier cambio invalida la firma.

## Config (opcional)

```json
"license": {
  "server": "https://lic.novusit.cl",
  "customer_id": "empresa_001",
  "api_key": "<secreto del cliente>",
  "public_key": "opcional, ruta PEM; default bundled",
  "cache_path": "opcional; default ~/.novus/license-<customer_id>.json",
  "refresh_minutes": 720
}
```

## CLI (cliente y servidor)

- `cli license status` · `cli license activate` · `cli license validate` · `cli license clear-cache`
- `python -m license_server.cli keygen` · `customer add|list|disable` ·
  `license issue|renew|revoke|suspend|show`

## Testing

- Firma/verificación (clave correcta/incorrecta, expirada, tamper).
- Estados ACTIVE/GRACE/EXPIRED y cache (hit/vencido/corrupto).
- `POST /api/activate`: 200, 401 (api_key mal), 403 (suspendida/revocada/sin activa).
- Gating: `reporte`/`bi` bloqueados sin módulo; `users add` más allá del límite;
  dashboard bloqueado (403/banner); `etl_runner` omite derived sin licencia.
- Modo sin licencia: suite existente intacta.
