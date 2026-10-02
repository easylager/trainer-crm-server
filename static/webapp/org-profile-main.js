/**
 * Org Профиль школы (TASK-141 S3 + TASK-143 площадка/фото): чек-лист обязательное +
 * форма на одном экране + площадка + загрузка лого/обложки/галереи.
 * Scope note: readiness (чек-лист "обязательное") по-прежнему покрывает только
 * name/about/contact — media остаётся необязательной, как решено в org_profile_readiness.
 */
(function () {
  'use strict';

  var REQUIRED_LABELS = {
    display_name: 'Название школы',
    about: 'О школе',
    contact: 'Телефон или Telegram',
  };
  var REQUIRED_ORDER = ['display_name', 'about', 'contact'];

  var state = {
    primaryArenaId: null,
    primaryArenaName: null,
    primaryArenaCityName: null,
    cities: [],
    arenas: [],
    arenasCityId: null,
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

  function renderArenaCurrent() {
    el('orgProfileArenaCurrentText').textContent = state.primaryArenaId
      ? state.primaryArenaName + (state.primaryArenaCityName ? ', ' + state.primaryArenaCityName : '')
      : 'Не выбрана';
  }

  function renderCitySelect() {
    var sel = el('orgProfileArenaCity');
    sel.innerHTML = state.cities
      .map(function (c) {
        return '<option value="' + c.id + '">' + c.name + '</option>';
      })
      .join('');
  }

  function renderArenaList() {
    var filter = (el('orgProfileArenaFilter').value || '').trim().toLowerCase();
    var items = state.arenas.filter(function (a) {
      return !filter || (a.name || '').toLowerCase().indexOf(filter) !== -1;
    });
    var listEl = el('orgProfileArenaList');
    var emptyEl = el('orgProfileArenaEmpty');
    if (!items.length) {
      listEl.innerHTML = '';
      show(emptyEl);
      return;
    }
    hide(emptyEl);
    listEl.innerHTML = items
      .map(function (a) {
        var selected = a.id === state.primaryArenaId;
        return (
          '<button type="button" class="org-arena-row' +
          (selected ? ' org-arena-row--selected' : '') +
          '" data-arena-id="' +
          a.id +
          '" data-arena-name="' +
          (a.name || '').replace(/"/g, '&quot;') +
          '"><span class="org-arena-row__name">' +
          (a.name || '') +
          '</span>' +
          (a.address ? '<span class="org-arena-row__address">' + a.address + '</span>' : '') +
          '</button>'
        );
      })
      .join('');
    listEl.querySelectorAll('.org-arena-row').forEach(function (row) {
      row.addEventListener('click', function () {
        state.primaryArenaId = parseInt(row.getAttribute('data-arena-id'), 10);
        state.primaryArenaName = row.getAttribute('data-arena-name');
        var citySel = el('orgProfileArenaCity');
        var cityOpt = citySel.options[citySel.selectedIndex];
        state.primaryArenaCityName = cityOpt ? cityOpt.textContent : null;
        renderArenaCurrent();
        closeArenaPicker();
      });
    });
  }

  function loadArenasForCity(cityId) {
    if (state.arenasCityId === cityId) {
      renderArenaList();
      return;
    }
    state.arenasCityId = cityId;
    fetch('/api/webapp/org/profile/arenas?city_id=' + encodeURIComponent(cityId), { headers: authHeaders() })
      .then(function (resp) {
        if (!resp.ok) throw new Error();
        return resp.json();
      })
      .then(function (data) {
        state.arenas = data.items || [];
        renderArenaList();
      })
      .catch(function () {
        state.arenas = [];
        renderArenaList();
      });
  }

  function openArenaPicker() {
    show(el('orgProfileArenaPicker'));
    var citySel = el('orgProfileArenaCity');
    var cityId = state.primaryArenaId != null && citySelIdForCityName(state.primaryArenaCityName);
    if (cityId) citySel.value = String(cityId);
    if (citySel.value) loadArenasForCity(parseInt(citySel.value, 10));
  }

  function citySelIdForCityName(name) {
    if (!name) return null;
    var found = state.cities.filter(function (c) {
      return c.name === name;
    })[0];
    return found ? found.id : null;
  }

  function closeArenaPicker() {
    hide(el('orgProfileArenaPicker'));
  }

  function render(data) {
    hide(el('orgProfileLoading'));
    hide(el('orgProfileError'));
    show(el('orgProfileRoot'));
    renderStatus(data.readiness.ready);
    renderChecklist(data.readiness.missing);
    fillForm(data);
    state.primaryArenaId = data.primary_arena_id != null ? Number(data.primary_arena_id) : null;
    state.primaryArenaName = data.primary_arena_name || null;
    state.primaryArenaCityName = data.primary_arena_city_name || null;
    state.cities = (data.refs && data.refs.cities && data.refs.cities.items) || [];
    renderCitySelect();
    renderArenaCurrent();
    renderPhotos(data);
  }

  function renderPhotos(data) {
    var logoPreview = el('orgProfileLogoPreview');
    if (data.logo_url) {
      logoPreview.style.backgroundImage = 'url(' + data.logo_url + ')';
      logoPreview.innerHTML = '';
    } else {
      logoPreview.style.backgroundImage = '';
      logoPreview.innerHTML = '<span class="org-photo-preview__empty">Лого</span>';
    }
    var coverPreview = el('orgProfileCoverPreview');
    if (data.cover_url) {
      coverPreview.style.backgroundImage = 'url(' + data.cover_url + ')';
      coverPreview.innerHTML = '';
    } else {
      coverPreview.style.backgroundImage = '';
      coverPreview.innerHTML = '<span class="org-photo-preview__empty">Обложка</span>';
    }
    var gallery = data.gallery || [];
    el('orgProfileGallery').innerHTML = gallery
      .map(function (item) {
        return '<div class="org-photo-gallery__item" style="background-image:url(' + item.url + ')"></div>';
      })
      .join('');
  }

  function uploadPhoto(kind, file) {
    var errorEl = el('orgProfilePhotoError');
    errorEl.hidden = true;
    if (!file) return;
    var fd = new FormData();
    fd.append('file', file, file.name || (kind + '.jpg'));
    fetch('/api/webapp/org/profile/assets?kind=' + encodeURIComponent(kind), {
      method: 'POST',
      headers: authHeaders(),
      body: fd,
    })
      .then(function (resp) {
        if (resp.ok) return resp.json();
        return resp
          .json()
          .catch(function () {
            return {};
          })
          .then(function (errBody) {
            var detail = errBody && errBody.detail;
            var msg = 'Не удалось загрузить файл';
            if (detail === 'File too large') msg = 'Файл слишком большой';
            else if (detail === 'Not a valid image') msg = 'Нужно изображение (JPEG/PNG/WebP)';
            else if (detail === 'Gallery full') msg = 'Достигнут лимит фото в галерее';
            else if (detail === 'Owner only') msg = 'Загружать фото может только владелец школы';
            throw new Error(msg);
          });
      })
      .then(function (data) {
        if (data && data.profile) renderPhotos(data.profile);
      })
      .catch(function (err) {
        errorEl.textContent = err.message || 'Не удалось загрузить файл';
        errorEl.hidden = false;
      });
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
      primary_arena_id: state.primaryArenaId,
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
        state.primaryArenaId = data.primary_arena_id != null ? Number(data.primary_arena_id) : null;
        state.primaryArenaName = data.primary_arena_name || null;
        state.primaryArenaCityName = data.primary_arena_city_name || null;
        renderArenaCurrent();
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

  var pickBtn = el('orgProfileArenaPickBtn');
  if (pickBtn) pickBtn.addEventListener('click', openArenaPicker);

  var pickerCloseBtn = el('orgProfileArenaPickerClose');
  if (pickerCloseBtn) pickerCloseBtn.addEventListener('click', closeArenaPicker);

  var clearBtn = el('orgProfileArenaClearBtn');
  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      state.primaryArenaId = null;
      state.primaryArenaName = null;
      state.primaryArenaCityName = null;
      renderArenaCurrent();
      closeArenaPicker();
    });
  }

  var citySelect = el('orgProfileArenaCity');
  if (citySelect) {
    citySelect.addEventListener('change', function () {
      loadArenasForCity(parseInt(citySelect.value, 10));
    });
  }

  var arenaFilter = el('orgProfileArenaFilter');
  if (arenaFilter) arenaFilter.addEventListener('input', renderArenaList);

  ['logo', 'cover', 'gallery'].forEach(function (kind) {
    var input = el('orgProfile' + kind.charAt(0).toUpperCase() + kind.slice(1) + 'Input');
    if (!input) return;
    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      uploadPhoto(kind, file);
      input.value = '';
    });
  });

  if (window.MiniAppRuntime && typeof window.MiniAppRuntime.ready === 'function') {
    window.MiniAppRuntime.ready();
  }
  load();
})();
