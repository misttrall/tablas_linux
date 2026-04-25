import time
import random
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import os

def generate_report_pdf():
    report_id = f"RPT-{int(time.time())}"
    filename = f"{report_id}.pdf"
    filepath = os.path.join("reports", filename)

    os.makedirs("reports", exist_ok=True)

    # Simulación de proceso ETL antes del PDF
    logs = [
        "Recolectando datos del ETL...",
        "Calculando KPIs de inventario...",
        "Generando métricas...",
        "Construyendo reporte PDF..."
    ]

    # Crear PDF real
    c = canvas.Canvas(filepath, pagesize=letter)

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 750, "📊 DataHub - Reporte Ejecutivo")

    c.setFont("Helvetica", 11)
    c.drawString(50, 720, f"ID Reporte: {report_id}")
    c.drawString(50, 705, f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    y = 670

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Resumen de ejecución ETL:")
    y -= 30

    c.setFont("Helvetica", 10)

    for log in logs:
        c.drawString(60, y, f"✔ {log}")
        y -= 20

    # KPIs mock
    y -= 20
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "KPIs:")
    y -= 25

    kpis = {
        "Registros procesados": random.randint(5000, 20000),
        "Errores detectados": random.randint(0, 50),
        "Tiempo ejecución (s)": round(random.uniform(1.5, 4.5), 2),
        "Calidad de datos": f"{random.randint(90, 99)}%"
    }

    c.setFont("Helvetica", 10)

    for k, v in kpis.items():
        c.drawString(60, y, f"{k}: {v}")
        y -= 18

    c.save()

    return {
        "report_id": report_id,
        "file": filename,
        "path": filepath,
        "logs": logs
    }