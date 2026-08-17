#!/usr/bin/env python3
"""Simulador de Licenciamiento y Entorno de Pruebas (Novus BI Platform).

Permite recrear de forma determinista y reproducible los 12 escenarios de licenciamiento,
generar tokens al vuelo, inyectar estados en caché, arrancar servidores efímeros
y ejecutar la suite de validación matricial completa.

Uso:
    python scripts/simulate_licensing.py run-all [--md] [--json]
    python scripts/simulate_licensing.py scenario <E01..E12> [--config PATH]
    python scripts/simulate_licensing.py token [--modules derived,dashboard] [--limits users=5]
    python scripts/simulate_licensing.py server [--port 8082]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Añadir raíz del proyecto al sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
import jwt

from licensing.cache import cache_path, save_cache
from licensing.client import (
    LicenseError,
    LicenseBlocked,
    LicenseInvalid,
    LicenseNotEntitled,
    LicenseUnreachable,
    get_manager,
    LicenseManager,
)
from licensing.models import LicenseState
from licensing.validator import verify_token
from license_server.signing import sign_claims
from utils.config_loader import load_config

DAY = 86400

# Claves por defecto
DEFAULT_PRIV_KEY_PATH = ROOT_DIR / "license_server" / "private_key.pem"
DEFAULT_PUB_KEY_PATH = ROOT_DIR / "licensing" / "novus_public.pem"


def generate_ephemeral_keypair():
    """Genera un par de claves Ed25519 en memoria."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    priv_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


def load_signing_keys(custom_priv=None, custom_pub=None, config_dict=None):
    """Carga claves existentes, co-ubicadas con el config, o genera un par efímero."""
    priv_bytes = None
    pub_bytes = None

    # Si hay config, buscar clave privada en el mismo directorio que la pública configurada
    if config_dict and not custom_priv:
        pub_path_cfg = config_dict.get("license", {}).get("public_key")
        if pub_path_cfg:
            pub_p = Path(pub_path_cfg)
            if pub_p.exists():
                pub_bytes = pub_p.read_bytes()
            sibling_priv = pub_p.parent / "private_key.pem"
            if sibling_priv.exists():
                priv_bytes = sibling_priv.read_bytes()

    priv_p = Path(custom_priv) if custom_priv else DEFAULT_PRIV_KEY_PATH
    pub_p = Path(custom_pub) if custom_pub else DEFAULT_PUB_KEY_PATH

    if not priv_bytes and priv_p.exists():
        priv_bytes = priv_p.read_bytes()
    if not pub_bytes and pub_p.exists():
        pub_bytes = pub_p.read_bytes()

    if not priv_bytes or not pub_bytes:
        ephem_priv, ephem_pub = generate_ephemeral_keypair()
        priv_bytes = priv_bytes or ephem_priv
        pub_bytes = pub_bytes or ephem_pub

    return priv_bytes, pub_bytes


# Catálogo de los 12 escenarios de licenciamiento
SCENARIOS = {
    "E01": {
        "title": "Licencia Completa Activa",
        "description": "Todos los módulos activos, vigencia futura, límite 10 usuarios",
        "status": "active",
        "valid_offset_days": +30,
        "grace_offset_days": +37,
        "modules": {"derived": True, "dashboard": True, "bi": True},
        "limits": {"users": 10},
        "expected_state": LicenseState.ACTIVE,
        "expect_derived": True,
        "expect_dashboard": True,
        "expect_bi": True,
        "expect_users_limit": 10,
    },
    "E02": {
        "title": "Licencia Modular: Solo Dashboard",
        "description": "Dashboard habilitado; derived y bi desactivados",
        "status": "active",
        "valid_offset_days": +30,
        "grace_offset_days": +37,
        "modules": {"derived": False, "dashboard": True, "bi": False},
        "limits": {"users": 5},
        "expected_state": LicenseState.ACTIVE,
        "expect_derived": False,
        "expect_dashboard": True,
        "expect_bi": False,
        "expect_users_limit": 5,
    },
    "E03": {
        "title": "Licencia Modular: Sin Dashboard",
        "description": "Derived y BI activos por CLI; Dashboard web bloqueado",
        "status": "active",
        "valid_offset_days": +30,
        "grace_offset_days": +37,
        "modules": {"derived": True, "dashboard": False, "bi": True},
        "limits": {"users": 5},
        "expected_state": LicenseState.ACTIVE,
        "expect_derived": True,
        "expect_dashboard": False,
        "expect_bi": True,
        "expect_users_limit": 5,
    },
    "E04": {
        "title": "Límite de Usuarios Alcanzado",
        "description": "Licencia activa restringida a máximo 2 usuarios",
        "status": "active",
        "valid_offset_days": +30,
        "grace_offset_days": +37,
        "modules": {"derived": True, "dashboard": True, "bi": True},
        "limits": {"users": 2},
        "expected_state": LicenseState.ACTIVE,
        "expect_derived": True,
        "expect_dashboard": True,
        "expect_bi": True,
        "expect_users_limit": 2,
    },
    "E05": {
        "title": "Período de Gracia (Grace Period)",
        "description": "valid_until vencido, pero dentro del rango offline_until",
        "status": "active",
        "valid_offset_days": -2,
        "grace_offset_days": +5,
        "modules": {"derived": True, "dashboard": True, "bi": True},
        "limits": {"users": 5},
        "expected_state": LicenseState.GRACE,
        "expect_derived": True,
        "expect_dashboard": True,
        "expect_bi": True,
        "expect_users_limit": 5,
    },
    "E06": {
        "title": "Licencia Vencida (Expired)",
        "description": "offline_until superado; sistema bloquea módulos protegidos",
        "status": "active",
        "valid_offset_days": -10,
        "grace_offset_days": -2,
        "modules": {"derived": True, "dashboard": True, "bi": True},
        "limits": {"users": 5},
        "expected_state": LicenseState.EXPIRED,
        "expect_derived": False,
        "expect_dashboard": False,
        "expect_bi": False,
        "expect_users_limit": 5,
    },
    "E07": {
        "title": "Licencia Suspendida",
        "description": "Estado suspended por Novus (ej. mora en pago)",
        "status": "suspended",
        "valid_offset_days": +30,
        "grace_offset_days": +37,
        "modules": {"derived": True, "dashboard": True, "bi": True},
        "limits": {"users": 5},
        "expected_state": LicenseState.SUSPENDED,
        "expect_derived": False,
        "expect_dashboard": False,
        "expect_bi": False,
        "expect_users_limit": 5,
    },
    "E08": {
        "title": "Licencia Revocada",
        "description": "Estado revoked por Novus (anulación inmediata)",
        "status": "revoked",
        "valid_offset_days": +30,
        "grace_offset_days": +37,
        "modules": {"derived": True, "dashboard": True, "bi": True},
        "limits": {"users": 5},
        "expected_state": LicenseState.REVOKED,
        "expect_derived": False,
        "expect_dashboard": False,
        "expect_bi": False,
        "expect_users_limit": 5,
    },
    "E09": {
        "title": "Servidor Inaccesible con Caché Válido",
        "description": "Corte de red hacia servidor; caché local permite operación",
        "status": "active",
        "valid_offset_days": +30,
        "grace_offset_days": +37,
        "modules": {"derived": True, "dashboard": True, "bi": True},
        "limits": {"users": 10},
        "expected_state": LicenseState.ACTIVE,
        "expect_derived": True,
        "expect_dashboard": True,
        "expect_bi": True,
        "expect_users_limit": 10,
    },
    "E10": {
        "title": "Servidor Inaccesible sin Caché",
        "description": "Servidor caído y sin archivo de caché previo (LicenseUnreachable)",
        "expected_state": None,  # Levanta LicenseUnreachable
        "expect_derived": False,
        "expect_dashboard": False,
        "expect_bi": False,
        "expect_users_limit": None,
    },
    "E11": {
        "title": "Manipulación / Firma Adulterada",
        "description": "Token modificado o firmado con clave ajena (LicenseInvalid)",
        "expected_state": None,  # Levanta LicenseInvalid
        "expect_derived": False,
        "expect_dashboard": False,
        "expect_bi": False,
        "expect_users_limit": None,
    },
    "E12": {
        "title": "Modo Sin Licencia (Open / Unmanaged)",
        "description": "Sin bloque license en config; acceso completo irrestricto",
        "expected_state": LicenseState.NO_LICENSE,
        "expect_derived": True,
        "expect_dashboard": True,
        "expect_bi": True,
        "expect_users_limit": None,
    },
}


def build_scenario_token(scenario_id: str, priv_pem: bytes, customer_id: str = "demo_test",
                         license_id: str = "NOVUS-TEST-001") -> tuple[str, dict]:
    """Construye los claims y genera el token firmado para un escenario."""
    sc = SCENARIOS.get(scenario_id)
    if not sc:
        raise ValueError(f"Escenario desconocido: {scenario_id}")

    now = int(time.time())

    if scenario_id == "E11":  # Firma adulterada con otra clave
        foreign_priv, _ = generate_ephemeral_keypair()
        claims = {
            "customer_id": customer_id,
            "license_id": license_id,
            "status": "active",
            "valid_from": now - DAY,
            "valid_until": now + 30 * DAY,
            "offline_until": now + 37 * DAY,
            "modules": {"derived": True, "dashboard": True, "bi": True},
            "limits": {"users": 10},
            "iat": now,
            "exp": now + 37 * DAY,
        }
        token = sign_claims(claims, foreign_priv)
        return token, claims

    valid_until = now + sc.get("valid_offset_days", 30) * DAY
    offline_until = now + sc.get("grace_offset_days", 37) * DAY

    claims = {
        "customer_id": customer_id,
        "license_id": license_id,
        "status": sc.get("status", "active"),
        "valid_from": now - DAY,
        "valid_until": valid_until,
        "offline_until": offline_until,
        "modules": sc.get("modules", {}),
        "limits": sc.get("limits", {}),
        "iat": now,
        "exp": offline_until,
    }
    token = sign_claims(claims, priv_pem)
    return token, claims


def inject_scenario_cache(config_path: str, scenario_id: str, priv_pem: bytes = None):
    """Inyecta directamente en el archivo de caché el estado del escenario dado."""
    from licensing.client import _MANAGERS
    _MANAGERS.clear()

    cfg = load_config(config_path)
    if priv_pem is None:
        priv_pem, _ = load_signing_keys(config_dict=cfg)
    cpath = cache_path(cfg)

    if scenario_id == "E10":  # Sin caché
        if os.path.exists(cpath):
            os.remove(cpath)
        return None, cpath

    if scenario_id == "E12":  # Modo sin licencia
        return None, None

    token, claims = build_scenario_token(scenario_id, priv_pem,
                                         customer_id=cfg.get("license", {}).get("customer_id", "demo_test"))
    data = {
        "claims": claims,
        "token": token,
        "fetched_at": int(time.time()),
    }
    save_cache(cpath, data)
    return data, cpath


def evaluate_scenario(scenario_id: str, priv_pem: bytes, pub_pem: bytes, tmp_dir: Path) -> dict:
    """Evalúa programáticamente un escenario de licenciamiento y reporta el resultado."""
    sc = SCENARIOS[scenario_id]
    now = time.time()
    cfg_file = tmp_dir / f"config_{scenario_id}.json"
    cache_file = tmp_dir / f"cache_{scenario_id}.json"
    pub_file = tmp_dir / f"pub_{scenario_id}.pem"
    pub_file.write_bytes(pub_pem)

    config_data = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_dir)}},
        "database": {"dialect": "sqlite", "database": str(tmp_dir / "db.sqlite")},
        "tables": [],
        "fields": {},
        "license": {
            "server": "http://127.0.0.1:59999",  # Servidor intencionalmente no reachable para aislar con caché
            "customer_id": f"cust_{scenario_id}",
            "api_key": "secret-key",
            "public_key": str(pub_file),
            "cache_path": str(cache_file),
            "refresh_minutes": 1440,
        }
    }

    if scenario_id == "E12":
        del config_data["license"]

    cfg_file.write_text(json.dumps(config_data, indent=2))
    cfg = load_config(str(cfg_file))
    mgr = LicenseManager(cfg)

    # Inyección de estado previo en caché según el escenario
    if scenario_id not in ("E10", "E12"):
        token, claims = build_scenario_token(scenario_id, priv_pem,
                                             customer_id=cfg.get("license", {}).get("customer_id", "cust_test"))
        save_cache(str(cache_file), {
            "claims": claims,
            "token": token,
            "fetched_at": int(now),
        })

    result = {
        "id": scenario_id,
        "title": sc["title"],
        "description": sc["description"],
        "passed": False,
        "state": None,
        "derived_ok": False,
        "dashboard_ok": False,
        "bi_ok": False,
        "users_limit": None,
        "error": None,
    }

    try:
        if scenario_id == "E10":
            # Debe fallar con LicenseUnreachable
            try:
                mgr.get_license()
                result["error"] = "Se esperaba LicenseUnreachable pero no falló"
                return result
            except LicenseUnreachable:
                result["passed"] = True
                result["error"] = "LicenseUnreachable (Esperado OK)"
                return result
            except Exception as e:
                result["error"] = f"Error inesperado: {type(e).__name__}: {e}"
                return result

        if scenario_id == "E11":
            # Debe fallar con LicenseInvalid al validar la firma adulterada
            try:
                mgr.validate()
                result["error"] = "Se esperaba LicenseInvalid pero validate() pasó"
                return result
            except LicenseInvalid:
                result["passed"] = True
                result["error"] = None
                return result
            except Exception as e:
                result["error"] = f"Error inesperado al validar firma: {type(e).__name__}: {e}"
                return result

        lic = mgr.get_license()
        st = lic.state(now)
        result["state"] = st.value
        result["users_limit"] = mgr.users_limit()

        # Comprobar gating de módulos
        for mod, attr in [("derived", "derived_ok"), ("dashboard", "dashboard_ok"), ("bi", "bi_ok")]:
            try:
                mgr.require(mod)
                result[attr] = True
            except (LicenseBlocked, LicenseNotEntitled):
                result[attr] = False

        # Validación de aserciones esperadas
        expected_st = sc["expected_state"]
        state_match = (st == expected_st) if expected_st else True
        derived_match = (result["derived_ok"] == sc["expect_derived"])
        dashboard_match = (result["dashboard_ok"] == sc["expect_dashboard"])
        bi_match = (result["bi_ok"] == sc["expect_bi"])
        limit_match = (result["users_limit"] == sc["expect_users_limit"])

        if state_match and derived_match and dashboard_match and bi_match and limit_match:
            result["passed"] = True
        else:
            mismatches = []
            if not state_match:
                mismatches.append(f"state: {st} vs exp {expected_st}")
            if not derived_match:
                mismatches.append(f"derived: {result['derived_ok']} vs exp {sc['expect_derived']}")
            if not dashboard_match:
                mismatches.append(f"dashboard: {result['dashboard_ok']} vs exp {sc['expect_dashboard']}")
            if not bi_match:
                mismatches.append(f"bi: {result['bi_ok']} vs exp {sc['expect_bi']}")
            if not limit_match:
                mismatches.append(f"limit: {result['users_limit']} vs exp {sc['expect_users_limit']}")
            result["error"] = " · ".join(mismatches)

    except Exception as e:
        result["error"] = f"Excepción no esperada: {type(e).__name__}: {e}"

    return result


def run_all_simulations(output_format="table"):
    """Ejecuta la matriz completa de los 12 escenarios y formatea la salida."""
    import tempfile
    priv_pem, pub_pem = load_signing_keys()

    with tempfile.TemporaryDirectory() as tmp_d:
        tmp_dir = Path(tmp_d)
        results = []
        all_ok = True

        for sc_id in sorted(SCENARIOS.keys()):
            res = evaluate_scenario(sc_id, priv_pem, pub_pem, tmp_dir)
            results.append(res)
            if not res["passed"]:
                all_ok = False

        if output_format == "json":
            print(json.dumps({"success": all_ok, "scenarios": results}, indent=2))
            return 0 if all_ok else 1

        if output_format == "md":
            print("# Reporte de Simulación de Licenciamiento Novus\n")
            print(f"Fecha: `{datetime.now(timezone.utc).isoformat()}`\n")
            print("| ID | Escenario | Estado | Derived | Dashboard | BI | Límite Users | Resultado |")
            print("|:---|:---|:---|:---:|:---:|:---:|:---:|:---:|")
            for r in results:
                st = r["state"] or "-"
                dev = "✅" if r["derived_ok"] else "❌"
                dash = "✅" if r["dashboard_ok"] else "❌"
                bi = "✅" if r["bi_ok"] else "❌"
                lim = str(r["users_limit"]) if r["users_limit"] is not None else "-"
                verdict = "🟢 **PASS**" if r["passed"] else f"🔴 **FAIL** ({r['error']})"
                print(f"| **{r['id']}** | {r['title']} | `{st}` | {dev} | {dash} | {bi} | {lim} | {verdict} |")
            print(f"\n**Resultado General:** {'🟢 Todos los escenarios pasaron exitosamente.' if all_ok else '🔴 Se detectaron discrepancias.'}")
            return 0 if all_ok else 1

        # Formato consola (ANSI)
        c_green = "\033[92m"
        c_red = "\033[91m"
        c_yellow = "\033[93m"
        c_bold = "\033[1m"
        c_reset = "\033[0m"

        print(f"\n{c_bold}════════════════════════════════════════════════════════════════════════════════════{c_reset}")
        print(f"{c_bold}  MATRIZ DE SIMULACIÓN DE LICENCIAMIENTO NOVUS (12 ESCENARIOS){c_reset}")
        print(f"{c_bold}════════════════════════════════════════════════════════════════════════════════════{c_reset}\n")

        fmt_row = "{:<5} {:<32} {:<12} {:<6} {:<6} {:<6} {:<8} {:<10}"
        print(f"{c_bold}" + fmt_row.format("ID", "ESCENARIO", "ESTADO", "DERIV", "DASH", "BI", "LIMIT", "VEREDICTO") + f"{c_reset}")
        print("-" * 88)

        for r in results:
            verdict = f"{c_green}PASS{c_reset}" if r["passed"] else f"{c_red}FAIL{c_reset}"
            st = r["state"] or "-"
            dev = "SI" if r["derived_ok"] else "NO"
            dash = "SI" if r["dashboard_ok"] else "NO"
            bi = "SI" if r["bi_ok"] else "NO"
            lim = str(r["users_limit"]) if r["users_limit"] is not None else "-"
            print(fmt_row.format(r["id"], r["title"][:31], st, dev, dash, bi, lim, verdict))
            if not r["passed"] and r["error"]:
                print(f"      {c_yellow}↳ Detalle: {r['error']}{c_reset}")

        print("-" * 88)
        if all_ok:
            print(f"{c_green}{c_bold}✅ Matriz de licenciamiento 100% validada (12/12 escenarios exitosos).{c_reset}\n")
            return 0
        else:
            print(f"{c_red}{c_bold}❌ Fallaron algunos escenarios de licenciamiento.{c_reset}\n")
            return 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="simulate_licensing",
        description="Simulador de Licenciamiento y Entorno de Pruebas Novus",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # run-all
    run_parser = sub.add_parser("run-all", help="Ejecuta la matriz de simulación completa (12 escenarios)")
    run_parser.add_argument("--md", action="store_true", help="Salida en formato Markdown")
    run_parser.add_argument("--json", action="store_true", help="Salida en formato JSON")

    # scenario
    sc_parser = sub.add_parser("scenario", help="Aplica un escenario a un config.json o caché local")
    sc_parser.add_argument("id", choices=list(SCENARIOS.keys()), help="ID del escenario (E01 a E12)")
    sc_parser.add_argument("--config", default="config.json", help="Ruta al config.json destino")
    sc_parser.add_argument("--print-token", action="store_true", help="Imprime el token JWT generado")

    # token
    tok_parser = sub.add_parser("token", help="Genera un token JWT firmado a la medida")
    tok_parser.add_argument("--customer", default="demo_client", help="Customer ID")
    tok_parser.add_argument("--license-id", default="NOVUS-CUSTOM-001", help="License ID")
    tok_parser.add_argument("--status", default="active", choices=["active", "suspended", "revoked"])
    tok_parser.add_argument("--valid-days", type=int, default=30, help="Días de validez")
    tok_parser.add_argument("--grace-days", type=int, default=7, help="Días adicionales de gracia")
    tok_parser.add_argument("--modules", default="derived,dashboard,bi", help="Módulos separados por coma")
    tok_parser.add_argument("--limit", "--limits", dest="limits", action="append", default=[],
                            help="Límites en formato k=v (ej: users=5), se puede repetir")
    tok_parser.add_argument("--users-limit", type=int, default=None, help="Límite de usuarios (alias)")

    # server
    srv_parser = sub.add_parser("server", help="Inicia un servidor de licencias efímero")
    srv_parser.add_argument("--port", type=int, default=8082, help="Puerto del servidor")
    srv_parser.add_argument("--host", default="127.0.0.1", help="Host del servidor")

    args = parser.parse_args(argv)

    if args.action == "run-all":
        out_fmt = "json" if args.json else ("md" if args.md else "table")
        return run_all_simulations(output_format=out_fmt)

    if args.action == "scenario":
        cfg = load_config(args.config)
        priv_pem, _ = load_signing_keys(config_dict=cfg)
        sc = SCENARIOS[args.id]
        print(f"\n[info] Aplicando escenario {args.id}: {sc['title']}")
        print(f"       {sc['description']}")
        data, cpath = inject_scenario_cache(args.config, args.id, priv_pem)
        if cpath:
            print(f"[ok] Caché actualizado en: {cpath}")
        else:
            print("[ok] Modo sin licencia aplicado.")
        if args.print_token and data:
            print(f"\nToken JWT:\n{data['token']}\n")
        return 0

    if args.action == "token":
        priv_pem, _ = load_signing_keys()
        now = int(time.time())
        mods = {m.strip(): True for m in args.modules.split(",") if m.strip()}
        limits_dict = {}
        for entry in args.limits:
            for pair in entry.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    try:
                        limits_dict[k.strip()] = int(v.strip())
                    except ValueError:
                        limits_dict[k.strip()] = v.strip()
        if args.users_limit is not None:
            limits_dict["users"] = args.users_limit
        claims = {
            "customer_id": args.customer,
            "license_id": args.license_id,
            "status": args.status,
            "valid_from": now,
            "valid_until": now + args.valid_days * DAY,
            "offline_until": now + (args.valid_days + args.grace_days) * DAY,
            "modules": mods,
            "limits": limits_dict,
            "iat": now,
            "exp": now + (args.valid_days + args.grace_days) * DAY,
        }
        token = sign_claims(claims, priv_pem)
        print(f"Token JWT generado:\n{token}\n")
        print("Claims:")
        print(json.dumps(claims, indent=2))
        return 0

    if args.action == "server":
        import uvicorn
        from license_server.app import create_app
        from license_server.db import init_db
        from sqlalchemy import create_engine
        import tempfile

        priv_pem, _ = load_signing_keys()
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp_db:
            engine = create_engine(f"sqlite:///{tmp_db.name}")
            init_db(engine)
            app = create_app(engine, priv_pem, secret="sandbox-secret")
            print(f"[ok] Servidor efímero de licencias iniciado en http://{args.host}:{args.port}")
            uvicorn.run(app, host=args.host, port=args.port)
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
