from derived.views import derived_view_by_name, view_tab_label


def test_derived_view_by_name_single():
    config = {"derived": {"name": "inv_bodega"}}
    view = derived_view_by_name(config, "inv_bodega")
    assert view == {"name": "inv_bodega"}
    assert derived_view_by_name(config, "otra") is None


def test_derived_view_by_name_list():
    config = {"derived": [
        {"name": "inv_bodega"},
        {"name": "ventas", "tab": "Ventas"},
    ]}
    assert derived_view_by_name(config, "ventas")["tab"] == "Ventas"
    assert derived_view_by_name(config, "nope") is None


def test_view_tab_label_explicit():
    assert view_tab_label({"name": "ventas", "tab": "Ventas"}) == "Ventas"
    assert view_tab_label({"name": "ventas", "tab": ""}) == "Ventas"


def test_view_tab_label_derived_from_name():
    assert view_tab_label({"name": "inv_bodega"}) == "Inv Bodega"
    assert view_tab_label({"name": "ventas_mensuales"}) == "Ventas Mensuales"
    assert view_tab_label({"name": "STOCK_BAJO"}) == "Stock Bajo"
