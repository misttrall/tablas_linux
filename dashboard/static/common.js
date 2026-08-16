async function api(url, opts = {}) {
  const res = await fetch(url, opts);
  if (res.status === 401 || res.status === 403) {
    if (location.pathname !== '/login') location.href = '/login';
    throw new Error('no_authenticated');
  }
  return res;
}

async function me() {
  const res = await api('/api/auth/me');
  return res.json();
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  location.href = '/login';
}

async function changePassword(current, next) {
  const res = await api('/api/auth/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: current, new_password: next }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || 'No se pudo cambiar la password');
  return data;
}

function friendlyError(detail) {
  if (!detail) return 'Operación fallida.';
  if (typeof detail === 'string' && detail.startsWith('password_muy_corto')) {
    return 'La password es muy corta (mínimo 8).';
  }
  if (detail === 'password_igual_actual') return 'La password nueva debe ser distinta a la actual.';
  if (detail === 'password_actual_incorrecta') return 'Password actual incorrecta.';
  if (detail === 'root_protegido') return 'El usuario root está protegido.';
  return detail;
}

function formatMoney(v) {
  return (typeof v === 'number' && !isNaN(v)) ? '$' + v.toLocaleString('es-CL', { minimumFractionDigits: 2 }) : '-';
}

function renderBranding() {
  fetch('/api/branding').then(function (r) { return r.json(); }).then(function (b) {
    if (b.title) document.title = b.title;
    const t = document.getElementById('appTitle');
    if (t && b.title) t.textContent = b.title;
    const f = document.getElementById('appFooter');
    if (f && b.footer) f.textContent = b.footer;
  }).catch(function () {});
}

function renderPasswordModal() {
  const div = document.createElement('div');
  div.id = 'passwordModal';
  div.className = 'modal-backdrop';
  div.style.display = 'none';
  div.innerHTML =
    '<div class="modal">' +
    '<h3>Cambiar password</h3>' +
    '<div class="err" id="pwError"></div>' +
    '<label>Password actual</label><input type="password" id="pwCurrent">' +
    '<label>Password nueva</label><input type="password" id="pwNew">' +
    '<label>Repetir password nueva</label><input type="password" id="pwNew2">' +
    '<div class="modal-actions">' +
    '<button class="btn" id="pwCancel" style="display:none">Cancelar</button>' +
    '<button class="btn" id="pwOk">Cambiar</button>' +
    '</div></div>';
  document.body.appendChild(div);
  document.getElementById('pwCancel').onclick = function () {
    div.style.display = 'none';
    document.getElementById('pwError').textContent = '';
  };
  return div;
}

function showPasswordModal(forced, onDone) {
  const m = document.getElementById('passwordModal') || renderPasswordModal();
  m.style.display = 'flex';
  const err = document.getElementById('pwError');
  const cur = document.getElementById('pwCurrent');
  const n1 = document.getElementById('pwNew');
  const n2 = document.getElementById('pwNew2');
  cur.value = ''; n1.value = ''; n2.value = '';
  err.textContent = '';
  document.getElementById('pwCancel').style.display = forced ? 'none' : 'inline-block';
  const ok = document.getElementById('pwOk');
  ok.onclick = async function () {
    err.textContent = '';
    if (!cur.value) { err.textContent = 'Ingresa tu password actual.'; return; }
    if (n1.value !== n2.value) { err.textContent = 'Las passwords nuevas no coinciden.'; return; }
    try {
      await changePassword(cur.value, n1.value);
    } catch (e) {
      err.textContent = friendlyError(e.message);
      return;
    }
    m.style.display = 'none';
    onDone();
  };
}

async function bootPage(allowedRoles) {
  let u;
  try {
    u = await me();
  } catch (e) {
    return null;
  }
  if (allowedRoles && !allowedRoles.includes(u.role)) {
    location.href = u.role === 'admin' ? '/panel' : '/inventario';
    return null;
  }
  if (u.must_change_password) {
    showPasswordModal(true, function () { location.reload(); });
    return null;
  }
  return u;
}

function renderUserbar(user) {
  const bar = document.querySelector('#userbar');
  if (!bar) return;
  const role = user.role === 'admin' ? 'admin' : 'usuario';
  const links = [];
  if (user.role === 'admin') {
    links.push('<a href="/etl">ETL</a>');
    links.push('<a href="/inventario">Inventario</a>');
    links.push('<a href="/panel">Panel</a>');
  } else {
    links.push('<a href="/inventario">Inventario</a>');
  }
  bar.innerHTML = links.join('') +
    '<span class="user-menu">' +
    '<button class="user-menu-btn" onclick="toggleUserMenu(event)">' +
    user.username + ' (' + role + ') ▾</button>' +
    '<div class="dropdown" id="userMenu" style="display:none">' +
    '<button class="dropdown-item" onclick="userMenuPassword()">Cambiar contraseña</button>' +
    '<button class="dropdown-item" onclick="logout()">Salir</button>' +
    '</div></span>';
}

function toggleUserMenu(event) {
  event.stopPropagation();
  const dd = document.getElementById('userMenu');
  if (!dd) return;
  dd.style.display = dd.style.display === 'none' ? 'block' : 'none';
}

function closeUserMenu() {
  const dd = document.getElementById('userMenu');
  if (dd) dd.style.display = 'none';
}

function userMenuPassword() {
  closeUserMenu();
  showPasswordModal(false, function () { alert('Password actualizada'); });
}

document.addEventListener('click', closeUserMenu);
