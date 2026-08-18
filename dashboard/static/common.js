async function api(url, opts = {}) {
  const res = await fetch(url, opts);
  if (res.status === 401) {
    if (location.pathname !== '/login') location.href = '/login';
    throw new Error('no_authenticated');
  }
  if (res.status === 403) {
    try {
      const clone = res.clone();
      const data = await clone.json();
      const detail = data.detail || '';
      if (typeof detail === 'string' && (detail.startsWith('licencia:') || detail.startsWith('modulo_no_contratado'))) {
        if (location.pathname !== '/license') {
          location.href = '/license';
        }
        throw new Error(detail);
      }
    } catch (e) {
      if (e.message && (e.message.startsWith('licencia:') || e.message.startsWith('modulo_no_contratado'))) throw e;
    }
    if (location.pathname !== '/login' && location.pathname !== '/license') location.href = '/login';
    throw new Error('forbidden');
  }
  return res;
}

let _licenseDataCache = null;

async function getLicenseStatusData(force = false) {
  if (_licenseDataCache && !force) return _licenseDataCache;
  try {
    const res = await fetch('/api/public/license-status?t=' + Date.now());
    _licenseDataCache = await res.json();
  } catch(e) {
    _licenseDataCache = { state: 'UNKNOWN', is_valid: false, is_grace: false };
  }
  return _licenseDataCache;
}

async function updateHeaderLicensePill() {
  const pill = document.getElementById('headerLicensePill');
  if (!pill) return;
  if (location.pathname === '/login' || location.pathname === '/license') return;
  const data = await getLicenseStatusData();
  if (data.state === 'GRACE') {
    const label = data.grace_days_left != null ? 'Período de Gracia (' + data.grace_days_left + 'd)' : 'Período de Gracia';
    pill.innerHTML =
      '<a href="/license" class="header-license-badge warning" title="' + escapeHtml(data.message || '') + '">' +
      '<span class="pulse-dot warning"></span> ' + escapeHtml(label) +
      '</a>';
  } else if (data.state === 'ACTIVE') {
    pill.innerHTML =
      '<a href="/license" class="header-license-badge success" title="' + escapeHtml(data.message || '') + '">' +
      '<span class="pulse-dot success"></span> Licencia Activa' +
      '</a>';
  } else if (data.state === 'SUSPENDED' || data.state === 'EXPIRED' || data.state === 'REVOKED') {
    pill.innerHTML =
      '<a href="/license" class="header-license-badge danger" title="' + escapeHtml(data.message || data.state) + '">' +
      '<span class="pulse-dot danger"></span> ' + escapeHtml(data.state) +
      '</a>';
  }
}

async function checkAndRenderLicenseBanner() {
  // NUNCA desplegar banners en la pantalla de login ni en la pantalla dedicada de licencia
  if (location.pathname === '/login' || location.pathname === '/license') {
    return true;
  }

  try {
    const data = await getLicenseStatusData(true);
    if (!data.is_valid && data.state !== 'GRACE') {
      location.href = '/license';
      return false;
    }

    const container = document.getElementById('globalLicenseBanner');
    if (data.state === 'GRACE') {
      const bannerHtml =
        '<div class="license-banner-grace">' +
        '<div style="display:flex; align-items:center; gap:12px;">' +
        '<span style="font-size:20px; line-height:1;">⚠️</span>' +
        '<span><strong>Aviso de Licencia:</strong> ' + escapeHtml(data.message || 'Licencia en período de gracia.') + '</span>' +
        '</div>' +
        '<a href="/license" class="license-grace-btn">Ver Estado / Renovar</a>' +
        '</div>';

      if (container) {
        container.innerHTML = bannerHtml;
      }
    } else if (container) {
      container.innerHTML = '';
    }

    updateHeaderLicensePill();
  } catch (e) {}
  return true;
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
  if (typeof detail === 'string' && (detail.startsWith('password_muy_corto') || detail.includes('password_muy_corto'))) {
    return 'La contraseña es muy corta (mínimo 8 caracteres).';
  }
  if (detail === 'password_igual_actual') return 'La nueva contraseña debe ser distinta a la actual.';
  if (detail === 'password_actual_incorrecta') return 'La contraseña actual es incorrecta.';
  if (detail === 'usuario_ya_existe') return 'El nombre de usuario ya existe en el sistema.';
  if (detail === 'usuario_no_encontrado') return 'Usuario no encontrado.';
  if (detail === 'root_protegido') return 'El usuario administrador principal está protegido.';
  return detail;
}

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function toast(message, type) {
  let box = document.getElementById('toastBox');
  if (!box) {
    box = document.createElement('div');
    box.id = 'toastBox';
    document.body.appendChild(box);
  }
  const t = document.createElement('div');
  t.className = 'toast toast-' + (type || 'info');
  t.textContent = message;
  box.appendChild(t);
  setTimeout(function () {
    t.classList.add('hide');
    setTimeout(function () { t.remove(); }, 320);
  }, 3400);
}

function skeletonCards() {
  let h = '';
  for (let i = 0; i < 3; i++) {
    h += '<div class="card skeleton"><div class="sk-line" style="width:40%"></div>' +
      '<div class="sk-line big" style="width:70%"></div></div>';
  }
  return h;
}

function skeletonRows(cols) {
  let h = '';
  for (let i = 0; i < 5; i++) {
    h += '<tr><td colspan="' + cols + '"><div class="sk-row"></div></td></tr>';
  }
  return h;
}

function formatMoney(v) {
  return (typeof v === 'number' && !isNaN(v)) ? '$' + v.toLocaleString('es-CL', { minimumFractionDigits: 2 }) : '-';
}

function renderBranding() {
  fetch('/api/branding').then(function (r) { return r.json(); }).then(function (b) {
    if (b.title) document.title = b.title;
    const t = document.getElementById('appTitle');
    if (t && b.title) t.textContent = b.title;
    if (b.color) document.documentElement.style.setProperty('--brand-color', b.color);
    const img = document.getElementById('appLogo');
    if (img) {
      if (b.logo) {
        img.src = b.logo;
      }
      img.style.display = 'inline-block';
    }
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
    '<div class="modal" style="max-width:480px">' +
    '<div style="display:flex; justify-content:space-between; align-items:flex-start;">' +
    '<div>' +
    '<div class="eyebrow" style="margin-bottom:4px;">Seguridad de la Cuenta</div>' +
    '<h3>Actualizar Contraseña</h3>' +
    '<div class="sub" style="margin-bottom:16px;">Define una nueva clave de acceso de al menos 8 caracteres.</div>' +
    '</div>' +
    '<button id="pwCloseBtn" style="background:transparent; border:none; font-size:20px; color:var(--gray-500); cursor:pointer;">✕</button>' +
    '</div>' +
    '<div class="err" id="pwError"></div>' +
    '<div class="form-group">' +
    '<label>Contraseña Actual</label>' +
    '<input type="password" id="pwCurrent" placeholder="••••••••••••" autocomplete="current-password">' +
    '</div>' +
    '<div class="form-group">' +
    '<label>Nueva Contraseña</label>' +
    '<input type="password" id="pwNew" placeholder="Mínimo 8 caracteres" autocomplete="new-password">' +
    '</div>' +
    '<div class="form-group">' +
    '<label>Confirmar Nueva Contraseña</label>' +
    '<input type="password" id="pwNew2" placeholder="Repite la nueva contraseña" autocomplete="new-password">' +
    '</div>' +
    '<div class="modal-actions">' +
    '<button class="btn btn-secondary" id="pwCancel">Cancelar</button>' +
    '<button class="btn btn-primary" id="pwOk">Actualizar Contraseña</button>' +
    '</div></div>';
  document.body.appendChild(div);
  document.getElementById('pwCancel').onclick = function () {
    div.style.display = 'none';
    document.getElementById('pwError').textContent = '';
  };
  document.getElementById('pwCloseBtn').onclick = function () {
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
  document.getElementById('pwCloseBtn').style.display = forced ? 'none' : 'inline-block';
  const ok = document.getElementById('pwOk');
  ok.onclick = async function () {
    err.textContent = '';
    if (!cur.value) { err.textContent = 'Ingresa tu contraseña actual.'; return; }
    if (n1.value.length < 8) { err.textContent = 'La nueva contraseña debe tener al menos 8 caracteres.'; return; }
    if (n1.value !== n2.value) { err.textContent = 'Las contraseñas nuevas no coinciden.'; return; }
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
  const licOk = await checkAndRenderLicenseBanner();
  if (!licOk) return null;

  if (allowedRoles && !allowedRoles.includes(u.role)) {
    location.href = u.role === 'admin' ? '/panel' : '/derivadas';
    return null;
  }
  if (u.must_change_password) {
    showPasswordModal(true, function () { location.reload(); });
    return null;
  }
  return u;
}

async function triggerBrowserDownload(url, filename) {
  toast('Iniciando descarga de ' + (filename || 'archivo') + '…', 'info');
  try {
    const res = await fetch(url);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Error al descargar archivo' }));
      toast(err.detail || 'Error en la descarga', 'err');
      return false;
    }
    const blob = await res.blob();
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = downloadUrl;
    a.download = filename || 'descarga';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      window.URL.revokeObjectURL(downloadUrl);
      a.remove();
    }, 1000);
    toast('Descarga completada: ' + filename, 'ok');
    return true;
  } catch (e) {
    toast('Error de red al descargar archivo', 'err');
    return false;
  }
}

function navLink(href, label) {
  const cls = location.pathname === href ? ' class="nav-item active"' : ' class="nav-item"';
  return '<a href="' + href + '"' + cls + '>' + label + '</a>';
}

function renderUserbar(user) {
  const bar = document.querySelector('#userbar');
  if (!bar) return;
  const initial = (user.username || 'U').charAt(0).toUpperCase();
  const links = [];
  if (user.role === 'admin') {
    links.push(navLink('/etl', 'ETL'));
    links.push(navLink('/panel', 'Usuarios'));
  }
  links.push(navLink('/derivadas', 'Vistas & BI'));

  bar.innerHTML =
    '<div class="nav-links">' +
    links.join('') +
    '</div>' +
    '<div id="headerLicensePill"></div>' +
    '<div class="user-profile-badge">' +
    '<span class="user-avatar-circle">' + escapeHtml(initial) + '</span>' +
    '<span>' + escapeHtml(user.username) + '</span>' +
    '</div>' +
    '<button class="btn btn-secondary" style="padding:6px 16px; font-size:12.5px;" onclick="logout()">Salir</button>';

  updateHeaderLicensePill();
}

function userMenuPassword() {
  showPasswordModal(false, function () { toast('Contraseña actualizada con éxito', 'ok'); });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', function () {
    renderBranding();
    checkAndRenderLicenseBanner();
  });
} else {
  renderBranding();
  checkAndRenderLicenseBanner();
}

function renderSapModal() {
  if (document.getElementById('sapModal')) return;
  const div = document.createElement('div');
  div.id = 'sapModal';
  div.className = 'modal-backdrop';
  div.style.display = 'none';
  div.innerHTML =
    '<div class="modal" style="max-width:560px">' +
    '<div style="display:flex; justify-content:space-between; align-items:flex-start;">' +
    '<div>' +
    '<div class="eyebrow" style="margin-bottom:4px;">Integración ERP</div>' +
    '<h3>Configuración SAP RFC</h3>' +
    '<div class="sub" style="margin-bottom:18px;">Parámetros de enlace nativo con SAP NetWeaver RFC</div>' +
    '</div>' +
    '<button onclick="closeSapModal()" style="background:transparent; border:none; font-size:20px; color:var(--gray-500); cursor:pointer;">✕</button>' +
    '</div>' +
    '<div class="form-grid">' +
    '<div class="full"><label>Servidor / Host SAP (IP o FQDN) *</label><input type="text" id="sapHost" placeholder="sap-prod.empresa.cl o 192.168.1.100"></div>' +
    '<div><label>Nº de Sistema (sysnr)</label><input type="text" id="sapSysnr" placeholder="00"></div>' +
    '<div><label>Mandante / Client</label><input type="text" id="sapClient" placeholder="100 (o 300)"></div>' +
    '<div><label>Usuario RFC *</label><input type="text" id="sapUser" placeholder="RFC_ETL_USER"></div>' +
    '<div><label>Idioma</label><input type="text" id="sapLang" placeholder="ES"></div>' +
    '<div class="full"><label>Contraseña RFC *</label><input type="password" id="sapPass" placeholder="Contraseña de usuario RFC"></div>' +
    '</div>' +
    '<div id="sapStatusBox" class="conn-status-box"></div>' +
    '<div class="actions" style="margin-top:20px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px;">' +
    '<button class="btn btn-outline" id="btnTestSap" onclick="testSapConnection()">Probar Conexión RFC</button>' +
    '<div style="display:flex; gap:8px;">' +
    '<button class="btn btn-secondary" onclick="closeSapModal()">Cancelar</button>' +
    '<button class="btn btn-primary" id="btnSaveSap" onclick="saveSapConnection()">Guardar Configuración</button>' +
    '</div>' +
    '</div>' +
    '</div>';
  document.body.appendChild(div);

  ['sapHost', 'sapSysnr', 'sapClient', 'sapUser', 'sapPass', 'sapLang'].forEach(function(id) {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('input', function() {
        el.classList.remove('is-invalid');
        const box = document.getElementById('sapStatusBox');
        if (box && box.classList.contains('err')) {
          box.style.display = 'none';
        }
      });
    }
  });
}

function showSapModal() {
  renderSapModal();
  const box = document.getElementById('sapStatusBox');
  if (box) { box.className = 'conn-status-box'; box.textContent = ''; box.style.display = 'none'; }
  ['sapHost', 'sapSysnr', 'sapClient', 'sapUser', 'sapPass', 'sapLang'].forEach(function(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('is-invalid');
  });
  fetch('/api/onboarding/status')
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (data) {
        document.getElementById('sapHost').value = data.ashost || '';
        document.getElementById('sapSysnr').value = data.sysnr || '';
        document.getElementById('sapClient').value = data.client || '';
        document.getElementById('sapUser').value = data.user || '';
        document.getElementById('sapLang').value = data.lang || 'ES';
        if (data.has_password) {
          document.getElementById('sapPass').placeholder = '(Contraseña guardada - dejar vacío para conservar)';
        }
      }
    });
  document.getElementById('sapModal').style.display = 'flex';
}

function closeSapModal() {
  const m = document.getElementById('sapModal');
  if (m) m.style.display = 'none';
}

async function testSapConnection() {
  const btn = document.getElementById('btnTestSap');
  const box = document.getElementById('sapStatusBox');
  const hostEl = document.getElementById('sapHost');
  const sysnrEl = document.getElementById('sapSysnr');
  const clientEl = document.getElementById('sapClient');
  const userEl = document.getElementById('sapUser');
  const passEl = document.getElementById('sapPass');
  const langEl = document.getElementById('sapLang');

  [hostEl, sysnrEl, clientEl, userEl, passEl, langEl].forEach(el => el.classList.remove('is-invalid'));

  const host = hostEl.value.trim();
  const sysnr = sysnrEl.value.trim();
  const client = clientEl.value.trim();
  const user = userEl.value.trim();
  const pass = passEl.value;
  const lang = langEl.value.trim();

  let hasErrors = false;
  if (!host) { hostEl.classList.add('is-invalid'); hasErrors = true; }
  if (!user) { userEl.classList.add('is-invalid'); hasErrors = true; }
  if (!pass) { passEl.classList.add('is-invalid'); hasErrors = true; }

  if (hasErrors) {
    box.className = 'conn-status-box err';
    box.textContent = 'Por favor completa todos los campos requeridos marcados con (*) (Servidor Host, Usuario RFC y Contraseña) para probar la conexión.';
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> Probando Conexión RFC…';
  box.className = 'conn-status-box';
  box.style.display = 'none';

  try {
    const res = await fetch('/api/onboarding/test-sap', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ashost: host, sysnr: sysnr || '00', client: client || '100', user: user, passwd: pass, lang: lang || 'ES' }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      box.className = 'conn-status-box ok';
      box.textContent = 'Se estableció la conexión exitosamente con el servidor SAP NetWeaver (Mandante: ' + (client || '100') + ', Nº Sistema: ' + (sysnr || '00') + '). Conectividad operativa.';
      toast('Conexión con SAP exitosa', 'ok');
    } else {
      box.className = 'conn-status-box err';
      const msg = data.message || data.error || data.detail || 'No se pudo establecer conexión con el servidor SAP ERP. Verifica la dirección del Host y las credenciales RFC ingresadas.';
      box.textContent = msg;
      toast('No se pudo conectar con SAP', 'err');
    }
  } catch (err) {
    box.className = 'conn-status-box err';
    box.textContent = 'No se pudo establecer conexión: Error de red o tiempo de espera agotado al comunicar con el servidor SAP.';
    toast('Error de red en la conexión con SAP', 'err');
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Probar Conexión RFC';
  }
}

async function saveSapConnection() {
  const btn = document.getElementById('btnSaveSap');
  const box = document.getElementById('sapStatusBox');
  const hostEl = document.getElementById('sapHost');
  const sysnrEl = document.getElementById('sapSysnr');
  const clientEl = document.getElementById('sapClient');
  const userEl = document.getElementById('sapUser');
  const passEl = document.getElementById('sapPass');
  const langEl = document.getElementById('sapLang');

  [hostEl, sysnrEl, clientEl, userEl, passEl, langEl].forEach(el => el.classList.remove('is-invalid'));

  const host = hostEl.value.trim();
  const sysnr = sysnrEl.value.trim();
  const client = clientEl.value.trim();
  const user = userEl.value.trim();
  const pass = passEl.value;
  const lang = langEl.value.trim();

  let hasErrors = false;
  if (!host) { hostEl.classList.add('is-invalid'); hasErrors = true; }
  if (!user) { userEl.classList.add('is-invalid'); hasErrors = true; }

  if (hasErrors) {
    box.className = 'conn-status-box err';
    box.textContent = 'Por favor completa el Servidor Host y Usuario RFC para guardar la configuración.';
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> Guardando…';

  try {
    const res = await fetch('/api/onboarding/save-sap', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ashost: host, sysnr: sysnr || '00', client: client || '100', user: user, passwd: pass, lang: lang || 'ES' }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      box.className = 'conn-status-box ok';
      box.textContent = 'Configuración RFC guardada exitosamente en el sistema.';
      toast('Configuración SAP guardada con éxito', 'ok');
      setTimeout(function() {
        closeSapModal();
        const banner = document.getElementById('onboardingBanner');
        if (banner) banner.style.display = 'none';
      }, 1200);
    } else {
      box.className = 'conn-status-box err';
      box.textContent = data.detail || data.message || 'Error al guardar la configuración de SAP.';
    }
  } catch (err) {
    box.className = 'conn-status-box err';
    box.textContent = 'Error de comunicación con el backend al guardar la configuración.';
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Guardar Configuración';
  }
}

async function maybeCheckOnboardingBanner(user) {
  if (!user || user.role !== 'admin') return;
  try {
    const res = await fetch('/api/onboarding/status');
    if (!res.ok) return;
    const data = await res.json();
    const existing = document.getElementById('onboardingBanner');
    if (data.source_type === 'sap' && !data.configured) {
      renderSapModal();
      const main = document.querySelector('main');
      if (main && !existing) {
        const b = document.createElement('div');
        b.id = 'onboardingBanner';
        b.className = 'err';
        b.style.display = 'block';
        b.innerHTML = '<strong>Configuración SAP pendiente:</strong> Ingresa los parámetros RFC en la barra de herramientas para habilitar las sincronizaciones automáticas.';
        main.prepend(b);
      }
    } else if (existing) {
      existing.remove();
    }
  } catch (e) { /* silenciar */ }
}
