/*
 * Главная v2 (TASK-445, эпик glide-home-v1, флаг redesign_s1).
 * Один запрос /client/hub/bootstrap → одна верхняя карточка по приоритету:
 * запись сегодня → ближайшая запись → абонемент → тренер → лёд города → выбор города.
 * Ниже: «Лёд в {городе}» с днями-вкладками, «Матчи», «Ещё в городе».
 * Golos везде; Dela Gothic только на крупном времени верхней карточки.
 */
(function () {
  'use strict';

  var DEAD = { cancelled: 1, canceled: 1, declined: 1, rejected: 1, no_show: 1, completed: 1, expired: 1 };
  var TZ = 'Europe/Minsk';
  var els = {};
  var state = { data: null, cities: null, railTab: null, slots: {}, yellowUsed: false };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function tg() { return window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null; }
  function haptic(kind) {
    var w = tg();
    try {
      if (w && w.HapticFeedback) {
        if (kind === 'select') w.HapticFeedback.selectionChanged && w.HapticFeedback.selectionChanged();
        else if (kind === 'success' || kind === 'error') w.HapticFeedback.notificationOccurred && w.HapticFeedback.notificationOccurred(kind);
        else w.HapticFeedback.impactOccurred && w.HapticFeedback.impactOccurred(kind === 'light' ? 'light' : 'medium');
      }
    } catch (e) {}
  }
  function initData() {
    var rt = window.MiniAppRuntime;
    if (rt && rt.getCredential) return rt.getCredential() || '';
    var w = tg();
    return w && w.initData ? String(w.initData) : '';
  }
  function tgUser() {
    var w = tg();
    return (w && w.initDataUnsafe && w.initDataUnsafe.user) || null;
  }
  function profileId() {
    try {
      var v = localStorage.getItem('cw_active_profile_id_v1');
      var pid = v ? parseInt(v, 10) : null;
      if (pid == null || !(pid > 0)) {
        var init = initData();
        var user = JSON.parse(new URLSearchParams(init).get('user') || 'null');
        var d = JSON.parse(localStorage.getItem('cw_default_profile_v1') || 'null');
        if (user && d && d.u === String(user.id) && Number(d.id) > 0) pid = Number(d.id);
      }
      return pid && pid > 0 ? pid : null;
    } catch (e) { return null; }
  }
  function headersJson() {
    var h = { 'Content-Type': 'application/json' };
    var init = initData();
    if (init) h['X-Telegram-Init-Data'] = init;
    var pid = profileId();
    if (pid) h['X-Profile-Id'] = String(pid);
    return h;
  }
  function navigate(path) {
    if (window.ClientShell && typeof window.ClientShell.navigate === 'function') window.ClientShell.navigate(path);
    else window.location.href = '/webapp/' + path;
  }
  function openExternal(url) {
    var w = tg();
    try {
      if (w && w.openTelegramLink) { w.openTelegramLink(url); return; }
      if (w && w.openLink) { w.openLink(url); return; }
    } catch (e) {}
    window.open(url, '_blank');
  }
  function shareUrl(url) {
    var w = tg();
    try {
      if (w && w.shareURL) { w.shareURL(url); return; }
      if (w && w.openTelegramLink) { w.openTelegramLink('https://t.me/share/url?url=' + encodeURIComponent(url)); return; }
    } catch (e) {}
    openExternal('https://t.me/share/url?url=' + encodeURIComponent(url));
  }

  /* ── Время и слова (Europe/Minsk — как у сервера) ─────────── */
  function minskDate() {
    try {
      var f = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' });
      return f.format(new Date());
    } catch (e) {
      var d = new Date();
      return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }
  }
  function minskHour() {
    try {
      return parseInt(new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', hourCycle: 'h23' }).format(new Date()), 10);
    } catch (e) { return new Date().getHours(); }
  }
  function dateLine() {
    try {
      var s = new Intl.DateTimeFormat('ru-RU', { timeZone: TZ, weekday: 'long', day: 'numeric', month: 'long' }).format(new Date());
      return s.charAt(0).toUpperCase() + s.slice(1);
    } catch (e) { return ''; }
  }
  function greeting() {
    var h = minskHour();
    if (h >= 5 && h < 12) return 'Доброе утро';
    if (h >= 12 && h < 18) return 'Добрый день';
    if (h >= 18 && h < 23) return 'Добрый вечер';
    return 'Доброй ночи';
  }
  function hhmm(t) { return String(t || '').slice(0, 5); }
  /* TASK-447: единый обратный отсчёт — «через 25 мин» / «через 1 ч 40 мин». */
  function fmtUntil(min) {
    if (min == null || min <= 0) return null;
    if (min < 60) return 'через ' + Math.round(min) + ' мин';
    var h = Math.floor(min / 60), m = Math.round(min % 60);
    return 'через ' + h + ' ч' + (m ? ' ' + m + ' мин' : '');
  }
  function fmtUntilCap(min) {
    var s = fmtUntil(min);
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : null;
  }
  function plural(n, one, few, many) {
    n = Math.abs(Number(n) || 0) % 100;
    var d = n % 10;
    if (n > 10 && n < 20) return many;
    if (d > 1 && d < 5) return few;
    if (d === 1) return one;
    return many;
  }
  var DOW = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
  var MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  function dayWord(dateStr) {
    var today = minskDate();
    if (dateStr === today) return 'today';
    var d = new Date(dateStr + 'T12:00:00');
    if (isNaN(d)) return 'other';
    var diff = Math.round((d - new Date(today + 'T12:00:00')) / 86400000);
    return diff === 1 ? 'tomorrow' : 'other';
  }
  function shortDay(dateStr) {
    var d = new Date(dateStr + 'T12:00:00');
    if (isNaN(d)) return dateStr;
    return DOW[d.getDay()].charAt(0).toUpperCase() + DOW[d.getDay()].slice(1) + ', ' + d.getDate() + ' ' + MONTHS[d.getMonth()];
  }
  function minutesUntil(dateStr, hhmmStr) {
    try {
      var today = minskDate();
      var nowM = new Date();
      var parts = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(nowM).split(':');
      var nowMin = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
      var sp = String(hhmmStr || '').split(':');
      var startMin = parseInt(sp[0], 10) * 60 + parseInt(sp[1] || '0', 10);
      var dayDiff = Math.round((new Date(dateStr + 'T12:00:00') - new Date(today + 'T12:00:00')) / 86400000);
      return dayDiff * 1440 + (startMin - nowMin);
    } catch (e) { return null; }
  }
  function formatPrice(minor, currency) {
    if (minor == null || minor === '' || isNaN(Number(minor))) return '';
    var major = Number(minor) / 100;
    var num = Number.isInteger(major) ? String(major) : major.toFixed(2).replace('.', ',');
    return num + ' ' + (currency || 'BYN');
  }
  function trainerPhotoUrl(key) {
    return key ? '/api/public/photos/' + encodeURIComponent(key) : '';
  }

  /* ── Данные ──────────────────────────────────────────────── */
  function fetchBootstrap() {
    var early = window.__clientEarlyBootstrap;
    if (early && early.promise) return early.promise.then(function (r) { return r.json(); });
    var init = initData();
    if (!init) return Promise.reject(new Error('no init'));
    return fetch('/api/webapp/client/hub/bootstrap?init_data=' + encodeURIComponent(init), {
      headers: headersJson(), cache: 'no-store',
    }).then(function (r) { return r.ok ? r.json() : Promise.reject(new Error('bootstrap ' + r.status)); });
  }

  function home() { return (state.data && state.data.home) || {}; }
  function city() { return home().city || null; }
  function cityId() {
    var cs = (state.data && state.data.client_session) || {};
    return cs.city_id != null ? cs.city_id : (city() && city().id) || null;
  }

  /* Живая запись сегодня (не закончилась) → ближайшая будущая. */
  function topBooking(data) {
    var days = (data.bookings && data.bookings.days) || [];
    var today = minskDate();
    var nowMin = null;
    try {
      var parts = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date()).split(':');
      nowMin = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
    } catch (e) {}
    var todayRec = null, futureRec = null;
    for (var i = 0; i < days.length; i++) {
      var day = days[i];
      var list = day.bookings || [];
      for (var j = 0; j < list.length; j++) {
        var b = list[j];
        if (DEAD[String(b.status || '').toLowerCase()]) continue;
        if (day.date < today) continue;
        if (day.date === today) {
          var ep = String(b.end_time || '23:59').split(':');
          var endMin = parseInt(ep[0], 10) * 60 + parseInt(ep[1] || '0', 10);
          if (!todayRec && (nowMin === null || endMin > nowMin)) todayRec = { date: day.date, b: b };
          continue; // «ближайшая будущая» — другой день, сегодняшние уже прошли или выиграли
        }
        if (!futureRec || day.date < futureRec.date ||
            (day.date === futureRec.date && hhmm(b.start_time) < hhmm(futureRec.b.start_time))) {
          futureRec = { date: day.date, b: b };
        }
      }
    }
    return todayRec || futureRec;
  }

  function activePass(data) {
    var passes = data.passes || [];
    for (var i = 0; i < passes.length; i++) {
      var p = passes[i];
      if (p.status === 'active' && !p.is_expired && Number(p.sessions_remaining) > 0) return p;
    }
    return null;
  }
  function passForTrainer(data, trainerId) {
    var passes = data.passes || [];
    for (var i = 0; i < passes.length; i++) {
      var p = passes[i];
      if (p.trainer_id != null && String(p.trainer_id) === String(trainerId) && p.status === 'active' && !p.is_expired) return p;
    }
    return null;
  }

  /* Ближайший сеанс льда: rail → city.upcoming → ice_teaser. */
  function nearestIce(data) {
    var rail = home().ice_rail;
    if (rail && rail.windows) {
      for (var i = 0; i < rail.windows.length; i++) {
        var w = rail.windows[i];
        for (var j = 0; j < (w.arenas || []).length; j++) {
          var a = w.arenas[j];
          var t0 = (a.times || [])[0];
          if (t0) {
            return {
              arena_id: a.arena_id, name: a.name, photo: a.photo,
              time: t0.time, end: t0.end, session_id: t0.session_id,
              minutes_until: t0.minutes_until, href: t0.href || a.href,
              price: a.price, window: w.key, invite_url: t0.invite_url,
            };
          }
        }
      }
    }
    var c = city();
    var ups = (c && c.upcoming) || [];
    if (ups.length) {
      var u = ups[0];
      return {
        arena_id: u.arena_id, name: u.place, photo: u.photo, time: u.time, end: '',
        session_id: u.session_id, minutes_until: u.minutes_until, href: u.href,
        price: u.price, window: u.day === 'завтра' ? 'tomorrow' : 'today', invite_url: u.invite_url,
      };
    }
    var ice = data.ice_teaser;
    if (ice && ice.sessions && ice.sessions.length) {
      var s = ice.sessions[0];
      return {
        arena_id: s.arena_id, name: s.arena_name,
        photo: { card: ice.card || ice.thumb || null, thumb: ice.thumb || null },
        time: hhmm(s.starts_at_local), end: '',
        session_id: s.session_id, minutes_until: null,
        href: 'arena?ref=' + s.arena_id + '&s=' + s.session_id,
        price: formatPrice(s.price_adult_minor, s.currency_code), window: 'today',
      };
    }
    return null;
  }

  /* ── Шапка ───────────────────────────────────────────────── */
  var HERO_MAX_TRIES = 4;
  function heroCache(photo, cityName) {
    try {
      localStorage.setItem('hv2_hero_' + (window.__hv2Uid || '0'), JSON.stringify({ photo: photo || '', city: cityName || '' }));
    } catch (e) {}
  }
  function armHero(urls) {
    var img = els.heroImg;
    urls = (urls || []).filter(Boolean).slice(0, HERO_MAX_TRIES);
    if (!urls.length) { img.hidden = true; els.hero.classList.remove('hv2-hero--photo'); return; }
    var i = 0;
    function next() {
      if (i >= urls.length) { img.hidden = true; els.hero.classList.remove('hv2-hero--photo'); heroCache('', (city() || {}).name || ''); return; }
      var probe = new Image();
      if (i === 0) probe.fetchPriority = 'high';
      probe.onload = function () {
        if (!probe.naturalWidth) { i++; next(); return; }
        if (img.getAttribute('src') !== urls[i]) img.src = urls[i];
        img.hidden = false;
        els.hero.classList.add('hv2-hero--photo');
        heroCache(urls[i], (city() || {}).name || '');
      };
      probe.onerror = function () { i++; next(); };
      probe.src = urls[i];
    }
    next();
  }
  function renderHero(top) {
    var c = city();
    var u = tgUser();
    if (c && c.name) els.cityLabel.textContent = c.name;
    else els.cityLabel.textContent = 'Город';
    var heroUrls = [];
    if (c && c.hero_photos && c.hero_photos.length) heroUrls = c.hero_photos.map(function (p) { return p && (p.hero || p.card || p.thumb); });
    if (!heroUrls.length && c && c.hero_photo) heroUrls = [c.hero_photo.hero || c.hero_photo.card || c.hero_photo.thumb];
    if (!heroUrls.length) {
      var pick = (home().city_pick || [])[0];
      if (pick && pick.photo) heroUrls = [pick.photo.hero || pick.photo.card || pick.photo.thumb];
    }
    /* Герой и фото-карточка ниже не должны повторяться: тот же кадр — в конец очереди. */
    var topPhoto = state.topPhoto;
    if (topPhoto && heroUrls.length > 1 && heroUrls.indexOf(topPhoto) === 0) {
      heroUrls = heroUrls.slice(1).concat(heroUrls[0]);
    }
    armHero(heroUrls);
    els.dateEl.textContent = dateLine();
    var title;
    if (top === 'citypick') {
      els.dateEl.textContent = 'Glide';
      title = 'Где вы катаетесь?';
    } else if (top === 'onice') {
      var oi = home().on_ice || {};
      title = 'Ты на катке?';
      try {
        var hm = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date());
        els.dateEl.textContent += ' · ' + hm;
      } catch (e) {}
    } else if (top === 'newbie') {
      title = ((c && c.name) || 'Город') + ' на льду';
    } else if (top === 'onerink') {
      /* TASK-447: «Пинск · один каток». */
      els.dateEl.textContent = ((c && c.name) || 'Город') + ' · один каток';
      var u2 = tgUser();
      title = greeting() + (u2 && u2.first_name ? ', ' + u2.first_name : '');
    } else if (top === 'iceend') {
      /* TASK-447: «Гомель · 23:10» — время города рядом с именем. */
      try {
        var hm2 = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date());
        els.dateEl.textContent = ((c && c.name) || 'Город') + ' · ' + hm2;
      } catch (e) {}
      var u3 = tgUser();
      title = greeting() + (u3 && u3.first_name ? ', ' + u3.first_name : '');
    } else if (top === 'return') {
      var u4 = tgUser();
      title = 'С возвращением' + (u4 && u4.first_name ? ', ' + u4.first_name : '');
    } else if (top === 'kkmatch') {
      var kit = kkTodayItem();
      var km = (kit && kit.hockey && kit.hockey.match) || {};
      var hn = (km.home && (km.home.name || km.home.short)) || '';
      var an = (km.away && (km.away.name || km.away.short)) || '';
      title = hn && an ? hn + ' — ' + an : 'Кто кого';
      try {
        var tm2 = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(km.starts_at));
        els.dateEl.textContent = 'Сегодня · ' + tm2 + (km.arena ? ' · ' + km.arena : '');
      } catch (e) {}
    } else {
      var name = u && u.first_name ? ', ' + u.first_name : '';
      title = greeting() + name;
    }
    els.title.textContent = title;
    /* Аватар: если переключатель профилей пуст (один профиль) — своё лицо или первая буква. */
    var mount = $('clientProfileSwitcherMount');
    var switcherEmpty = !mount || !mount.children.length;
    if (switcherEmpty && u) {
      var img = $('hv2AvaImg');
      var letter = $('hv2AvaLetter');
      letter.textContent = (u.first_name || 'Я').charAt(0).toUpperCase();
      if (u.photo_url) {
        letter.hidden = true;
        img.onerror = function () { img.hidden = true; letter.hidden = false; };
        img.src = u.photo_url; img.hidden = false;
      } else { img.hidden = true; letter.hidden = false; }
      els.ava.hidden = false;
    }
  }

  /* ── Верхняя карточка ────────────────────────────────────── */
  function chipStatus(rec) {
    var b = rec.b;
    if (String(b.status || '').toLowerCase() === 'pending') {
      return { cls: 'hv2-chip--yellow', text: 'ждёт тренера', pending: true };
    }
    var mu = minutesUntil(rec.date, b.start_time);
    var word = dayWord(rec.date);
    if (word === 'today' && mu !== null && mu <= 180) {
      var u = fmtUntilCap(mu);
      return u
        ? { cls: '', dot: true, text: u }
        : { cls: '', dot: true, text: 'Идёт' };
    }
    if (word === 'today') return { cls: '', dot: true, text: 'Сегодня' };
    if (word === 'tomorrow') return { cls: '', dot: true, text: 'Завтра' };
    return { cls: 'hv2-chip--gray', text: shortDay(rec.date) };
  }
  var ICON_ROUTE = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="19" r="2.4"/><circle cx="18" cy="5" r="2.4"/><path d="M8.4 19h5.1a3.5 3.5 0 0 0 0-7h-3a3.5 3.5 0 0 1 0-7h5.1"/></svg>';
  var ICON_CHAT = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5c-1.5 0-2.9-.35-4.1-1L3 20l1.1-5.1A8.5 8.5 0 1 1 21 11.5Z"/></svg>';

  function ticketHtml(rec) {
    var b = rec.b;
    var st = chipStatus(rec);
    var cp = childProfile();
    if (cp && cp.name) {
      /* TASK-447: профиль ребёнка — оранжевый чип «Миша · завтра». */
      var word = dayWord(rec.date);
      var wd = word === 'today' ? 'сегодня' : word === 'tomorrow' ? 'завтра' : shortDay(rec.date);
      st = { cls: 'hv2-chip--orange', dot: true, text: cp.name + ' · ' + wd };
    }
    var pass = passForTrainer(state.data, b.trainer_id);
    var pp = (home().place_photos || {})[String(b.arena_id)] || {};
    var thumb = s3On() ? (pp.thumb || pp.card) : (pp.card || pp.thumb);
    var face = b.trainer_list_photo_key
      ? '<img class="hv2-ticket__face" src="' + esc(trainerPhotoUrl(b.trainer_list_photo_key)) + '" alt="">'
      : '<span class="hv2-ticket__face">' + esc(((b.trainer_name || 'Т').charAt(0)).toUpperCase()) + '</span>';
    var acts = '';
    if (b.trainer_telegram_username) {
      acts += '<button type="button" class="hv2-rbtn ga-press" data-act="map" data-href="https://t.me/' + esc(b.trainer_telegram_username) + '" aria-label="Написать тренеру">' + ICON_CHAT + '</button>';
    }
    if (!st.pending) {
      if (b.map_link) acts += '<button type="button" class="hv2-rbtn hv2-rbtn--ink ga-press" data-act="map" data-href="' + esc(b.map_link) + '" aria-label="Маршрут">' + ICON_ROUTE + '</button>';
      else if (b.arena_id) acts += '<button type="button" class="hv2-rbtn hv2-rbtn--ink ga-press" data-act="nav" data-path="arena?ref=' + encodeURIComponent(b.arena_id) + '" aria-label="Маршрут">' + ICON_ROUTE + '</button>';
    }
    var passLine = '';
    if (pass && Number(pass.sessions_total) <= 12) {
      var dots = '';
      for (var i = 0; i < Number(pass.sessions_total); i++) dots += '<i class="' + (i < Number(pass.sessions_remaining) ? 'on' : '') + '"></i>';
      passLine = '<div class="hv2-ticket__passline"><span>Абонемент' + (cp && cp.name ? ' ' + esc(childGen(cp.name)) : '') + ' · осталось ' + esc(pass.sessions_remaining) + ' из ' + esc(pass.sessions_total) + '</span><span class="hv2-dots">' + dots + '</span></div>';
    } else if (pass) {
      passLine = '<div class="hv2-ticket__passline"><span>Абонемент' + (cp && cp.name ? ' ' + esc(childGen(cp.name)) : '') + ' · осталось ' + esc(pass.sessions_remaining) + ' из ' + esc(pass.sessions_total) + '</span></div>';
    }
    return '<article class="hv2-card hv2-ticket" data-act="nav" data-path="client-bookings">' +
      '<div class="hv2-ticket__head">' +
        '<span class="hv2-chip ' + (st.cls || '') + '">' + (st.dot ? '<span class="hv2-chip__dot"></span>' : '') + esc(st.text) + '</span>' +
        (thumb ? '<img class="hv2-ticket__thumb" src="' + esc(thumb) + '" alt="">' : '') +
      '</div>' +
      '<div class="hv2-ticket__time">' + esc(hhmm(b.start_time)) + '</div>' +
      '<div class="hv2-ticket__name">' + esc(b.service_name || 'Занятие') + '</div>' +
      '<div class="hv2-ticket__sub">до ' + esc(hhmm(b.end_time)) + ' · ' + esc(b.arena_name || b.place_display || 'Каток') + '</div>' +
      '<div class="hv2-ticket__perf"></div>' +
      '<div class="hv2-ticket__trainer">' + face +
        '<div><div class="hv2-ticket__tname">' + esc(b.trainer_name || 'Тренер') + '</div>' +
        '<div class="hv2-ticket__trole">' + esc(cp && cp.name ? 'тренер ' + childGen(cp.name) : 'ваш тренер') + '</div></div>' +
        '<div class="hv2-ticket__acts">' + acts + '</div>' +
      '</div>' + passLine +
    '</article>';
  }

  function slotsInner(trainerId) {
    var list = state.slots[trainerId];
    if (list == null) {
      return '<span class="hv2-slot hv2-slot--skel"></span><span class="hv2-slot hv2-slot--skel"></span>';
    }
    return list.slice(0, 4).map(function (s) {
      var d = s.slot_date ? new Date(String(s.slot_date).slice(0, 10) + 'T12:00:00') : null;
      var day = d && !isNaN(d) ? DOW[d.getDay()].toUpperCase() + ' ' + d.getDate() : '';
      return '<a class="hv2-slot ga-press" href="' + esc(slotHref(trainerId, s)) + '">' +
        '<span class="hv2-slot__day">' + esc(day) + '</span><span class="hv2-slot__time">' + esc(hhmm(s.start_time)) + '</span></a>';
    }).join('') + '<a class="hv2-slot hv2-slot--all ga-press" href="' + esc(allSlotsHref(trainerId)) + '">Все</a>';
  }
  function slotsBlockHtml(trainerId) {
    return '<div id="hv2SlotsWrap"><div class="hv2-slots__title">Свободные окна</div>' +
      '<div class="hv2-slots" id="hv2Slots">' + slotsInner(trainerId) + '</div></div>';
  }
  function catalogSvcQuery() {
    var cs = (state.data && state.data.client_session) || {};
    return cs.primary_catalog_service_id ? '&service_id=' + encodeURIComponent(cs.primary_catalog_service_id) : '';
  }
  function allSlotsHref(trainerId) {
    return 'catalog?trainer_id=' + encodeURIComponent(trainerId) + '&action=book&from=hub' + catalogSvcQuery();
  }
  function slotHref(trainerId, s) {
    var parts = ['catalog?trainer_id=' + encodeURIComponent(trainerId), 'slot_id=' + encodeURIComponent(s.id), 'from=hub'];
    if (s.service_id) parts.splice(1, 0, 'service_id=' + encodeURIComponent(s.service_id));
    else if (catalogSvcQuery()) parts.splice(1, 0, catalogSvcQuery().slice(1));
    if (s.arena_id) parts.splice(parts.length - 1, 0, 'arena_id=' + encodeURIComponent(s.arena_id));
    return parts.join('&');
  }

  function passCardHtml(p) {
    var total = Math.max(1, Number(p.sessions_total) || 1);
    var left = Number(p.sessions_remaining) || 0;
    var C = 2 * Math.PI * 34;
    var pct = Math.max(0, Math.min(1, left / total));
    var exp = '';
    if (p.expires_at) {
      var d = new Date(p.expires_at);
      if (!isNaN(d)) exp = ' · действует до ' + d.getDate() + ' ' + MONTHS[d.getMonth()];
    }
    state.yellowUsed = true;
    return '<article class="hv2-card hv2-pass">' +
      '<div class="hv2-pass__head"><div class="hv2-pass__body">' +
        '<span class="hv2-chip hv2-chip--gray">Абонемент</span>' +
        '<div class="hv2-pass__title">Осталось ' + left + ' ' + plural(left, 'занятие', 'занятия', 'занятий') + '</div>' +
        '<div class="hv2-pass__sub">' + esc(p.trainer_name || 'Тренер') + esc(exp) + '</div>' +
      '</div>' +
      '<div class="hv2-ring"><svg width="76" height="76" viewBox="0 0 76 76">' +
        '<circle cx="38" cy="38" r="34" fill="none" stroke="#e7ebee" stroke-width="8"/>' +
        '<circle cx="38" cy="38" r="34" fill="none" stroke="#0a6f73" stroke-width="8" stroke-linecap="round" stroke-dasharray="' + (pct * C).toFixed(1) + ' ' + C.toFixed(1) + '"/>' +
      '</svg><div class="hv2-ring__num"><b>' + left + '</b><span>из ' + total + '</span></div></div>' +
      '</div>' +
      slotsBlockHtml(p.trainer_id) +
      '<button type="button" class="hv2-btn hv2-btn--yellow ga-press" data-act="book" data-path="' + esc(allSlotsHref(p.trainer_id)) + '">Записаться</button>' +
    '</article>';
  }

  function coachCardHtml(cs) {
    var tid = cs.primary_trainer_id;
    var name = cs.primary_trainer_name || 'Тренер';
    var face = cs.primary_trainer_list_photo_key
      ? '<img class="hv2-coach__face" src="' + esc(trainerPhotoUrl(cs.primary_trainer_list_photo_key)) + '" alt="">'
      : '<span class="hv2-coach__face">' + esc(name.charAt(0).toUpperCase()) + '</span>';
    state.yellowUsed = true;
    return '<article class="hv2-card hv2-coach">' +
      '<div class="hv2-coach__head">' + face +
        '<div><div class="hv2-coach__name">' + esc(name) + '</div><div class="hv2-coach__role">ваш тренер</div></div>' +
      '</div>' +
      slotsBlockHtml(tid) +
      '<button type="button" class="hv2-btn hv2-btn--yellow ga-press" data-act="book" data-path="' + esc(allSlotsHref(tid)) + '">Записаться</button>' +
    '</article>';
  }

  function photoCardHtml(found) {
    var img = found.photo && (found.photo.card || found.photo.hero || found.photo.thumb);
    var mu = found.minutes_until;
    var chip;
    var unt = fmtUntil(mu);
    if (unt) chip = 'Ближайший · ' + unt;
    else chip = found.window === 'tomorrow' ? 'Ближайший · завтра' : 'Ближайший · сегодня';
    var bits = [];
    if (found.end) bits.push('до ' + found.end);
    if (found.price) bits.push(found.price);
    var share = found.invite_url
      ? '<button type="button" class="hv2-btn hv2-btn--soft ga-press" data-act="share" data-url="' + esc(found.invite_url) + '">Позвать друзей</button>'
      : '';
    var route = '<button type="button" class="hv2-btn hv2-btn--ink ga-press" data-act="nav" data-path="' + esc(found.href || 'ice') + '">' +
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="6" cy="19" r="2.4"/><circle cx="18" cy="5" r="2.4"/><path d="M8.4 19h5.1a3.5 3.5 0 0 0 0-7h-3a3.5 3.5 0 0 1 0-7h5.1"/></svg> Маршрут</button>';
    return '<article class="hv2-pcard" data-act="nav" data-path="' + esc(found.href || 'ice') + '">' +
      (img ? '<img class="hv2-pcard__img" src="' + esc(img) + '" alt="">' : '') +
      '<span class="hv2-pcard__shade"></span>' +
      '<span class="hv2-pcard__chip"><span class="hv2-chip__dot"></span>' + esc(chip) + '</span>' +
      '<span class="hv2-pcard__in">' +
        '<span class="hv2-pcard__time">' + esc(found.time || '') + '</span>' +
        '<span class="hv2-pcard__place">' + esc(found.name || '') + '</span>' +
        (bits.length ? '<span class="hv2-pcard__sub">' + esc(bits.join(' · ')) + '</span>' : '') +
      '</span></article>' +
      '<div class="hv2-pcard__btns">' + route + share + '</div>';
  }

  /* ── TASK-446: состояние «Ты на катке?» (флаг s5, ключ home.on_ice) ──── */
  function loadCheckinAssets() {
    if (window.GlideCheckin || state.ciAssets) return;
    state.ciAssets = true;
    var v = (document.querySelector('link[href*="home-v2.css"]') || {}).href || '';
    var m = v.match(/[?&]v=([^&]+)/);
    var q = m ? '?v=' + m[1] : '';
    var css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = 'checkin-sheet.css' + q;
    document.head.appendChild(css);
    var js = document.createElement('script');
    js.src = 'checkin-sheet.js' + q;
    js.defer = true;
    document.head.appendChild(js);
  }

  function fmtLeft(min) {
    if (min == null) return '';
    var h = Math.floor(min / 60), m = min % 60;
    if (h && m) return h + ' ч ' + m + ' мин';
    if (h) return h + ' ч';
    return m + ' мин';
  }
  function loadBarsHtml(live) {
    if (!live) return '';
    var lv = live.level;
    var bars = '';
    for (var i = 1; i <= 3; i++) bars += '<i class="' + (i <= lv ? 'on' : '') + '"></i>';
    var word = { 1: 'свободно', 2: 'в меру', 3: 'людно' }[lv] || '';
    return '<span class="hv2-onice__load"><span class="hv2-onice__bars">' + bars + '</span>сейчас ' + esc(word) +
      ' · ' + live.count + ' ' + plural(live.count, 'отметка', 'отметки', 'отметок') + '</span>';
  }
  function weekPillsHtml(streak) {
    var out = '';
    for (var i = 0; i < 4; i++) out += '<i class="' + (i < Math.min(4, streak) ? 'on' : '') + '"></i>';
    return '<span class="hv2-weeks">' + out + '</span>';
  }
  function onIceHtml(o) {
    var img = o.photo && (o.photo.card || o.photo.hero || o.photo.thumb);
    var live = o.live;
    var bits = ['до ' + o.ends_local];
    var liveHtml = loadBarsHtml(live);
    var checked = !!o.checked_in;
    var mainBtn = checked
      ? '<button type="button" class="hv2-btn hv2-btn--soft ga-press" data-act="checkin">Отмечено · ' + o.season_days + '-й раз</button>'
      : '<button type="button" class="hv2-btn hv2-btn--yellow ga-press" data-act="checkin">✓ Я здесь</button>';
    state.yellowUsed = !checked;
    var share = o.invite_url
      ? '<button type="button" class="hv2-btn hv2-btn--soft ga-press" data-act="share" data-url="' + esc(o.invite_url) + '">Позвать сюда</button>'
      : '';
    var stats =
      '<article class="hv2-card hv2-onice__stats">' +
        '<div class="hv2-onice__row">' +
          '<svg class="hv2-onice__ic" width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M12 3c2 4-3 5-3 9a3 3 0 006 0c0-2-1-3-1-3s4 2 4 6a6 6 0 11-12 0c0-6 6-8 6-12z" fill="currentColor"/></svg>' +
          '<div><div class="hv2-onice__t">Серия: ' + o.streak_weeks + ' ' + plural(o.streak_weeks, 'неделя', 'недели', 'недель') + ' подряд</div>' +
          '<div class="hv2-onice__s">' + (o.has_this_week ? 'Отметка этой недели засчитана' : 'Отметься сегодня — будет ' + (o.streak_weeks + 1) + '-я') + '</div></div>' +
          weekPillsHtml(o.streak_weeks) +
        '</div>' +
        '<div class="hv2-onice__row">' +
          '<svg class="hv2-onice__ic" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M12 4v4m0 0-2 2m2-2 2 2M4 20l2-9h12l2 9z"/></svg>' +
          '<div><div class="hv2-onice__t">На льду ' + o.season_days + ' ' + plural(o.season_days, 'раз', 'раза', 'раз') + ' за сезон</div>' +
          '<div class="hv2-onice__s">' + (checked ? 'Отметка засчитана' : 'Сегодня будет ' + (o.season_days + 1) + '-й') + '</div></div>' +
        '</div>' +
      '</article>';
    return '<article class="hv2-pcard" data-act="nav" data-path="arena?ref=' + o.arena_id + '&s=' + o.session_id + '">' +
      (img ? '<img class="hv2-pcard__img" src="' + esc(img) + '" alt="">' : '') +
      '<span class="hv2-pcard__shade"></span>' +
      '<span class="hv2-pcard__chip"><span class="hv2-chip__dot hv2-chip__dot--pulse"></span>Идёт сеанс · ещё ' + esc(fmtLeft(o.minutes_left)) + '</span>' +
      '<span class="hv2-pcard__in">' +
        '<span class="hv2-pcard__time">' + esc(o.starts_local || '') + '</span>' +
        '<span class="hv2-pcard__place">' + esc(o.arena_name || '') + '</span>' +
        '<span class="hv2-pcard__sub">' + esc(bits.join(' · ')) + (liveHtml ? ' · ' + liveHtml : '') + '</span>' +
      '</span></article>' +
      '<div class="hv2-pcard__btns">' + mainBtn + share + '</div>' + stats;
  }

  function openCheckinSheet() {
    var o = home().on_ice;
    if (!o) return;
    var go = function () {
      if (!window.GlideCheckin) return;
      window.GlideCheckin.open({
        session_id: o.session_id,
        arena_name: o.arena_name,
        checkin_id: o.checked_in ? o.checkin_id : null,
        load_level: o.load_level,
        season_days: o.checked_in ? o.season_days : null,
        streak_weeks: o.streak_weeks,
        onLive: function (live) { o.live = live; renderAll(); },
        onDone: function () {
          /* После отметки перечитываем состояние — кнопка и цифры свежие. */
          boot();
        },
      });
    };
    if (window.GlideCheckin) go();
    else {
      loadCheckinAssets();
      var tries = 0;
      var t = setInterval(function () {
        tries++;
        if (window.GlideCheckin) { clearInterval(t); go(); }
        else if (tries > 40) clearInterval(t);
      }, 50);
    }
  }

  function cityPickHtml() {
    return '<article class="hv2-card hv2-citypick" id="hv2CityPick">' +
      '<div id="hv2CityPickList"><div style="padding:20px;color:var(--muted);font-size:15px">Загрузка городов…</div></div>' +
      '<button type="button" class="hv2-cprow hv2-cprow--geo ga-press" id="hv2CityPickGeo">' +
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="2.2"/><path d="M12 1.5v4M12 18.5v4M1.5 12h4M18.5 12h4"/></svg>' +
        'Определить по геолокации</button>' +
    '</article>';
  }
  function cityPickRows(items) {
    return items.slice(0, 6).map(function (c) {
      var sub = [];
      var ts = Number(c.today_sessions != null ? c.today_sessions : c.skate_count) || 0;
      var tr = Number(c.trainer_count) || 0;
      if (ts) sub.push(ts + ' ' + plural(ts, 'сеанс', 'сеанса', 'сеансов') + ' сегодня');
      if (tr) sub.push(tr + ' ' + plural(tr, 'тренер', 'тренера', 'тренеров'));
      var photo = c.photo && (s3On() ? (c.photo.thumb || c.photo.card) : (c.photo.card || c.photo.thumb));
      var img = photo
        ? '<img class="hv2-cprow__img" src="' + esc(photo) + '" alt="" loading="lazy" decoding="async">'
        : '<span class="hv2-cprow__img">' + esc(String(c.name || '?').charAt(0).toUpperCase()) + '</span>';
      return '<button type="button" class="hv2-cprow ga-press" data-city="' + c.id + '">' + img +
        '<span><span class="hv2-cprow__name">' + esc(c.name) + '</span><br>' +
        '<span class="hv2-cprow__sub">' + sub.map(function (p) { return '<span class="hv2-cprow__part">' + esc(p) + '</span>'; }).join(' · ') + '</span></span>' +
        '<svg class="hv2-cprow__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>' +
      '</button>';
    }).join('');
  }
  function bindCityPick() {
    var geo = $('hv2CityPickGeo');
    if (geo) geo.addEventListener('click', function () { haptic('select'); geoPick(); });
    var host = $('hv2CityPickList');
    if (!host) return;
    var items = home().city_pick;
    if (items && items.length) { host.innerHTML = cityPickRows(items); }
    else {
      fetch('/api/public/ice/cities', { cache: 'no-store' })
        .then(function (r) { return r.ok ? r.json() : { items: [] }; })
        .then(function (d) {
          state.cities = (d && d.items) || [];
          host.innerHTML = cityPickRows(state.cities);
        })
        .catch(function () { host.innerHTML = '<div style="padding:20px;color:var(--muted);font-size:15px">Не удалось загрузить города.</div>'; });
    }
  }

  /* ── «Лёд в городе» ──────────────────────────────────────── */
  function railWindows() {
    var rail = home().ice_rail;
    if (rail && rail.windows) return rail.windows;
    var c = city();
    if (c && c.upcoming && c.upcoming.length) {
      /* Старый ответ без rail: строим одно окно из upcoming. */
      var arenas = c.upcoming.map(function (u) {
        return {
          arena_id: u.arena_id, name: u.place, href: u.href, photo: u.photo, price: u.price || '',
          times: [{ time: u.badge || u.time, session_id: u.session_id, minutes_until: u.minutes_until, href: u.href }],
        };
      });
      return [{ key: 'today', label: 'Сегодня', count: arenas.length, href: c.upcoming_href || 'ice', arenas: arenas }];
    }
    return null;
  }
  function railArenaHtml(a, wkey) {
    var s3 = s3On();
    var photo = a.photo && ((s3 ? a.photo.thumb : a.photo.card) || a.photo.card || a.photo.thumb);
    var t0 = (a.times || [])[0] || {};
    var chip = fmtUntilCap(t0.minutes_until) || (wkey === 'tomorrow' ? 'Завтра' : wkey === 'weekend' ? 'На выходных' : 'Сегодня');
    var chips = (a.times || []).slice(0, 3).map(function (t) {
      return '<a class="hv2-rcard__tchip ga-press" href="' + esc(t.href || a.href || 'ice') + '" data-act="nav" data-path="' + esc(t.href || a.href || 'ice') + '">' + esc(t.time) + '</a>';
    }).join('');
    return '<div class="hv2-rcard ga-press" role="link" tabindex="0" data-act="nav" data-path="' + esc(a.href || 'ice') + '">' +
      '<span class="hv2-rcard__imgwrap">' +
        (photo ? '<img class="hv2-rcard__img" src="' + esc(photo) + '" alt="" loading="lazy" decoding="async">' : '') +
        (chip ? '<span class="hv2-rcard__chip">' + esc(chip) + '</span>' : '') +
      '</span>' +
      '<span class="hv2-rcard__name">' + esc(a.name) + '</span>' +
      (chips ? '<span class="hv2-rcard__chips">' + chips + '</span>' : '') +
      (a.price ? '<span class="hv2-rcard__sub">' + esc(a.price) + '</span>' : '') +
    '</div>';
  }
  var EMPTY_LINES = { today: 'Сегодня лёд закончился', tomorrow: 'Завтра пока пусто', weekend: 'На выходных пока пусто' };
  function renderRail(w) {
    var host = els.rail;
    var arenas = (w.arenas || []);
    if (state.dedupSession) {
      arenas = arenas.map(function (a) {
        var ts = (a.times || []).filter(function (t) { return String(t.session_id) !== String(state.dedupSession); });
        return ts.length ? Object.assign({}, a, { times: ts }) : null;
      }).filter(Boolean);
    }
    if (!arenas.length) {
      host.innerHTML = '<div class="hv2-rail__empty">' + esc(EMPTY_LINES[w.key] || 'Пока пусто') +
        (w.href ? ' · <a href="' + esc(w.href) + '" data-hv2-nav>Весь день</a>' : '') + '</div>';
      return;
    }
    /* TASK-447: ≥3 — rail, 2 — две колонки, 1 — широкая карточка. */
    host.classList.toggle('hv2-rail--grid2', arenas.length === 2);
    host.classList.toggle('hv2-rail--one', arenas.length === 1);
    setBlockHtml(host, arenas.map(function (a) { return railArenaHtml(a, w.key); }).join(''), state.quiet);
  }
  function renderIce() {
    var windows = railWindows();
    var c = city();
    /* TASK-447: «На неделе» внутри top заменяет rail (один каток / лёд закончился с данными /
       межсезонье) — секцию скрываем. */
    if (state.topState === 'onerink' || state.topState === 'offseason' ||
        (state.topState === 'iceend' && home().week)) { els.iceSec.hidden = true; return; }
    if (!windows || !cityId()) { els.iceSec.hidden = true; return; }
    var title = 'Лёд в ' + (c && c.name_in ? c.name_in : 'городе');
    if (c && c.name_in == null) title = 'Лёд в городе';
    els.iceTitle.textContent = title;
    var defIdx = windows.findIndex(function (w) { return (w.arenas || []).length; });
    if (defIdx < 0) defIdx = 0;
    if (state.railTab == null) state.railTab = windows[defIdx].key;
    setIceMore(windows.find(function (w) { return w.key === state.railTab; }) || windows[0]);
    els.tabs.innerHTML = windows.map(function (w) {
      return '<button type="button" role="tab" class="hv2-tab ga-press' +
        (w.key === state.railTab ? ' hv2-tab--on' : '') + (w.count ? '' : ' hv2-tab--empty') +
        '" data-wkey="' + esc(w.key) + '">' + esc(w.label) + '<sup>' + esc(w.count) + '</sup></button>';
    }).join('') + '<span class="hv2-tabs__ink" id="hv2TabsInk"></span>';
    els.iceSec.hidden = false;
    positionInk();
    var w = windows.find(function (x) { return x.key === state.railTab; }) || windows[0];
    renderRail(w);
    els.tabs.querySelectorAll('.hv2-tab').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.getAttribute('data-wkey') === state.railTab) return;
        state.railTab = btn.getAttribute('data-wkey');
        haptic('select');
        els.tabs.querySelectorAll('.hv2-tab').forEach(function (b2) { b2.classList.toggle('hv2-tab--on', b2 === btn); });
        positionInk();
        els.rail.classList.add('hv2-rail--fade');
        setTimeout(function () {
          var cur = railWindows().find(function (x) { return x.key === state.railTab; });
          if (cur) { renderRail(cur); setIceMore(cur); }
          els.rail.classList.remove('hv2-rail--fade');
        }, 180);
      });
    });
  }
  /* «Все {count}» ведёт на окно активной вкладки, а не всегда на «сегодня». */
  function setIceMore(w) {
    els.iceMore.setAttribute('href', (w && w.href) || 'ice');
    els.iceMore.textContent = 'Все' + (w && w.count ? ' ' + w.count : '');
  }
  function positionInk() {
    var ink = $('hv2TabsInk');
    var on = els.tabs && els.tabs.querySelector('.hv2-tab--on');
    if (!ink || !on) return;
    ink.style.width = on.offsetWidth + 'px';
    ink.style.transform = 'translateX(' + on.offsetLeft + 'px)';
  }

  /* ── «Матчи» ─────────────────────────────────────────────── */
  function teamLogo(t, dark) {
    if (t && t.logo) return '<img class="hv2-mcard__logo" src="' + esc(t.logo) + '" alt="" loading="lazy">';
    var bg = (t && t.color) || (dark ? 'rgba(255,255,255,.25)' : '#6b7a86');
    return '<span class="hv2-mcard__logo" style="background:' + esc(bg) + '">' + esc(((t && (t.short || t.name)) || '?').slice(0, 3)) + '</span>';
  }
  function matchKicker(startsAt, live, sticker) {
    if (live) return 'ИДЁТ';
    var w = '';
    try {
      var d = new Date(startsAt);
      var day = dayWord(d.toISOString().slice(0, 10));
      var datePart = day === 'today' ? 'сегодня' : day === 'tomorrow' ? 'завтра'
        : new Intl.DateTimeFormat('ru-RU', { weekday: 'short', day: 'numeric', month: 'long', timeZone: TZ }).format(d);
      w = datePart + ' · ' + new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone: TZ }).format(d);
    } catch (e) { w = sticker || ''; }
    return (w || '').toUpperCase();
  }
  function kkCardHtml(item, yellowFree) {
    var h = item.hockey || {};
    var m = h.match || {};
    var href = h.event_href || 'kto-kogo';
    var kick = 'КТО КОГО' + (m.starts_at ? ' · ' + matchKicker(m.starts_at, false, '') : '');
    return '<a class="hv2-mcard hv2-mcard--kk ga-press" href="' + esc(href) + '">' +
      '<span class="hv2-mcard__kick">' + esc(kick) + '</span>' +
      '<span class="hv2-mcard__team">' + teamLogo(m.home, true) + '<span class="hv2-mcard__tname">' + esc((m.home && m.home.name) || '') + '</span></span>' +
      '<span class="hv2-mcard__team">' + teamLogo(m.away, true) + '<span class="hv2-mcard__tname">' + esc((m.away && m.away.name) || '') + '</span></span>' +
      '<span class="hv2-mcard__place">' + esc(m.arena || m.city || '') + '</span>' +
      '<span class="hv2-mcard__play' + (yellowFree ? ' hv2-mcard__play--yellow' : '') + '">Играть</span>' +
    '</a>';
  }
  function matchCardHtml(m) {
    var r = m.result;
    var kick = matchKicker(m.starts_at, m.live, m.sticker);
    if (r) kick = 'ИТОГ ' + r.home_score + ':' + r.away_score;
    return '<a class="hv2-mcard ga-press" href="' + esc(m.href || 'client-matches') + '">' +
      '<span class="hv2-mcard__kick">' + esc(kick) + '</span>' +
      '<span class="hv2-mcard__team">' + teamLogo(m.home) + '<span class="hv2-mcard__tname">' + esc((m.home && (m.home.name || m.home.short)) || '') + '</span></span>' +
      '<span class="hv2-mcard__team">' + teamLogo(m.away) + '<span class="hv2-mcard__tname">' + esc((m.away && (m.away.name || m.away.short)) || '') + '</span></span>' +
      '<span class="hv2-mcard__place">' + esc(m.arena || m.city || '') + '</span>' +
    '</a>';
  }
  function renderMatches() {
    if (state.topState === 'kkmatch') { els.matchSec.hidden = true; return; }
    var now = home().now;
    var feed = home().matches;
    var items = [], allHref = (feed && feed.all_href) || 'client-matches', count = (feed && feed.week_count) || 0;
    if (now && now.kind === 'feed') {
      items = (now.items || []).filter(function (it) { return it && it.kind !== 'more'; });
      var more = (now.items || []).find(function (it) { return it && it.kind === 'more'; });
      if (more) { allHref = more.href || allHref; count = more.count || count; }
    } else if (now && (now.kind === 'kk_before' || now.kind === 'kk_result' || now.kind === 'kk_month')) {
      items = [now];
    } else if (feed && feed.matches && feed.matches.length) {
      items = feed.matches;
    }
    if (!items.length) { els.matchSec.hidden = true; return; }
    els.matchSec.hidden = false;
    els.matchMore.setAttribute('href', allHref);
    els.matchMore.textContent = 'Все' + (count ? ' ' + count : '');
    var yellowFree = !state.yellowUsed;
    els.matches.innerHTML = items.map(function (it) {
      if (it.kind === 'kk_before' || it.kind === 'kk_result' || it.kind === 'kk_month') return kkCardHtml(it, yellowFree);
      return matchCardHtml(it);
    }).join('');
  }

  /* ── «Ещё в городе» ──────────────────────────────────────── */
  var TILE_ICONS = {
    ohm: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20 17 7l2-2.5a1.2 1.2 0 0 1 1.7 0l.8.8a1.2 1.2 0 0 1 0 1.7L19 9.5 6 22l-4-4Z"/><path d="m14 10 2 2"/></svg>',
    coach: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c1.5-4 4.5-6 7.5-6s6 2 7.5 6"/></svg>',
    service: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/><circle cx="12" cy="12" r="2.5"/></svg>',
    shop: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 8h14l-1.2 12a2 2 0 0 1-2 1.8H8.2a2 2 0 0 1-2-1.8L5 8Z"/><path d="M8.5 10V6.5a3.5 3.5 0 0 1 7 0V10"/></svg>',
  };
  var TILE_TITLES = { ohm: 'С клюшкой', coach: 'Тренеры', service: 'Заточка', shop: 'Магазины' };
  var TILE_ORDER = ['ohm', 'coach', 'service', 'shop'];
  function tileOrder() {
    return state.coachFirst ? ['coach', 'ohm', 'service', 'shop'] : TILE_ORDER;
  }
  function tileSub(n) {
    var line = String(n.line || '');
    var parts = line.split(' · ');
    if (n.key === 'ohm') {
      var tail = parts.length > 1 ? parts.slice(1).join(' · ') : parts[0];
      return tail.charAt(0).toUpperCase() + tail.slice(1);
    }
    if (n.key === 'service' || n.key === 'shop') {
      var open = parts.find(function (p) { return /открыт/i.test(p); });
      if (open) return open.charAt(0).toUpperCase() + open.slice(1);
      return parts[0];
    }
    return parts[0];
  }
  function renderMore() {
    var needs = (city() && city().needs) || [];
    var tiles = tileOrder().map(function (k) {
      var n = needs.find(function (x) { return x.key === k; });
      return n ? '<a class="hv2-tile ga-press" href="' + esc(n.href || 'ice') + '">' +
        '<span class="hv2-tile__icon">' + TILE_ICONS[k] + '</span>' +
        '<span class="hv2-tile__title">' + esc(TILE_TITLES[k]) + '</span>' +
        '<span class="hv2-tile__sub">' + esc(tileSub(n)) + '</span></a>' : '';
    }).filter(Boolean);
    if (!tiles.length) { els.moreSec.hidden = true; return; }
    els.moreSec.hidden = false;
    els.more.innerHTML = tiles.join('');
  }

  /* ── Слоты тренера (после первого кадра) ─────────────────── */
  function fetchSlots(trainerId) {
    if (!trainerId) return;
    fetch('/api/webapp/client/slots?trainer_id=' + encodeURIComponent(String(trainerId)), { headers: headersJson(), cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : { slots: [] }; })
      .then(function (d) {
        var list = (d.slots || []).filter(function (s) { return s && String(s.start_time || '').trim(); });
        list.sort(function (a, b) { return String(a.slot_date) + String(a.start_time) < String(b.slot_date) + String(b.start_time) ? -1 : 1; });
        state.slots[trainerId] = list;
        var wrap = $('hv2SlotsWrap');
        if (wrap) {
          if (!list.length) wrap.parentNode.removeChild(wrap);
          else $('hv2Slots').innerHTML = slotsInner(trainerId);
        }
      })
      .catch(function () { state.slots[trainerId] = []; });
  }

  /* ── Город: лист + геолокация ─────────────────────────────── */
  function openSheet() { els.sheet.hidden = false; loadCities(); }
  function closeSheet() { els.sheet.hidden = true; }
  function loadCities() {
    if (state.cities) { renderCityOpts(state.cities); return; }
    fetch('/api/public/ice/cities', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (d) { state.cities = (d && d.items) || []; renderCityOpts(state.cities); })
      .catch(function () { renderCityOpts([]); });
  }
  function citySheetLine(c) {
    var n = Number(c.skate_count) || 0;
    if (n > 0) return n + ' ' + plural(n, 'каток', 'катка', 'катков');
    var tr = Number(c.trainer_count) || 0;
    return tr > 0 ? tr + ' ' + plural(tr, 'тренер', 'тренера', 'тренеров') : '';
  }
  function renderCityOpts(cities) {
    var host = els.cityList;
    if (!cities.length) { host.innerHTML = '<div style="padding:16px 20px;color:var(--muted);font-size:15px">Не удалось загрузить города.</div>'; return; }
    host.innerHTML = cities.map(function (c) {
      return '<button type="button" class="hv2-cprow ga-press" data-city="' + c.id + '">' +
        '<span><span class="hv2-cprow__name">' + esc(c.name) + '</span><br>' +
        '<span class="hv2-cprow__sub">' + esc(citySheetLine(c)) + '</span></span>' +
        '<svg class="hv2-cprow__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></button>';
    }).join('');
  }
  function pickCity(id) {
    fetch('/api/webapp/client/session/catalog-filters', {
      method: 'PATCH', headers: headersJson(), body: JSON.stringify({ city_id: id }),
    }).then(function (r) {
      if (!r.ok) throw new Error('city ' + r.status);
      haptic('success');
      closeSheet();
      boot();
    }).catch(function () { haptic('error'); });
  }
  function geoPick() {
    var nav = navigator.geolocation;
    if (!nav) return;
    nav.getCurrentPosition(function (pos) {
      var lat = pos.coords.latitude, lon = pos.coords.longitude;
      var cities = state.cities || [];
      var best = null, bestD = 1e9;
      cities.forEach(function (c) {
        if (c.latitude == null || c.longitude == null) return;
        var d = (c.latitude - lat) * (c.latitude - lat) + (c.longitude - lon) * (c.longitude - lon);
        if (d < bestD) { bestD = d; best = c; }
      });
      if (best) pickCity(best.id);
      else if (cities.length) pickCity(cities[0].id);
    }, function () {}, { timeout: 8000, maximumAge: 300000 });
  }


  /* ── TASK-447: этап 2 — состояния главной и правила городов (флаг redesign_s2) ──── */
  function s2On() {
    var h = home();
    return h && ('variant' in h || 'profile' in h || 'kk_player' in h);
  }
  function childProfile() {
    var p = home().profile;
    return p && p.is_own === false ? p : null;
  }
  function childGen(name) {
    try {
      var g = window.RuPersonName && window.RuPersonName.inflectPersonName(name, '', 'gen');
      return g && g !== name ? g : name;
    } catch (e) { return name; }
  }
  function localMin() {
    try {
      var parts = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date()).split(':');
      return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
    } catch (e) { return null; }
  }

  /* ── TASK-448: этап 3 — скорость и переходы (флаг redesign_s3) ─────────── */
  /* Читаем флаг из кэша cw_ui_flags_v1 синхронно — как тема читает redesign_s1. */
  function s3On() {
    try {
      var u = tgUser();
      var uid = u && u.id != null ? String(u.id) : '';
      var c = JSON.parse(localStorage.getItem('cw_ui_flags_v1') || 'null');
      return !!(c && String(c.u) === uid && c.redesign_s3 === true);
    } catch (e) { return false; }
  }
  function screenCacheKey() {
    var u = tgUser();
    var uid = u && u.id != null ? String(u.id) : '0';
    return 'hv2_screen_v1:' + uid + ':' + (profileId() || 0);
  }
  function screenCacheRead() {
    try {
      var c = JSON.parse(localStorage.getItem(screenCacheKey()) || 'null');
      if (!c || c.v !== 1 || !c.data || typeof c.at !== 'number') return null;
      if (Date.now() - c.at > 24 * 60 * 60 * 1000) return null;
      return c;
    } catch (e) { return null; }
  }
  /* Урезаем лишнее, чтобы не упираться в квоту localStorage. */
  function trimForCache(data) {
    try {
      var d = JSON.parse(JSON.stringify(data));
      var h = d.home || {};
      if (h.now && h.now.items) h.now.items = h.now.items.slice(0, 5);
      if (h.matches && h.matches.matches) h.matches.matches = h.matches.matches.slice(0, 6);
      var r = h.ice_rail;
      if (r && r.windows) r.windows.forEach(function (w) {
        (w.arenas || []).slice(0, 8).forEach(function (a) { if (a.times) a.times = a.times.slice(0, 6); });
        w.arenas = (w.arenas || []).slice(0, 8);
      });
      if (h.nearby) h.nearby = h.nearby.slice(0, 6);
      if (h.week) h.week.forEach(function (d2) { if (d2.times) d2.times = d2.times.slice(0, 6); });
      if (d.bookings && d.bookings.days) {
        d.bookings.days = d.bookings.days.slice(0, 7).map(function (day) {
          return { date: day.date, day_label: day.day_label, bookings: (day.bookings || []).slice(0, 4) };
        });
      }
      return d;
    } catch (e) { return data; }
  }
  function screenCacheWrite(data) {
    try {
      var payload = JSON.stringify({ v: 1, at: Date.now(), data: data });
      if (payload.length > 150 * 1024) payload = JSON.stringify({ v: 1, at: Date.now(), data: trimForCache(data) });
      if (payload.length > 220 * 1024) return;
      localStorage.setItem(screenCacheKey(), payload);
    } catch (e) {
      /* QuotaExceeded — чистим только свои ключи и пропускаем запись. */
      try {
        var ks = [];
        for (var i = 0; i < localStorage.length; i++) {
          var k = localStorage.key(i);
          if (k && k.indexOf('hv2_screen_v1:') === 0) ks.push(k);
        }
        ks.forEach(function (k) { localStorage.removeItem(k); });
      } catch (e2) { /* */ }
    }
  }
  /* Кэш старый — пересчитываем «мёртвое»: прошедшие записи и отметку «на льду». */
  function sanitizeCached(data) {
    var d = data;
    var today = minskDate();
    var nowM = localMin();
    if (d.bookings && d.bookings.days) {
      d.bookings.days = d.bookings.days.map(function (day) {
        return { date: day.date, day_label: day.day_label, bookings: (day.bookings || []).filter(function (b) {
          if (day.date < today) return false;
          if (day.date === today && nowM != null && b.end_time) {
            var sp = String(b.end_time).split(':');
            if (parseInt(sp[0], 10) * 60 + parseInt(sp[1] || '0', 10) <= nowM) return false;
          }
          return true;
        }) };
      }).filter(function (day) { return day.bookings.length; });
    }
    var o = (d.home || {}).on_ice;
    if (o && o.ends_local && nowM != null) {
      var sp2 = String(o.ends_local).split(':');
      if (parseInt(sp2[0], 10) * 60 + parseInt(sp2[1] || '0', 10) <= nowM) d.home.on_ice = null;
    }
    /* Рейл: минуты до сеанса хранятся в ответе — пересчитываем от «сейчас». */
    var r = (d.home || {}).ice_rail;
    if (r && r.windows) r.windows.forEach(function (w) {
      var wDate = w.key === 'today' ? minskDate()
        : w.key === 'tomorrow' ? (function () { var dd = new Date(minskDate() + 'T12:00:00'); dd.setDate(dd.getDate() + 1); return dd.getFullYear() + '-' + String(dd.getMonth() + 1).padStart(2, '0') + '-' + String(dd.getDate()).padStart(2, '0'); })()
        : null;
      (w.arenas || []).forEach(function (a) {
        (a.times || []).forEach(function (t) {
          if (wDate && t.time) {
            var mu = minutesUntil(wDate, t.time);
            if (mu != null) t.minutes_until = mu;
          }
        });
      });
    });
    /* Неделя: прошедшие сегодняшние слоты помечаем past. */
    var wk = (d.home || {}).week;
    if (wk) wk.forEach(function (d2) {
      if (d2.date !== today || nowM == null) return;
      (d2.times || []).forEach(function (t) {
        var sp3 = String(t.time || '').split(':');
        if (parseInt(sp3[0], 10) * 60 + parseInt(sp3[1] || '0', 10) <= nowM) t.past = true;
      });
    });
    return d;
  }
  /* Плашка «Нет сети · данные на HH:MM» (макет 12, белая по доку) под верхней строкой шапки. */
  function showOfflinePlate(cacheAt) {
    removeOfflinePlate();
    var t = '';
    try {
      t = new Intl.DateTimeFormat('ru-RU', { timeZone: TZ, hour: '2-digit', minute: '2-digit' }).format(new Date(cacheAt));
    } catch (e) { t = ''; }
    var el = document.createElement('div');
    el.className = 'hv2-offline';
    el.id = 'hv2Offline';
    el.textContent = 'Нет сети' + (t ? ' · данные на ' + t : '');
    els.hero.appendChild(el);
  }
  function removeOfflinePlate() {
    var el = document.getElementById('hv2Offline');
    if (el) el.remove();
  }
  /* Тихая замена блока: общий html не трогаем, изменённый — короткий кросс-фейд. */
  function setBlockHtml(el, htmlStr, quiet) {
    if (el.__lastHtml === htmlStr) return;
    el.__lastHtml = htmlStr;
    if (quiet) {
      el.classList.remove('hv2-xfade');
      void el.offsetWidth;
      el.classList.add('hv2-xfade');
    }
    el.innerHTML = htmlStr;
  }
  function notifyContent(src) {
    try {
      if (window.ClientShell && typeof window.ClientShell.contentShown === 'function') {
        window.ClientShell.contentShown({ src: src, data_ms: Math.round(performance.now()) });
      }
    } catch (e) { /* */ }
  }
  /* «Лёд» прогревается, пока главная простаивает — один раз за сессию. */
  function scheduleIcePrefetch() {
    if (state.icePrefetched) return;
    state.icePrefetched = true;
    try { if (sessionStorage.getItem('hv2_ice_pf') === '1') return; } catch (e) { /* */ }
    var go = function () {
      try { sessionStorage.setItem('hv2_ice_pf', '1'); } catch (e) { /* */ }
      try {
        var conn = navigator.connection || {};
        if (conn.saveData === true || /(^|-)2g$/.test(String(conn.effectiveType || ''))) return;
      } catch (e) { /* */ }
      if (window.ClientShell && typeof window.ClientShell.prefetchTab === 'function') {
        window.ClientShell.prefetchTab('catalog');
      }
    };
    if (typeof window.requestIdleCallback === 'function') window.requestIdleCallback(go, { timeout: 2500 });
    else setTimeout(go, 1500);
  }

  /* Все не-мертвые записи от сегодня вперёд, по дате и времени. */
  function futureBookings(data) {
    var days = (data.bookings && data.bookings.days) || [];
    var today = minskDate();
    var nowMin = localMin();
    var out = [];
    for (var i = 0; i < days.length; i++) {
      var day = days[i];
      if (String(day.date) < today) continue;
      for (var j = 0; j < (day.bookings || []).length; j++) {
        var b = day.bookings[j];
        if (DEAD[String(b.status || '').toLowerCase()]) continue;
        if (String(day.date) === today && nowMin !== null) {
          var ep = String(b.end_time || '23:59').split(':');
          if (parseInt(ep[0], 10) * 60 + parseInt(ep[1] || '0', 10) <= nowMin) continue;
        }
        out.push({ date: String(day.date), b: b });
      }
    }
    out.sort(function (x, y) {
      return (x.date + hhmm(x.b.start_time)) < (y.date + hhmm(y.b.start_time)) ? -1 : 1;
    });
    return out;
  }

  /* Несколько записей (макет 2): верхний билет как стопка + секция «Дальше». */
  function stackTicketHtml(rec) {
    return '<div class="hv2-stack">' +
      '<i class="hv2-stack__g hv2-stack__g2" aria-hidden="true"></i>' +
      '<i class="hv2-stack__g hv2-stack__g1" aria-hidden="true"></i>' +
      ticketHtml(rec) + '</div>';
  }
  function bookingRowHtml(rec) {
    var b = rec.b;
    var d = new Date(rec.date + 'T12:00:00');
    var pend = String(b.status || '').toLowerCase() === 'pending';
    return '<a class="hv2-brow ga-press" href="client-bookings" data-act="nav" data-path="client-bookings">' +
      '<span class="hv2-brow__tile"><span class="hv2-brow__day">' + d.getDate() + '</span>' +
        '<span class="hv2-brow__dow">' + esc(DOW[d.getDay()]) + '</span></span>' +
      '<span class="hv2-brow__body">' +
        '<span class="hv2-brow__title">' + esc(hhmm(b.start_time)) + ' · ' + esc(b.service_name || 'Занятие') + '</span>' +
        (pend ? '<span class="hv2-brow__pend">ждёт тренера</span>' : '') +
        '<span class="hv2-brow__sub">' + esc(b.arena_name || b.place_display || 'Каток') +
          (b.trainer_name ? ' · ' + esc(b.trainer_name) : '') + '</span>' +
      '</span>' +
      '<svg class="hv2-brow__chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></a>';
  }
  function nextBookingsSecHtml(list, skipId) {
    var rows = list.filter(function (r) { return String(r.b.id) !== String(skipId); });
    if (!rows.length) return '';
    var total = rows.length + 1;
    return '<section class="hv2-sec">' +
      '<div class="hv2-sec__head"><h2 class="hv2-sec__title">Дальше</h2>' +
      '<a class="hv2-sec__more" href="client-bookings" data-act="nav" data-path="client-bookings">Все записи · ' + total + '</a></div>' +
      '<div class="hv2-card hv2-brows">' + rows.slice(0, 3).map(bookingRowHtml).join('') + '</div></section>';
  }

  /* Матч «Кто кого» сегодня (макет 5): у игрока без записи — большая синяя карточка. */
  function kkTodayItem() {
    if (!home().kk_player) return null;
    var now = home().now;
    if (!now) return null;
    var items = now.kind === 'feed' ? (now.items || []) : [now];
    var today = minskDate();
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      if (!it || it.kind !== 'kk_before' && it.kind !== 'kk_live' && it.kind !== 'kk_waiting') continue;
      var m = (it.hockey || {}).match || {};
      if (!m.starts_at) continue;
      var d = new Date(m.starts_at);
      try {
        var local = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
        if (local === today) return it;
      } catch (e) {}
    }
    return null;
  }
  function kkMatchCardHtml(item) {
    var h = item.hockey || {};
    var m = h.match || {};
    var href = h.event_href || 'kto-kogo';
    var d = new Date(m.starts_at);
    var tm = '';
    try { tm = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(d); } catch (e) {}
    var mu = Math.max(0, Math.round((d.getTime() - Date.now()) / 60000));
    var till = fmtUntil(mu) || 'скоро';
    var pick = h.my_pick;
    var pickLine = pick && pick.home_score != null
      ? 'Твой прогноз ' + esc(pick.home_score) + ':' + esc(pick.away_score)
      : 'Угадай счёт до начала';
    state.yellowUsed = true;
    return '<article class="hv2-card hv2-kk">' +
      '<div class="hv2-kk__kick">КТО КОГО</div>' +
      '<div class="hv2-kk__teams">' +
        '<span class="hv2-kk__team">' + teamLogo(m.home, true) + '<span class="hv2-kk__tname">' + esc((m.home && (m.home.name || m.home.short)) || '') + '</span></span>' +
        '<span class="hv2-kk__mid"><span class="hv2-kk__time">' + esc(tm) + '</span><span class="hv2-kk__till">' + esc(till) + '</span></span>' +
        '<span class="hv2-kk__team">' + teamLogo(m.away, true) + '<span class="hv2-kk__tname">' + esc((m.away && (m.away.name || m.away.short)) || '') + '</span></span>' +
      '</div>' +
      '<a class="hv2-btn hv2-btn--yellow hv2-kk__play ga-press" href="' + esc(href) + '" data-act="nav" data-path="' + esc(href) + '">Играть</a>' +
      '<div class="hv2-kk__pick">' + pickLine + '</div>' +
    '</article>';
  }

  /* «С возвращением» (макет 7): основной тренер, последнее занятие ≥21 дня. */
  var RETURN_AFTER_DAYS = 21;
  function returnInfo(cs) {
    var hist = cs.primary_history;
    if (!hist || !hist.last_completed_at) return null;
    var last = new Date(hist.last_completed_at);
    if (isNaN(last)) return null;
    var days = Math.floor((Date.now() - last.getTime()) / 86400000);
    if (days < RETURN_AFTER_DAYS) return null;
    var ago;
    if (days >= 60) { var m = Math.round(days / 30); ago = m + ' ' + plural(m, 'месяц', 'месяца', 'месяцев') + ' назад'; }
    else if (days >= 14) { var w = Math.floor(days / 7); ago = w + ' ' + plural(w, 'неделю', 'недели', 'недель') + ' назад'; }
    else ago = days + ' ' + plural(days, 'день', 'дня', 'дней') + ' назад';
    return { days: days, ago: ago, count: Number(hist.completed_count) || 0 };
  }
  function trainersHref() {
    return 'trainers' + (cityId() ? '?city_id=' + encodeURIComponent(cityId()) : '');
  }
  function returnCardHtml(cs, info) {
    var tid = cs.primary_trainer_id;
    var name = cs.primary_trainer_name || 'Тренер';
    var face = cs.primary_trainer_list_photo_key
      ? '<img class="hv2-ret__face" src="' + esc(trainerPhotoUrl(cs.primary_trainer_list_photo_key)) + '" alt="">'
      : '<span class="hv2-ret__face">' + esc(name.charAt(0).toUpperCase()) + '</span>';
    var cnt = info.count;
    var sub = (cnt ? cnt + ' ' + plural(cnt, 'занятие', 'занятия', 'занятий') + ' вместе · ' : '') +
      'последнее ' + info.ago;
    state.yellowUsed = true;
    return '<article class="hv2-card hv2-ret">' +
      '<div class="hv2-ret__head">' + face +
        '<div class="hv2-ret__col"><div class="hv2-ret__kick">Давно не виделись</div>' +
        '<div class="hv2-ret__name">' + esc(name) + '</div>' +
        '<div class="hv2-ret__sub">' + esc(sub) + '</div></div>' +
      '</div>' +
      slotsBlockHtml(tid) +
      '<div class="hv2-ret__btns">' +
        '<button type="button" class="hv2-btn hv2-btn--yellow ga-press" data-act="book" data-path="' + esc(allSlotsHref(tid)) + '">Записаться</button>' +
        '<a class="hv2-btn hv2-btn--soft ga-press" href="' + esc(trainersHref()) + '" data-act="nav" data-path="' + esc(trainersHref()) + '">Другие тренеры</a>' +
      '</div></article>';
  }

  /* Один каток в городе (макет 9): белый билет вместо фото-карточки. */
  var ICON_BELL = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 8a6 6 0 1 0-12 0c0 7-3 8-3 8h18s-3-1-3-8"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>';
  function oneRinkCardHtml(o) {
    var chip = (o.day_label === 'Сегодня' ? fmtUntilCap(o.minutes_until) : null) ||
      (o.day_label || 'Скоро');
    var bits = [];
    if (o.end) bits.push('до ' + o.end);
    if (o.arena_name) bits.push(o.arena_name);
    if (o.later_today) bits.push('ещё сегодня ' + o.later_today);
    var prices = (o.prices || []).slice(0, 3).map(function (p) {
      return '<span class="hv2-one__price"><b>' + esc(p.value) + '</b><span>' + esc(p.label) + '</span></span>';
    }).join('');
    var route = o.map_link
      ? '<button type="button" class="hv2-btn hv2-btn--ink ga-press" data-act="map" data-href="' + esc(o.map_link) + '">' + ICON_ROUTE + ' Маршрут</button>'
      : '<button type="button" class="hv2-btn hv2-btn--ink ga-press" data-act="nav" data-path="' + esc(o.href || 'ice') + '">' + ICON_ROUTE + ' Маршрут</button>';
    var share = o.invite_url
      ? '<button type="button" class="hv2-btn hv2-btn--soft ga-press" data-act="share" data-url="' + esc(o.invite_url) + '">Позвать друзей</button>'
      : '';
    return '<article class="hv2-card hv2-one" data-act="nav" data-path="' + esc(o.href || 'ice') + '">' +
      '<span class="hv2-chip">' + '<span class="hv2-chip__dot"></span>' + esc(chip) + '</span>' +
      '<div class="hv2-one__time">' + esc(o.time || '') + '</div>' +
      '<div class="hv2-one__title">' + esc(o.title || 'Массовое катание') + '</div>' +
      (bits.length ? '<div class="hv2-one__sub">' + esc(bits.join(' · ')) + '</div>' : '') +
      '<div class="hv2-ticket__perf"></div>' +
      (prices ? '<div class="hv2-one__prices">' + prices + '</div>' : '') +
      '<div class="hv2-one__btns">' + route + share + '</div></article>';
  }

  /* «На неделе» / «Неделя в городе»: строки по дням, пустые схлопнуты. */
  function weekSecHtml(title) {
    var week = home().week;
    if (!week || !week.length) return '';
    var allHref = 'ice' + (cityId() ? '?city_id=' + encodeURIComponent(cityId()) : '');
    var total = week.reduce(function (n, d) { return n + (d.times || []).length; }, 0);
    var rows = '';
    var i = 0;
    while (i < week.length) {
      var d = week[i];
      if ((d.times || []).length) {
        var chips = (d.times || []).map(function (t) {
          return '<a class="hv2-wchip ga-press' + (t.past ? ' hv2-wchip--past' : '') + '" href="' + esc(t.href || allHref) + '" data-act="nav" data-path="' + esc(t.href || allHref) + '"' +
            (t.arena_name ? ' title="' + esc(t.arena_name) + '"' : '') + '>' + esc(t.time) + '</a>';
        }).join('');
        rows += '<div class="hv2-wrow"><span class="hv2-wrow__day"><b>' + esc(d.label) + '</b>' +
          '<span class="hv2-wrow__sub">' + esc(d.sub) + '</span></span>' +
          '<span class="hv2-wrow__chips">' + chips + '</span></div>';
        i++;
        continue;
      }
      /* Серия пустых дней — одна строка «Пн–Пт · 23–27». */
      var j = i;
      while (j < week.length && !(week[j].times || []).length) j++;
      var first = week[i], last = week[j - 1];
      var range = first.label === last.label ? esc(first.label) : esc(first.label) + '–' + esc(last.label);
      var rangeSub = first.sub === last.sub ? esc(first.sub) : esc(first.sub) + '–' + esc(last.sub);
      rows += '<div class="hv2-wrow hv2-wrow--empty"><span class="hv2-wrow__day"><b>' + range + '</b>' +
        '<span class="hv2-wrow__sub">' + rangeSub + '</span></span>' +
        '<span class="hv2-wrow__note">Расписание ещё не вышло</span></div>';
      i = j;
    }
    return '<section class="hv2-sec">' +
      '<div class="hv2-sec__head"><h2 class="hv2-sec__title">' + esc(title || 'На неделе') + '</h2>' +
      (total ? '<a class="hv2-sec__more" href="' + esc(allHref) + '" data-act="nav" data-path="' + esc(allHref) + '">Все ' + total + '</a>' : '') +
      '</div><div class="hv2-card hv2-week">' + rows + '</div></section>';
  }

  function weekTitle() {
    var c = city();
    return c && c.name_in ? 'Неделя ' + c.name_in : 'На неделе';
  }
  function nearbySecHtml() {
    var list = home().nearby;
    if (!list || !list.length) return '';
    var cards = list.map(function (n) {
      var inner =
        '<span class="hv2-rcard__imgwrap">' +
          (n.photo ? '<img class="hv2-rcard__img" src="' + esc(n.photo) + '" alt="" loading="lazy" decoding="async">' : '') +
          (n.rink_count ? '<span class="hv2-rcard__chip">' + esc(n.rink_count + ' ' + plural(n.rink_count, 'каток', 'катка', 'катков')) + '</span>' : '') +
        '</span>' +
        '<span class="hv2-rcard__name">' + esc(n.name) + '</span>' +
        (n.sub ? '<span class="hv2-rcard__sub">' + esc(n.sub) + '</span>' : '');
      return n.href
        ? '<a class="hv2-rcard ga-press" href="' + esc(n.href) + '" data-act="nav" data-path="' + esc(n.href) + '">' + inner + '</a>'
        : '<div class="hv2-rcard">' + inner + '</div>';
    }).join('');
    return '<section class="hv2-sec"><div class="hv2-sec__head"><h2 class="hv2-sec__title">Лёд рядом</h2></div>' +
      '<div class="hv2-rail">' + cards + '</div></section>';
  }

  /* «Лёд закончился» (макет 10) и «Межсезонье»: колокольчик-подписка. */
  function watchArenaId() {
    var pp = home().place_photos || {};
    var keys = Object.keys(pp);
    return keys.length ? Number(keys[0]) : null;
  }
  function iceEndedCardHtml(n) {
    var thumb = n.photo ? '<img class="hv2-end__thumb" src="' + esc(n.photo) + '" alt="">' : '';
    var sub = [n.date_sub, n.time, n.arena_name].filter(Boolean).join(' · ');
    return '<article class="hv2-card hv2-end">' +
      '<span class="hv2-chip hv2-chip--gray">Сегодня лёд закончился</span>' +
      '<div class="hv2-end__row"><div class="hv2-end__col">' +
        '<div class="hv2-end__title">Следующий — ' + esc(n.date_label || '') + '</div>' +
        (sub ? '<div class="hv2-end__sub">' + esc(sub) + '</div>' : '') +
      '</div>' + thumb + '</div>' +
      '<button type="button" class="hv2-btn hv2-btn--ink ga-press" id="hv2Watch" ' +
        'data-act="watch" data-kind="schedule_fresh" data-arena="' + esc(n.arena_id || '') + '">' +
        ICON_BELL + ' Сообщить о новом льде</button></article>';
  }
  function offseasonCardHtml() {
    return '<article class="hv2-card hv2-end">' +
      '<span class="hv2-chip hv2-chip--gray">Межсезонье</span>' +
      '<div class="hv2-end__title">Лёд вернётся</div>' +
      '<div class="hv2-end__sub">Расписания на ближайшие недели нет. Напишем, как только откроют сезон.</div>' +
      '<button type="button" class="hv2-btn hv2-btn--ink ga-press" id="hv2Watch" ' +
        'data-act="watch" data-kind="season_open" data-arena="' + esc(watchArenaId() || '') + '">' +
        ICON_BELL + ' Сообщить, когда откроют</button></article>';
  }
  function watchSubscribe(btn) {
    var kind = btn.getAttribute('data-kind') || 'schedule_fresh';
    var arenaId = Number(btn.getAttribute('data-arena')) || null;
    var body = { watch_kind: kind, city_id: cityId() };
    if (arenaId) body.arena_id = arenaId;
    btn.disabled = true;
    fetch('/api/webapp/client/ice-watches', {
      method: 'POST', headers: headersJson(), body: JSON.stringify(body),
    }).then(function (r) {
      if (r.status === 409) { btn.parentNode && btn.parentNode.removeChild(btn); return null; }
      if (!r.ok) { btn.disabled = false; return null; }
      haptic('success');
      var soft = document.createElement('div');
      soft.className = 'hv2-watch-ok';
      soft.textContent = kind === 'season_open' ? 'Сообщим, когда откроют сезон' : 'Сообщим, когда появится лёд';
      btn.parentNode.replaceChild(soft, btn);
      return null;
    }).catch(function () { btn.disabled = false; });
  }

  /* ── Сборка ──────────────────────────────────────────────── */
  function renderAll() {
    var data = state.data;
    var top = 'citypick';
    var html = '';
    var onIce = home().on_ice;
    if (onIce) {
      /* TASK-446: «Ты на катке?» — главнее любой карточки. */
      top = 'onice';
      state.topPhoto = onIce.photo && (onIce.photo.hero || onIce.photo.card || onIce.photo.thumb);
      html = onIceHtml(onIce);
      loadCheckinAssets();
    } else if (cityId()) {
      var s2 = s2On();
      var rec = topBooking(data);
      var todayRec = rec && rec.date === minskDate() ? rec : null;
      var kk = s2 && !todayRec ? kkTodayItem() : null;
      var p = rec ? null : activePass(data);
      var cs = data.client_session || {};
      if (rec) {
        top = 'ticket';
        var futures = s2 ? futureBookings(data) : [];
        if (futures.length >= 2) {
          /* TASK-447: стопка записей + «Дальше» под билетом. */
          html = stackTicketHtml(rec) + nextBookingsSecHtml(futures, rec.b.id);
        } else {
          html = ticketHtml(rec) + (futures.length > 1 ? nextBookingsSecHtml(futures, rec.b.id) : '');
        }
      }
      else if (kk) { top = 'kkmatch'; html = kkMatchCardHtml(kk) + nextBookingsSecHtml(futureBookings(data), -1); }
      else if (p) { top = 'pass'; html = passCardHtml(p); }
      else if (cs.primary_trainer_id) {
        var ret = s2 ? returnInfo(cs) : null;
        if (ret) { top = 'return'; html = returnCardHtml(cs, ret); }
        else { top = 'coach'; html = coachCardHtml(cs); }
      }
      else {
        var one = s2 ? home().one_rink : null;
        var nextIce = s2 && 'next_ice' in home() ? home().next_ice : undefined;
        if (one) { top = 'onerink'; html = oneRinkCardHtml(one) + weekSecHtml('На неделе') + nearbySecHtml(); }
        else if (nextIce) { top = 'iceend'; html = iceEndedCardHtml(nextIce) + weekSecHtml(weekTitle()); }
        else if (nextIce === null && (home().place_photos && Object.keys(home().place_photos).length || railWindows())) {
          top = 'offseason';
          state.coachFirst = true;
          html = offseasonCardHtml();
        }
        else {
          var found = nearestIce(data);
          if (found) {
            top = 'newbie';
            state.dedupSession = found.session_id;
            state.topPhoto = found.photo && (found.photo.card || found.photo.hero || found.photo.thumb);
            html = photoCardHtml(found);
          } else top = 'ice-empty';
        }
      }
    } else {
      html = cityPickHtml();
    }
    state.topState = top;
    renderHero(top);
    setBlockHtml(els.top, html, state.quiet);
    if (top === 'citypick') {
      els.iceSec.hidden = true; els.matchSec.hidden = true; els.moreSec.hidden = true;
      bindCityPick();
    } else {
      renderIce();
      renderMatches();
      renderMore();
    }
    if (top === 'pass') fetchSlots(activePass(data).trainer_id);
    if (top === 'coach' || top === 'return') fetchSlots((data.client_session || {}).primary_trainer_id);
    /* появление блоков со сдвигом по очереди (≤6) — при тихом обновлении не машем. */
    if (!state.quiet) {
      var kids = els.main.querySelectorAll('.hv2-card, .hv2-pcard, .hv2-pcard__btns, .hv2-sec');
      kids.forEach(function (el, i) {
        if (i < 6) { el.classList.add('hv2-up'); el.style.animationDelay = (i * 30) + 'ms'; }
      });
    }
  }

  function showError() {
    els.skel.style.display = 'none';
    els.top.innerHTML = '<div class="hv2-card hv2-error hv2-fade">' +
      '<div class="hv2-error__t">Нет сети · Проверьте подключение</div>' +
      '<div class="hv2-error__s">Покажем расписание, как только интернет вернётся.</div>' +
      '<button type="button" class="hv2-btn hv2-btn--ink ga-press" id="hv2Retry">Повторить</button></div>';
    $('hv2Retry').addEventListener('click', function () { boot(); });
  }

  function applyNetData(data, quiet) {
    state.data = data;
    state.quiet = quiet;
    renderAll();
    state.quiet = false;
    els.skel.style.display = 'none';
    if (!quiet) els.top.classList.add('hv2-fade');
    if (s3On()) screenCacheWrite(data);
  }

  function boot() {
    var s3 = s3On();
    var cached = s3 ? screenCacheRead() : null;
    var hadCache = !!(cached && cached.data);
    if (hadCache) {
      /* TASK-448: прошлый экран из кэша до сети — скелетон не показываем. */
      state.railTab = null; state.yellowUsed = false; state.dedupSession = null; state.topPhoto = null;
      state.data = sanitizeCached(cached.data);
      state.quiet = false;
      renderAll();
      els.skel.style.display = 'none';
      notifyContent('cache');
      scheduleIcePrefetch();
    } else {
      els.skel.style.display = '';
    }
    state.railTab = null; state.yellowUsed = false; state.dedupSession = null; state.topPhoto = null;
    fetchBootstrap(s3 ? 8000 : 0).then(function (data) {
      removeOfflinePlate();
      if (hadCache) {
        applyNetData(data, true);
      } else {
        applyNetData(data, false);
      }
      notifyContent('net');
      scheduleIcePrefetch();
    }).catch(function () {
      if (hadCache) {
        /* Кэш уже на экране — белая плашка и ретраи по сети/возврату на страницу. */
        showOfflinePlate(cached.at);
        var retry = function () { boot(); };
        window.addEventListener('online', retry, { once: true });
        document.addEventListener('visibilitychange', function vis() {
          if (document.visibilityState === 'visible' && document.getElementById('hv2Offline')) {
            document.removeEventListener('visibilitychange', vis);
            retry();
          }
        });
      } else {
        showError();
      }
    });
  }

  function init() {
    els.main = $('hv2Main'); els.top = $('hv2Top'); els.skel = $('hv2Skel');
    els.hero = $('hv2Hero'); els.heroImg = $('hv2HeroImg'); els.dateEl = $('hv2Date'); els.title = $('hv2Title');
    els.cityLabel = $('hv2CityLabel'); els.ava = $('hv2Ava');
    els.iceSec = $('hv2IceSec'); els.iceTitle = $('hv2IceTitle'); els.iceMore = $('hv2IceMore'); els.tabs = $('hv2Tabs'); els.rail = $('hv2Rail');
    els.matchSec = $('hv2MatchSec'); els.matchMore = $('hv2MatchMore'); els.matches = $('hv2Matches');
    els.moreSec = $('hv2MoreSec'); els.more = $('hv2More');
    els.sheet = $('hv2Sheet'); els.cityList = $('hv2CityList');
    $('hv2City').addEventListener('click', function () { haptic('select'); openSheet(); });
    $('hv2Geo').addEventListener('click', function () { haptic('select'); geoPick(); });
    els.ava.addEventListener('click', function () { haptic('light'); navigate('client-me'); });
    els.sheet.addEventListener('click', function (ev) { if (ev.target === els.sheet) closeSheet(); });
    els.sheet.querySelectorAll('[data-close]').forEach(function (b) { b.addEventListener('click', closeSheet); });
    /* Делегированные переходы и действия: ссылки, кнопки data-act, города.
       Центральный обработчик — перерисовка рейлов не теряет слушателей. */
    document.addEventListener('click', function (ev) {
      var t = ev.target;
      var closest = function (sel) { return t && t.closest ? t.closest(sel) : null; };
      var cityBtn = closest('[data-city]');
      if (cityBtn) { haptic('select'); pickCity(Number(cityBtn.getAttribute('data-city'))); return; }
      var actEl = closest('[data-act]');
      if (actEl) {
        var act = actEl.getAttribute('data-act');
        if (act === 'checkin') { ev.preventDefault(); haptic('light'); openCheckinSheet(); return; }
        if (act === 'share') { ev.preventDefault(); haptic('light'); shareUrl(actEl.getAttribute('data-url')); return; }
        if (act === 'map') { ev.preventDefault(); haptic('light'); openExternal(actEl.getAttribute('data-href')); return; }
        if (act === 'watch') { ev.preventDefault(); haptic('light'); watchSubscribe(actEl); return; }
        if (act === 'book' || act === 'nav') {
          ev.preventDefault();
          if (act === 'book') haptic('light');
          var path = actEl.getAttribute('data-path') || actEl.getAttribute('href');
          if (path) navigate(path);
          return;
        }
      }
      var a = closest('a[href]');
      if (!a) return;
      var href = a.getAttribute('href');
      if (!href || href.indexOf('http') === 0 || href.indexOf('#') === 0) return;
      if (window.ClientShell && typeof window.ClientShell.navigate === 'function') {
        ev.preventDefault();
        navigate(href);
      }
    });
    /* Фон <body> под листом и при overscroll — #f5f6f8. Перебивает старые !important
       правила темы (mini-app-components / mini-app-client-theme) инлайном — надёжнее,
       чем гонка специфичности между стилями. */
    document.body.style.setProperty('background-color', '#f5f6f8', 'important');
    boot();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
