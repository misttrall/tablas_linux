#!/usr/bin/env python3
"""Generador del dataset de demostración corporativo sintético para Novus Data Platform."""

import os
import sqlite3
import pandas as pd
from sqlalchemy import create_engine

import cli
from dashboard.auth import engine as auth_engine, users as auth_users

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "demo_enterprise.sqlite")

os.makedirs(DATA_DIR, exist_ok=True)

# 1. Ejecutar migraciones
def setup_demo_database():
    cfg_temp = {
        "environment": "prd",
        "source": {"type": "csv", "config": {"directory": DATA_DIR}},
        "database": {"dialect": "sqlite", "database": DB_PATH},
        "tables": [],
        "fields": {},
    }
    temp_cfg_path = os.path.join(DATA_DIR, "temp_migrate_cfg.json")
    import json
    with open(temp_cfg_path, "w") as fh:
        json.dump(cfg_temp, fh)
    
    cli.cmd_migrate(temp_cfg_path)
    if os.path.exists(temp_cfg_path):
        os.remove(temp_cfg_path)

    engine = create_engine(f"sqlite:///{DB_PATH}")

    # 2. Crear usuarios iniciales
    auth_engine._ENGINE_PROVIDER = lambda: engine
    try:
        auth_users.create_user("admin", "admin", role="admin", is_root=True, must_change_password=True)
        auth_users.create_user("analista", "demo1234", role="user", is_root=False, must_change_password=True)
    except Exception:
        pass

    # 3. Datos sintéticos de inventario industrial (100% genéricos y profesionales)
    inventory_items = [
        {"MATNR": "MAT-1010", "Descripcion": "Motor Asíncrono Trifásico 7.5 kW 380V", "Centro": "C001", "Almacen": "A010", "AlmacenDesc": "Bodega de Motores", "StockLibre": 14, "stock_minimo": 5, "Precio": 175000.0, "ValorTotal": 2450000.0, "Area": "Mantenimiento Eléctrico", "UMB": "UN"},
        {"MATNR": "MAT-1020", "Descripcion": "Variador de Frecuencia 10HP IP66", "Centro": "C001", "Almacen": "A010", "AlmacenDesc": "Bodega de Motores", "StockLibre": 8, "stock_minimo": 4, "Precio": 236250.0, "ValorTotal": 1890000.0, "Area": "Automatización", "UMB": "UN"},
        {"MATNR": "MAT-2010", "Descripcion": 'Válvula de Bola Acero Inox 316 2" ANSI 150', "Centro": "C001", "Almacen": "A020", "AlmacenDesc": "Válvulas y Cañerías", "StockLibre": 3, "stock_minimo": 10, "Precio": 140000.0, "ValorTotal": 420000.0, "Area": "Fluidos y Piping", "UMB": "UN"},
        {"MATNR": "MAT-2020", "Descripcion": "Actuador Neumático Doble Efecto 90°", "Centro": "C002", "Almacen": "A020", "AlmacenDesc": "Válvulas y Cañerías", "StockLibre": 12, "stock_minimo": 6, "Precio": 95833.33, "ValorTotal": 1150000.0, "Area": "Automatización", "UMB": "UN"},
        {"MATNR": "MAT-3010", "Descripcion": "Sensor Inductivo M18 PNP NO Alcance 8mm", "Centro": "C002", "Almacen": "A030", "AlmacenDesc": "Instrumentación", "StockLibre": 45, "stock_minimo": 20, "Precio": 15000.0, "ValorTotal": 675000.0, "Area": "Instrumentación", "UMB": "UN"},
        {"MATNR": "MAT-3020", "Descripcion": "Transmisor de Presión 4-20mA 0-10 Bar", "Centro": "C001", "Almacen": "A030", "AlmacenDesc": "Instrumentación", "StockLibre": 2, "stock_minimo": 5, "Precio": 290000.0, "ValorTotal": 580000.0, "Area": "Instrumentación", "UMB": "UN"},
        {"MATNR": "MAT-4010", "Descripcion": "Rodamiento Rígido de Bolas SKF 6208-2RS", "Centro": "C003", "Almacen": "A040", "AlmacenDesc": "Transmisión Mecánica", "StockLibre": 60, "stock_minimo": 25, "Precio": 12000.0, "ValorTotal": 720000.0, "Area": "Mecánica General", "UMB": "UN"},
        {"MATNR": "MAT-4020", "Descripcion": "Correa Trapezoidal de Alta Capacidad SPB 2500", "Centro": "C003", "Almacen": "A040", "AlmacenDesc": "Transmisión Mecánica", "StockLibre": 1, "stock_minimo": 8, "Precio": 45000.0, "ValorTotal": 45000.0, "Area": "Mecánica General", "UMB": "UN"},
        {"MATNR": "MAT-5010", "Descripcion": "Grasa Sintética Complejo Litio Balde 18kg", "Centro": "C001", "Almacen": "A050", "AlmacenDesc": "Lubricantes y Químicos", "StockLibre": 15, "stock_minimo": 5, "Precio": 59333.33, "ValorTotal": 890000.0, "Area": "Lubricación", "UMB": "BL"},
        {"MATNR": "MAT-5020", "Descripcion": "Aceite Hidráulico Anti-Desgaste ISO VG 68 Tambor 208L", "Centro": "C002", "Almacen": "A050", "AlmacenDesc": "Lubricantes y Químicos", "StockLibre": 6, "stock_minimo": 3, "Precio": 350000.0, "ValorTotal": 2100000.0, "Area": "Lubricación", "UMB": "TB"},
        {"MATNR": "MAT-6010", "Descripcion": "Filtro de Aire Industrial Cartucho Celulosa", "Centro": "C001", "Almacen": "A060", "AlmacenDesc": "Filtros y Consumibles", "StockLibre": 22, "stock_minimo": 10, "Precio": 28000.0, "ValorTotal": 616000.0, "Area": "Servicios Generales", "UMB": "UN"},
        {"MATNR": "MAT-6020", "Descripcion": "Empaquetadura Espirometálica 3\" ANSI 150", "Centro": "C002", "Almacen": "A020", "AlmacenDesc": "Válvulas y Cañerías", "StockLibre": 35, "stock_minimo": 15, "Precio": 8500.0, "ValorTotal": 297500.0, "Area": "Fluidos y Piping", "UMB": "UN"},
    ]
    df_inv = pd.DataFrame(inventory_items)
    df_inv.to_sql("inv_bodega", engine, if_exists="replace", index=False)
    print(f"[ok] Base de datos demo generada en {DB_PATH} con {len(df_inv)} registros sintéticos.")

if __name__ == "__main__":
    setup_demo_database()
