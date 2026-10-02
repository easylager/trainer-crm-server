/**
 * Org Каталог (TASK-141 S5): статус публикации + preview + чек-лист + история.
 * Self-serve — нет модератора (owner-решение): школа публикуется сама, как только
 * профиль-чек-лист закрыт.
 */
(function () {
  'use strict';

  var REQUIRED_LABELS = {
    display_name: 'Название школы',
    about: 'О школе',
    contact: 'Телефон или Telegram',
  };
  var REQUIRED_ORDER = ['display_name', 'about', 'contact'];

  function el(id) {
    return document.getElementById(id);
  }

  function show(node) {
    if (node) node.hidden = false;
  }

  function hide(node) {
    if (node) node.hidden = true;
  }

  function escapeHtml(text) {
    var d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  function authHeaders() {
    return window.MiniAppRuntime ? window.MiniAppRuntime.authHeaders() : {};
  }

  function renderChecklist(missing) {
    var checklistEl = el('orgCatalogChecklist');
    if (!missing || missing.length === 0) {
      hide(checklistEl);
      checklistEl.innerHTML = '';
      return;
    }
    show(checklistEl);
    var missingSet = {};
    missing.forEach(function (key) {
      missingSet[key] = true;
    });
    var html = '';
    REQUIRED_ORDER.forEach(function (key) {
      var done = !missingSet[key];
      html +=
        '<div class="org-ck' +
        (done ? ' org-ck--done' : '') +
        '"><span class="org-ck__box">' +
        (done ? '✓' : '') +
        '</span><span class="org-ck__t">' +
        REQUIRED_LABELS[key] +
        '</span></div>';
    });
    checklistEl.innerHTML = html;
  }

  function renderPreview(preview) {
    el('orgCatalogPreviewName').textContent = preview.display_name || '—';
    el('orgCatalogPreviewAbout').textContent = preview.about || 'Описание пока не заполнено';
    var contact = preview.phone || preview.telegram || '';
    el('orgCatalogPreviewContact').textContent = contact || 'Контакт не указан';
  }

  function renderHistory(events) {
    var historyEl = el('orgCatalogHistory');
    if (!events || events.length === 0) {
      historyEl.innerHTML = '<p class="org-catalog-history__empty">Пока пусто</p>';
      return;
    }
    historyEl.innerHTML = events
      .map(function (e) {
        var date = e.created_at ? new Date(e.created_at).toLocaleDateString('ru-RU') : '';
        return (
          '<div class="org-catalog-history__row">' +
          '<span class="org-catalog-history__t">' + escapeHtml(e.headline) + '</span>' +
          '<span class="org-catalog-history__d">' + escapeHtml(date) + '</span>' +
          '</div>'
        );
      })
      .join('');
  }

  function render(data) {
    hide(el('orgCatalogLoading'));
    hide(el('orgCatalogError'));
    show(el('orgCatalogRoot'));

    var dot = el('orgCatalogStatus').querySelector('.org-home-status__dot');
    dot.classList.remove('org-home-status__dot--ok', 'org-home-status__dot--wait');
    dot.classList.add(data.state === 'published' ? 'org-home-status__dot--ok' : 'org-home-status__dot--wait');
    el('orgCatalogStatusText').textContent = data.headline;
    el('orgCatalogBody').textContent = data.body;

    renderPreview(data.preview);
    renderChecklist(data.readiness.missing);
    renderHistory(data.events);

    var publishBtn = el('orgCatalogPublish');
    var hideBtn = el('orgCatalogHide');
    var linkEl = el('orgCatalogPublicLink');
    var isOwner = data.role === 'owner';

    publishBtn.hidden = !(isOwner && data.can_publish);
    publishBtn.disabled = !data.readiness.ready;
    hideBtn.hidden = !(isOwner && data.can_hide);

    if (data.public_url) {
      linkEl.href = data.public_url;
      show(linkEl);
    } else {
      hide(linkEl);
    }
  }

  function renderError(text) {
    hide(el('orgCatalogLoading'));
    hide(el('orgCatalogRoot'));
    show(el('orgCatalogError'));
    el('orgCatalogErrorText').textContent = text;
  }

  function load() {
    show(el('orgCatalogLoading'));
    hide(el('orgCatalogRoot'));
    hide(el('orgCatalogError'));

    fetch('/api/webapp/org/catalog', { headers: authHeaders() })
      .then(function (resp) {
        if (resp.status === 404) throw new Error('Вы пока не оператор ни одной школы.');
        if (resp.status === 401) throw new Error('Не удалось подтвердить вход. Откройте кабинет из бота.');
        if (!resp.ok) throw new Error('Не удалось загрузить раздел');
        return resp.json();
      })
      .then(render)
      .catch(function (err) {
        renderError(err.message || 'Не удалось загрузить раздел');
      });
  }

  function runAction(path, btn) {
    var errorEl = el('orgCatalogActionError');
    hide(errorEl);
    btn.disabled = true;

    fetch(path, { method: 'POST', headers: authHeaders() })
      .then(function (resp) {
        if (resp.status === 422) throw new Error('Заполните обязательные поля профиля перед публикацией.');
        if (resp.status === 403) throw new Error('Действие доступно только владельцу школы.');
        if (!resp.ok) throw new Error('Не удалось выполнить действие');
        return resp.json();
      })
      .then(render)
      .catch(function (err) {
        errorEl.textContent = err.message || 'Не удалось выполнить действие';
        show(errorEl);
      })
      .finally(function () {
        btn.disabled = false;
      });
  }

  var publishBtn = el('orgCatalogPublish');
  if (publishBtn) {
    publishBtn.addEventListener('click', function () {
      runAction('/api/webapp/org/catalog/publish', publishBtn);
    });
  }

  var hideBtn = el('orgCatalogHide');
  if (hideBtn) {
    hideBtn.addEventListener('click', function () {
      runAction('/api/webapp/org/catalog/hide', hideBtn);
    });
  }

  var retryBtn = el('orgCatalogRetry');
  if (retryBtn) retryBtn.addEventListener('click', load);

  if (window.MiniAppRuntime && typeof window.MiniAppRuntime.ready === 'function') {
    window.MiniAppRuntime.ready();
  }
  load();
})();
