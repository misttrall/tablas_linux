"""Conector de demostración y simulación en tiempo real para Novus Data Platform."""

import time
import pandas as pd
from sources.base import SourceConnector
from scripts.init_demo_data import generate_rich_inventory

class DemoConnector(SourceConnector):
    """Conector para demostraciones interactivas en vivo con telemetría en tiempo real."""

    type = "demo"

    def __init__(self, config):
        super().__init__(config)
        self._items = generate_rich_inventory(450)

    def connect(self):
        time.sleep(0.05)

    def close(self):
        pass

    def ping(self):
        return True

    def extract(self, table, fields, filters=None, batch_size=None, max_wa_chars=None):
        # Simular latencia de red RFC (~40ms por chunk para un recorrido fluido y visible en la UI)
        time.sleep(0.04)
        
        rows = []
        if table == "MARA":
            for item in self._items:
                rows.append({
                    "MATNR": item["MATNR"],
                    "MTART": "ROH" if item["Area"] == "Fluidos y Piping" else "VERP",
                    "MATKL": "MAT-IND",
                    "XCHPF": "X",
                    "MEINS": item["UMB"],
                })
        elif table == "MARD":
            for item in self._items:
                rows.append({
                    "MANDT": "100",
                    "MATNR": item["MATNR"],
                    "WERKS": item["Centro"],
                    "LGORT": item["Almacen"],
                    "PSTAT": "K",
                    "LVORM": "",
                    "LABST": float(item["StockLibre"]),
                    "UMLME": 0.0,
                    "INSME": 0.0,
                    "EINME": 0.0,
                    "SPEME": 0.0,
                    "RETME": 0.0,
                    "LMINB": float(item["stock_minimo"]),
                })
        elif table == "MBEW":
            for item in self._items:
                rows.append({
                    "MANDT": "100",
                    "MATNR": item["MATNR"],
                    "BWKEY": item["Centro"],
                    "BWTAR": "",
                    "LVORM": "",
                    "LBKUM": float(item["StockLibre"]),
                    "SALK3": float(item["ValorTotal"]),
                    "VPRSV": "V",
                    "VERPR": float(item["Precio"]),
                    "STPRS": float(item["Precio"]),
                    "PEINH": 1,
                    "BKLAS": "3000",
                })
        elif table == "MAKT":
            for item in self._items:
                rows.append({
                    "MANDT": "100",
                    "MATNR": item["MATNR"],
                    "SPRAS": "ES",
                    "MAKTX": item["Descripcion"],
                    "MAKTG": item["Descripcion"].upper(),
                })
        elif table == "T001L":
            almacenes = {
                ("C001", "A010", "Bodega Motores y Accionamientos"),
                ("C001", "A020", "Bodega Válvulas y Piping"),
                ("C001", "A030", "Bodega Instrumentación"),
                ("C001", "A040", "Bodega Transmisión Mecánica"),
                ("C001", "A050", "Bodega Lubricantes y Químicos"),
                ("C001", "A060", "Bodega Filtros y Consumibles"),
                ("C001", "A070", "Bodega Materiales Eléctricos"),
                ("C001", "A080", "Bodega EPP y Seguridad"),
                ("C002", "A010", "Bodega Motores Norte"),
                ("C002", "A020", "Bodega Piping Norte"),
                ("C003", "A040", "Bodega Mecánica Biobío"),
                ("C004", "A030", "Hub Instrumentación"),
                ("C005", "A050", "Bodega Lubricación Faena"),
            }
            for werks, lgort, lgobe in almacenes:
                rows.append({
                    "MANDT": "100",
                    "WERKS": werks,
                    "LGORT": lgort,
                    "LGOBE": lgobe,
                })
        else:
            for item in self._items:
                rows.append({f: item.get(f, "") for f in fields})

        df = pd.DataFrame(rows)
        for f in fields:
            if f not in df.columns:
                df[f] = ""
        return df[fields]
