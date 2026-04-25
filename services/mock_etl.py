import time
import random

def run_etl_process():
    logs = []

    steps = [
        "Conectando a fuentes de datos...",
        "Extrayendo datos desde SAP (simulado)...",
        "Validando integridad de registros...",
        "Transformando dataset...",
        "Aplicando reglas de negocio...",
        "Normalizando campos...",
        "Cargando datos en data mart...",
        "Validación final..."
    ]

    for step in steps:
        time.sleep(random.uniform(0.3, 0.8))  # simula carga real
        logs.append(f"✔ {step}")

    logs.append("🎉 ETL ejecutado correctamente")

    return logs