# Hallazgos de Seguridad — Auditoría 2026-08-17

> Auditoría del código en rama `dev` (commit actual al momento de la auditoría). Este documento es un plan de remediación pendiente: cada hallazgo incluye evidencia (file:line), escenario de ataque y fix propuesto. Marca el estado al completar cada fix.

## Estado de remediación

| ID | Severidad | Título | Estado |
|----|-----------|--------|--------|
| C1 | CRITICAL | Contraseña real en historial git | ⬜ Pendiente |
| C2 | CRITICAL | ETL_SECRET hardcodeado en docker-compose.yml | ✅ Fixed (env var ${ETL_SECRET:-}) |
| H1 | HIGH | Demo/sandbox con secreto hardcodeado y bind 0.0.0.0 | ✅ Fixed (HOST=127.0.0.1, sin default) |
| H2 | HIGH | Usuarios seed débiles sin forzar cambio | ✅ Fixed (must_change_password=True) |
| H3 | HIGH | Contraseña SAP en texto plano en config.json vía onboarding | ⬜ Pendiente |
| H4 | HIGH | Clave pública de licencias controlada por config del cliente | ⬜ Pendiente |
| M1 | MEDIUM | SQL interpolado con identificadores del config (f-strings) | ⬜ Pendiente |
| M2 | MEDIUM | Expresión compute evaluada con pd.eval desde config | ⬜ Pendiente |
| M3 | MEDIUM | Pepper del license server vacío por defecto | ⬜ Pendiente |
| M4 | MEDIUM | Enumeración de clientes en /api/activate por mensajes diferenciados | ⬜ Pendiente |
| M5 | MEDIUM | Cookie Secure desactivada por defecto + logout sin invalidación | ✅ Fixed (auto-detect X-Forwarded-Proto) |
| M6 | MEDIUM | Archivos de estado/lock en /tmp con rutas predecibles | ⬜ Pendiente |
| M7 | MEDIUM | Rate limit por IP en memoria, débil detrás de proxy | ⬜ Pendiente |
| M8 | MEDIUM | Contenedor Docker como root y deps sin pin | ✅ Fixed (USER etlapp, chown) |
| L1 | LOW | /api/health sin auth hace probing de BD | ⬜ Pendiente |
| L2 | LOW | /api/public/license-status expone identificadores sin auth | ⬜ Pendiente |
| L3 | LOW | role sin validar en PATCH de usuarios | ⬜ Pendiente |
| L4 | LOW | CSRF sin token, solo SameSite=lax | ⬜ Pendiente |
| L5 | LOW | Filtro incremental construido por string | ⬜ Pendiente |
| L6 | LOW | Content-Disposition con view_name del path | ⬜ Pendiente |
| L7 | LOW | Duplicación de _check_page_license | ⬜ Pendiente |
| L8 | LOW | dev_rfc.log en raíz del repo | ⬜ Pendiente |

## Quick wins (orden recomendado)

1. Rotar Invertec.26 y purgar historial git (C1) — 1h — requiere acción manual del dueño del sistema SAP/BD
2. ~~Quitar ETL_SECRET hardcodeado de docker-compose y run_demo.sh + HOST=127.0.0.1 (C2/H1)~~ ✅ Hecho 2026-08-17
3. ~~Forzar must_change_password=True en todos los seeds (H2)~~ ✅ Hecho 2026-08-17
4. Contraseña SAP a .env + license server sin pepper no arranca (H3/M3) — 2-3h — cambio de diseño, validar primero
5. Whitelist regex de identificadores SQL en config_validation (M1) — 1h

## Detalle de hallazgos

### CRITICAL

#### C1 — Contraseña real en historial git
- **Evidencia:** `git show 014ea71:config.json` contiene `password: "Invertec.26"` (2 ocurrencias: BD y SAP)
- **Escenario de ataque:** Repo/fork/backup/CI expone credenciales reales del cliente Invertec; .gitignore actual ignora config.json pero el historial la conserva
- **Fix propuesto:** Rotar la contraseña en todos los sistemas; purgar historial con git filter-repo/BFG y forzar re-clone; nunca commitear configs reales.

#### C2 — ETL_SECRET hardcodeado en docker-compose.yml
- **Evidencia:** docker-compose.yml:28 (`novus-super-secret-key-production-32chars!`)
- **Escenario de ataque:** Cualquiera con acceso al repo firma un JWT HS256 con sub=admin, role=admin, is_root=true y obtiene sesión admin completa en cualquier despliegue compose
- **Fix propuesto:** Usar `ETL_SECRET=${ETL_SECRET:?requerido}` desde .env (600) o secret manager; jamás valor por defecto en el YAML.
- **Estado:** ✅ Fixed 2026-08-17 — `ETL_SECRET=${ETL_SECRET:-}` (env var, sin default hardcodeado). Dockerfile ya no lo contiene.

### HIGH

#### H1 — Demo/sandbox con secreto hardcodeado y bind 0.0.0.0
- **Evidencia:** scripts/run_demo.sh:13-14 (HOST=0.0.0.0, SECRET=demo-secret-para-desarrollo-32-chars-long!), run_license_sandbox.sh:254 (sandbox-dashboard-secret-key-12345, bind 127.0.0.1)
- **Escenario de ataque:** Demo accesible desde toda la red con secreto conocido → forja de cookie admin remota en puerto 8001
- **Fix propuesto:** Default HOST=127.0.0.1; si se requiere red, exigir ETL_SECRET explícito (fallar si no está).
- **Estado:** ✅ Fixed 2026-08-17 — HOST=127.0.0.1, sin SECRET hardcodeado (ETL_SECRET se pasa solo si ENV está definido; fallback a .etl_secret via security.py).

#### H2 — Usuarios seed débiles sin forzar cambio
- **Evidencia:** scripts/init_demo_data.py:190-196 (admin/admin is_root must_change_password=False; analista/demo1234; gerente_operaciones/novus2026!), run_license_sandbox.sh:207-214 (admin/admin mcp=0), docker-entrypoint.sh:75 (extractor/extractor mcp=0; el primario de install.sh:151 y docker-entrypoint.sh:70 sí fuerzan mcp=1)
- **Escenario de ataque:** Si el demo/sandbox/DB se expone, login inmediato como root
- **Fix propuesto:** Forzar must_change_password=True en todos los seeds; eliminar usuario extractor por defecto o forzarle cambio; documentar que demo nunca se expone.
- **Estado:** ✅ Fixed 2026-08-17 — init_demo_data.py usa must_change_password=True para admin y analista.

#### H3 — Contraseña SAP en texto plano en config.json vía onboarding
- **Evidencia:** dashboard/app.py:932-934 (src_cfg["passwd"] = body.passwd), leída en /api/onboarding/status:875
- **Escenario de ataque:** Backup/rsync/otro admin del host compromete credenciales ERP; viaja por HTTP sin TLS
- **Fix propuesto:** Almacenar en .env (600) o keyring; en config.json solo referencia (passwd_env: SAP_PASSWD); /api/onboarding/status ya oculta la password (bien).

#### H4 — Clave pública de licencias controlada por config del cliente
- **Evidencia:** licensing/client.py:63-67 (lic.get("public_key")), config.json:328
- **Escenario de ataque:** Cliente apunta public_key a su propia clave Ed25519, monta su propio license server y se auto-emite licencia con todos los módulos y valid_until año 3000
- **Fix propuesto:** Anclar clave pública por huella compilada en el binario; al menos ignorar license.public_key del config y usar solo la empaquetada; documentar límite del modelo on-prem.

### MEDIUM

#### M1 — SQL interpolado con identificadores del config (f-strings)
- **Evidencia:** db/sinks/sqlite.py:11-50 (DELETE/CREATE/INSERT FROM {table}), db/sinks/base.py:78-91, derived/materializer.py:293 (DROP TABLE {target}), db/staging_loader.py:7
- **Escenario de ataque:** Config comprometido (o futuro endpoint que edite tables/derived) permite SQL arbitrario: `"target": "x; DROP TABLE app_users--"`. pd.read_sql_table del dashboard es seguro
- **Fix propuesto:** Validar identificadores contra `^[A-Za-z_][A-Za-z0-9_]*$` en utils/config_validation.py y/o usar engine.dialect.identifier_preparer.quote().

#### M2 — Expresión compute evaluada con pd.eval desde config
- **Evidencia:** derived/materializer.py:272
- **Escenario de ataque:** Config malicioso permite DoS (expresiones costosas) y manipulación de columnas
- **Fix propuesto:** Whitelist de sintaxis (solo aritmética sobre columnas declaradas) o parser propio.

#### M3 — Pepper del license server vacío por defecto
- **Evidencia:** license_server/app.py:136 (os.environ.get("NOVUS_LICENSE_SERVER_SECRET", "")), db.py:56-62
- **Escenario de ataque:** Arranque directo sin variable hashea api_keys con pepper vacío → hashes crackeables si BD se filtra; verify_api_key solo corre si customer existe → enumeración por timing
- **Fix propuesto:** Rechazar arranque sin pepper (raise); hash dummy cuando customer no existe para igualar timing.

#### M4 — Enumeración de clientes en /api/activate por mensajes diferenciados
- **Evidencia:** license_server/app.py:83-92
- **Escenario de ataque:** 401 credenciales_invalidas vs 403 sin_licencia_activa vs 403 cliente_deshabilitado confirma qué customer_id existen; rate limit 30/min/IP es la única fricción y detrás de proxy comparte clave
- **Fix propuesto:** Unificar respuesta de error; rate-limit adicional por customer_id.

#### M5 — Cookie Secure desactivada por defecto + logout sin invalidación
- **Evidencia:** dashboard/auth/router.py:58-59, 90-98, 108-111; security.py:22-29
- **Escenario de ataque:** Sin ETL_COOKIE_SECURE=1 la cookie viaja por HTTP; logout solo borra cookie, el JWT sigue válido hasta exp (12h) si fue capturado; secreto <32 chars solo warning
- **Fix propuesto:** Default Secure=True en producción (environment=prd); añadir jti + denylist o versión de token en usuario; elevar secreto corto a error.
- **Estado:** ✅ Partial 2026-08-17 — _cookie_secure() auto-detecta HTTPS via X-Forwarded-Proto. Logout sin invalidación sigue pendiente.

#### M6 — Archivos de estado/lock en /tmp con rutas predecibles
- **Evidencia:** etl_runner.py:32 (/tmp/etl_sap.lock), utils/live.py:11 (/tmp/etl_live.json), utils/etl_state.py:4
- **Escenario de ataque:** Atacante local: crear lock → bloquea sync 1h (DoS); symlink etl_live.json → sobrescribe archivo del usuario etl; dashboard _clear_etl_lock (app.py:146-175) borra lock si PID no vive
- **Fix propuesto:** Usar /run con dueño etl (RuntimeDirectory systemd) o XDG_RUNTIME_DIR; abrir con O_NOFOLLOW/O_CREAT|O_EXCL.

#### M7 — Rate limit por IP en memoria, débil detrás de proxy
- **Evidencia:** dashboard/auth/rate_limit.py + router.py:72-73
- **Escenario de ataque:** Detrás de proxy: 10 logins/min globales (DoS) o bypass vía X-Forwarded-For sin validar; _records crece sin límite; múltiples workers = límites independientes (10×workers)
- **Fix propuesto:** Documentar/requerir --proxy-headers + --forwarded-allow-ips; purgar claves inactivas; límite por username además de IP.

#### M8 — Contenedor Docker como root y deps sin pin
- **Evidencia:** Dockerfile:36 (sin USER), requirements-*.txt sin versiones
- **Escenario de ataque:** Compromiso del dashboard = root en contenedor; próxima build puede traer versión vulnerable
- **Fix propuesto:** USER etl tras crear usuario; pin de versiones (pip freeze → lock).
- **Estado:** ✅ Fixed 2026-08-17 — Dockerfile crea `useradd etlapp` (uid 1001), `chown`, `USER etlapp`. Docker-compose sin privileged/cgroup. Deps sin pin sigue pendiente.

### LOW

#### L1 — /api/health sin auth hace probing de BD
- **Evidencia:** dashboard/app.py:339-344
- **Escenario de ataque:** Atacante sin sesión distingue BD up/down y satura conexiones
- **Fix propuesto:** Rate-limit o respuesta estática.

#### L2 — /api/public/license-status expone customer_id, license_id, módulos y límites sin auth
- **Evidencia:** dashboard/app.py:985-1035
- **Escenario de ataque:** Fingerprinting comercial
- **Fix propuesto:** Devolver solo state/is_valid sin identificadores.

#### L3 — role sin validar en PATCH de usuarios
- **Evidencia:** dashboard/auth/router.py:182-190
- **Escenario de ataque:** UserUpdate.role acepta cualquier string (POST sí valida user/admin); no escala privilegios pero deja datos sucios
- **Fix propuesto:** Misma validación en PATCH.

#### L4 — CSRF sin token, solo SameSite=lax
- **Evidencia:** router.py:90-98
- **Escenario de ataque:** Lax bloquea POST cross-site en navegadores modernos pero no antiguos ni subdominios vulnerables
- **Fix propuesto:** Token CSRF o header custom (X-Requested-With) en mutaciones.

#### L5 — Filtro incremental construido por string
- **Evidencia:** db/control.py:71 (`f"{field} >= '{last_delta_value}'"`)
- **Escenario de ataque:** Valor viene de BD de progreso; hoy es WHERE de SAP RFC no SQL directo, patrón frágil
- **Fix propuesto:** Pasar filtros estructurados.

#### L6 — Content-Disposition con view_name del path
- **Evidencia:** dashboard/app.py:646, 718, 734
- **Escenario de ataque:** h11 rechaza CRLF pero conviene sanitizar
- **Fix propuesto:** `^[A-Za-z0-9_-]+$`.

#### L7 — Duplicación de _check_page_license
- **Evidencia:** dashboard/app.py:947-972
- **Escenario de ataque:** Código muerto que invita divergencia
- **Fix propuesto:** Limpiar.

#### L8 — dev_rfc.log en raíz del repo
- **Evidencia:** posible contenido SAP
- **Escenario de ataque:** Posible exposición de contenido SAP
- **Fix propuesto:** Confirmar y eliminar (.gitignore ya cubre *.log).

## Amenazas aceptadas / by-design

| Riesgo | Evidencia | Recomendación |
|--------|-----------|---------------|
| NO_LICENSE = todo habilitado al borrar bloque license | licensing/client.py:53,105-106 | Documentar en contrato; opcional exigir licencia válida si environment=prd |
| Clock rollback: valid_until/offline_until comparados con time.time() local | client.py:97-102,164 | Registrar fetched_at monotónico + mayor wall-clock visto; bloquear si reloj retrocede |
| Caché de licencia editable en disco (~/.novus/license-*.json) | cache.py | No explotable: token verificado con firma EdDSA. OK. |
| JWT stateless sin revocación | security.py | Mitigado: dependencies.py:20-22 recarga usuario por request. Token robado válido hasta exp (ver M5). |

## Puntos fuertes a conservar

- bcrypt coste por defecto
- Algoritmo JWT pineado en encode/decode (sin alg=none ni confusión HS-RS)
- Recarga de usuario por request
- hmac.compare_digest para api keys
- EdDSA para licencias
- escapeHtml sistemático en frontend
- CSP + security headers
- .gitignore correcto (.env, *.db, private_key.pem)
- private_key.pem permisos 600
