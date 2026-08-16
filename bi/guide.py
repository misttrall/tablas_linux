"""Guía de conectividad de Power BI por dialecto, parametrizada por empresa."""

from derived.views import derived_views, view_tab_label


def guide_text(dialect):
    if dialect == "mssql":
        return (
            "- Conector nativo 'SQL Server' de Power BI (sin costo).\n"
            "- Recomendado: modo Importación para el DWH; DirectQuery si el volumen lo exige.\n"
            "- Publica el modelo en el Power BI Service y configura una puerta de "
            "enlace (gateway) si la BD es on-premise."
        )
    if dialect in ("postgresql", "mysql"):
        return (
            f"- Conector '{'PostgreSQL' if dialect == 'postgresql' else 'MySQL'}' de Power BI.\n"
            "- Requiere el driver ODBC del motor instalado en la máquina del gateway.\n"
            "- Recomendado: modo Importación."
        )
    if dialect == "sqlite":
        return (
            "- SQLite no está soportado de forma nativa por Power BI.\n"
            "- SQLite, no recomendado para clientes BI: migra el DWH a SQL Server "
            "(conector nativo)."
        )
    return f"- Dialecto '{dialect}': revisa el conector disponible en Power BI."


def render_guide(config, views=None):
    views = views if views is not None else derived_views(config)
    db = config["database"]
    dialect = db.get("dialect", "mssql")
    lines = [
        "# Guía de conectividad · Power BI",
        "",
        f"Empresa: {config.get('environment', '?')} · BD destino: {dialect}",
        "",
        "## Conexión",
        *guide_text(dialect).splitlines(),
    ]
    if db.get("server"):
        lines.append(f"- Servidor: {db['server']}")
    if db.get("database"):
        lines.append(f"- BD: {db['database']}")
    lines += [
        "",
        "## Vistas disponibles (dataset)",
        "",
        "| Vista | Pestaña | Tabla | Claves |",
        "|-------|---------|-------|--------|",
    ]
    for view in views:
        name = view.get("name", "inv_bodega")
        lines.append(
            f"| {name} | {view_tab_label(view)} | {name} | "
            f"{', '.join(view.get('keys', [])) or '-'} |"
        )
    lines += [
        "",
        "## Publicación",
        "- Abre el archivo .pbix, obtén datos desde la vista que necesites.",
        "- Agrega medidas a medida (servicio Novus) y publica en el Power BI Service.",
        "- El manifiesto (etl bi manifest) lista columnas y medidas sugeridas.",
    ]
    return "\n".join(lines)
