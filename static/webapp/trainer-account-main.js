/**
 * Вкладка «Профиль» (TASK-313).
 *
 * Тренер не находил, где ставить цены и писать о себе: профиль был анкетой с тремя вкладками
 * и семью якорями, спрятанной в шторке «Ещё». Здесь — один экран-оглавление:
 *   шапка (фото, имя, услуга · город, «Как меня видят ученики») →
 *   «Странице не хватает» (только реально пустое, с действием) →
 *   группы разделов, у каждого справа короткое текущее значение.
 *
 * Сам экран ничего не редактирует. Разделы анкеты открываются карусельным экраном профиля
 * с одним блоком (`trainer-profile?task=…&return=trainer-account`), цены — отдельной страницей
 * `trainer-prices`. Данные — те же ручки, что у анкеты и раздела «Каталог».
 */
(function () {
  'use strict';

  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    try { tg.ready(); tg.expand(); } catch (e) { /* старые клиенты */ }
    if (typeof window.__applyTrainerMiniAppTheme === 'function') window.__applyTrainerMiniAppTheme();
    if (tg.onEvent) {
      tg.onEvent('themeChanged', function () {
        if (typeof window.__applyTrainerMiniAppTheme === 'function') window.__applyTrainerMiniAppTheme();
      });
    }
    try {
      var bgHex = tg.colorScheme === 'dark' ? '#0B0C0E' : '#F1F3F2';
      if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
      if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
    } catch (e2) { /* */ }
  }

  var ICONS = {
    tag: 'M3 12V4h8l10 10-8 8L3 12z M7.5 7.5h.01',
    text: 'M5 6h14 M5 11h14 M5 16h9',
    pin: 'M12 21s-7-6.5-7-12a7 7 0 0 1 14 0c0 5.5-7 12-7 12z M12 7a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5',
    medal: 'M12 15a5 5 0 1 0 0-10a5 5 0 1 0 0 10z M9 14l-1 7 4-2 4 2-1-7',
    phone: 'M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z',
    ticket: 'M4 7h16v3a2 2 0 0 0 0 4v3H4v-3a2 2 0 0 0 0-4z M14 7v10',
    people: 'M9 11a3 3 0 1 0 0-6a3 3 0 1 0 0 6z M3 20a6 6 0 0 1 12 0 M16 5a3 3 0 0 1 0 6 M18 14a6 6 0 0 1 3 6',
    inbox: 'M4 13l2-8h12l2 8v6H4z M4 13h5l1 2h4l1-2h5',
    stats: 'M5 20V11 M12 20V5 M19 20v-6',
    clock: 'M12 21a9 9 0 1 0 0-18a9 9 0 1 0 0 18z M12 7v5l3 2',
    bell: 'M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z M10 21h4',
    card: 'M3 6h18v12H3z M3 10h18',
    invite: 'M10 11a4 4 0 1 0 0-8a4 4 0 1 0 0 8z M3 21a7 7 0 0 1 14 0 M19 8v6 M16 11h6',
    help: 'M12 21a9 9 0 1 0 0-18a9 9 0 1 0 0 18z M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.7 M12 17h.01',
    studio: 'M3 21h18 M6 21V7l6-4 6 4v14 M10 21v-6h4v6',
  };

  /* Раздел анкеты — экран с одним блоком, после сохранения назад сюда. */
  var BACK = '&return=trainer-account';
  var ROUTES = {
    prices: 'trainer-prices',
    basics: 'trainer-profile?task=basics' + BACK,
    about: 'trainer-profile?task=about' + BACK,
    arenas: 'trainer-arenas',
    experience: 'trainer-profile?task=experience' + BACK,
    contacts: 'trainer-profile?task=contacts' + BACK,
    booking: 'trainer-profile?task=booking' + BACK,
    notifications: 'trainer-profile?task=notifications' + BACK,
  };

  var DESCRIPTION_MIN = 25;
  var MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
    'сентября', 'октября', 'ноября', 'декабря'];

  var state = { boot: null, catalog: null, subscription: null, menu: null };

  function el(id) { return document.getElementById(id); }

  function credential() {
    var rt = window.MiniAppRuntime;
    if (rt && typeof rt.getCredential === 'function') {
      var c = rt.getCredential();
      if (c) return c;
    }
    if (tg && tg.initData) return String(tg.initData);
    /* Переходы внутри кабинета несут init_data в адресе (как у анкеты). */
    try {
      var qs = new URLSearchParams(window.location.search || '');
      return qs.get('init_data') || qs.get('initData') || '';
    } catch (e) {
      return '';
    }
  }

  function apiUrl(path) {
    var url = '/api/webapp' + path;
    var c = credential();
    if (c) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(c);
    return url;
  }

  function getJson(path) {
    var c = credential();
    var h = { Accept: 'application/json' };
    if (c) h['X-Telegram-Init-Data'] = c;
    return fetch(apiUrl(path), { headers: h, cache: 'no-store' }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error((d && d.detail) || ('http_' + r.status));
        return d;
      });
    });
  }

  function go(path) {
    haptic();
    if (window.TrainerShell && typeof window.TrainerShell.navigate === 'function') {
      window.TrainerShell.navigate(path);
      return;
    }
    var base = (window.location.pathname || '').replace(/[^/]+$/, '') || '/webapp/';
    var c = credential();
    var url = base + path;
    if (c) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(c);
    window.location.href = url;
  }

  function haptic() {
    try {
      if (tg && tg.HapticFeedback) tg.HapticFeedback.selectionChanged();
    } catch (e) { /* */ }
  }

  function svg(path, cls) {
    return '<svg class="' + cls + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + path + '"/></svg>';
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function plural(n, one, few, many) {
    var m10 = n % 10;
    var m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }

  function dayMonth(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    var out = d.getDate() + '\u00a0' + MONTHS[d.getMonth()];
    if (d.getFullYear() !== new Date().getFullYear()) out += ' ' + d.getFullYear();
    return out;
  }

  /* ─── Что знаем о тренере ─────────────────────────────────────────────── */

  /* Предлог не остаётся в конце строки: «катанию «с / нуля»» → неразрывный пробел. */
  function glueShortWords(text) {
    return String(text || '').replace(/(^|[\s«(])(с|в|к|и|о|у|на|по|до|за|от|для)\s+/gi, '$1$2\u00a0');
  }

  function trainer() { return (state.boot && state.boot.trainer) || {}; }
  function profile() { return trainer().profile || {}; }
  function services() { return trainer().services || []; }

  function servicePrices(s) {
    var out = [];
    (s.price_tiers || []).forEach(function (t) {
      if (t && t.price_byn != null && !isNaN(Number(t.price_byn))) out.push(Number(t.price_byn));
    });
    if (!out.length) {
      if (s.price_byn != null) out.push(Number(s.price_byn));
      if (s.price_child_byn != null) out.push(Number(s.price_child_byn));
    }
    return out;
  }

  function currencySign() {
    var list = services();
    for (var i = 0; i < list.length; i++) {
      if (list[i].currency_code === 'RUB') return '₽';
      if (list[i].currency_code) return 'BYN';
    }
    var city = cityObj();
    return city && city.country === 'RU' ? '₽' : 'BYN';
  }

  function formatMoney(n) {
    var r = Math.round(n * 100) / 100;
    return String(r).replace('.', ',');
  }

  function cityObj() {
    var cid = profile().city_id;
    var refs = (state.boot && state.boot.refs) || {};
    var items = (refs.cities && refs.cities.items) || [];
    for (var i = 0; i < items.length; i++) if (Number(items[i].id) === Number(cid)) return items[i];
    return null;
  }

  function hasPhoto() {
    var ph = trainer().photos || [];
    return !!(ph[0] && ph[0].file_key);
  }

  function photoUrl() {
    var ph = trainer().photos || [];
    return ph[0] && ph[0].file_key ? '/api/public/photos/' + encodeURIComponent(ph[0].file_key) : '';
  }

  function fullName() {
    var p = profile();
    var name = [p.first_name, p.last_name].filter(Boolean).join(' ').trim();
    if (name) return name;
    var u = tg && tg.initDataUnsafe && tg.initDataUnsafe.user;
    return u ? [u.first_name, u.last_name].filter(Boolean).join(' ') : 'Тренер';
  }

  function initials(name) {
    return name.split(/\s+/).filter(Boolean).slice(0, 2).map(function (w) { return w.charAt(0); }).join('').toUpperCase();
  }

  function descriptionFilled() {
    return String(profile().description || '').trim().length >= DESCRIPTION_MIN;
  }

  function anyServiceUnpriced() {
    return services().some(function (s) { return !servicePrices(s).length; });
  }

  /* ─── Значения справа ─────────────────────────────────────────────────── */

  function pricesValue() {
    var list = services();
    if (!list.length) return { text: 'Не выбраны', attention: true };
    var all = [];
    list.forEach(function (s) { all = all.concat(servicePrices(s)); });
    if (!all.length) return { text: 'Без цен', attention: true };
    var min = Math.min.apply(null, all);
    var txt = 'от ' + formatMoney(min) + '\u00a0' + currencySign();
    if (anyServiceUnpriced()) txt = 'Не у всех цена';
    return { text: txt, attention: anyServiceUnpriced() };
  }

  function arenasValue() {
    var names = trainer().arena_names || [];
    if (names.length) return names.join(', ');
    var onlineOnly = services().length && services().every(function (s) { return s.is_online; });
    return onlineOnly ? 'Онлайн' : 'Не указано';
  }

  function experienceValue() {
    var y = profile().experience_years;
    if (y == null || y === '') return '';
    y = Number(y);
    if (!y) return 'Меньше года';
    return y + '\u00a0' + plural(y, 'год', 'года', 'лет');
  }

  function phoneValue() {
    var p = String(profile().phone || '').trim();
    if (!p) return { text: 'Не указан', attention: false };
    var m = p.match(/^\+375(\d{2})(\d{3})(\d{2})(\d{2})$/);
    if (m) p = '+375\u00a0' + m[1] + '\u00a0' + m[2] + '-' + m[3] + '-' + m[4];
    var r = p.match(/^\+7(\d{3})(\d{3})(\d{2})(\d{2})$/);
    if (r) p = '+7\u00a0' + r[1] + '\u00a0' + r[2] + '-' + r[3] + '-' + r[4];
    return { text: p, attention: false };
  }

  function bookingValue() {
    var p = profile();
    var parts = [];
    if (p.session_duration_minutes) parts.push(p.session_duration_minutes + '\u00a0мин');
    if (p.min_hours_before_booking != null) parts.push('запись за\u00a0' + p.min_hours_before_booking + '\u00a0ч');
    return parts.join(' · ');
  }

  function subscriptionValue() {
    var s = state.subscription;
    if (!s) return { text: '', attention: false };
    if (!s.is_active) return { text: 'Не активна', attention: true };
    var until = dayMonth(s.expires_at);
    if (s.is_trial) return { text: until ? 'Пробная до\u00a0' + until : 'Пробная', attention: false };
    var name = s.tier_name_ru || 'Активна';
    return { text: until ? name + ' до\u00a0' + until : name, attention: false };
  }

  /* ─── Рендер ──────────────────────────────────────────────────────────── */

  function renderHead() {
    var name = fullName();
    el('taName').textContent = name;
    var first = services()[0];
    var city = cityObj();
    var line = [first ? first.service_name : '', city ? city.name : ''].filter(Boolean).join(' · ');
    el('taLine').textContent = glueShortWords(line) || 'Нажмите, чтобы добавить фото';
    var av = el('taAvatar');
    var url = photoUrl();
    if (url) {
      av.style.backgroundImage = 'url("' + url + '")';
      av.textContent = '';
    } else {
      av.style.backgroundImage = '';
      av.textContent = initials(name);
    }
    el('taWho').onclick = function () { go(ROUTES.basics); };
    var link = state.catalog && state.catalog.preview_link;
    var btn = el('taPreview');
    btn.hidden = !link;
    btn.onclick = function () {
      haptic();
      if (tg && typeof tg.openTelegramLink === 'function') tg.openTelegramLink(link);
      else window.open(link, '_blank');
    };
  }

  function renderMissing() {
    var items = [];
    if (!services().length) {
      items.push({ label: 'Занятий', hint: 'Ученику пока нечего выбрать', action: 'Добавить', route: ROUTES.prices });
    } else if (anyServiceUnpriced()) {
      items.push({ label: 'Цен', hint: 'Сейчас ученики видят «по\u00a0запросу»', action: 'Указать', route: ROUTES.prices });
    }
    if (!descriptionFilled()) {
      items.push({ label: 'Пары слов о\u00a0себе', hint: 'С\u00a0кем работаете и\u00a0как', action: 'Написать', route: ROUTES.about });
    }
    if (!hasPhoto()) {
      items.push({ label: 'Фото', hint: 'Ученику спокойнее, когда видно тренера', action: 'Добавить', route: ROUTES.basics });
    }
    var box = el('taMissing');
    var list = el('taMissingList');
    list.innerHTML = '';
    box.hidden = !items.length;
    items.forEach(function (it) {
      var row = document.createElement('div');
      row.className = 'ta-missing__row';
      row.innerHTML =
        '<span class="ta-missing__text"><span class="ta-missing__label">' + it.label + '</span>' +
        '<span class="ta-missing__hint">' + it.hint + '</span></span>';
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ta-btn ta-btn--small';
      b.textContent = it.action;
      b.onclick = function () { go(it.route); };
      row.appendChild(b);
      list.appendChild(row);
    });
  }

  function groups() {
    var menu = state.menu || {};
    var badges = menu.badges || {};
    var prices = pricesValue();
    var phone = phoneValue();
    var sub = subscriptionValue();
    var out = [];
    if (menu.collective) {
      out.push({ title: menu.collective.label, rows: [
        { icon: ICONS.studio, label: menu.collective.label, value: menu.collective.hint || '', route: menu.collective.path },
      ] });
    }
    out.push({ title: 'Моя страница', rows: [
      { icon: ICONS.tag, label: 'Услуги и цены', value: prices.text, attention: prices.attention, route: ROUTES.prices },
      { icon: ICONS.text, label: 'О себе', value: descriptionFilled() ? '' : 'Пусто', route: ROUTES.about },
      { icon: ICONS.pin, label: 'Где занимаюсь', value: arenasValue(), route: ROUTES.arenas },
      { icon: ICONS.medal, label: 'Опыт и образование', value: experienceValue(), route: ROUTES.experience },
      { icon: ICONS.phone, label: 'Контакты', value: phone.text, route: ROUTES.contacts },
    ] });
    out.push({ title: 'Продажи', rows: [
      { icon: ICONS.ticket, label: 'Абонементы', value: '', route: 'trainer-pass-products' },
      { icon: ICONS.people, label: 'Группы', value: '', route: 'trainer-groups' },
    ] });
    out.push({ title: 'Работа', rows: [
      { icon: ICONS.inbox, label: 'Заявки', value: '', badge: Number(badges['trainer-requests'] || 0), route: 'trainer-requests' },
      { icon: ICONS.stats, label: 'Статистика', value: '', route: 'trainer-stats' },
    ] });
    out.push({ title: 'Настройки', rows: [
      { icon: ICONS.clock, label: 'Запись', value: bookingValue(), route: ROUTES.booking },
      { icon: ICONS.bell, label: 'Уведомления', value: trainer().digest_enabled ? 'Утренняя сводка' : '', route: ROUTES.notifications },
    ] });
    out.push({ title: 'Аккаунт', rows: [
      { icon: ICONS.card, label: 'Подписка', value: sub.text, attention: sub.attention, route: 'trainer-subscription' },
      { icon: ICONS.invite, label: 'Пригласить коллегу', value: '', route: 'trainer-referral' },
      { icon: ICONS.help, label: 'Помощь', value: '', route: 'trainer-faq' },
    ] });
    return out;
  }

  function renderGroups() {
    var host = el('taGroups');
    host.innerHTML = '';
    groups().forEach(function (g) {
      var sec = document.createElement('section');
      sec.className = 'ta-group';
      var h = document.createElement('h2');
      h.className = 'ta-group__title';
      h.textContent = g.title;
      sec.appendChild(h);
      var card = document.createElement('div');
      card.className = 'ta-group__card';
      g.rows.forEach(function (r) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'ta-row';
        var badge = r.badge > 0
          ? '<span class="ta-row__badge" aria-label="' + r.badge + ' ' + plural(r.badge, 'новая', 'новые', 'новых') + '">' +
            (r.badge > 9 ? '9+' : r.badge) + '</span>'
          : '';
        b.innerHTML =
          svg(r.icon, 'ta-row__icon') +
          '<span class="ta-row__main">' +
          '<span class="ta-row__label">' + esc(r.label) + '</span>' +
          '<span class="ta-row__value' + (r.attention ? ' ta-row__value--attention' : '') + '">' + esc(r.value || '') + '</span>' +
          badge +
          svg('M9 6l6 6-6 6', 'ta-row__chevron') +
          '</span>';
        b.onclick = function () { go(r.route); };
        card.appendChild(b);
      });
      sec.appendChild(card);
      host.appendChild(sec);
    });
  }

  function render() {
    el('taLoading').hidden = true;
    el('taError').hidden = true;
    el('taRoot').hidden = false;
    renderHead();
    renderMissing();
    renderGroups();
  }

  function readMenu() {
    if (window.TrainerShell && typeof window.TrainerShell.getMenuState === 'function') {
      state.menu = window.TrainerShell.getMenuState();
    }
  }

  function load() {
    el('taLoading').hidden = false;
    el('taError').hidden = true;
    /* Каталог и подписка — второстепенные: без них экран всё равно строится. */
    var soft = function (p) { return p.catch(function () { return null; }); };
    Promise.all([
      getJson('/trainer/profile/page-bootstrap'),
      soft(getJson('/trainer/catalog')),
      soft(getJson('/trainer/subscription/status')),
    ])
      .then(function (res) {
        state.boot = res[0];
        state.catalog = res[1];
        state.subscription = res[2];
        readMenu();
        render();
      })
      .catch(function () {
        el('taLoading').hidden = true;
        el('taRoot').hidden = true;
        el('taError').hidden = false;
      });
  }

  document.addEventListener('trainer-shell:menu', function (ev) {
    state.menu = ev.detail || null;
    if (state.boot) renderGroups();
  });

  function start() {
    el('taRetry').onclick = load;
    el('taFullForm').onclick = function () { go('trainer-profile'); };
    load();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
