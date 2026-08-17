let views = [];
let activeView = null;
let activeColumns = [];
let itemsPageN = 0;
const ITEMS_LIMIT = 50;
let searchTimer = null;

function tabLabel(name) {
  return name.split('_').map(function (w) {
    return w.charAt(0).toUpperCase() + w.slice(1);
  }).join(' ');
}

async function loadViews() {
  const res = await api('/api/derived-views');
  const data = await res.json();
  views = data.views || [];
  const nav = document.getElementById('tabs');
  nav.innerHTML = views.map(function (v) {
    const label = escapeHtml(v.tab || tabLabel(v.name));
    return '<button class="tab' + (v.name === activeView ? ' active' : '') +
      '" onclick="selectView(\'' + v.name + '\')">' + label + '</button>';
  }).join('');
  if (!activeView && views.length) selectView(views[0].name);
}

function showSkeleton() {
  document.getElementById('kpis').innerHTML = skeletonCards();
  document.getElementById('viewBody').innerHTML =
    '<div class="table-wrap"><table><tbody>' + skeletonRows(5) + '</tbody></table></div>';
  document.getElementById('filtersBar').style.display = 'none';
}

async function selectView(name) {
  activeView = name;
  itemsPageN = 0;
  const v = views.filter(function (x) { return x.name === name; })[0];
  activeColumns = (v && v.columns) || [];
  showSkeleton();
  loadViews();
  try {
    const res = await api('/api/derived/' + name + '/summary');
    const sum = await res.json();
    if (!sum.available) {
      renderEmpty('Datos no disponibles para esta vista (requiere sincronización)');
      return;
    }
    renderKpis(sum);
    await loadFilters();
    await loadItems();
  } catch (e) {
    renderError();
  }
}

function renderKpis(sum) {
  document.getElementById('kpis').innerHTML =
    '<div class="card">' +
    '<div class="eyebrow">Inventario</div>' +
    '<div class="label">Total Materiales</div>' +
    '<div class="value">' + Number(sum.total_rows || 0).toLocaleString('es-CL') + '</div>' +
    '<div class="sub-stat">Registros en maestro de materiales</div>' +
    '</div>' +
    '<div class="card">' +
    '<div class="eyebrow">Finanzas</div>' +
    '<div class="label">Valorización de Stock</div>' +
    '<div class="value">' + formatMoney(sum.total_value) + '</div>' +
    '<div class="sub-stat">Costo promedio ponderado (VERPR)</div>' +
    '</div>' +
    '<div class="card">' +
    '<div class="eyebrow">Control Operacional</div>' +
    '<div class="label">Alertas de Stock Bajo</div>' +
    '<div class="value" style="color:' + (sum.alerts_count > 0 ? '#DC2626' : 'var(--navy)') + '">' +
    Number(sum.alerts_count || 0).toLocaleString('es-CL') + '</div>' +
    '<div class="sub-stat">' + (sum.alerts_count > 0 ? 'Materiales bajo punto de reorden' : 'Niveles de stock conformes') + '</div>' +
    '</div>' +
    '<div class="card">' +
    '<div class="eyebrow">Integración BI</div>' +
    '<div class="label">Conectividad Power BI</div>' +
    '<div class="value" style="font-size:22px; color:var(--navy); margin-top:4px;">En Línea</div>' +
    '<div class="sub-stat">Dataset Parquet y DirectQuery activo</div>' +
    '</div>';
}

async function loadFilters() {
  const bar = document.getElementById('filtersBar');
  try {
    const res = await api('/api/derived/' + activeView + '/filters');
    const data = await res.json();
    if (!data.available) { bar.style.display = 'none'; return; }
    setFilterOptions('fCentro', data.centro || []);
    setFilterOptions('fAlmacen', data.almacen || []);
    setFilterOptions('fArea', data.area || []);
    bar.style.display = 'flex';
  } catch (e) {
    bar.style.display = 'none';
  }
}

function setFilterOptions(id, values) {
  const sel = document.getElementById(id);
  const keep = sel.value;
  const label = id === 'fArea' ? 'Área: todas' : id === 'fAlmacen' ? 'Almacén: todos' : 'Centro: todos';
  sel.innerHTML = '<option value="">' + label + '</option>' +
    values.map(function (v) {
      return '<option value="' + escapeHtml(v) + '">' + escapeHtml(v) + '</option>';
    }).join('');
  if (keep && values.indexOf(keep) >= 0) sel.value = keep;
}

function itemsQuery() {
  const p = new URLSearchParams();
  const c = document.getElementById('fCentro').value;
  const a = document.getElementById('fAlmacen').value;
  const ar = document.getElementById('fArea').value;
  const q = document.getElementById('fSearch').value.trim();
  const lo = document.getElementById('fLowOnly').checked;
  if (c) p.set('centro', c);
  if (a) p.set('almacen', a);
  if (ar) p.set('area', ar);
  if (q) p.set('q', q);
  if (lo) p.set('low_only', 'true');
  p.set('limit', ITEMS_LIMIT);
  p.set('offset', itemsPageN * ITEMS_LIMIT);
  return p;
}

async function loadItems() {
  const body = document.getElementById('viewBody');
  body.innerHTML = '<div class="table-wrap"><table><tbody>' + skeletonRows(5) + '</tbody></table></div>';
  try {
    const res = await api('/api/derived/' + activeView + '/items?' + itemsQuery().toString());
    const data = await res.json();
    if (!data.available) {
      renderEmpty('Sin datos disponibles para esta vista');
      return;
    }
    renderItems(data);
  } catch (e) {
    renderError();
  }
}

function renderEmpty(msg) {
  document.getElementById('viewBody').innerHTML =
    '<div class="table-wrap" style="padding:48px 24px; text-align:center; color:var(--gray-500);">' +
    '<h4 style="color:var(--navy); margin-bottom:8px;">Sin registros</h4>' +
    '<p>' + escapeHtml(msg) + '</p>' +
    '</div>';
}

function renderError() {
  document.getElementById('viewBody').innerHTML =
    '<div class="table-wrap" style="padding:48px 24px; text-align:center; color:#DC2626;">' +
    '<h4 style="color:#DC2626; margin-bottom:8px;">Error al cargar datos</h4>' +
    '<p>Ocurrió un problema al comunicarse con el servidor.</p>' +
    '</div>';
}

function renderItems(data) {
  const rows = data.rows || [];
  const total = data.total || 0;
  const body = document.getElementById('viewBody');

  if (rows.length === 0) {
    body.innerHTML =
      '<div class="table-wrap" style="padding:48px 24px; text-align:center; color:var(--gray-500);">' +
      '<p>No se encontraron registros con los filtros seleccionados.</p>' +
      '</div>';
    return;
  }

  const cols = activeColumns.length ? activeColumns : Object.keys(rows[0]).map(function (k) {
    return { as: k, label: k };
  });

  const thead = '<thead><tr>' +
    cols.map(function (c) {
      const cls = isNumericColumn(c.as) ? ' style="text-align:right;"' : '';
      return '<th' + cls + '>' + escapeHtml(c.label || c.as) + '</th>';
    }).join('') +
    '<th style="text-align:center;">Estado Stock</th>' +
    '</tr></thead>';

  const tbody = '<tbody>' +
    rows.map(function (r) {
      const stock = Number(r.StockLibre || r.LABST || 0);
      const min = Number(r.stock_minimo || 0);
      const isLow = min > 0 && stock < min;
      const trClass = isLow ? ' class="low"' : '';

      const cells = cols.map(function (c) {
        const val = r[c.as];
        const num = isNumericColumn(c.as);
        const formatted = formatCell(c.as, val);
        const style = num ? ' style="text-align:right; font-family:var(--font-mono);"' : '';
        return '<td' + style + '>' + escapeHtml(formatted) + '</td>';
      }).join('');

      const badge = isLow
        ? '<span class="tag tag-danger">Stock Bajo</span>'
        : '<span class="tag tag-ok">Óptimo</span>';

      return '<tr' + trClass + '>' + cells + '<td style="text-align:center;">' + badge + '</td></tr>';
    }).join('') +
    '</tbody>';

  const start = itemsPageN * ITEMS_LIMIT + 1;
  const end = Math.min((itemsPageN + 1) * ITEMS_LIMIT, total);
  const totalPages = Math.ceil(total / ITEMS_LIMIT) || 1;

  const pager =
    '<div class="pager">' +
    '<span>Mostrando ' + start + '–' + end + ' de ' + total.toLocaleString('es-CL') + ' registros</span>' +
    '<div style="display:flex; gap:8px; align-items:center;">' +
    '<button ' + (itemsPageN === 0 ? 'disabled' : '') + ' onclick="itemsPage(' + (itemsPageN - 1) + ')">Anterior</button>' +
    '<span>Página ' + (itemsPageN + 1) + ' de ' + totalPages + '</span>' +
    '<button ' + (end >= total ? 'disabled' : '') + ' onclick="itemsPage(' + (itemsPageN + 1) + ')">Siguiente</button>' +
    '</div>' +
    '</div>';

  body.innerHTML = '<div class="table-wrap"><table>' + thead + tbody + '</table>' + pager + '</div>';
}

function isNumericColumn(name) {
  const lower = (name || '').toLowerCase();
  return lower.includes('stock') || lower.includes('precio') || lower.includes('valor') ||
    lower.includes('labst') || lower.includes('verpr') || lower.includes('total');
}

function formatCell(col, val) {
  if (val === null || val === undefined) return '-';
  const lower = (col || '').toLowerCase();
  if (lower.includes('valor') || lower.includes('precio')) {
    return formatMoney(val);
  }
  if (typeof val === 'number') {
    return val.toLocaleString('es-CL');
  }
  return String(val);
}

function formatMoney(val) {
  if (val === null || val === undefined || isNaN(val)) return '$0';
  return '$' + Math.round(Number(val)).toLocaleString('es-CL');
}

function itemsPage(pageN) {
  itemsPageN = Math.max(0, pageN);
  loadItems();
}

function skeletonCards() {
  return '<div class="card"><div class="label">Cargando…</div><div class="value">-</div></div>' +
    '<div class="card"><div class="label">Cargando…</div><div class="value">-</div></div>' +
    '<div class="card"><div class="label">Cargando…</div><div class="value">-</div></div>' +
    '<div class="card"><div class="label">Cargando…</div><div class="value">-</div></div>';
}

function skeletonRows(n) {
  let s = '';
  for (let i = 0; i < n; i++) {
    s += '<tr><td colspan="8" style="padding:16px; color:var(--gray-500);">Cargando registros…</td></tr>';
  }
  return s;
}

// Descargas
function downloadViewExcel() {
  if (!activeView) return;
  const url = '/api/derived/' + activeView + '/export/excel';
  triggerBrowserDownload(url, activeView + '.xlsx');
}

function downloadViewCsv() {
  if (!activeView) return;
  const url = '/api/derived/' + activeView + '/export/csv';
  triggerBrowserDownload(url, activeView + '.csv');
}

function downloadBiParquet() {
  if (!activeView) return;
  const url = '/api/bi/download/' + activeView + '/parquet';
  triggerBrowserDownload(url, activeView + '.parquet');
}

function downloadBiManifest() {
  triggerBrowserDownload('/api/bi/download/manifest', 'manifest.json');
}

function downloadBiGuideFile() {
  triggerBrowserDownload('/api/bi/download/guide', 'GUIA_CONEXION_POWER_BI.md');
}

function downloadBiZip() {
  triggerBrowserDownload('/api/bi/download-zip', 'novus_power_bi_dataset.zip');
}

// Modal Power BI
function renderBiModal() {
  if (document.getElementById('biModal')) return;
  const div = document.createElement('div');
  div.id = 'biModal';
  div.className = 'modal-backdrop';
  div.style.display = 'none';
  div.innerHTML =
    '<div class="modal">' +
    '<div style="display:flex; justify-content:space-between; align-items:flex-start;">' +
    '<div>' +
    '<h3>Entregables y Exportación Power BI</h3>' +
    '<div class="sub">Modelos de datos optimizados para análisis y reportería ejecutiva</div>' +
    '</div>' +
    '<button onclick="closeBiModal()" style="background:transparent; border:none; font-size:20px; color:var(--gray-500); cursor:pointer;">✕</button>' +
    '</div>' +

    '<div style="background:var(--gray-50); border:1px solid var(--gray-100); border-radius:var(--radius-sm); padding:16px; margin-bottom:18px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">' +
    '<div>' +
    '<div style="font-weight:700; font-size:14px; color:var(--navy);">Compilación de Modelos BI</div>' +
    '<div style="font-size:12.5px; color:var(--gray-500);">Genera los archivos Parquet de alto rendimiento y actualiza el manifiesto</div>' +
    '</div>' +
    '<button class="btn btn-primary" id="btnGenBi" onclick="generateBiExport()">Compilar Modelos</button>' +
    '</div>' +

    '<div id="biStatusBox" class="conn-status-box"></div>' +

    '<div class="eyebrow" style="margin-bottom:10px;">Formatos Individuales</div>' +
    '<div class="download-grid">' +
    '<div class="download-card">' +
    '<div><div class="file-title">Dataset Parquet</div><div class="file-desc">Optimizado para Power BI Desktop y DirectQuery</div></div>' +
    '<button class="btn btn-secondary" style="width:100%; padding:8px 12px; font-size:12.5px;" onclick="downloadBiParquet()">Descargar .parquet</button>' +
    '</div>' +
    '<div class="download-card">' +
    '<div><div class="file-title">Dataset CSV</div><div class="file-desc">Datos tabulares completos en formato UTF-8</div></div>' +
    '<button class="btn btn-secondary" style="width:100%; padding:8px 12px; font-size:12.5px;" onclick="downloadViewCsv()">Descargar .csv</button>' +
    '</div>' +
    '<div class="download-card">' +
    '<div><div class="file-title">Manifiesto JSON</div><div class="file-desc">Metadatos, llaves primarias y esquemas de vistas</div></div>' +
    '<button class="btn btn-secondary" style="width:100%; padding:8px 12px; font-size:12.5px;" onclick="downloadBiManifest()">Descargar .json</button>' +
    '</div>' +
    '<div class="download-card">' +
    '<div><div class="file-title">Guía de Conexión</div><div class="file-desc">Documentación técnica de enlace</div></div>' +
    '<button class="btn btn-secondary" style="width:100%; padding:8px 12px; font-size:12.5px;" onclick="downloadBiGuideFile()">Descargar .md</button>' +
    '</div>' +
    '</div>' +

    '<div style="margin-top:20px; padding-top:20px; border-top:1px solid var(--gray-100); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">' +
    '<div>' +
    '<div style="font-weight:700; font-size:13.5px; color:var(--navy);">Paquete Completo de Modelos</div>' +
    '<div style="font-size:12px; color:var(--gray-500);">Descarga un solo archivo comprimido con todos los entregables</div>' +
    '</div>' +
    '<button class="btn btn-primary" onclick="downloadBiZip()">Descargar Paquete ZIP</button>' +
    '</div>' +

    '<div style="margin-top:20px;">' +
    '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">' +
    '<div class="eyebrow" style="margin-bottom:0;">Instrucciones de Conectividad</div>' +
    '<button onclick="copyBiGuide()" style="background:transparent; border:none; color:var(--orange-dark); font-weight:700; font-size:12px; cursor:pointer;" id="btnCopyGuide">Copiar Guía</button>' +
    '</div>' +
    '<div id="biGuideBox" style="background:var(--gray-50); border:1px solid var(--gray-300); border-radius:var(--radius-sm); padding:14px; font-size:12px; max-height:160px; overflow-y:auto; font-family:var(--font-mono); white-space:pre-wrap; color:var(--gray-700);">Cargando guía…</div>' +
    '</div>' +

    '<div style="margin-top:24px; text-align:right;">' +
    '<button class="btn btn-secondary" onclick="closeBiModal()">Cerrar</button>' +
    '</div>' +
    '</div>';
  document.body.appendChild(div);
}

function showBiModal() {
  renderBiModal();
  const box = document.getElementById('biStatusBox');
  if (box) { box.className = 'conn-status-box'; box.textContent = ''; box.style.display = 'none'; }
  document.getElementById('biModal').style.display = 'flex';
  loadBiGuide();
}

function closeBiModal() {
  const m = document.getElementById('biModal');
  if (m) m.style.display = 'none';
}

async function loadBiGuide() {
  const guideBox = document.getElementById('biGuideBox');
  try {
    const res = await api('/api/bi/guide');
    if (!res.ok) {
      guideBox.textContent = 'Módulo BI no disponible en la licencia actual.';
      return;
    }
    const data = await res.json();
    guideBox.textContent = data.guide_markdown || 'Sin contenido de guía.';
  } catch (e) {
    guideBox.textContent = 'No se pudo cargar la guía de conexión.';
  }
}

async function copyBiGuide() {
  const guideBox = document.getElementById('biGuideBox');
  const btn = document.getElementById('btnCopyGuide');
  if (!guideBox) return;
  try {
    await navigator.clipboard.writeText(guideBox.textContent);
    btn.textContent = 'Copiado al Portapapeles';
    toast('Guía copiada al portapapeles', 'ok');
    setTimeout(function () { btn.textContent = 'Copiar Guía'; }, 2500);
  } catch (e) {
    toast('Selecciona el texto para copiar manualmente', 'info');
  }
}

async function generateBiExport() {
  const btn = document.getElementById('btnGenBi');
  const box = document.getElementById('biStatusBox');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> Compilando…';
  box.className = 'conn-status-box';
  box.style.display = 'none';

  try {
    const res = await fetch('/api/bi/export', { method: 'POST' });
    const data = await res.json();
    if (res.ok && data.ok) {
      const filesCount = (data.files || []).length;
      box.className = 'conn-status-box ok';
      box.textContent = 'Modelos compilados exitosamente (' + filesCount + ' vistas procesadas). Listo para descarga directa.';
      toast('Modelos Power BI compilados', 'ok');
    } else {
      box.className = 'conn-status-box err';
      box.textContent = data.detail || data.message || 'Error al exportar dataset BI';
    }
  } catch (err) {
    box.className = 'conn-status-box err';
    box.textContent = 'Error de red al generar modelos BI.';
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Compilar Modelos';
  }
}

function scheduleSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(function () { itemsPage(0); }, 400);
}

function bindFilters() {
  ['fCentro', 'fAlmacen', 'fArea'].forEach(function (id) {
    document.getElementById(id).addEventListener('change', function () { itemsPage(0); });
  });
  document.getElementById('fSearch').addEventListener('input', scheduleSearch);
  document.getElementById('fLowOnly').addEventListener('change', function () { itemsPage(0); });
}

async function initDerivadas() {
  const u = await bootPage(['user', 'admin']);
  if (!u) return;
  renderUserbar(u);
  bindFilters();
  loadViews();
}

document.addEventListener('DOMContentLoaded', initDerivadas);
