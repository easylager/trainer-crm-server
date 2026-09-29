/**
 * Org Главная (TASK-141 S1): bootstrap fetch, render school name/status/role.
 * S1 shows only what /bootstrap actually returns — no fabricated "today" snapshot until
 * the slices that back it (Расписание, Клиенты, Каталог) exist.
 */
(function () {
  'use strict';

  var STATUS_LABELS = {
    draft: 'Черновик — заполните профиль, чтобы продолжить',
    active: 'Школа активна',
    suspended: 'Школа приостановлена',
  };

  var ROLE_LABELS = {
    owner: 'Владелец',
    admin: 'Администратор',
  };

  function el(id) {
    return document.getElementById(id);
  }

  function show(node) {
    if (node) node.hidden = false;
  }

  function hide(node) {
    if (node) node.hidden = true;
  }

  function render(data) {
    hide(el('orgHomeLoading'));
    hide(el('orgHomeError'));
    show(el('orgHomeRoot'));

    el('orgHomeName').textContent = data.display_name || data.slug || 'Школа';
    var roleLabel = ROLE_LABELS[data.role] || data.role;
    el('orgHomeSub').textContent = roleLabel || '';

    var statusEl = el('orgHomeStatus');
    var dot = statusEl.querySelector('.org-home-status__dot');
    dot.classList.remove('org-home-status__dot--ok', 'org-home-status__dot--wait');
    dot.classList.add(data.status === 'active' ? 'org-home-status__dot--ok' : 'org-home-status__dot--wait');
    el('orgHomeStatusText').textContent = STATUS_LABELS[data.status] || data.status;
  }

  function renderError(text) {
    hide(el('orgHomeLoading'));
    hide(el('orgHomeRoot'));
    show(el('orgHomeError'));
    el('orgHomeErrorText').textContent = text;
  }

  function load() {
    show(el('orgHomeLoading'));
    hide(el('orgHomeRoot'));
    hide(el('orgHomeError'));

    var headers = window.MiniAppRuntime ? window.MiniAppRuntime.authHeaders() : {};
    fetch('/api/webapp/org/bootstrap', { headers: headers })
      .then(function (resp) {
        if (resp.status === 404) {
          throw new Error('Вы пока не оператор ни одной школы.');
        }
        if (resp.status === 401) {
          throw new Error('Не удалось подтвердить вход. Откройте кабинет из бота.');
        }
        if (!resp.ok) {
          throw new Error('Не удалось загрузить раздел');
        }
        return resp.json();
      })
      .then(render)
      .catch(function (err) {
        renderError(err.message || 'Не удалось загрузить раздел');
      });
  }

  var retryBtn = el('orgHomeRetry');
  if (retryBtn) retryBtn.addEventListener('click', load);

  var profileLink = el('orgHomeProfileLink');
  if (profileLink) {
    profileLink.addEventListener('click', function () {
      window.location.href = 'org-profile';
    });
  }

  if (window.MiniAppRuntime && typeof window.MiniAppRuntime.ready === 'function') {
    window.MiniAppRuntime.ready();
  }
  load();
})();
