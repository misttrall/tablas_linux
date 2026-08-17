# Protección de Propiedad Intelectual (IP) y Asistente de Onboarding Web

Fecha: 2026-08-17 · Estado: aprobado · Rama: dev · Espec padre: `2026-08-16-licenciamiento-product.md`

---

## 1. Alcance de Protección de Arquitectura y Código (Fases Finales)

Para entregas en infraestructura de cliente (on-premise o VM privada), la plataforma Novus implementa una estrategia de defensa en profundidad para blindar el código fuente, la propiedad intelectual y evitar copias no autorizadas:

```
┌────────────────────────────────────────────────────────────────────────┐
│ ESTRATEGIA DE BLINDAJE DE PROPIEDAD INTELECTUAL NOVUS                  │
│                                                                        │
│ 1. Compilación C (Cython / Nuitka)                                     │
│    • Módulos core (.py) compilados a binarios nativos C (.so en Linux) │
│    • Inexistencia de archivos .py en la imagen Docker entregada.       │
│                                                                        │
│ 2. Machine Binding / Node-Locking (Criptografía Ed25519)              │
│    • La licencia incluye en sus claims el identificador único del      │
│      host (Machine UUID / CPUID / HostID).                             │
│    • Si el contenedor se clona a otra VM, se bloquea automáticamente.  │
│                                                                        │
│ 3. Distribución por Registry Privado                                   │
│    • El cliente solo descarga imágenes precompiladas autenticadas      │
│      desde registry.novusit.cl (sin acceso al repositorio Git).        │
│                                                                        │
│ 4. Validación Criptográfica en la Nube (Heartbeat)                     │
│    • El License Server en lic.novusit.cl custodia la clave privada     │
│      Ed25519. El cliente solo posee la clave pública de verificación.  │
└────────────────────────────────────────────────────────────────────────┘
```

### 1.1 Pipeline de Compilación a Binarios C (`.so`)
En el pipeline de Release/Build para producción:
1. Las carpetas propietarias (`licensing/`, `derived/`, `bi/`, `db/sinks/`, `sources/`) se compilan mediante Cython a bibliotecas compartidas de C (`*.so`).
2. Se eliminan todos los archivos fuente `.py` y comentarios.
3. El entrypoint de Python importa directamente los módulos `.so` compilados a nivel de lenguaje de máquina x86_64.

### 1.2 Vinculación de Hardware (Machine Binding)
1. El cliente envía su `machine_id` (generado desde `/etc/machine-id` o `systemd-id128`).
2. El License Server firma el JWT incorporando el claim `"hw_uuid": "<hash>"`.
3. `LicenseManager.get_license()` valida que `current_machine_id() == token.hw_uuid`.

---

## 2. Asistente de Configuración Inicial (Onboarding UI Wizard)

### 2.1 Principio de Separación de Responsabilidades
- **Novus entrega:** Mapeos de tablas, fórmulas de cálculo, vistas derivadas, manifiestos Power BI y configuración de licenciamiento.
- **TI del Cliente aporta:** Exclusivamente sus credenciales privadas de conexión a su red interna (SAP Host, Mandante, Usuario RFC, Password).

### 2.2 Arquitectura del Wizard Web
```
 NAVEGADOR DEL ADMINISTRADOR (TI)
┌────────────────────────────────────────────────────────────────────────┐
│  Panel Admin / ETL (/panel /etl)                                       │
│  [ ⚙️ Conexión Origen SAP ]                                            │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Asistente Modal de Configuración SAP                             │  │
│  │  • Host/IP, Nº Sistema, Mandante, Usuario, Password              │  │
│  │  • [ 🔌 Probar Conexión ] ➔ POST /api/onboarding/test-sap       │  │
│  │  • [ Guardar y Sincronizar ] ➔ POST /api/onboarding/save-sap    │  │
│  └──────────────────────────────────┬───────────────────────────────┘  │
└─────────────────────────────────────┼──────────────────────────────────┘
                                      │
                                      ▼
 FASTAPI BACKEND (dashboard/app.py)
┌────────────────────────────────────────────────────────────────────────┐
│ • GET  /api/onboarding/status   ➔ Verifica si SAP está configurado     │
│ • POST /api/onboarding/test-sap ➔ Ping RFC en vivo con medición de ms │
│ • POST /api/onboarding/save-sap ➔ Actualiza atómicamente config.json   │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Contrato de APIs de Onboarding
- **`GET /api/onboarding/status`** (Admin only):
  - Respuesta: `{"configured": bool, "type": "sap", "ashost": str, "sysnr": str, "client": str, "user": str, "lang": str}`. (Nunca expone el password).
- **`POST /api/onboarding/test-sap`** (Admin only):
  - Body: `{"ashost": str, "sysnr": str, "client": str, "user": str, "passwd": str, "lang": str}`.
  - Respuesta: `{"ok": bool, "latency_ms": float, "message": str, "error": str | None}`.
- **`POST /api/onboarding/save-sap`** (Admin only):
  - Body: `{"ashost": str, "sysnr": str, "client": str, "user": str, "passwd": str, "lang": str}`.
  - Respuesta: `{"ok": True, "message": "Conexión SAP guardada correctamente"}`.
