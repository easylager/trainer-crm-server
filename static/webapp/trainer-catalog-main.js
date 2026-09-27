/**
 * Раздел «Каталог» тренерского Mini App (TASK-140).
 *
 * До этого публикация жила тумблером в «Настройках» экрана «Профиль», а состояние собиралось из
 * двух несвязанных полей. Из каталога можно было выпасть молча: тренер стирал телефон, получал
 * `{"ok": true}` и пропадал из выдачи, а узнать мог только вернувшись на экран анкеты.
 *
 * Экран отвечает ровно на четыре вопроса: в каталоге я или нет, почему, что видит клиент и что
 * с карточкой происходило. Весь контент — из `GET /api/webapp/trainer/catalog`; тексты состояний
 * приходят с сервера, чтобы пуш, дайджест и экран не описывали одно состояние по-разному.
 *
 * Карточку заполняет существующая карусель профиля: «Разместить» уходит на
 * `trainer-profile?task=catalog&return=trainer-catalog`, у неё уже есть возврат
 * (`focusedTaskReturnUrl`). Ничего не переносим — визард остаётся там, где живут блоки формы.
 */
(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    try {
      var darkUi = tg.colorScheme === 'dark';
      var bgHex = darkUi ? '#0B0C0E' : '#F1F3F2';
      if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
      if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
    } catch (e) { /* старые клиенты */ }
  }

  var initData = tg ? tg.initData : '';
  var state = { payload: null, busy: false };

  function apiUrl(path) {
    var url = '/api/webapp' + path;
    if (initData) {
      url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
    }
    return url;
  }

  function headers() {
    var h = { 'Content-Type': 'application/json' };
    if (initData) h['X-Telegram-Init-Data'] = initData;
    return h;
  }

  function el(id) {
    return document.getElementById(id);
  }

  function show(node, visible) {
    if (!node) return;
    if (visible) node.removeAttribute('hidden');
    else node.setAttribute('hidden', 'hidden');
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function formatDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
  }

  function formatDateTime(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return (
      d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) +
      ' ' +
      d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
    );
  }

  function money(cents) {
    if (cents == null) return null;
    var v = cents / 100;
    return (v % 1 === 0 ? v.toFixed(0) : v.toFixed(2)) + ' BYN';
  }

  function photoUrl(fileKey) {
    if (!fileKey) return null;
    return '/api/public/photos/' + encodeURIComponent(fileKey);
  }

  /* ─── Рендер ────────────────────────────────────────────────────────────── */

  function renderCard(node, person) {
    if (!node) return;
    var bits = [];
    if (person.city_name) bits.push(esc(person.city_name));
    if (person.public_arena_count) {
      bits.push(esc(String(person.public_arena_count)) + ' ' + arenaWord(person.public_arena_count));
    }
    var price = money(person.price_from_cents);
    var rating =
      person.rating_count > 0
        ? '★ ' + Number(person.rating_avg).toFixed(1) + ' (' + person.rating_count + ')'
        : 'оценок пока нет';
    var img = photoUrl(person.photo_file_key);
    var name = [person.first_name, person.last_name].filter(Boolean).join(' ') || 'Без имени';
    node.innerHTML =
      '<div class="tc-card__photo">' +
      (img
        ? '<img src="' + esc(img) + '" alt="" loading="lazy" />'
        : '<span class="tc-card__photo-empty" aria-hidden="true">фото</span>') +
      '</div>' +
      '<div class="tc-card__body">' +
      '<p class="tc-card__name">' + esc(name) + '</p>' +
      (bits.length ? '<p class="tc-card__meta">' + bits.join(' · ') + '</p>' : '') +
      '<p class="tc-card__meta tc-card__meta--muted">' +
      (price ? 'от ' + esc(price) + ' · ' : '') +
      esc(rating) +
      '</p>' +
      '</div>';
  }

  function arenaWord(n) {
    var mod10 = n % 10;
    var mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return 'площадка';
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'площадки';
    return 'площадок';
  }

  function renderStatus(p) {
    el('tcHeadline').textContent = p.headline || '';
    el('tcStatusBody').textContent = p.body || '';
    var dot = el('tcStatusDot');
    dot.className = 'tc-status__dot tc-status__dot--' + (p.state || 'draft');

    var meta = el('tcStatusMeta');
    var since = formatDate(p.state_changed_at);
    if (since && p.state === 'published') {
      meta.textContent = 'Опубликовано ' + since;
      show(meta, true);
    } else if (since && (p.state === 'hidden' || p.state === 'paused' || p.state === 'needs_revision')) {
      meta.textContent = since;
      show(meta, true);
    } else {
      show(meta, false);
    }

    // Причина показывается дословно: в paused это единственное, что объясняет исчезновение.
    var detail = el('tcStatusDetail');
    if (p.state_detail && p.state !== 'published') {
      detail.textContent = p.state_detail;
      show(detail, true);
    } else {
      show(detail, false);
    }

    show(el('tcPitch'), p.state === 'draft');

    var studio = el('tcStudioNote');
    if (p.managed_by_studio) {
      studio.textContent =
        'Публикацией карточки управляет ' + (p.studio_name || 'студия') + '. Состояние и история — здесь.';
      show(studio, true);
    } else {
      show(studio, false);
    }
    el('tcSubscriptionNote').textContent = p.subscription_note || '';
  }

  function renderPreview(p) {
    renderCard(el('tcPreviewCard'), p.preview || {});
    var revision = p.revision;
    var label = el('tcPreviewLabel');
    if (revision) {
      // То, чего раньше не было видно вообще: клиент до сих пор смотрит на старые значения.
      label.textContent = 'Сейчас клиенты видят';
      renderCard(el('tcPreviewCard'), mergeForCard(p.preview, revision.current));
      renderCard(el('tcRevisionCard'), mergeForCard(p.preview, revision.next));
      show(el('tcRevisionLabel'), true);
      show(el('tcRevisionCard'), true);
      show(el('tcCancelRevision'), !!p.can_act);
    } else {
      label.textContent = p.state === 'published' ? 'Так вас видят в списке' : 'Так вас увидят в списке';
      show(el('tcRevisionLabel'), false);
      show(el('tcRevisionCard'), false);
      show(el('tcCancelRevision'), false);
    }
  }

  function mergeForCard(preview, version) {
    var out = {};
    Object.keys(preview || {}).forEach(function (k) { out[k] = preview[k]; });
    if (version) {
      if (version.first_name !== undefined) out.first_name = version.first_name;
      if (version.last_name !== undefined) out.last_name = version.last_name;
      if (version.photo_file_key !== undefined) out.photo_file_key = version.photo_file_key;
    }
    return out;
  }

  function renderReadiness(p) {
    var r = p.readiness || {};
    var required = r.missing_labels_ru || [];
    var optional = r.optional_missing_labels_ru || [];
    var section = el('tcReadiness');
    if (!required.length && !optional.length) {
      show(section, false);
      return;
    }
    show(section, true);
    var label = el('tcReadinessLabel');
    var list = el('tcMissingList');
    list.innerHTML = '';
    if (required.length) {
      label.textContent = 'Для проверки осталось заполнить';
      required.forEach(function (text) {
        var li = document.createElement('li');
        li.className = 'tc-checklist__item tc-checklist__item--todo';
        li.textContent = text;
        list.appendChild(li);
      });
    } else {
      label.textContent = 'Готово к проверке';
    }
    // Необязательное отдельным блоком: иначе непонятно, что блокирует публикацию, а что нет.
    show(el('tcOptionalLabel'), optional.length > 0);
    var optList = el('tcOptionalList');
    optList.innerHTML = '';
    optional.forEach(function (text) {
      var li = document.createElement('li');
      li.className = 'tc-checklist__item tc-checklist__item--soft';
      li.textContent = text;
      optList.appendChild(li);
    });
    show(optList, optional.length > 0);
  }

  function renderWarnings(p) {
    var node = el('tcWarnings');
    var items = p.warnings || [];
    node.innerHTML = '';
    show(node, items.length > 0);
    items.forEach(function (w) {
      var row = document.createElement('div');
      row.className = 'tc-warning';
      row.innerHTML =
        '<span class="tc-warning__icon" aria-hidden="true">⚠</span>' +
        '<span class="tc-warning__text">' + esc(w.text) + '</span>';
      if (w.action === 'arenas' || w.action === 'profile') {
        var a = document.createElement('button');
        a.type = 'button';
        a.className = 'tc-link-btn tc-warning__action';
        a.textContent = w.action === 'arenas' ? 'Открыть площадки' : 'Дополнить';
        a.addEventListener('click', function () { openProfile(w.action === 'arenas' ? 'arenas' : ''); });
        row.appendChild(a);
      }
      node.appendChild(row);
    });
  }

  function renderMetrics(p) {
    var m = p.metrics;
    var section = el('tcMetrics');
    if (!m || p.state !== 'published') {
      show(section, false);
      return;
    }
    show(section, true);
    el('tcMetricsGrid').innerHTML = [
      ['Просмотры профиля', m.profile_views],
      ['Переходы в Telegram', m.contact_clicks],
      ['В избранном', m.catalog_favorites],
    ]
      .map(function (pair) {
        return (
          '<div class="tc-metric"><span class="tc-metric__val">' +
          esc(String(pair[1] == null ? 0 : pair[1])) +
          '</span><span class="tc-metric__lbl">' + esc(pair[0]) + '</span></div>'
        );
      })
      .join('');
  }

  function renderHistory(p) {
    var events = p.events || [];
    show(el('tcHistorySection'), events.length > 0);
    var list = el('tcHistoryList');
    list.innerHTML = '';
    events.forEach(function (e) {
      var li = document.createElement('li');
      li.className = 'tc-history__item';
      var when = formatDateTime(e.created_at);
      var who = e.actor_type === 'trainer' ? 'вами'
        : e.actor_type === 'moderator' ? 'модератором'
        : e.actor_type === 'studio' ? 'студией'
        : e.actor_type === 'system' ? 'автоматически'
        : '';
      li.innerHTML =
        '<span class="tc-history__when">' + esc(when) + '</span>' +
        '<span class="tc-history__what">' + esc(e.headline || e.to_state) +
        (who ? ' · ' + esc(who) : '') + '</span>' +
        (e.reason_detail ? '<span class="tc-history__why">' + esc(e.reason_detail) + '</span>' : '');
      list.appendChild(li);
    });
  }

  /* ─── Действия ──────────────────────────────────────────────────────────── */

  var ACTION_LABELS = {
    submit: 'Отправить на проверку',
    fill: 'Разместить карточку',
    hide: 'Снять с публикации',
    restore: 'Вернуть в каталог',
    withdraw: 'Отменить заявку',
  };

  function renderActions(p) {
    var node = el('tcActions');
    node.innerHTML = '';
    (p.actions || []).forEach(function (action) {
      var btn = document.createElement('button');
      btn.type = 'button';
      // Снятие — редкое и деструктивное: текстовой ссылкой, не кнопкой в вес «Изменить».
      var quiet = action === 'hide' || action === 'withdraw';
      btn.className = quiet ? 'tc-link-btn tc-link-btn--danger' : 'tc-btn tc-btn--primary';
      btn.textContent = ACTION_LABELS[action] || action;
      btn.addEventListener('click', function () { runAction(action); });
      node.appendChild(btn);
    });
    if (p.can_act && p.state === 'published') {
      var edit = document.createElement('button');
      edit.type = 'button';
      edit.className = 'tc-btn tc-btn--soft';
      edit.textContent = 'Изменить карточку';
      edit.addEventListener('click', function () { openProfile(''); });
      node.insertBefore(edit, node.firstChild);
      var note = document.createElement('p');
      note.className = 'tc-actions__note';
      note.textContent =
        'Имя, фото и описание проходят проверку. Цены, услуги и площадки — сразу.';
      node.appendChild(note);
    }
  }

  /** «Разместить» = карусель профиля с возвратом сюда; её рельс собирается из missing_fields. */
  function openProfile(anchor) {
    var base = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
    var url = base + 'trainer-profile?task=catalog&return=trainer-catalog';
    if (anchor) url += '&focus=' + encodeURIComponent(anchor);
    window.location.href = url;
  }

  function runAction(action) {
    if (state.busy) return;
    if (action === 'fill') {
      openProfile('');
      return;
    }
    if (action === 'hide') {
      confirmHide().then(function (ok) {
        if (ok) post('hide');
      });
      return;
    }
    if (action === 'submit') post('submit');
    else if (action === 'restore') post('restore');
    else if (action === 'withdraw') post('withdraw');
  }

  /** Диалог снятия: честно перечисляет, что изменится и что нет. */
  function confirmHide() {
    var text =
      'Изменится: вас не будет в списке и в фильтрах, новые заявки из каталога перестанут ' +
      'приходить.\n\nНе изменится: запись по вашей ссылке, уже назначенные занятия, клиенты и ' +
      'абонементы.\n\nВернуть можно в один тап, без повторной проверки.';
    if (typeof window.showAppConfirm === 'function') {
      return window.showAppConfirm(text, {
        title: 'Снять карточку с публикации?',
        okText: 'Снять',
        cancelText: 'Отмена',
      });
    }
    return Promise.resolve(window.confirm('Снять карточку с публикации?\n\n' + text));
  }

  function post(path) {
    state.busy = true;
    return fetch(apiUrl('/trainer/catalog/' + path), { method: 'POST', headers: headers(), body: '{}' })
      .then(function (r) {
        return r.json().then(function (data) { return { ok: r.ok, status: r.status, data: data }; });
      })
      .then(function (res) {
        state.busy = false;
        if (res.ok) {
          apply(res.data);
          return;
        }
        // 422 = карточка не готова. Не ошибка, а следующий шаг: ведём в карусель.
        if (res.status === 422) {
          apply(Object.assign({}, state.payload || {}, {}));
          openProfile('');
          return;
        }
        toast((res.data && res.data.detail) || 'Не удалось выполнить действие');
      })
      .catch(function () {
        state.busy = false;
        toast('Сеть недоступна — попробуйте ещё раз');
      });
  }

  function toast(message) {
    if (tg && tg.showAlert) {
      try { tg.showAlert(String(message)); return; } catch (e) { /* ignore */ }
    }
    window.alert(String(message));
  }

  /* ─── Загрузка ──────────────────────────────────────────────────────────── */

  function apply(payload) {
    state.payload = payload;
    show(el('tcLoading'), false);
    show(el('tcError'), false);
    show(el('tcRoot'), true);
    renderStatus(payload);
    renderPreview(payload);
    renderReadiness(payload);
    renderWarnings(payload);
    renderMetrics(payload);
    renderActions(payload);
    renderHistory(payload);
  }

  function load() {
    show(el('tcError'), false);
    show(el('tcLoading'), true);
    return fetch(apiUrl('/trainer/catalog'), { headers: headers(), cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error(String(r.status))); })
      .then(apply)
      .catch(function () {
        show(el('tcLoading'), false);
        show(el('tcRoot'), false);
        show(el('tcError'), true);
      });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var toggle = el('tcHistoryToggle');
    if (toggle) {
      toggle.addEventListener('click', function () {
        var list = el('tcHistoryList');
        var open = list.hasAttribute('hidden');
        show(list, open);
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    }
    var retry = el('tcRetry');
    if (retry) retry.addEventListener('click', load);
    var cancel = el('tcCancelRevision');
    if (cancel) cancel.addEventListener('click', function () { post('cancel-revision'); });
    load();
  });

  window.__trainerCatalogReload = load;
})();
