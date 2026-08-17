import argparse
import os
import sys

from sqlalchemy import create_engine, text

from db.db_connection import _connection_string
from utils.config_loader import load_config

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")


def _engine_from_config(config, fast_executemany=True):
    kwargs = {}
    if config["database"].get("dialect", "mssql") == "mssql" and fast_executemany:
        kwargs["fast_executemany"] = True
    return create_engine(_connection_string(config["database"]), **kwargs)


def cmd_migrate(config_path):
    config = load_config(config_path)
    dialect = config["database"].get("dialect", "mssql")
    base = os.path.join(MIGRATIONS_DIR, dialect)

    if not os.path.isdir(base):
        print(f"No hay carpeta de migraciones para dialecto '{dialect}': {base}")
        return 1

    engine = _engine_from_config(config)

    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version VARCHAR(128) PRIMARY KEY, "
            "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        applied = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}

    files = sorted(f for f in os.listdir(base) if f.endswith(".sql"))
    if not files:
        print(f"No hay archivos .sql para dialecto '{dialect}'")
        return 0

    count = 0
    for f in files:
        if f in applied:
            print(f"[skip] {f}")
            continue
        with open(os.path.join(base, f)) as fh:
            sql = fh.read()
        statements = [
            s.strip() for s in sql.split(";")
            if s.strip() and not s.strip().startswith("--")
        ]
        try:
            with engine.begin() as conn:
                for stmt in statements:
                    conn.execute(text(stmt))
                conn.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                    {"v": f},
                )
            print(f"[ok] {f} ({len(statements)} sentencias)")
        except Exception as e:
            if _is_duplicate_schema_error(str(e)):
                with engine.begin() as conn:
                    conn.execute(
                        text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                        {"v": f},
                    )
                print(f"[ok-baseline] {f} (schema ya presente: {str(e).strip()[:80]})")
            else:
                print(f"[error] {f}: {e}")
                return 1
        count += 1

    pending = [f for f in files if f not in applied]
    print(f"Migraciones aplicadas: {count}, pendientes: {len(pending)}")
    return 0


def _is_duplicate_schema_error(message):
    patterns = (
        "duplicate column name",
        "duplicate column",
        "already exists",
        "Multiple-step OLE DB operation",
    )
    return any(p.lower() in message.lower() for p in patterns)


def cmd_status(config_path, last=10):
    config = load_config(config_path)
    engine = _engine_from_config(config, fast_executemany=False)

    with engine.connect() as conn:
        try:
            runs = conn.execute(
                text("SELECT id, status, start_time, end_time "
                     "FROM etl_execution ORDER BY id DESC LIMIT :n"),
                {"n": last},
            ).fetchall()
        except Exception as e:
            print(f"No se pudo leer etl_execution: {e} (¿corrió 'etl migrate'?)")
            return 1

        print(f"Últimas {len(runs)} corridas:")
        for r in runs:
            print(f"  #{r.id}  {r.status:<10} inicio={r.start_time}  fin={r.end_time}")

        try:
            progress = conn.execute(
                text("SELECT table_name, status, rows_loaded, last_delta_value, updated_at "
                     "FROM etl_progress ORDER BY table_name"),
            ).fetchall()
        except Exception as e:
            print(f"No se pudo leer etl_progress: {e} (¿corrió 'etl migrate'?)")
            return 1

        print("\nProgreso por tabla:")
        for p in progress:
            print(f"  {p.table_name:<24} {str(p.status):<8} "
                  f"filas={p.rows_loaded} delta={p.last_delta_value} updated={p.updated_at}")

    return 0


def cmd_run(config_path, tables):
    from etl_runner import run_etl_job
    run_etl_job(config_path=config_path, tables=tables)
    return 0


def cmd_reporte(config_path, tabla=None):
    config = load_config(config_path)
    from licensing.client import LicenseError, require_license
    try:
        require_license(config, "derived")
    except LicenseError as exc:
        print(f"[error] {exc}")
        return 1
    if not config.get("derived"):
        print("No hay sección 'derived' en config; nada que generar")
        return 0
    from derived.excel_export import export_report_from_table
    from derived.views import derived_views
    engine = _engine_from_config(config)
    views = derived_views(config)
    if tabla:
        views = [v for v in views if v.get("name", "inv_bodega") == tabla]
        if not views:
            print(f"No existe la visión derivada '{tabla}'")
            return 1
    for v in views:
        name = v.get("name", "inv_bodega")
        try:
            path = export_report_from_table(engine, config, derived=v)
            print(f"Reporte '{name}' generado: {path}")
        except ValueError as e:
            print(f"[error] {name}: {e}")
            return 1
    return 0


def cmd_bootstrap(config_path, with_derived=False, skip_sap=False):
    """Onboarding de un cliente: valida config, conectividad y deja la BD lista."""
    from sources import get_source, resolve_source_config, validate_environment, validate_prd_limits

    def fail(msg):
        print(f"[error] {msg}")
        return 1

    config = load_config(config_path)
    print("[ok] config válido")

    try:
        env = validate_environment(config)
        validate_prd_limits(config)
    except ValueError as e:
        return fail(str(e))
    print(f"[ok] environment: {env}")

    engine = _engine_from_config(config)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        return fail(f"BD destino inalcanzable: {e}")
    print("[ok] BD destino alcanzable")

    if cmd_migrate(config_path) != 0:
        return fail("no se pudieron aplicar las migraciones")
    print("[ok] migraciones aplicadas")

    source_config = resolve_source_config(config)
    connector = None
    if not skip_sap:
        try:
            connector = get_source(source_config)
            connector.connect()
            if not connector.ping():
                return fail(f"fuente '{connector.type}' no responde al ping")
        except Exception as e:
            return fail(f"fuente '{source_config.get('type')}' no verificable: {e}")
        print(f"[ok] fuente '{connector.type}' conectada")

        smoke = next((t for t in config.get("tables", []) if t["source"] == "T001L"), None)
        if smoke:
            fields = config["fields"].get("T001L", [])
            try:
                df = connector.extract("T001L", fields)
            except Exception as e:
                return fail(f"smoke extract T001L falló: {e}")
            print(f"[ok] smoke extract T001L: {len(df)} registros")
    else:
        print("[warn] verificación de fuente omitida (--skip-sap)")

    if with_derived and config.get("derived"):
        from licensing.client import LicenseError, require_license
        try:
            require_license(config, "derived")
        except LicenseError as exc:
            return fail(f"módulo derived no contratado: {exc}")
        from db.sinks import get_sink
        from derived.materializer import run_deriveds
        try:
            results = run_deriveds(engine=engine, sink=get_sink(engine), config=config)
        except ValueError as e:
            if "no existe" in str(e):
                print(f"[warn] modelo derivado omitido (aún no hay tablas crudas): {e}")
            else:
                return fail(f"modelo derivado falló: {e}")
        else:
            for name, n_rows, path in results:
                print(f"[ok] visión '{name}': {n_rows} filas -> {path}")

    if connector:
        connector.close()

    print("Bootstrap completado: cliente listo.")
    return 0


def cmd_importar_minimos(config_path, archivo, hoja, tabla="stock_minimo",
                         col_material=None, col_stock=None, col_area=None):
    config = load_config(config_path)
    from db.sinks import get_sink
    from derived.minimos_import import import_stock_minimo
    columns = {}
    if col_material:
        columns["material"] = col_material
    if col_stock:
        columns["stock_minimo"] = col_stock
    if col_area:
        columns["area"] = col_area
    engine = _engine_from_config(config)
    n = import_stock_minimo(engine, get_sink(engine), archivo, sheet=hoja,
                            columns=columns or None, table=tabla)
    print(f"Importados {n} materiales con stock mínimo a '{tabla}'")
    return 0


def cmd_bi(config_path, action, out_dir="output/bi"):
    from bi.export import export_views
    from bi.guide import render_guide
    from bi.manifest import build_manifest, manifest_to_json

    config = load_config(config_path)
    from licensing.client import LicenseError, require_license
    try:
        require_license(config, "bi")
    except LicenseError as exc:
        print(f"[error] {exc}")
        return 1
    engine = _engine_from_config(config)

    if action == "manifest":
        print(manifest_to_json(build_manifest(config, engine)))
        return 0
    if action == "export":
        try:
            results = export_views(config, engine, out_dir=out_dir)
        except ValueError as e:
            print(f"[error] {e}")
            return 1
        for r in results:
            extra = f", parquet={r['parquet_path']}" if r["parquet_path"] else ""
            print(f"[ok] '{r['name']}': {r['rows']} filas -> {r['csv_path']}{extra}")
        return 0
    if action == "guide":
        print(render_guide(config))
        return 0
    print("Uso: etl bi {manifest|export|guide}")
    return 1


def _fmt_epoch(epoch):
    import datetime
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d") if epoch else "-"


def cmd_license(config_path, action):
    import time
    config = load_config(config_path)
    from licensing.client import LicenseError, get_manager
    mgr = get_manager(config)
    if action == "status":
        try:
            lic = mgr.get_license()
        except LicenseError as exc:
            print(f"[error] {exc}")
            return 1
        print(f"estado: {lic.state(time.time()).value}")
        print(f"cliente: {lic.customer_id or '-'} · licencia: {lic.license_id or '-'}")
        print(f"válida hasta: {_fmt_epoch(lic.valid_until)} · gracia hasta: {_fmt_epoch(lic.offline_until)}")
        if lic.modules is None:
            print("módulos: todos (sin licenciar)")
        else:
            on = ", ".join(sorted(m for m, ok in lic.modules.items() if ok)) or "(ninguno)"
            print(f"módulos: {on}")
        if lic.limits:
            print("límites: " + ", ".join(f"{k}={v}" for k, v in sorted(lic.limits.items())))
        return 0
    if action == "activate":
        try:
            mgr.force_activate()
        except LicenseError as exc:
            print(f"[error] {exc}")
            return 1
        print("[ok] licencia activada")
        return 0
    if action == "validate":
        import time as _time
        try:
            lic = mgr.validate()
        except LicenseError as exc:
            print(f"[error] {exc}")
            return 1
        print(f"[ok] firma válida · estado {lic.state(_time.time()).value}")
        return 0
    if action == "clear-cache":
        mgr.clear_cache()
        print("[ok] caché de licencia eliminada")
        return 0
    print("Uso: etl license {status|activate|validate|clear-cache}")
    return 1


def _add_config_arg(subparser):
    subparser.add_argument(
        "--config", default=None,
        help="Ruta al archivo config.json (por defecto: config.json del proyecto)",
    )
    return subparser


def cmd_users(args):
    from dashboard.auth import engine as auth_engine
    from dashboard.auth import users as auth_users

    config = load_config(args.config)
    previous = auth_engine.get_engine_provider()
    auth_engine.set_engine_provider(
        lambda: _engine_from_config(config, fast_executemany=False))
    try:
        return _cmd_users_action(auth_users, args, config)
    finally:
        auth_engine.set_engine_provider(previous)


def _cmd_users_action(auth_users, args, config):
    action = args.users_action
    if action == "add":
        from licensing.client import LicenseError, get_manager
        try:
            limit = get_manager(config).users_limit()
        except LicenseError as exc:
            print(f"[error] {exc}")
            return 1
        if limit is not None and len(auth_users.list_users()) >= limit:
            print(f"[error] límite de usuarios alcanzado ({limit}); contacta a Novus")
            return 1
        role = "admin" if args.root else args.role
        try:
            user_id = auth_users.create_user(
                username=args.username,
                password=args.password,
                role=role,
                is_root=args.root,
                must_change_password=not args.no_force_password_change,
            )
        except Exception as e:
            print(f"[error] no se pudo crear el usuario: {e}")
            return 1
        print(f"[ok] usuario '{args.username}' creado (id={user_id}, role={role})")
        return 0
    if action == "list":
        for u in auth_users.list_users():
            flags = []
            if u["is_root"]:
                flags.append("root")
            flags.append("activo" if u["active"] else "inactivo")
            if u["must_change_password"]:
                flags.append("cambiar-password")
            print(f"#{u['id']} {u['username']} [{u['role']}] ({', '.join(flags)})")
        return 0
    if action == "set-password":
        user = auth_users.get_user_by_username(args.username)
        if user is None:
            print(f"[error] usuario '{args.username}' no existe")
            return 1
        auth_users.set_password(user["id"], args.password)
        print(f"[ok] password actualizada para '{args.username}'")
        return 0
    print("Uso: etl users {add|list|set-password} ...")
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="etl",
        description="Motor ETL multi-ERP y multi-base de datos",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Ejecuta el pipeline ETL")
    run_parser.add_argument("--job", default="etl",
                            help="Nombre del job a ejecutar (por defecto: etl)")
    run_parser.add_argument("--tables", default=None,
                            help="Tablas a procesar (source o target, separadas por coma)")
    _add_config_arg(run_parser)

    migrate_parser = subparsers.add_parser("migrate", help="Aplica las migraciones de la BD destino")
    _add_config_arg(migrate_parser)

    status_parser = subparsers.add_parser("status", help="Muestra el estado de corridas y progreso")
    status_parser.add_argument("--last", type=int, default=10,
                               help="Cantidad de corridas a mostrar (por defecto: 10)")
    _add_config_arg(status_parser)

    reporte_parser = subparsers.add_parser(
        "reporte", help="Regenera los Excel del modelo derivado desde la BD destino (sin SAP)")
    reporte_parser.add_argument("--tabla", default=None,
                                help="Nombre de la visión derivada a regenerar (por defecto: todas)")
    _add_config_arg(reporte_parser)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Onboarding de un cliente: valida config, conectividad y deja la BD lista")
    bootstrap_parser.add_argument("--with-derived", action="store_true",
                                  help="Materializa las visiones derivadas si las tablas crudas ya existen")
    bootstrap_parser.add_argument("--skip-sap", action="store_true",
                                  help="Omite la verificación de la fuente (útil sin SDK SAP o CI)")
    _add_config_arg(bootstrap_parser)

    import_parser = subparsers.add_parser(
        "importar-minimos",
        help="Importa la matriz de stock mínimo (Excel del cliente) a la BD destino")
    import_parser.add_argument("--archivo", required=True,
                               help="Ruta al libro Excel del cliente")
    import_parser.add_argument("--hoja", required=True,
                               help="Nombre de la hoja del libro (dato del cliente)")
    import_parser.add_argument("--tabla", default="stock_minimo",
                               help="Tabla de referencia destino (por defecto: stock_minimo)")
    import_parser.add_argument("--col-material", default=None,
                               help="Columna de origen del material (por defecto: material)")
    import_parser.add_argument("--col-stock", default=None,
                               help="Columna de origen del stock mínimo (por defecto: stock_minimo)")
    import_parser.add_argument("--col-area", default=None,
                               help="Columna de origen del área (por defecto: area)")
    _add_config_arg(import_parser)

    bi_parser = subparsers.add_parser(
        "bi", help="Entregable BI: manifiesto, export y guía de conectividad para Power BI")
    bi_sub = bi_parser.add_subparsers(dest="bi_action", required=True)

    bi_manifest = bi_sub.add_parser("manifest", help="Genera el manifiesto del dataset")
    _add_config_arg(bi_manifest)
    bi_manifest.add_argument("--out", default=None, help=argparse.SUPPRESS)

    bi_export = bi_sub.add_parser("export", help="Exporta las vistas a CSV/Parquet")
    bi_export.add_argument("--out-dir", default="output/bi",
                           help="Directorio de salida (por defecto: output/bi)")
    _add_config_arg(bi_export)

    bi_guide = bi_sub.add_parser("guide", help="Emite la guía de conectividad de Power BI")
    _add_config_arg(bi_guide)

    users_parser = subparsers.add_parser(
        "users", help="Gestiona usuarios del dashboard (app_users de la BD destino)")
    users_sub = users_parser.add_subparsers(dest="users_action")

    add_parser = users_sub.add_parser("add", help="Crea un usuario")
    add_parser.add_argument("--username", required=True)
    add_parser.add_argument("--password", required=True)
    add_parser.add_argument("--role", default="user", choices=["user", "admin"])
    add_parser.add_argument("--root", action="store_true",
                            help="Marca como admin raíz (protegido contra borrado)")
    add_parser.add_argument("--no-force-password-change", action="store_true",
                            help="No obliga a cambiar la password en el primer login")
    _add_config_arg(add_parser)

    list_parser = users_sub.add_parser("list", help="Lista los usuarios")
    _add_config_arg(list_parser)

    pass_parser = users_sub.add_parser("set-password", help="Cambia la password de un usuario")
    pass_parser.add_argument("--username", required=True)
    pass_parser.add_argument("--password", required=True)
    _add_config_arg(pass_parser)

    license_parser = subparsers.add_parser(
        "license", help="Estado y gestión de la licencia de la empresa")
    license_sub = license_parser.add_subparsers(dest="license_action", required=True)
    for action_name in ("status", "activate", "validate", "clear-cache"):
        action_parser = license_sub.add_parser(action_name,
                                               help=f"{action_name} de la licencia")
        _add_config_arg(action_parser)

    args = parser.parse_args(argv)

    if args.command == "run":
        tables = args.tables.split(",") if args.tables else None
        return cmd_run(args.config, tables)
    if args.command == "migrate":
        return cmd_migrate(args.config)
    if args.command == "status":
        return cmd_status(args.config, args.last)
    if args.command == "reporte":
        return cmd_reporte(args.config, args.tabla)
    if args.command == "bootstrap":
        return cmd_bootstrap(args.config, args.with_derived, args.skip_sap)
    if args.command == "importar-minimos":
        return cmd_importar_minimos(args.config, args.archivo, args.hoja, args.tabla,
                                    args.col_material, args.col_stock, args.col_area)
    if args.command == "bi":
        if args.bi_action == "manifest":
            return cmd_bi(args.config, "manifest")
        if args.bi_action == "export":
            return cmd_bi(args.config, "export", out_dir=args.out_dir)
        if args.bi_action == "guide":
            return cmd_bi(args.config, "guide")
        return 1
    if args.command == "license":
        return cmd_license(args.config, args.license_action)
    if args.command == "users":
        return cmd_users(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
