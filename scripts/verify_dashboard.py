#!/usr/bin/env python3
"""Verificación E2E del dashboard (Novus BI Platform).

Requiere Playwright (pip install playwright && playwright install chromium) y un
servidor corriendo (default http://127.0.0.1:8001):

    python scripts/verify_dashboard.py [--base http://127.0.0.1:8001]
                                       [--username demo] [--password demo1234]

Cubre: login y branding, toggle de password, nav por rol admin, redirecciones
(/inventario, root), Vistas (columnas curadas, KPIs, filtros, bajo stock,
búsqueda, paginación), página ETL con botón Sincronizar y cero errores JS.

Exit != 0 ante cualquier fallo.
"""

import argparse
import asyncio
import sys

from playwright.async_api import async_playwright

EXPECT_HEADERS = ["Material", "Descripción", "Centro", "Almacén",
                  "Stock", "Mínimo", "Área", "Valor"]
EXPECT_NAV_ADMIN = [["/etl", "ETL"], ["/panel", "Panel"], ["/derivadas", "Vistas"]]


def check(label, ok, extra=""):
    print(("OK  " if ok else "FAIL") + " " + label + ((" | " + str(extra)) if extra else ""))
    if not ok:
        raise AssertionError(label + ((" | " + str(extra)) if extra else ""))


async def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--username", default="demo")
    ap.add_argument("--password", default="demo1234")
    args = ap.parse_args()

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1360, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append("console:" + m.text) if m.type == "error" else None)

        # --- /inventario sin sesión → /login ---
        await page.goto(args.base + "/inventario", wait_until="networkidle")
        check("redirect /inventario sin sesión", page.url.endswith("/login"), page.url)

        # --- Login: título, toggle password, favicon, branding ---
        await page.goto(args.base + "/login", wait_until="networkidle")
        title = await page.title()
        check("título login", "Novus" in title, title)
        toggled = page.locator("#pwToggle")
        check("toggle password visible", await toggled.is_visible())
        pw = page.locator("#password")
        check("password oculto por defecto", await pw.get_attribute("type") == "password")
        await toggled.click()
        check("toggle muestra password", await pw.get_attribute("type") == "text")
        await toggled.click()
        styles = await page.evaluate("""() => {
          const cs = getComputedStyle(document.body);
          const btn = getComputedStyle(document.querySelector('#loginBtn'));
          const card = getComputedStyle(document.querySelector('.login-box'));
          return {
            font: cs.fontFamily.split(',')[0],
            brand: getComputedStyle(document.documentElement).getPropertyValue('--brand-color').trim(),
            btnRadius: btn.borderRadius,
            boxRadius: card.borderRadius,
            boxTop: card.borderTopColor,
          };
        }""")
        check("branding login", styles["brand"].lower() == "#ea7222", styles["brand"])
        check("fuente login", "Plus Jakarta Sans" in styles["font"], styles["font"])
        check("estilos login",
              styles["btnRadius"] == "999px" and styles["boxRadius"] == "14px"
              and styles["boxTop"] == "rgb(234, 114, 34)", styles)

        # --- Login demo (admin) ---
        await page.fill("#username", args.username)
        await page.fill("#password", args.password)
        await page.click("#loginBtn")
        try:
            await page.wait_for_url("**/panel", timeout=10000)
        except Exception:
            err = await page.locator("#loginError").inner_text() if await page.locator("#loginError").count() else "?"
            print("URL actual:", page.url, "| loginError:", err)
            raise
        await page.wait_for_selector("#users tbody tr", timeout=10000)
        check("login → /panel", True)
        check("toast helper", await page.evaluate("typeof window.toast === 'function'"))

        # --- Nav admin: ETL / Panel / Vistas ---
        links = await page.eval_on_selector_all(
            "header .userbar a", "els => els.map(e => [e.getAttribute('href'), e.textContent])")
        check("nav admin", links == EXPECT_NAV_ADMIN, links)

        # --- Vistas: cabecera curada + KPIs + filtros ---
        await page.goto(args.base + "/derivadas", wait_until="networkidle")
        await page.wait_for_selector(".tab.active", timeout=10000)
        await page.wait_for_selector("table tbody tr", timeout=15000)
        head = await page.locator("#viewBody thead th").all_inner_texts()
        check("columnas de Vistas = vista de inventario", head == EXPECT_HEADERS, head)
        check("sin columnas crudas",
              not any(h in head for h in ("UMB", "Precio", "AlmacenDesc", "MATNR")), head)
        kpis = await page.locator("#kpis .card").count()
        check("3 KPIs", kpis == 3, kpis)
        check("filtros visibles", await page.locator("#filtersBar").is_visible())
        info = await page.locator("#viewBody .pager span").inner_text()
        check("paginación Página 1", "Página 1" in info, info)
        print("      info:", info)

        # filtro bajo stock
        await page.check("#fLowOnly")
        await page.wait_for_timeout(1200)
        info2 = await page.locator("#viewBody .pager span").inner_text()
        check("filtro bajo stock", "bajo stock" in info2, info2)
        await page.uncheck("#fLowOnly")

        # búsqueda
        await page.fill("#fSearch", "perno")
        await page.wait_for_timeout(900)
        await page.wait_for_selector("table tbody tr", timeout=15000)
        check("búsqueda", True)
        await page.fill("#fSearch", "")
        await page.wait_for_timeout(900)

        # paginación
        nxt = page.locator("#viewBody #btnNext")
        if await nxt.is_enabled():
            await nxt.click()
            await page.wait_for_timeout(800)
            info3 = await page.locator("#viewBody .pager span").inner_text()
            check("paginación Página 2", "Página 2" in info3, info3)
            await page.click("#viewBody #btnPrev")
            await page.wait_for_timeout(600)

        # estilos de Vistas
        d = await page.evaluate("""() => {
          const header = getComputedStyle(document.querySelector('header'));
          const tab = getComputedStyle(document.querySelector('.tab.active'));
          const card = getComputedStyle(document.querySelector('#kpis .card'));
          const value = getComputedStyle(document.querySelector('#kpis .card .value'));
          return {
            headerBottom: header.borderBottomColor,
            tabBg: tab.backgroundColor,
            tabRadius: tab.borderRadius,
            cardRadius: card.borderRadius,
            valueColor: value.color,
            navActiveBg: getComputedStyle(document.querySelector('header .userbar a.active')).backgroundColor,
          };
        }""")
        check("estilos Vistas",
              d["headerBottom"] == "rgb(234, 114, 34)" and d["tabBg"] == "rgb(234, 114, 34)"
              and d["tabRadius"] == "999px" and d["cardRadius"] == "14px"
              and d["valueColor"] == "rgb(12, 42, 73)"
              and d["navActiveBg"] == "rgb(234, 114, 34)", d)

        # --- /inventario con sesión → /derivadas ---
        await page.goto(args.base + "/inventario", wait_until="networkidle")
        check("redirect /inventario con sesión", page.url.endswith("/derivadas"), page.url)

        # --- root admin → /panel ---
        await page.goto(args.base + "/", wait_until="networkidle")
        check("root admin → /panel", page.url.endswith("/panel"), page.url)

        # --- ETL: botón Sincronizar + ejecuciones ---
        await page.click('header .userbar a[href="/etl"]')
        await page.wait_for_selector("#btnSync", timeout=10000)
        await page.wait_for_selector("#executions tbody tr", timeout=15000)
        btn = await page.locator("#btnSync").inner_text()
        check("botón Sincronizar en ETL", "Sincronizar" in btn, btn)

        if errors:
            print("JS ERRORS:", errors)
            sys.exit(1)
        print("DASHBOARD_OK")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
