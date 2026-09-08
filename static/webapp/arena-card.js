/**
 * TASK-052 arena card page. Data: GET /api/public/arenas/{ref} + /sessions + /trainers.
 */
(function (global) {
  'use strict';

  var M = global.ArenaCardModel;
  var root = document.getElementById('arenaRoot');
  var state = {
    ref: null,
    card: null,
    sessions: null,
    trainers: null,
    day: 'today',
    galleryIndex: 0,
  };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function todayIso(now) {
    now = now || new Date();
    return M.ymd(now);
  }

  function addDaysIso(iso, n) {
    var d = M.parseLocalDate(iso);
    d.setDate(d.getDate() + n);
    return M.ymd(d);
  }

  function weekdayOf(iso) {
    return M.parseLocalDate(iso).getDay();
  }

  function sessionsByDate() {
    var map = {};
    var days = (state.sessions && state.sessions.days) || [];
    var i;
    for (i = 0; i < days.length; i++) {
      map[days[i].local_date] = days[i].sessions || [];
    }
    return map;
  }

  function allGroups() {
    return (state.trainers && state.trainers.groups) || [];
  }

  function hasAnySessions() {
    var days = (state.sessions && state.sessions.days) || [];
    var i;
    for (i = 0; i < days.length; i++) {
      if ((days[i].sessions || []).length) return true;
    }
    return false;
  }

  function initData() {
    var tg = global.Telegram && global.Telegram.WebApp;
    return (tg && tg.initData) || '';
  }

  function shellNav(path) {
    if (global.ClientShell && typeof global.ClientShell.navigate === 'function') {
      global.ClientShell.navigate(path);
      return;
    }
    global.location.href = path;
  }

  function goBooking(trainerId, action) {
    var href = M.buildBookingHref({
      trainerId: trainerId,
      arenaId: state.card && state.card.id,
      action: action || 'book',
    });
    shellNav(href);
  }

  function goWrite(trainer) {
    var url = trainer && trainer.contact_telegram_url;
    if (url) {
      global.location.href = url;
      return;
    }
    goBooking(trainer && trainer.id, null);
  }

  function photoUrl(trainer) {
    var photos = (trainer && trainer.photos) || [];
    if (!photos.length) return '';
    return photos[0].list_url || photos[0].url || '';
  }

  function trainerName(t) {
    var p = (t && t.profile) || t || {};
    return [p.first_name, p.last_name].filter(Boolean).join(' ').trim() || 'Тренер';
  }

  function renderHero() {
    var card = state.card;
    var hero = M.heroView(card);
    var url = hero.url;
    var gallery = card.gallery || [];
    var n = gallery.length || (hero.mode === 'photo' ? 1 : 0);
    var cls = 'arena-hero' + (hero.mode === 'photo' ? ' arena-hero--photo' : ' arena-hero--placeholder');
    var style = url ? ' style="background-image:url(\'' + esc(url).replace(/'/g, '%27') + '\')"' : '';
    var galleryHtml = n
      ? '<span class="arena-hero__gallery">' + (state.galleryIndex + 1) + ' / ' + n + ' фото</span>'
      : '';
    return (
      '<div class="' +
      cls +
      '"' +
      style +
      '>' +
      (hero.mode === 'photo' ? '<span class="arena-hero__shade"></span>' : '<span class="arena-hero__glare"></span>') +
      '<span class="arena-hero__txt">' +
      '<h1>' +
      esc(card.name || 'Арена') +
      '</h1>' +
      '<span class="arena-hero__meta">' +
      esc(M.heroMetaLine(card)) +
      '</span>' +
      '</span>' +
      galleryHtml +
      '</div>'
    );
  }

  function renderAmenities() {
    var chips = M.amenityChips(state.card.amenities);
    if (!chips.length) return '';
    return (
      '<div class="arena-sec"><div class="arena-amen">' +
      chips.map(function (c) { return '<span>' + esc(c) + '</span>'; }).join('') +
      '</div></div>'
    );
  }

  function rowHtml(row) {
    var stripe = row.stripe || (row.nature === 'lesson' ? 'lesson' : 'ice');
    var cls =
      'arena-row' +
      (stripe === 'lesson' ? ' arena-row--lesson' : '') +
      (row.nowState === 'live' ? ' arena-row--live' : '') +
      (row.empty ? ' arena-row--empty' : '');
    var ctaCls = 'arena-cta arena-cta--' + (row.ctaKind || 'ghost');
    var tag = 'div';
    var extra = '';
    if (row.nature === 'lesson' || row.openDay) {
      tag = 'button';
      extra = ' type="button"';
    } else if (row.nature === 'ice' && row.href && !row.empty) {
      tag = 'a';
      extra =
        ' href="' +
        esc(row.href) +
        '" target="_blank" rel="noopener noreferrer"';
    }
    if (row.nature === 'lesson' && row.group) {
      extra += ' data-action="group" data-trainer="' + esc(row.trainerId) + '" data-group="' + esc(row.group.id) + '"';
    }
    if (row.openDay) extra += ' data-action="open-day" data-date="' + esc(row.localDate) + '"';
    return (
      '<' + tag + ' class="' + cls + '"' + extra + '>' +
      '<span class="arena-row__t">' + esc(row.time || row.weekday) + '</span>' +
      '<span class="arena-row__m"><b>' + esc(row.title) + '</b><span>' + esc(row.meta || '') + '</span></span>' +
      '<span class="' + ctaCls + '">' + esc(row.cta) + '</span>' +
      '</' + tag + '>'
    );
  }

  function ribbonForIso(iso) {
    var byDate = sessionsByDate();
    return M.buildRibbonForDay({
      localDate: iso,
      sessions: byDate[iso] || [],
      groups: allGroups(),
      weekday: weekdayOf(iso),
      now: new Date(),
    });
  }

  function renderRibbonRows() {
    var today = todayIso();
    if (state.day === 'week') {
      var weekFrom = today;
      var weekTo = addDaysIso(today, 6);
      var summaries = M.buildWeekSummaries({
        from: weekFrom,
        to: weekTo,
        sessionDays: (state.sessions && state.sessions.days) || [],
        groups: allGroups(),
      });
      return summaries
        .map(function (d) {
          return rowHtml({
            nature: 'ice',
            empty: d.empty,
            time: d.weekday,
            weekday: d.weekday,
            title: d.title,
            meta: d.meta,
            cta: d.cta,
            ctaKind: 'ghost',
            openDay: !d.empty,
            localDate: d.localDate,
          });
        })
        .join('');
    }
    var iso = M.ribbonIsoForDay(state.day, today) || today;
    var rows = ribbonForIso(iso);
    if (!rows.length) {
      return (
        '<div class="arena-row arena-row--empty">' +
        '<span class="arena-row__t">—</span>' +
        '<span class="arena-row__m"><b>Данных нет</b><span>на этот день расписания нет</span></span>' +
        '<span class="arena-cta arena-cta--ghost">—</span>' +
        '</div>'
      );
    }
    return rows.map(rowHtml).join('');
  }

  function renderIceSection() {
    var feed = M.iceFeedView({
      card: state.card,
      hasSessions: hasAnySessions(),
    });
    if (feed.mode === 'closed') {
      return (
        '<div class="arena-sec">' +
        '<p class="arena-h">Лёд</p>' +
        '<div class="arena-closed">' + esc(feed.banner) + '</div>' +
        '</div>'
      );
    }
    if (feed.mode === 'none') {
      return '';
    }
    if (feed.mode === 'pending') {
      var phone = (state.card.phone || '').trim();
      var site = (state.card.website_url || '').trim();
      var actions = '';
      if (phone) {
        actions +=
          '<a class="arena-btn" href="tel:' +
          esc(phone.replace(/\s+/g, '')) +
          '">Позвонить ' +
          esc(phone) +
          '</a>';
      }
      if (site) {
        actions +=
          '<a class="arena-btn" href="' +
          esc(site) +
          '" target="_blank" rel="noopener">Сайт катка</a>';
      }
      return (
        '<div class="arena-sec">' +
        '<p class="arena-h">Лёд</p>' +
        '<div class="arena-empty">' +
        '<b>Расписание уточняется</b>' +
        '<p>Мы пока не получили расписание массового катания от этого катка. Не показываем то, за что не отвечаем.</p>' +
        actions +
        '</div>' +
        '</div>'
      );
    }
    return (
      '<div class="arena-sec">' +
      '<p class="arena-h">Лента льда<span class="arena-new">НОВОЕ</span></p>' +
      '<div class="arena-days" id="arenaDayTabs">' +
      '<button type="button" class="arena-day" data-day="today" aria-pressed="' +
      (state.day === 'today' ? 'true' : 'false') +
      '">Сегодня</button>' +
      '<button type="button" class="arena-day" data-day="tomorrow" aria-pressed="' +
      (state.day === 'tomorrow' ? 'true' : 'false') +
      '">Завтра</button>' +
      '<button type="button" class="arena-day" data-day="week" aria-pressed="' +
      (state.day === 'week' ? 'true' : 'false') +
      '">Неделя</button>' +
      '</div>' +
      '<div class="arena-rows" id="arenaRows">' +
      renderRibbonRows() +
      '</div>' +
      '<div class="arena-legend">' +
      M.ribbonLegend()
        .map(function (item) {
          return (
            '<span><i class="arena-sw arena-sw--' +
            esc(item.stripe) +
            '"></i>' +
            esc(item.text) +
            '</span>'
          );
        })
        .join('') +
      '</div>' +
      '</div>'
    );
  }

  function renderTrainers() {
    var items = (state.trainers && state.trainers.items) || [];
    if (!items.length) return '';
    var html =
      '<div class="arena-sec"><p class="arena-h">Тренеры на этой арене<span class="arena-new">НОВОЕ</span></p>';
    var i;
    for (i = 0; i < items.length; i++) {
      var t = items[i];
      var cta = M.trainerCta(t);
      var ava = photoUrl(t);
      html +=
        '<button type="button" class="arena-coach" data-action="trainer" data-trainer="' +
        esc(t.id) +
        '" data-can-book="' +
        (t.can_book ? '1' : '0') +
        '">' +
        (ava
          ? '<img class="arena-coach__ava" alt="" src="' + esc(ava) + '">'
          : '<i class="arena-coach__ava"></i>') +
        '<span class="arena-coach__b"><b>' +
        esc(trainerName(t)) +
        '</b><span>' +
        esc(M.trainerSubtitle(t)) +
        '</span></span>' +
        '<span class="arena-cta arena-cta--' +
        cta.kind +
        '">' +
        esc(cta.label) +
        '</span>' +
        '</button>';
    }
    html +=
      '<p class="arena-sub">Тренер без онлайн-записи показывается честно — «Написать», а не мёртвая кнопка.</p></div>';
    return html;
  }

  function renderGroups() {
    var groups = allGroups();
    if (!groups.length) return '';
    var html = '<div class="arena-sec"><p class="arena-h">Группы с набором</p>';
    var i;
    for (i = 0; i < groups.length; i++) {
      var g = groups[i];
      var right =
        g.spots_left > 0 ? g.spots_left + ' места' : 'набор открыт';
      html +=
        '<button type="button" class="arena-fake-row" data-action="group" data-trainer="' +
        esc(g.trainer_id) +
        '" data-group="' +
        esc(g.id) +
        '"><b style="font-weight:640;font-size:14px">' +
        esc(g.name || 'Группа') +
        '</b><span>' +
        esc(right) +
        '</span></button>';
    }
    html += '</div>';
    return html;
  }

  function renderPractice() {
    var card = state.card;
    var mode = M.iceSectionMode({ tier: card.tier, hasSessions: hasAnySessions() });
    var contacts = M.practiceContacts(card);
    if (
      mode === 'none' &&
      !card.address &&
      !card.phone &&
      !contacts.website &&
      !contacts.socials.length &&
      !contacts.shortDescription
    ) {
      return '';
    }
    var html = '<div class="arena-sec"><p class="arena-h">Как добраться и что есть</p>';
    if (contacts.shortDescription) {
      html += '<p class="arena-sub">' + esc(contacts.shortDescription) + '</p>';
    }
    if (card.address) {
      var mapHref = '';
      if (card.latitude != null && card.longitude != null) {
        mapHref =
          'https://maps.google.com/?q=' +
          encodeURIComponent(card.latitude + ',' + card.longitude);
      } else {
        mapHref = 'https://maps.google.com/?q=' + encodeURIComponent(card.address);
      }
      html +=
        '<a class="arena-fake-row" href="' +
        esc(mapHref) +
        '" target="_blank" rel="noopener"><b style="font-weight:600;font-size:13.5px">' +
        esc(card.address) +
        '</b><span>Открыть карту</span></a>';
    }
    if (card.phone) {
      html +=
        '<a class="arena-fake-row" href="tel:' +
        esc(String(card.phone).replace(/\s+/g, '')) +
        '"><b style="font-weight:600;font-size:13.5px">' +
        esc(card.phone) +
        '</b><span>Позвонить</span></a>';
    }
    var hours = M.formatOpeningHours(card.opening_hours);
    var season =
      card.season_start_month === 1 && card.season_end_month === 12
        ? 'Сезон: круглый год'
        : hours
          ? 'Часы работы'
          : '';
    if (hours || season) {
      html +=
        '<div class="arena-fake-row"><b style="font-weight:600;font-size:13.5px">' +
        esc(season || 'Часы работы') +
        '</b><span>' +
        esc(hours) +
        '</span></div>';
    }
    if (contacts.website) {
      html +=
        '<a class="arena-fake-row" href="' +
        esc(contacts.website.href) +
        '" target="_blank" rel="noopener"><b style="font-weight:600;font-size:13.5px">' +
        esc(contacts.website.label) +
        '</b><span>Открыть</span></a>';
    }
    if (contacts.socials.length) {
      html +=
        '<p class="arena-sub">' +
        contacts.socials
          .map(function (s) {
            return (
              '<a href="' +
              esc(s.href) +
              '" target="_blank" rel="noopener">' +
              esc(s.label) +
              '</a>'
            );
          })
          .join(' · ') +
        '</p>';
    }
    html += '</div>';
    return html;
  }

  function renderFreshness() {
    var text = M.formatFreshness(state.card.freshness, new Date());
    var html = '<div class="arena-sec"><div class="arena-fresh">';
    if (text) html += '<span>' + esc(text) + '</span>';
    html +=
      '<span><button type="button" class="linkish" data-action="report">Сообщить об ошибке</button> — конкретное поле, а не письмо в поддержку</span>';
    html += '</div></div>';
    return html;
  }

  function renderOwner() {
    var pending = M.iceSectionMode({
      tier: state.card.tier,
      hasSessions: hasAnySessions(),
    }) === 'pending';
    if (pending) {
      return (
        '<div class="arena-sec"><div class="arena-owner">' +
        '<b>Знаете расписание этого катка?</b>' +
        '<p>Подскажите время и цены — проверим и опубликуем со ссылкой на источник.</p>' +
        '<button type="button" class="arena-btn" data-action="claim-schedule">Дополнить карточку</button>' +
        '</div></div>'
      );
    }
    return (
      '<div class="arena-sec"><div class="arena-owner">' +
      '<b>Это ваш каток?</b>' +
      '<p>Заберите страницу: ведите расписание сами, добавьте фото и своих тренеров.</p>' +
      '<button type="button" class="arena-btn" data-action="claim">Забрать страницу</button>' +
      '</div></div>'
    );
  }

  function paint() {
    if (!root || !state.card) return;
    var title = document.getElementById('headerTitle');
    if (title) title.textContent = state.card.name || 'Арена';
    root.innerHTML =
      renderHero() +
      renderAmenities() +
      renderIceSection() +
      renderTrainers() +
      renderGroups() +
      renderPractice() +
      renderFreshness() +
      renderOwner();
  }

  function paintRowsOnly() {
    var el = document.getElementById('arenaRows');
    if (el) el.innerHTML = renderRibbonRows();
    var tabs = document.getElementById('arenaDayTabs');
    if (!tabs) return;
    [].forEach.call(tabs.querySelectorAll('[data-day]'), function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-day') === state.day ? 'true' : 'false');
    });
  }

  var REPORT_FIELDS = [
    { id: 'schedule', label: 'Расписание / время сеанса' },
    { id: 'price_adult', label: 'Цена взрослый' },
    { id: 'price_child', label: 'Цена детский' },
    { id: 'price_rental', label: 'Прокат' },
    { id: 'phone', label: 'Телефон' },
    { id: 'hours', label: 'Часы работы' },
    { id: 'other', label: 'Другое' },
  ];

  function openModal(kind) {
    var modal = document.getElementById('arenaModal');
    var title = document.getElementById('arenaModalTitle');
    var lead = document.getElementById('arenaModalLead');
    var field = document.getElementById('arenaModalField');
    var value = document.getElementById('arenaModalValue');
    if (!modal) return;
    modal.dataset.kind = kind;
    if (kind === 'claim') {
      title.textContent = 'Забрать страницу';
      lead.textContent = 'Оставьте контакт — заявка уйдёт администратору.';
      field.innerHTML = '<option value="claim">Контакт оператора катка</option>';
      value.placeholder = 'телефон или сайт';
    } else if (kind === 'claim-schedule') {
      title.textContent = 'Дополнить карточку';
      lead.textContent = 'Время и цены массового катания — проверим по источнику.';
      field.innerHTML = '<option value="schedule">Расписание МК</option>';
      value.placeholder = 'например 18:00–19:00, взр. 12';
    } else {
      title.textContent = 'Сообщить об ошибке';
      lead.textContent = 'Укажите поле и верное значение — не письмо в поддержку.';
      field.innerHTML = REPORT_FIELDS.map(function (f) {
        return '<option value="' + f.id + '">' + esc(f.label) + '</option>';
      }).join('');
      value.placeholder = 'как должно быть';
    }
    value.value = '';
    modal.hidden = false;
  }

  function closeModal() {
    var modal = document.getElementById('arenaModal');
    if (modal) modal.hidden = true;
  }

  function storeLocalReport(payload) {
    var key = 'tcb_arena_reports_v1';
    var list = [];
    try {
      list = JSON.parse(global.localStorage.getItem(key) || '[]');
    } catch (e) {
      list = [];
    }
    if (!Array.isArray(list)) list = [];
    list.push(payload);
    try {
      global.localStorage.setItem(key, JSON.stringify(list.slice(-50)));
    } catch (e2) { /* quota */ }
  }

  function submitModal(ev) {
    ev.preventDefault();
    var modal = document.getElementById('arenaModal');
    var field = document.getElementById('arenaModalField');
    var value = document.getElementById('arenaModalValue');
    var kind = modal && modal.dataset.kind;
    var payload = {
      kind: kind || 'report',
      arena_id: state.card && state.card.id,
      arena_slug: state.card && state.card.slug,
      field: field && field.value,
      suggested: value && value.value,
      at: new Date().toISOString(),
    };
    var msg =
      '[arena-' +
      payload.kind +
      '] arena=' +
      (payload.arena_id || payload.arena_slug) +
      ' field=' +
      payload.field +
      ' value=' +
      (payload.suggested || '');
    storeLocalReport(payload);
    var cred = initData();
    if (cred) {
      fetch('/api/webapp/support', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Telegram-Init-Data': cred,
        },
        body: JSON.stringify({ message: msg, role: 'client' }),
      }).catch(function () { /* local store already saved */ });
    }
    closeModal();
    if (global.Telegram && global.Telegram.WebApp && global.Telegram.WebApp.showAlert) {
      global.Telegram.WebApp.showAlert('Спасибо, передали администратору.');
    }
  }

  function onRootClick(ev) {
    var dayBtn = ev.target.closest('[data-day]');
    if (dayBtn && dayBtn.closest('#arenaDayTabs')) {
      state.day = dayBtn.getAttribute('data-day');
      paintRowsOnly();
      return;
    }
    var t = ev.target.closest('[data-action]');
    if (!t) return;
    var action = t.getAttribute('data-action');
    if (action === 'trainer') {
      var can = t.getAttribute('data-can-book') === '1';
      var tid = t.getAttribute('data-trainer');
      if (can) goBooking(tid, 'book');
      else {
        var trainer = ((state.trainers && state.trainers.items) || []).filter(function (x) {
          return String(x.id) === String(tid);
        })[0];
        goWrite(trainer || { id: tid });
      }
      return;
    }
    if (action === 'group') {
      goBooking(t.getAttribute('data-trainer'), 'book');
      return;
    }
    if (action === 'open-day') {
      state.day = M.dayTabFromIso(t.getAttribute('data-date'), todayIso());
      paint();
      return;
    }
    if (action === 'report') openModal('report');
    if (action === 'claim') openModal('claim');
    if (action === 'claim-schedule') openModal('claim-schedule');
  }

  function fetchJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      if (r.status === 404) return null;
      if (!r.ok) throw new Error('http ' + r.status);
      return r.json();
    });
  }

  function showError(text) {
    if (!root) return;
    root.innerHTML = '<div class="arena-state">' + esc(text) + '</div>';
  }

  function resolveRef() {
    var tg = global.Telegram && global.Telegram.WebApp;
    var start =
      (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param) ||
      M.startParamFromLocation(global.location);
    return M.parseArenaRef(global.location.search || '', start);
  }

  function load() {
    state.ref = resolveRef();
    if (!state.ref) {
      showError('Не указана арена. Откройте карточку по ссылке из каталога или бота.');
      return;
    }
    var base = '/api/public/arenas/' + encodeURIComponent(state.ref);
    var today = todayIso();
    var to = addDaysIso(today, 13);
    Promise.all([
      fetchJson(base),
      fetchJson(base + '/sessions?from=' + encodeURIComponent(today) + '&to=' + encodeURIComponent(to)),
      fetchJson(base + '/trainers'),
    ])
      .then(function (parts) {
        if (!parts[0]) {
          showError('Арена не найдена.');
          return;
        }
        state.card = parts[0];
        state.sessions = parts[1] || { days: [] };
        state.trainers = parts[2] || { items: [], groups: [] };
        paint();
      })
      .catch(function () {
        showError('Не удалось загрузить карточку. Попробуйте ещё раз.');
      });
  }

  function bindChrome() {
    var home = document.getElementById('btnHome');
    if (home) {
      home.addEventListener('click', function () {
        shellNav('client-home');
      });
    }
    var back = document.getElementById('btnBack');
    if (back) {
      back.addEventListener('click', function () {
        if (global.history.length > 1) global.history.back();
        else {
          shellNav('ice');
        }
      });
    }
    if (root) root.addEventListener('click', onRootClick);
    var form = document.getElementById('arenaModalForm');
    if (form) form.addEventListener('submit', submitModal);
    var cancel = document.getElementById('arenaModalCancel');
    if (cancel) cancel.addEventListener('click', closeModal);
    if (global.ClientShell && typeof global.ClientShell.setForcedTab === 'function') {
      global.ClientShell.setForcedTab('catalog');
    }
  }

  global.ArenaCardPage = {
    load: load,
    paint: paint,
    state: state,
  };

  bindChrome();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})(typeof window !== 'undefined' ? window : this);
