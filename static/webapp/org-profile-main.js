/**
 * Org Профиль школы (TASK-141 S3): чек-лист обязательное + форма на одном экране.
 * Scope note: readiness here covers name/about/contact only — logo/cover upload isn't
 * wired for the org webapp yet, so "media" isn't a checklist item (see org_profile_readiness).
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

  function renderChecklist(missing) {
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
    el('orgProfileChecklist').innerHTML = html;
  }

  function renderStatus(ready) {
    var dot = el('orgProfileStatus').querySelector('.org-home-status__dot');
    dot.classList.remove('org-home-status__dot--ok', 'org-home-status__dot--wait');
    dot.classList.add(ready ? 'org-home-status__dot--ok' : 'org-home-status__dot--wait');
    el('orgProfileStatusText').textContent = ready ? 'Профиль заполнен' : 'Заполните обязательные поля';
  }

  function fillForm(data) {
    el('orgProfileName').value = data.display_name || '';
    el('orgProfileAbout').value = data.about || '';
    var contacts = data.contacts || {};
    el('orgProfilePhone').value = contacts.phone || '';
    el('orgProfileTelegram').value = contacts.telegram || '';
  }

  function render(data) {
    hide(el('orgProfileLoading'));
    hide(el('orgProfileError'));
    show(el('orgProfileRoot'));
    renderStatus(data.readiness.ready);
    renderChecklist(data.readiness.missing);
    fillForm(data);
  }

  function renderError(text) {
    hide(el('orgProfileLoading'));
    hide(el('orgProfileRoot'));
    show(el('orgProfileError'));
    el('orgProfileErrorText').textContent = text;
  }

  function authHeaders() {
    return window.MiniAppRuntime ? window.MiniAppRuntime.authHeaders() : {};
  }

  function load() {
    show(el('orgProfileLoading'));
    hide(el('orgProfileRoot'));
    hide(el('orgProfileError'));

    fetch('/api/webapp/org/profile', { headers: authHeaders() })
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

  function save(e) {
    e.preventDefault();
    var errorEl = el('orgProfileFormError');
    errorEl.hidden = true;

    var body = {
      display_name: el('orgProfileName').value,
      about: el('orgProfileAbout').value,
      contacts: {
        phone: el('orgProfilePhone').value,
        telegram: el('orgProfileTelegram').value,
      },
    };

    var headers = authHeaders();
    headers['Content-Type'] = 'application/json';
    var saveBtn = el('orgProfileSave');
    saveBtn.disabled = true;

    fetch('/api/webapp/org/profile', {
      method: 'PATCH',
      headers: headers,
      body: JSON.stringify(body),
    })
      .then(function (resp) {
        if (!resp.ok) throw new Error('Не удалось сохранить — проверьте поля');
        return resp.json();
      })
      .then(function (data) {
        renderStatus(data.readiness.ready);
        renderChecklist(data.readiness.missing);
      })
      .catch(function (err) {
        errorEl.textContent = err.message || 'Не удалось сохранить';
        errorEl.hidden = false;
      })
      .finally(function () {
        saveBtn.disabled = false;
      });
  }

  var backBtn = el('orgProfileBack');
  if (backBtn) {
    backBtn.addEventListener('click', function () {
      window.location.href = 'org-home';
    });
  }

  var retryBtn = el('orgProfileRetry');
  if (retryBtn) retryBtn.addEventListener('click', load);

  var form = el('orgProfileForm');
  if (form) form.addEventListener('submit', save);

  if (window.MiniAppRuntime && typeof window.MiniAppRuntime.ready === 'function') {
    window.MiniAppRuntime.ready();
  }
  load();
})();
