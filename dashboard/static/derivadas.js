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
      renderEmpty('Datos no disponibles para esta vista');
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
    '<div class="card"><div class="label">Filas</div><div class="value">' +
    Number(sum.total_rows || 0).toLocaleString('es-CL') + '</div></div>' +
    '<div class="card"><div class="label">Total</div><div class="value">' +
    formatMoney(sum.total_value) + '</div></div>' +
    '<div class="card"><div class="label">Alertas</div><div class="value">' +
    sum.alerts_count + '</div></div>';
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
      renderEmpty('Sin datos para esta vista');
      return;
    }
    renderItems(data);
  } catch (e) {
    renderError();
  }
}

function moneyCol(col) {
  return /total|valor|precio|price|amount|cost|value/i.test(col) && !/minimo|min_|stock|qty|exist/i.test(col);
}

function cell(v, col) {
  if (v === null || v === undefined || v === '') return '';
  if (typeof v === 'number' && !isNaN(v) && moneyCol(col)) return formatMoney(v);
  return escapeHtml(v);
}

function numOf(r, keys) {
  for (let i = 0; i < keys.length; i++) {
    const k = keys[i];
    if (r[k] !== undefined && r[k] !== null && r[k] !== '') {
      const n = Number(r[k]);
      if (!isNaN(n)) return n;
    }
  }
  return null;
}

function isLow(r) {
  const q = numOf(r, ['StockLibre', 'Stock', 'Cantidad', 'Cant', 'Qty', 'Existencia']);
  const m = numOf(r, ['stock_minimo', 'StockMinimo', 'Minimo', 'Min', 'Minimum']);
  return q !== null && m !== null && q < m;
}

function displayCols(rows) {
  if (activeColumns && activeColumns.length) {
    return activeColumns.filter(function (c) { return !c.hidden; });
  }
  return Object.keys(rows[0]).map(function (k) { return { as: k, label: k }; });
}

function renderItems(data) {
  const body = document.getElementById('viewBody');
  const rows = data.rows || [];
  if (!rows.length) {
    renderEmpty('Sin resultados con los filtros actuales');
    return;
  }
  const cols = displayCols(rows);
  const head = '<tr>' + cols.map(function (c) {
    return '<th>' + escapeHtml(c.label) + '</th>';
  }).join('') + '</tr>';
  const trs = rows.map(function (r) {
    return '<tr' + (isLow(r) ? ' class="low"' : '') + '>' +
      cols.map(function (c) {
        let v = r[c.as];
        if ((v === undefined || v === null || v === '') && c.fallback) v = r[c.fallback];
        return '<td>' + cell(v, c.as) + '</td>';
      }).join('') +
      '</tr>';
  }).join('');
  const total = Number(data.total || 0);
  const info = 'Página ' + (itemsPageN + 1) + ' · ' + total.toLocaleString('es-CL') + ' resultados' +
    (data.low_only_count ? ' (bajo stock: ' + Number(data.low_only_count).toLocaleString('es-CL') + ')' : '');
  const prevDisabled = itemsPageN === 0;
  const nextDisabled = itemsPageN * ITEMS_LIMIT + rows.length >= total;
  body.innerHTML =
    '<div class="table-wrap"><table><thead>' + head + '</thead><tbody>' + trs + '</tbody></table></div>' +
    '<div class="pager">' +
    '<button id="btnPrev" onclick="itemsPage(itemsPageN - 1)"' + (prevDisabled ? ' disabled' : '') + '>‹ Anterior</button>' +
    '<span>' + info + '</span>' +
    '<button id="btnNext" onclick="itemsPage(itemsPageN + 1)"' + (nextDisabled ? ' disabled' : '') + '>Siguiente ›</button>' +
    '</div>';
}

function renderEmpty(msg) {
  document.getElementById('viewBody').innerHTML =
    '<div id="viewMessage">' + escapeHtml(msg) + '</div>';
}

function renderError() {
  document.getElementById('viewBody').innerHTML =
    '<div id="viewMessage">' +
    '<strong>No se pudieron cargar los datos.</strong>' +
    '<br><button class="btn" style="margin-top:12px" onclick="retryView()">Reintentar</button>' +
    '</div>';
}

function retryView() {
  if (activeView) selectView(activeView);
}

function itemsPage(page) {
  if (page < 0) return;
  itemsPageN = page;
  loadItems();
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
