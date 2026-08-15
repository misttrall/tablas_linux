import os

import pytest

from sources.sap.connector import SAPConnector

SAP_ENV_VARS = [
    "ETL_TEST_SAP_USER",
    "ETL_TEST_SAP_PASSWD",
    "ETL_TEST_SAP_ASHOST",
    "ETL_TEST_SAP_SYSNR",
    "ETL_TEST_SAP_CLIENT",
]

pytestmark = pytest.mark.skipif(
    not os.environ.get("ETL_TEST_SAP_ASHOST"),
    reason="SAP en vivo no configurado. Requiere: "
    "ETL_TEST_SAP_USER, ETL_TEST_SAP_PASSWD, ETL_TEST_SAP_ASHOST, "
    "ETL_TEST_SAP_SYSNR, ETL_TEST_SAP_CLIENT, ETL_TEST_SAP_LANG "
    "y SAPNWRFC_HOME/LD_LIBRARY_PATH apuntando al SDK",
)

FULL_TABLE_TESTS_ENABLED = os.environ.get("ETL_TEST_SAP_FULL_TABLES") == "1"

SAP_FIELDS_T001L = [
    "MANDT", "WERKS", "LGORT", "LGOBE", "SPART", "XLONG", "XBUFX", "DISKZ",
    "XBLGO", "XRESS", "XHUPF", "PARLG", "VKORG", "VTWEG", "VSTEL", "LIFNR",
    "KUNNR", "MESBS", "MESST", "OIH_LICNO", "OIG_ITRFL", "OIB_TNKASSIGN",
]

SAP_FULL_TABLES = {
    "MARA": ["MATNR", "MTART", "MATKL", "XCHPF", "MEINS"],
    "MAKT": ["MANDT", "MATNR", "SPRAS", "MAKTX", "MAKTG"],
    "MARD": [
        "MANDT", "MATNR", "WERKS", "LGORT", "PSTAT", "LVORM", "LFGJA", "LFMON",
        "SPERR", "LABST", "UMLME", "INSME", "EINME", "SPEME", "RETME", "VMLAB",
        "VMUML", "VMINS", "VMEIN", "VMSPE", "VMRET", "KZILL", "KZILQ", "KZILE",
        "KZILS", "KZVLL", "KZVLQ", "KZVLE", "KZVLS", "DISKZ", "LSOBS", "LMINB",
    ],
    "MBEW": ["MATNR", "BWKEY", "LBKUM", "SALK3", "VPRSV", "STPRS", "VERPR"],
}


def _sap_config():
    return {
        "user": os.environ["ETL_TEST_SAP_USER"],
        "passwd": os.environ["ETL_TEST_SAP_PASSWD"],
        "ashost": os.environ["ETL_TEST_SAP_ASHOST"],
        "sysnr": os.environ["ETL_TEST_SAP_SYSNR"],
        "client": os.environ["ETL_TEST_SAP_CLIENT"],
        "lang": os.environ.get("ETL_TEST_SAP_LANG", "ES"),
    }


@pytest.fixture(scope="module")
def connector():
    conn = SAPConnector(_sap_config())
    conn.connect()
    yield conn
    conn.close()


def test_sap_connect_ping(connector):
    assert connector.ping() is True


def test_sap_extract_small_table(connector):
    df = connector.extract("T001L", SAP_FIELDS_T001L)
    assert list(df.columns) == SAP_FIELDS_T001L
    assert len(df) > 0


def test_sap_extract_filtered(connector):
    fields = ["MANDT", "WERKS", "LGORT", "LGOBE"]
    df_all = connector.extract("T001L", fields)
    werks_values = df_all["WERKS"].astype(str).str.strip()
    werks_values = werks_values[werks_values != ""]
    if len(werks_values) == 0:
        pytest.skip("T001L sin valores WERKS")
    werks = werks_values.iloc[0]
    df_filtered = connector.extract("T001L", fields, filters=[f"WERKS = '{werks}'"])
    assert set(df_filtered["WERKS"].astype(str).str.strip()) <= {werks}


@pytest.mark.skipif(
    not FULL_TABLE_TESTS_ENABLED,
    reason="Extracción full solo contra QA (ETL_TEST_SAP_FULL_TABLES=1)",
)
@pytest.mark.parametrize("table,fields", list(SAP_FULL_TABLES.items()))
def test_sap_extract_full_table(connector, table, fields):
    df = connector.extract(table, fields)
    assert list(df.columns) == fields
    assert len(df) > 0
