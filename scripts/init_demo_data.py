#!/usr/bin/env python3
"""Generador del dataset de demostración corporativo sintético para Novus Data Platform."""

import json
import os
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
from sqlalchemy import create_engine, text

import cli
from dashboard.auth import engine as auth_engine, users as auth_users

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "demo_enterprise.sqlite")

os.makedirs(DATA_DIR, exist_ok=True)

# Catálogo maestro de componentes industriales para generación realista
CATALOG_TEMPLATES = [
    # Mantenimiento Eléctrico & Motores
    ("Motor Asíncrono Trifásico {kw}kW {volt}V {rpm}RPM IE3", "Mantenimiento Eléctrico", "UN", 120000, 2800000, "A010", "Bodega Motores y Accionamientos"),
    ("Servomotor AC de Alta Precisión {kw}kW {volt}V", "Mantenimiento Eléctrico", "UN", 350000, 1850000, "A010", "Bodega Motores y Accionamientos"),
    ("Contactor Tripolar {amp}A Bobina 220VAC", "Mantenimiento Eléctrico", "UN", 22000, 180000, "A070", "Bodega Materiales Eléctricos"),
    ("Relé Térmico de Sobrecarga Rango {amp}A", "Mantenimiento Eléctrico", "UN", 18500, 125000, "A070", "Bodega Materiales Eléctricos"),
    ("Guardamotor Magnetotérmico {amp}A 50kA", "Mantenimiento Eléctrico", "UN", 32000, 240000, "A070", "Bodega Materiales Eléctricos"),
    ("Cable de Fuerza RZ1-K 0.6/1kV {secc} mm2 Cu", "Mantenimiento Eléctrico", "MT", 3500, 85000, "A070", "Bodega Materiales Eléctricos"),
    ("Interruptor Automático Caja Moldeada {amp}A 3P", "Mantenimiento Eléctrico", "UN", 85000, 950000, "A070", "Bodega Materiales Eléctricos"),
    
    # Automatización y Control
    ("Variador de Frecuencia {hp}HP 380V IP66 Control Vectorial", "Automatización", "UN", 280000, 3200000, "A010", "Bodega Motores y Accionamientos"),
    ("Módulo PLC I/O Digital 16 Entradas / 16 Salidas 24VDC", "Automatización", "UN", 145000, 680000, "A030", "Bodega Instrumentación y Control"),
    ("Módulo PLC Entradas Analógicas 8ch 4-20mA / 0-10V", "Automatización", "UN", 195000, 890000, "A030", "Bodega Instrumentación y Control"),
    ("Pantalla HMI Táctil Color {pulg}\" Ethernet / RS485 IP65", "Automatización", "UN", 230000, 1400000, "A030", "Bodega Instrumentación y Control"),
    ("Switch Industrial Gestionable 8 Puertos Gigabit DIN-Rail", "Automatización", "UN", 95000, 480000, "A030", "Bodega Instrumentación y Control"),
    ("Fuente de Poder Conmutada 24VDC {amp}A Carril DIN", "Automatización", "UN", 38000, 210000, "A030", "Bodega Instrumentación y Control"),

    # Fluidos, Piping y Válvulas
    ("Válvula de Bola Acero Inoxidable 316 {pulg_pipe}\" ANSI 150", "Fluidos y Piping", "UN", 45000, 380000, "A020", "Bodega Válvulas y Cañerías"),
    ("Válvula Mariposa Tipo Wafer {pulg_pipe}\" Asiento EPDM Disco 316", "Fluidos y Piping", "UN", 35000, 290000, "A020", "Bodega Válvulas y Cañerías"),
    ("Válvula de Retención (Check) Tipo Clapeta {pulg_pipe}\" WCB 300#", "Fluidos y Piping", "UN", 52000, 420000, "A020", "Bodega Válvulas y Cañerías"),
    ("Actuador Neumático Rotativo Doble Efecto {pulg_pipe}\"", "Fluidos y Piping", "UN", 85000, 650000, "A020", "Bodega Válvulas y Cañerías"),
    ("Posicionador Electroneumático Smart 4-20mA HART", "Fluidos y Piping", "UN", 280000, 1200000, "A020", "Bodega Válvulas y Cañerías"),
    ("Empaquetadura Espirometálica {pulg_pipe}\" Grafito/316 ANSI 150", "Fluidos y Piping", "UN", 4500, 32000, "A020", "Bodega Válvulas y Cañerías"),
    ("Brida Forjada Slip-On Acero Carbono A105 {pulg_pipe}\" 150#", "Fluidos y Piping", "UN", 12000, 110000, "A020", "Bodega Válvulas y Cañerías"),

    # Instrumentación Industrial
    ("Transmisor de Presión Manométrica 4-20mA 0-{bar} Bar HART", "Instrumentación", "UN", 160000, 750000, "A030", "Bodega Instrumentación y Control"),
    ("Transmisor de Nivel Ultrasónico Rango 0-{mts}m 2 Hilos 24V", "Instrumentación", "UN", 320000, 1450000, "A030", "Bodega Instrumentación y Control"),
    ("Caudalímetro Electromagnético {pulg_pipe}\" Revestimiento PTFE", "Instrumentación", "UN", 580000, 2900000, "A030", "Bodega Instrumentación y Control"),
    ("Sensor de Temperatura RTD Pt100 Vaina Inox 316 L={mm}mm", "Instrumentación", "UN", 28000, 185000, "A030", "Bodega Instrumentación y Control"),
    ("Sensor Inductivo M18 PNP NO Alcance {mm_ind}mm Flush", "Instrumentación", "UN", 14000, 65000, "A030", "Bodega Instrumentación y Control"),
    ("Sensor Fotoeléctrico Láser Retro-reflectante Alcance 10m", "Instrumentación", "UN", 32000, 140000, "A030", "Bodega Instrumentación y Control"),

    # Mecánica, Transmisión y Rodamientos
    ("Rodamiento Rígido de Bolas SKF {rod_code}-2RS1/C3", "Mecánica General", "UN", 8500, 195000, "A040", "Bodega Transmisión Mecánica"),
    ("Rodamiento de Rodillos Cónicos Timken {rod_code_con}", "Mecánica General", "UN", 22000, 340000, "A040", "Bodega Transmisión Mecánica"),
    ("Soporte Chumacera Tipo Pedestal SNL {rod_chum}", "Mecánica General", "UN", 45000, 280000, "A040", "Bodega Transmisión Mecánica"),
    ("Correa Trapezoidal Dentada de Alto Rendimiento {correa_code}", "Mecánica General", "UN", 12000, 85000, "A040", "Bodega Transmisión Mecánica"),
    ("Acoplamiento Elástico de Mallas Metálicas Modelo {acop}", "Mecánica General", "UN", 65000, 520000, "A040", "Bodega Transmisión Mecánica"),
    ("Cadena de Transmisión de Rodillos Doble ANSI {cadena} (Caja 5m)", "Mecánica General", "CJ", 42000, 310000, "A040", "Bodega Transmisión Mecánica"),
    ("Retén de Aceite Doble Labio NBR {reten_dim} mm", "Mecánica General", "UN", 3500, 28000, "A040", "Bodega Transmisión Mecánica"),

    # Lubricantes y Químicos
    ("Aceite Hidráulico Anti-Desgaste ISO VG {iso_vg} Tambor 208L", "Lubricación", "TB", 280000, 650000, "A050", "Bodega Lubricantes y Químicos"),
    ("Aceite Sintético para Engranajes Industriales ISO VG {iso_vg_gear} Balde 19L", "Lubricación", "BL", 85000, 240000, "A050", "Bodega Lubricantes y Químicos"),
    ("Grasa Sintética Complejo de Litio EP2 Alta Carga Balde 18kg", "Lubricación", "BL", 65000, 195000, "A050", "Bodega Lubricantes y Químicos"),
    ("Grasa Grado Alimenticio NSF H1 para Altas Temperaturas Cartucho 400g", "Lubricación", "UN", 8500, 26000, "A050", "Bodega Lubricantes y Químicos"),
    ("Desengrasante Dieléctrico Industrial de Rápida Evaporación Bidón 20L", "Lubricación", "BD", 42000, 115000, "A050", "Bodega Lubricantes y Químicos"),
    ("Líquido Refrigerante Larga Vida 50/50 Tambor 208L", "Lubricación", "TB", 195000, 420000, "A050", "Bodega Lubricantes y Químicos"),

    # Filtros y Consumibles
    ("Elemento Filtrante Hidráulico de Retorno 10 Micrones Fibra de Vidrio", "Filtros y Consumibles", "UN", 24000, 145000, "A060", "Bodega Filtros y Consumibles"),
    ("Filtro de Aire Industrial Cartucho Celulosa Heavy Duty", "Filtros y Consumibles", "UN", 18000, 110000, "A060", "Bodega Filtros y Consumibles"),
    ("Filtro Separador Aire/Aceite para Compresor de Tornillo", "Filtros y Consumibles", "UN", 35000, 220000, "A060", "Bodega Filtros y Consumibles"),
    ("Disco de Corte Abrasivo Acero Inoxidable 7\" x 1.6mm (Pack 25)", "Filtros y Consumibles", "PK", 18000, 45000, "A060", "Bodega Filtros y Consumibles"),
    ("Electrodo para Soldadura E7018 1/8\" Caja 20kg", "Filtros y Consumibles", "CJ", 48000, 95000, "A060", "Bodega Filtros y Consumibles"),
    ("Sellador de Roscas Anaeróbico de Alta Resistencia Frasco 250ml", "Filtros y Consumibles", "UN", 16000, 42000, "A060", "Bodega Filtros y Consumibles"),

    # EPP y Seguridad Industrial
    ("Casco de Seguridad Dielectrico Tipo 1 Clase E con Portalámpara", "Seguridad y EPP", "UN", 8500, 32000, "A080", "Bodega EPP y Seguridad Industrial"),
    ("Respirador Medio Rostro Doble Vía Silicona con Filtros P100/Vapores", "Seguridad y EPP", "UN", 22000, 68000, "A080", "Bodega EPP y Seguridad Industrial"),
    ("Arnés de Seguridad Cuerpo Completo 4 Argollas Anticaída", "Seguridad y EPP", "UN", 38000, 160000, "A080", "Bodega EPP y Seguridad Industrial"),
    ("Guantes de Nitrilo para Trabajo Pesado Resistente Químicos (Par)", "Seguridad y EPP", "PR", 3500, 18000, "A080", "Bodega EPP y Seguridad Industrial"),
    ("Calzado de Seguridad Dieléctrico Puntera Composite Cuero Hidrofugado", "Seguridad y EPP", "PR", 32000, 98000, "A080", "Bodega EPP y Seguridad Industrial"),
    ("Lentes de Seguridad Anti-Empaño Protección UV400 Pack x12", "Seguridad y EPP", "PK", 14000, 45000, "A080", "Bodega EPP y Seguridad Industrial"),
]

CENTROS = [
    ("C001", "Planta Central Santiago"),
    ("C002", "Planta Norte Antofagasta"),
    ("C003", "Planta Biobío Concepción"),
    ("C004", "Hub Logístico Pudahuel"),
    ("C005", "Faena Minera Cordillera"),
]


def generate_rich_inventory(target_count=450):
    random.seed(42)  # Semilla fija para consistencia
    items = []
    mat_seq = 1000

    while len(items) < target_count:
        template, area, umb, p_min, p_max, alm_code, alm_desc = random.choice(CATALOG_TEMPLATES)
        centro_code, centro_desc = random.choice(CENTROS)
        
        # Parámetros aleatorios para descripción técnica
        desc = template.format(
            kw=random.choice(["2.2", "4.0", "5.5", "7.5", "11.0", "15.0", "22.0", "37.0", "55.0", "75.0"]),
            volt=random.choice(["380", "440", "220/380", "400/690"]),
            rpm=random.choice(["1500", "3000", "1000", "980"]),
            amp=random.choice(["9", "12", "18", "25", "32", "40", "65", "80", "100", "160", "250", "400"]),
            secc=random.choice(["2.5", "4.0", "6.0", "10", "16", "25", "35", "50", "70", "95", "120", "150"]),
            hp=random.choice(["3", "5.5", "7.5", "10", "15", "20", "30", "50", "75", "100", "150"]),
            pulg=random.choice(["7.0", "10.1", "12.1", "15.0"]),
            pulg_pipe=random.choice(['1/2', '3/4', '1', '1-1/2', '2', '3', '4', '6', '8', '10']),
            bar=random.choice(["6", "10", "16", "25", "40", "100", "250", "400"]),
            mts=random.choice(["5", "8", "10", "15"]),
            mm=random.choice(["100", "150", "200", "300", "450", "600"]),
            mm_ind=random.choice(["5", "8", "12", "15"]),
            rod_code=random.choice(["6004", "6205", "6208", "6210", "6308", "6312", "6315", "6410"]),
            rod_code_con=random.choice(["30208", "30310", "32212", "32314", "33215"]),
            rod_chum=random.choice(["511-609", "512-610", "515-612", "518-615", "520-617"]),
            correa_code=random.choice(["SPZ 1250", "SPA 1600", "SPB 2500", "SPC 3550", "XPB 2240"]),
            acop=random.choice(["1020T10", "1040T10", "1060T10", "1080T10", "1100T10"]),
            cadena=random.choice(["40-2", "50-2", "60-2", "80-2", "100-2"]),
            reten_dim=random.choice(["25x47x7", "35x62x10", "45x72x8", "50x80x10", "65x90x10", "85x110x12"]),
            iso_vg=random.choice(["32", "46", "68", "100"]),
            iso_vg_gear=random.choice(["150", "220", "320", "460", "680"]),
        )

        mat_seq += 10
        matnr = f"MAT-{mat_seq}"
        
        # Precio unitario en CLP (redondeado)
        precio = round(random.uniform(p_min, p_max) / 500) * 500
        
        # Stock y alertas: 25% de los items tienen stock bajo mínimo para enriquecer los KPIs de alerta
        stock_min = random.choice([2, 3, 5, 8, 10, 15, 20, 25, 30, 50])
        es_critico = random.random() < 0.25
        
        if es_critico:
            stock_libre = random.randint(0, max(0, stock_min - 1))
        else:
            stock_libre = random.randint(stock_min, stock_min * random.choice([2, 3, 4, 5, 8]))
            
        valor_total = round(stock_libre * precio, 2)
        
        items.append({
            "MATNR": matnr,
            "Descripcion": desc,
            "Centro": centro_code,
            "Almacen": alm_code,
            "AlmacenDesc": alm_desc,
            "StockLibre": stock_libre,
            "stock_minimo": stock_min,
            "Precio": precio,
            "ValorTotal": valor_total,
            "Area": area,
            "UMB": umb,
        })
        
    return items


def setup_demo_database():
    print("[1/5] Ejecutando migraciones de esquema...")
    cfg_temp = {
        "environment": "prd",
        "source": {"type": "csv", "config": {"directory": DATA_DIR}},
        "database": {"dialect": "sqlite", "database": DB_PATH},
        "tables": [],
        "fields": {},
    }
    temp_cfg_path = os.path.join(DATA_DIR, "temp_migrate_cfg.json")
    with open(temp_cfg_path, "w") as fh:
        json.dump(cfg_temp, fh)
    
    cli.cmd_migrate(temp_cfg_path)
    if os.path.exists(temp_cfg_path):
        os.remove(temp_cfg_path)

    engine = create_engine(f"sqlite:///{DB_PATH}")

    # 2. Crear usuarios iniciales
    print("[2/5] Creando usuarios y roles de acceso corporativo...")
    auth_engine._ENGINE_PROVIDER = lambda: engine
    for u_name, u_pass, u_role in [
        ("admin", "admin", "admin"),
        ("analista", "demo1234", "user"),
        ("gerente_operaciones", "novus2026!", "user"),
    ]:
        try:
            auth_users.create_user(u_name, u_pass, role=u_role, is_root=(u_role == "admin"), must_change_password=True)
        except Exception:
            pass

    # 3. Generar dataset de inventario
    print("[3/5] Generando 450+ registros de inventario industrial realista...")
    inventory_items = generate_rich_inventory(450)
    df_inv = pd.DataFrame(inventory_items)
    df_inv.to_sql("inv_bodega", engine, if_exists="replace", index=False)

    df_min = pd.DataFrame([{
        "material": item["MATNR"],
        "centro": item["Centro"],
        "almacen": item["Almacen"],
        "area": item["Area"],
        "stock_minimo": item["stock_minimo"],
    } for item in inventory_items])
    df_min.to_sql("stock_minimo", engine, if_exists="replace", index=False)

    # 4. Poblar historial de ejecuciones ETL realistas
    print("[4/5] Generando historial de telemetría y sincronización ETL...")
    with engine.begin() as conn:
        # Limpiar ejecuciones previas
        conn.execute(text("DELETE FROM etl_execution"))
        conn.execute(text("DELETE FROM etl_execution_tables"))
        conn.execute(text("DELETE FROM etl_progress"))
        
        now = datetime.now(ZoneInfo("America/Santiago"))
        
        runs_data = [
            (now - timedelta(days=3, hours=4), 48.2, 450, "finished"),
            (now - timedelta(days=2, hours=12), 46.5, 450, "finished"),
            (now - timedelta(days=1, hours=6), 51.1, 450, "finished"),
            (now - timedelta(hours=2, minutes=15), 44.8, 450, "finished"),
        ]
        
        tables_to_report = [
            ("MARA", 18500, 12.4),
            ("MARD", 34200, 16.8),
            ("MBEW", 28900, 9.2),
            ("MAKT", 19100, 4.5),
            ("T001L", 42, 0.6),
            ("inv_bodega", 450, 2.8),
        ]
        
        for idx, (start_dt, dur, total_rows, status) in enumerate(runs_data, start=1):
            end_dt = start_dt + timedelta(seconds=dur)
            conn.execute(text(
                "INSERT INTO etl_execution (id, start_time, end_time, status, message) "
                "VALUES (:id, :st, :et, :stat, NULL)"
            ), {
                "id": idx,
                "st": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "et": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "stat": status,
            })
            
            for tbl, rows, t_dur in tables_to_report:
                conn.execute(text(
                    "INSERT INTO etl_execution_tables (run_id, table_name, chunks_total, chunks_ok, rows_extracted, duration_s, status) "
                    "VALUES (:eid, :tname, 10, 10, :rows, :dur, 'ok')"
                ), {
                    "eid": idx,
                    "tname": tbl,
                    "rows": rows,
                    "dur": t_dur,
                })

        for tbl, rows, _ in tables_to_report:
            conn.execute(text(
                "INSERT INTO etl_progress (table_name, rows_loaded, status, updated_at) "
                "VALUES (:tname, :rows, 'ok', :upd)"
            ), {
                "tname": tbl,
                "rows": rows,
                "upd": now.strftime("%Y-%m-%d %H:%M:%S"),
            })

    # 5. Resumen
    total_val = df_inv["ValorTotal"].sum()
    alert_count = (df_inv["StockLibre"] <= df_inv["stock_minimo"]).sum()
    print(f"[5/5] ¡Listo! Base de datos demo generada en {DB_PATH}")
    print(f"      - Registros de inventario: {len(df_inv)}")
    print(f"      - Valorización total del stock: ${total_val:,.0f} CLP")
    print(f"      - Alertas de Stock Bajo Mínimo: {alert_count} ítems")
    print(f"      - Usuarios listos: admin (admin/admin), analista (analista/demo1234)")


if __name__ == "__main__":
    setup_demo_database()
