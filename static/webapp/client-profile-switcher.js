/**
 * EPIC1 Slice 6: client profile switcher (self + guardian/child profiles).
 *
 * Two jobs in one file, both self-contained (no build step, matches this codebase's
 * plain-JS static/webapp/*.js convention):
 *
 * 1. Attach `X-Profile-Id` to every `/api/webapp/client/*` fetch once the visitor has
 *    switched away from their own (default) profile — a global `window.fetch` patch, so
 *    pages that only include this script (no chip UI) still send the right header without
 *    touching each page's own fetch call sites. Silent no-op for the overwhelming majority
 *    of accounts that never add a child profile: no header is ever sent, current behavior
 *    is unchanged byte-for-byte.
 * 2. On pages that opt in with a `#clientProfileSwitcherMount` element, render the current
 *    profile chip + a bottom sheet to switch profiles or add a child
 *    (GET/POST /client/profiles, PATCH .../default — see .ai/EPIC1-client-multi-profile.md).
 *
 * Selection is client-only (localStorage) — the server has no notion of "current screen",
 * only of which profiles an account may act as (client_profile_links).
 */
(function () {
  var STORAGE_KEY = 'cw_active_profile_id_v1';
  var tg = window.Telegram && window.Telegram.WebApp;
  var initData = tg && tg.initData ? tg.initData : '';

  var state = {
    profiles: [],
    defaultProfileId: null,
    activeProfileId: readStoredProfileId(),
    loaded: false,
  };

  function readStoredProfileId() {
    try {
      var v = window.localStorage.getItem(STORAGE_KEY);
      return v ? parseInt(v, 10) : null;
    } catch (e) {
      return null;
    }
  }

  function writeStoredProfileId(id) {
    try {
      if (id == null) window.localStorage.removeItem(STORAGE_KEY);
      else window.localStorage.setItem(STORAGE_KEY, String(id));
    } catch (e) {
      /* ignore — worst case the switch doesn't persist across reloads */
    }
  }

  /* ── fetch patch ──────────────────────────────────────────────────── */
  var nativeFetch = window.fetch ? window.fetch.bind(window) : null;
  if (nativeFetch) {
    window.fetch = function (input, init) {
      try {
        if (
          typeof input === 'string' &&
          input.indexOf('/api/webapp/client/') !== -1 &&
          state.activeProfileId != null &&
          state.activeProfileId !== state.defaultProfileId
        ) {
          init = init || {};
          var headers = init.headers ? Object.assign({}, init.headers) : {};
          headers['X-Profile-Id'] = String(state.activeProfileId);
          init = Object.assign({}, init, { headers: headers });
        }
      } catch (e) {
        /* a broken tag must never block the actual request */
      }
      return nativeFetch(input, init);
    };
  }

  /* ── data ─────────────────────────────────────────────────────────── */
  function apiUrl(path) {
    var url = '/api/webapp' + path;
    if (initData) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
    return url;
  }

  function jsonHeaders() {
    var h = { 'Content-Type': 'application/json' };
    if (initData) h['X-Telegram-Init-Data'] = initData;
    return h;
  }

  function loadProfiles() {
    return nativeFetch(apiUrl('/client/profiles'), { headers: jsonHeaders() })
      .then(function (r) {
        return r.ok ? r.json() : { items: [], default_profile_id: null };
      })
      .then(function (data) {
        state.profiles = data.items || [];
        state.defaultProfileId = data.default_profile_id != null ? Number(data.default_profile_id) : null;
        // A stale/foreign id from a previous account or a removed profile — fall back to default
        // rather than silently tagging every request with an id the server will reject anyway.
        if (state.activeProfileId != null && !state.profiles.some(function (p) { return p.client_id === state.activeProfileId; })) {
          state.activeProfileId = null;
          writeStoredProfileId(null);
        }
        state.loaded = true;
        return data;
      })
      .catch(function () {
        state.loaded = true;
        return { items: [], default_profile_id: null };
      });
  }

  function activeProfile() {
    var id = state.activeProfileId != null ? state.activeProfileId : state.defaultProfileId;
    var found = null;
    for (var i = 0; i < state.profiles.length; i++) {
      if (state.profiles[i].client_id === id) {
        found = state.profiles[i];
        break;
      }
    }
    return found || state.profiles[0] || null;
  }

  function roleLabel(role) {
    if (role === 'guardian') return 'Ребёнок';
    if (role === 'family_access') return 'Общий доступ';
    return 'Вы';
  }

  function displayName(p) {
    var fn = (p.first_name || '').trim();
    var ln = (p.last_name || '').trim();
    return (fn + ' ' + ln).trim() || 'Профиль';
  }

  function initial(p) {
    var fn = (p.first_name || '').trim();
    return fn ? fn.charAt(0).toUpperCase() : '•';
  }

  /* ── styles (scoped, injected once) ──────────────────────────────── */
  var STYLE_ID = 'cpsStyles';
  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent =
      '.cps-chip{display:inline-flex;align-items:center;gap:8px;padding:6px 12px 6px 6px;' +
      'border-radius:999px;border:none;background:var(--tg-theme-secondary-bg-color,#2c2c2e);' +
      'color:var(--tg-theme-text-color,#fff);font-family:inherit;font-size:14px;font-weight:600;' +
      'cursor:pointer;}' +
      '.cps-chip__avatar{width:26px;height:26px;border-radius:50%;display:flex;align-items:center;' +
      'justify-content:center;background:var(--tg-theme-button-color,#45B9BB);' +
      'color:var(--app-cta-text,#fff);font-size:13px;font-weight:700;flex-shrink:0;}' +
      '.cps-chip__chevron{width:14px;height:14px;opacity:0.55;flex-shrink:0;}' +
      '.cps-sheet-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.45);display:flex;' +
      'align-items:flex-end;justify-content:center;z-index:10100;}' +
      '.cps-sheet{width:100%;max-width:480px;background:var(--tg-theme-bg-color,#1c1c1e);' +
      'border-radius:20px 20px 0 0;padding:8px 16px max(16px,env(safe-area-inset-bottom));' +
      'max-height:80vh;overflow-y:auto;-webkit-overflow-scrolling:touch;}' +
      '.cps-sheet__handle{width:36px;height:4px;border-radius:2px;background:var(--tg-theme-hint-color,#999);' +
      'opacity:0.35;margin:8px auto 14px;}' +
      '.cps-sheet__title{font-size:17px;font-weight:700;color:var(--tg-theme-text-color,#fff);margin:0 0 12px;}' +
      '.cps-row{display:flex;align-items:center;gap:12px;padding:12px 8px;border-radius:14px;' +
      'cursor:pointer;background:none;border:none;width:100%;text-align:left;font-family:inherit;}' +
      '.cps-row:active{background:var(--tg-theme-secondary-bg-color,#2c2c2e);}' +
      '.cps-row__avatar{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;' +
      'justify-content:center;background:var(--tg-theme-secondary-bg-color,#2c2c2e);' +
      'color:var(--tg-theme-text-color,#fff);font-size:15px;font-weight:700;flex-shrink:0;}' +
      '.cps-row--active .cps-row__avatar{background:var(--tg-theme-button-color,#45B9BB);' +
      'color:var(--app-cta-text,#fff);}' +
      '.cps-row__body{flex:1;min-width:0;}' +
      '.cps-row__name{display:block;font-size:15px;font-weight:600;color:var(--tg-theme-text-color,#fff);' +
      'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}' +
      '.cps-row__role{display:block;font-size:12px;color:var(--tg-theme-hint-color,#999);margin-top:1px;}' +
      '.cps-row__check{width:20px;height:20px;flex-shrink:0;color:var(--tg-theme-button-color,#45B9BB);}' +
      '.cps-add-btn{display:flex;align-items:center;gap:12px;padding:12px 8px;border-radius:14px;' +
      'cursor:pointer;background:none;border:none;width:100%;text-align:left;font-family:inherit;' +
      'color:var(--tg-theme-button-color,#45B9BB);font-size:15px;font-weight:600;margin-top:4px;}' +
      '.cps-add-icon{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;' +
      'justify-content:center;border:2px dashed rgba(var(--accent-rgb,69,185,187),0.5);flex-shrink:0;}' +
      '.cps-form{margin-top:8px;padding-top:12px;border-top:1px solid rgba(127,127,127,0.18);}' +
      '.cps-form__label{display:block;font-size:11px;font-weight:700;letter-spacing:0.08em;' +
      'text-transform:uppercase;color:var(--tg-theme-hint-color,#999);margin:0 0 8px;}' +
      '.cps-form__input{display:block;width:100%;box-sizing:border-box;padding:13px 14px;' +
      'min-height:48px;border-radius:14px;border:none;background:var(--tg-theme-secondary-bg-color,#2c2c2e);' +
      'font-size:15px;font-weight:500;font-family:inherit;outline:none;margin-bottom:12px;' +
      'color:var(--tg-theme-text-color,#fff);}' +
      '.cps-form__error{font-size:13px;color:#e5484d;margin:0 0 10px;min-height:16px;}' +
      '.cps-form__actions{display:flex;gap:8px;}' +
      '.cps-form__actions button{flex:1;padding:12px;border-radius:12px;border:none;' +
      'font-weight:600;font-size:14px;cursor:pointer;font-family:inherit;}' +
      '.cps-form__cancel{background:var(--tg-theme-secondary-bg-color,#2c2c2e);' +
      'color:var(--tg-theme-text-color,#fff);}' +
      '.cps-form__submit{background:var(--tg-theme-button-color,#45B9BB);color:var(--app-cta-text,#fff);}' +
      '.cps-form__submit:disabled{opacity:0.55;}';
    document.head.appendChild(style);
  }

  var ICON_CHEVRON =
    '<svg class="cps-chip__chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>';
  var ICON_CHECK =
    '<svg class="cps-row__check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>';
  var ICON_PLUS =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><path d="M12 5v14M5 12h14"/></svg>';

  function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* ── chip ─────────────────────────────────────────────────────────── */
  function renderChip(mount) {
    var p = activeProfile();
    if (!p) {
      mount.innerHTML = '';
      return;
    }
    ensureStyles();
    mount.innerHTML =
      '<button type="button" class="cps-chip" id="cpsChipBtn" aria-haspopup="dialog">' +
      '<span class="cps-chip__avatar">' + esc(initial(p)) + '</span>' +
      '<span>' + esc(displayName(p)) + '</span>' +
      ICON_CHEVRON +
      '</button>';
    var btn = document.getElementById('cpsChipBtn');
    if (btn) btn.onclick = openSheet;
  }

  /* ── bottom sheet ─────────────────────────────────────────────────── */
  var formOpen = false;

  function closeSheet() {
    var overlay = document.getElementById('cpsSheetOverlay');
    if (overlay) overlay.remove();
    formOpen = false;
    document.removeEventListener('keydown', onSheetKeyDown, true);
  }

  function onSheetKeyDown(e) {
    if (e.key === 'Escape') closeSheet();
  }

  function selectProfile(clientId) {
    if (clientId === (state.activeProfileId != null ? state.activeProfileId : state.defaultProfileId)) {
      closeSheet();
      return;
    }
    state.activeProfileId = clientId === state.defaultProfileId ? null : clientId;
    writeStoredProfileId(state.activeProfileId);
    // Every on-screen feature (hub, bookings, passes, catalog…) resolves data through this
    // profile server-side — a full reload is the simplest way to guarantee nothing on the
    // current page is left showing the previous profile's stale state.
    window.location.reload();
  }

  function submitAddChild(firstNameInput, lastNameInput, errorEl, submitBtn) {
    var firstName = (firstNameInput.value || '').trim();
    if (!firstName) {
      errorEl.textContent = 'Укажите имя.';
      return;
    }
    errorEl.textContent = '';
    submitBtn.disabled = true;
    nativeFetch(apiUrl('/client/profiles'), {
      method: 'POST',
      headers: jsonHeaders(),
      body: JSON.stringify({
        first_name: firstName,
        last_name: (lastNameInput.value || '').trim() || null,
      }),
    })
      .then(function (r) {
        return r.json().then(function (body) {
          return { ok: r.ok, status: r.status, body: body };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          var detail = res.body && res.body.detail;
          errorEl.textContent =
            res.status === 409
              ? 'Достигнут лимит добавленных профилей.'
              : (typeof detail === 'string' && detail) || 'Не удалось добавить профиль.';
          submitBtn.disabled = false;
          return;
        }
        var newId = res.body.client_id;
        // A parent adding a child almost always means "book/act for them right now".
        return nativeFetch(apiUrl('/client/profiles/' + newId + '/default'), {
          method: 'PATCH',
          headers: jsonHeaders(),
        }).then(function () {
          selectProfile(newId);
        });
      })
      .catch(function () {
        errorEl.textContent = 'Ошибка сети. Попробуйте ещё раз.';
        submitBtn.disabled = false;
      });
  }

  function renderAddChildForm(container) {
    formOpen = true;
    container.innerHTML =
      '<div class="cps-form" id="cpsForm">' +
      '<label class="cps-form__label" for="cpsChildFirstName">Имя ребёнка</label>' +
      '<input type="text" id="cpsChildFirstName" class="cps-form__input" placeholder="Имя" maxlength="64" autocomplete="off" />' +
      '<label class="cps-form__label" for="cpsChildLastName">Фамилия <span style="text-transform:none;opacity:.75;">(необязательно)</span></label>' +
      '<input type="text" id="cpsChildLastName" class="cps-form__input" placeholder="Фамилия" maxlength="64" autocomplete="off" />' +
      '<p class="cps-form__error" id="cpsFormError"></p>' +
      '<div class="cps-form__actions">' +
      '<button type="button" class="cps-form__cancel" id="cpsFormCancel">Отмена</button>' +
      '<button type="button" class="cps-form__submit" id="cpsFormSubmit">Добавить</button>' +
      '</div></div>';
    var firstEl = document.getElementById('cpsChildFirstName');
    var lastEl = document.getElementById('cpsChildLastName');
    var errEl = document.getElementById('cpsFormError');
    var submitBtn = document.getElementById('cpsFormSubmit');
    document.getElementById('cpsFormCancel').onclick = function () {
      renderSheetBody();
    };
    submitBtn.onclick = function () {
      submitAddChild(firstEl, lastEl, errEl, submitBtn);
    };
    if (firstEl) firstEl.focus();
  }

  function renderSheetBody() {
    formOpen = false;
    var body = document.getElementById('cpsSheetBody');
    if (!body) return;
    var activeId = state.activeProfileId != null ? state.activeProfileId : state.defaultProfileId;
    var rows = state.profiles
      .map(function (p) {
        var isActive = p.client_id === activeId;
        return (
          '<button type="button" class="cps-row' + (isActive ? ' cps-row--active' : '') + '" data-cps-profile="' + p.client_id + '">' +
          '<span class="cps-row__avatar">' + esc(initial(p)) + '</span>' +
          '<span class="cps-row__body"><span class="cps-row__name">' + esc(displayName(p)) + '</span>' +
          '<span class="cps-row__role">' + esc(roleLabel(p.role)) + '</span></span>' +
          (isActive ? ICON_CHECK : '') +
          '</button>'
        );
      })
      .join('');
    body.innerHTML =
      rows +
      '<button type="button" class="cps-add-btn" id="cpsAddChildBtn">' +
      '<span class="cps-add-icon">' + ICON_PLUS + '</span>Добавить ребёнка</button>';
    var rowEls = body.querySelectorAll('[data-cps-profile]');
    for (var i = 0; i < rowEls.length; i++) {
      rowEls[i].onclick = (function (id) {
        return function () {
          selectProfile(id);
        };
      })(Number(rowEls[i].getAttribute('data-cps-profile')));
    }
    var addBtn = document.getElementById('cpsAddChildBtn');
    if (addBtn) addBtn.onclick = function () { renderAddChildForm(body); };
  }

  function openSheet() {
    ensureStyles();
    closeSheet();
    var overlay = document.createElement('div');
    overlay.id = 'cpsSheetOverlay';
    overlay.className = 'cps-sheet-overlay';
    overlay.setAttribute('role', 'presentation');
    overlay.innerHTML =
      '<div class="cps-sheet" role="dialog" aria-modal="true" aria-label="Профили">' +
      '<div class="cps-sheet__handle"></div>' +
      '<h3 class="cps-sheet__title">Профили</h3>' +
      '<div id="cpsSheetBody"></div>' +
      '</div>';
    overlay.onclick = function (e) {
      if (e.target === overlay) closeSheet();
    };
    document.body.appendChild(overlay);
    document.addEventListener('keydown', onSheetKeyDown, true);
    renderSheetBody();
  }

  /* ── public API + auto-init ──────────────────────────────────────── */
  window.ClientProfileSwitcher = {
    getActiveProfileId: function () {
      return state.activeProfileId != null ? state.activeProfileId : state.defaultProfileId;
    },
    init: function () {
      return loadProfiles().then(function () {
        var mount = document.getElementById('clientProfileSwitcherMount');
        // Shown even with a single (self) profile — the sheet it opens is the only entry
        // point to "Добавить ребёнка", so a first-time parent must be able to find it too.
        // Only a brand-new, unregistered account (no clients row yet) has zero profiles.
        if (mount && state.profiles.length >= 1) renderChip(mount);
        return state;
      });
    },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      window.ClientProfileSwitcher.init();
    });
  } else {
    window.ClientProfileSwitcher.init();
  }
})();
