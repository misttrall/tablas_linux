import pandas as pd
from reportlab.pdfgen import canvas
import os
import time


def fake_data():
    return pd.DataFrame({
        "Producto": ["A", "B", "C"],
        "Stock": [100, 50, 80],
        "Ventas": [20, 10, 40],
        "Estado": ["OK", "CRITICO", "OK"]
    })


def export_excel():
    df = fake_data()

    os.makedirs("reports", exist_ok=True)

    filename = f"report_{int(time.time())}.xlsx"
    path = os.path.join("reports", filename)

    df.to_excel(path, index=False)

    return filename


def export_pdf():
    df = fake_data()

    os.makedirs("reports", exist_ok=True)

    filename = f"report_{int(time.time())}.pdf"
    path = os.path.join("reports", filename)

    c = canvas.Canvas(path)

    c.drawString(50, 750, "BI Report Export")

    y = 700
    for _, row in df.iterrows():
        c.drawString(50, y, f"{row['Producto']} | {row['Stock']} | {row['Ventas']} | {row['Estado']}")
        y -= 20

    c.save()

    return filename