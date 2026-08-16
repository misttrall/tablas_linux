let views = [];
let activeView = null;

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
    const label = v.tab || tabLabel(v.name);
    return '<button class="tab' + (v.name === activeView ? ' active' : '') +
      '" onclick="selectView(\'' + v.name + '\')">' + label + '</button>';
  }).join('');
  if (!activeView && views.length) selectView(views[0].name);
}

async function selectView(name) {
  activeView = name;
  document.getElementById('viewBody').innerHTML =
    '<div id="viewMessage">Cargando…</div>';
  const res = await api('/api/derived/' + name + '/summary');
  const sum = await res.json();
  const body = document.getElementById('viewBody');
  if (!sum.available) {
    body.innerHTML = '<div id="viewMessage">Datos no disponibles (' + name + ')</div>';
    loadViews();
    return;
  }
  const kpis = document.getElementById('kpis');
  kpis.innerHTML =
    '<div class="card"><div class="label">Filas</div><div class="value">' + sum.total_rows + '</div></div>' +
    '<div class="card"><div class="label">Total</div><div class="value">' + formatMoney(sum.total_value) + '</div></div>' +
    '<div class="card"><div class="label">Alertas</div><div class="value">' + sum.alerts_count + '</div></div>';
  body.innerHTML = '<div id="viewMessage">Filtros y detalle por vista disponibles vía /api/derived/' + name + '/items</div>';
  loadViews();
}

function initDerivadas() {
  renderBranding();
  loadViews();
}

document.addEventListener('DOMContentLoaded', initDerivadas);
