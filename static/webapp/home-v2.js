/*
 * Главная v2 (TASK-445, эпик glide-home-v1, флаг redesign_s1).
 * Один запрос /client/hub/bootstrap → состояние по приоритету:
 * запись → абонемент → тренер → ближайший сеанс → выбор города.
 * Ниже всегда: «Лёд в городе», «Матчи», «Ещё».
 */
(function () {
  'use strict';

  var DEAD = { cancelled: 1, canceled: 1, declined: 1, rejected: 1, no_show: 1, completed: 1, expired: 1 };
  var els = {};
  var state = { data: null, cityId: null, cities: null };

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
        if (kind === 'success' && w.HapticFeedback.notificationOccurred) w.HapticFeedback.notificationOccurred('success');
        else if (w.HapticFeedback.impactOccurred) w.HapticFeedback.impactOccurred(kind === 'light' ? 'light' : 'medium');
        else if (w.HapticFeedback.selectionChanged) w.HapticFeedback.selectionChanged();
      }
    } catch (e) {}
  }
  function initData() {
    var rt = window.MiniAppRuntime;
    if (rt && rt.getCredential) return rt.getCredential() || '';
    var w = tg();
    return w && w.initData ? String(w.initData) : '';
  }
  function headersJson(extra) {
    var h = { 'Content-Type': 'application/json' };
    var init = initData();
    if (init) h['X-Telegram-Init-Data'] = init;
    var pid = profileId();
    if (pid) h['X-Profile-Id'] = String(pid);
    if (extra) for (var k in extra) h[k] = extra[k];
    return h;
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

  /* ── Даты (локальные, Europe/Minsk — как сервер) ─────────── */
  function todayStr() {
    try {
      return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Minsk', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    } catch (e) {
      var d = new Date();
      return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }
  }
  var DOW = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
  function dayLabel(dateStr) {
    var t = todayStr();
    if (dateStr === t) return 'сегодня';
    var d = new Date(dateStr + 'T12:00:00');
    if (isNaN(d)) return dateStr;
    var diff = Math.round((d - new Date(t + 'T12:00:00')) / 86400000);
    if (diff === 1) return 'завтра';
    if (diff > 1 && diff < 7) return DOW[d.getDay()];
    return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
  }
  function hhmm(t) { return String(t || '').slice(0, 5); }
  /* Цена сеанса из minor-единиц — как IceTeaserModel.formatPrice («взр. 12 BYN»). */
  function formatPrice(minor, currency) {
    if (minor == null || minor === '' || isNaN(Number(minor))) return '';
    var major = Number(minor) / 100;
    var num = Number.isInteger(major) ? String(major) : major.toFixed(2);
    return 'взр. ' + num + ' ' + (currency || 'BYN');
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

  function upcomingBooking(data) {
    var days = (data.bookings && data.bookings.days) || [];
    var today = todayStr();
    var best = null;
    for (var i = 0; i < days.length; i++) {
      var day = days[i];
      var list = day.bookings || [];
      for (var j = 0; j < list.length; j++) {
        var b = list[j];
        if (DEAD[String(b.status || '').toLowerCase()]) continue;
        if (day.date < today) continue;
        if (!best || day.date < best.date || (day.date === best.date && hhmm(b.start_time) < hhmm(best.b.start_time))) {
          best = { date: day.date, b: b, dayLabel: dayLabel(day.date) };
        }
      }
    }
    return best;
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
  function nearestSession(data) {
    var city = (data.home && data.home.city) || null;
    var ups = (city && city.upcoming) || [];
    if (ups.length) return { session: ups[0], cityId: city.id, cityName: city.name, fromCity: true };
    var ice = data.ice_teaser;
    if (ice && ice.sessions && ice.sessions.length) {
      var s = ice.sessions[0];
      return { session: s, cityId: ice.city_id, cityName: ice.city_name, fromCity: false, teaser: ice };
    }
    return null;
  }

  /* ── Рендер: верхняя карточка ────────────────────────────── */
  function ticketHtml(rec) {
    var b = rec.b;
    var isToday = rec.date === todayStr();
    var pending = String(b.status || '').toLowerCase() === 'pending';
    var pass = passForTrainer(state.data, b.trainer_id);
    var passLine = '';
    if (pass) {
      passLine = '<div class="hv2-ticket__pass">Осталось занятий: <b>' + esc(pass.sessions_remaining) + '</b> из ' + esc(pass.sessions_total) + '</div>';
    }
    var route = b.map_link
      ? '<button type="button" class="hv2-btn hv2-btn--dark" data-act="map" data-href="' + esc(b.map_link) + '">Маршрут</button>'
      : (b.arena_id ? '<button type="button" class="hv2-btn hv2-btn--dark" data-act="nav" data-path="arena?ref=' + encodeURIComponent(b.arena_id) + '">Маршрут</button>' : '');
    return '<article class="hv2-card hv2-ticket hv2-fade-in">' +
      '<div class="hv2-ticket__top">' +
        '<div><div class="hv2-ticket__time">' + esc(hhmm(b.start_time)) + '</div>' +
        '<div class="hv2-ticket__when">' + esc(isToday ? 'сегодня' : dayLabel(rec.date)) + ' · ' + esc(hhmm(b.end_time)) + '</div></div>' +
        (pending ? '<span class="hv2-ticket__status">ждёт тренера</span>' : '<span class="hv2-ticket__status hv2-ticket__status--ok">запись</span>') +
      '</div>' +
      '<div><div class="hv2-ticket__place">' + esc(b.arena_name || b.place_display || 'Каток') + '</div>' +
      '<div class="hv2-ticket__meta"><span>' + esc(b.trainer_name || 'Тренер') + (b.service_name ? ' · ' + esc(b.service_name) : '') + '</span></div></div>' +
      passLine +
      '<div class="hv2-ticket__actions">' + route +
      '<button type="button" class="hv2-btn hv2-btn--soft" data-act="nav" data-path="client-bookings">Все записи</button></div>' +
    '</article>';
  }

  function passCardHtml(p) {
    var total = Math.max(1, Number(p.sessions_total) || 1);
    var left = Number(p.sessions_remaining) || 0;
    var pct = Math.max(0, Math.min(1, left / total));
    var R = 30, C = 2 * Math.PI * R;
    var ring =
      '<svg width="76" height="76" viewBox="0 0 76 76">' +
      '<circle cx="38" cy="38" r="' + R + '" fill="none" stroke="#eef1f3" stroke-width="8"/>' +
      '<circle cx="38" cy="38" r="' + R + '" fill="none" stroke="#0a6f73" stroke-width="8" stroke-linecap="round" ' +
      'stroke-dasharray="' + (pct * C).toFixed(1) + ' ' + C.toFixed(1) + '"/>' +
      '</svg>';
    var exp = p.expires_at ? ' до ' + esc(String(p.expires_at).slice(0, 10).split('-').reverse().join('.')) : '';
    return '<article class="hv2-card hv2-pass hv2-fade-in">' +
      '<div class="hv2-pass__ring"><div class="hv2-pass__ring-num">' + esc(left) + '<small>из ' + esc(p.sessions_total) + '</small></div>' + ring + '</div>' +
      '<div class="hv2-pass__body">' +
        '<div class="hv2-pass__title">' + esc(p.product_name || 'Абонемент') + '</div>' +
        '<div class="hv2-pass__sub">' + esc(p.trainer_name || 'Тренер') + (p.service_name ? ' · ' + esc(p.service_name) : '') + exp + '</div>' +
      '</div></article>' +
      '<div class="hv2-ticket__actions" style="padding:0 4px">' +
      (p.trainer_id ? '<button type="button" class="hv2-btn hv2-btn--dark hv2-btn--block" data-act="nav" data-path="catalog?trainer_id=' + encodeURIComponent(p.trainer_id) + '">Записаться</button>' : '') +
      '</div>';
  }

  function coachCardHtml(cs) {
    var t = cs.primary_trainer_id;
    var name = cs.primary_trainer_name || 'Тренер';
    var photo = cs.primary_trainer_list_photo_key
      ? '<img class="hv2-coach__photo" src="/api/public/photos/' + encodeURIComponent(cs.primary_trainer_list_photo_key) + '" alt="" loading="lazy">'
      : '<div class="hv2-coach__photo hv2-coach__photo--empty">' + esc(name.charAt(0).toUpperCase()) + '</div>';
    return '<article class="hv2-card hv2-coach hv2-fade-in" data-act="nav" data-path="catalog?trainer_id=' + encodeURIComponent(t || '') + '" role="link" tabindex="0">' +
      photo +
      '<div class="hv2-coach__body"><div class="hv2-coach__name">' + esc(name) + '</div>' +
      '<div class="hv2-coach__sub">Ваш тренер · записаться</div></div>' +
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="hv2-row__chev" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>' +
    '</article>';
  }

  function photoCardHtml(found) {
    var s = found.session;
    var isTeaser = !found.fromCity;
    var time = hhmm(s.starts_at_local || s.time || s.badge) || '';
    var badge = s.badge || time;
    var place = s.place || s.arena_name || '';
    var href = s.href || (s.arena_id ? 'arena?ref=' + s.arena_id + (s.session_id ? '&s=' + s.session_id : '') : 'ice');
    var img = s.photo && (s.photo.card || s.photo.hero || s.photo.thumb);
    if (!img && found.teaser && (found.teaser.card || found.teaser.thumb)) img = found.teaser.card || found.teaser.thumb;
    var price = s.price || formatPrice(s.price_adult_minor, s.currency_code);
    var geo = '';
    if (s.map_link) {
      geo = '<button type="button" class="hv2-btn hv2-btn--soft" data-act="map" data-href="' + esc(s.map_link) + '">Маршрут</button>';
    } else if (s.arena_id) {
      geo = '<button type="button" class="hv2-btn hv2-btn--soft" data-act="nav" data-path="arena?ref=' + encodeURIComponent(s.arena_id) + (s.session_id ? '&s=' + encodeURIComponent(s.session_id) : '') + '">Маршрут</button>';
    }
    var invite = s.invite_url
      ? '<button type="button" class="hv2-btn hv2-btn--yellow" data-act="share" data-url="' + esc(s.invite_url) + '">Позвать друзей</button>'
      : '';
    return '<article class="hv2-photo hv2-fade-in" data-act="nav" data-path="' + esc(href) + '">' +
      (img ? '<img class="hv2-photo__img" src="' + esc(img) + '" alt="" loading="lazy">' : '') +
      '<span class="hv2-photo__shade"></span>' +
      '<span class="hv2-photo__in">' +
        '<span class="hv2-photo__badge">' + esc(badge) + (price ? ' · ' + esc(price) : '') + '</span>' +
        '<span class="hv2-photo__title">' + esc(place) + '</span>' +
        (isTeaser && found.cityName ? '<span class="hv2-photo__sub">Ближайший сеанс · ' + esc(found.cityName) + '</span>' : '') +
        ((geo || invite) ? '<span class="hv2-photo__actions">' + geo + invite + '</span>' : '') +
      '</span></article>';
  }

  function cityPickHtml() {
    return '<article class="hv2-card hv2-citypick hv2-fade-in">' +
      '<h2 class="hv2-citypick__title">Выберите город</h2>' +
      '<p class="hv2-citypick__sub">Покажем расписание катков и тренеров вашего города.</p>' +
      '<div class="hv2-cityopts" id="hv2CityOpts"><div class="hv2-empty__text">Загрузка…</div></div>' +
    '</article>';
  }

  function renderTop() {
    var host = els.top;
    if (!state.data) return;
    var data = state.data;
    var cityId = data.client_session && data.client_session.city_id;
    var html = '';
    if (!cityId) {
      html = cityPickHtml();
      loadCitiesInto('hv2CityOpts');
    } else {
      var rec = upcomingBooking(data);
      if (rec) html = ticketHtml(rec);
      else {
        var p = activePass(data);
        if (p) html = passCardHtml(p);
        else {
          var cs = data.client_session || {};
          if (cs.primary_trainer_id) html = coachCardHtml(cs);
          else {
            var found = nearestSession(data);
            if (found) html = photoCardHtml(found);
          }
        }
      }
    }
    host.innerHTML = html || '';
    bindTopActions(host);
  }

  function bindTopActions(host) {
    host.querySelectorAll('[data-act]').forEach(function (el) {
      el.addEventListener('click', function (ev) {
        ev.preventDefault(); ev.stopPropagation();
        var act = el.getAttribute('data-act');
        if (act === 'nav') { haptic('light'); navigate(el.getAttribute('data-path')); }
        else if (act === 'map') { haptic('light'); openExternal(el.getAttribute('data-href')); }
        else if (act === 'share') { haptic('light'); shareUrl(el.getAttribute('data-url')); }
      });
    });
  }

  function shareUrl(url) {
    var w = tg();
    try {
      if (w && w.shareURL) { w.shareURL(url); return; }
      if (w && w.openTelegramLink) { w.openTelegramLink('https://t.me/share/url?url=' + encodeURIComponent(url)); return; }
    } catch (e) {}
    openExternal('https://t.me/share/url?url=' + encodeURIComponent(url));
  }

  /* ── «Лёд в городе» ──────────────────────────────────────── */
  function renderIce() {
    var data = state.data;
    var city = data.home && data.home.city;
    var rows = [];
    var moreHref = 'ice';
    var moreLabel = 'Все';
    if (city && city.upcoming && city.upcoming.length) {
      rows = city.upcoming.slice(0, 4);
      moreHref = city.upcoming_href || 'ice';
      moreLabel = city.upcoming_more || 'Все';
    } else {
      var ice = data.ice_teaser;
      if (ice && ice.sessions && ice.sessions.length) {
        rows = ice.sessions.slice(0, 4).map(function (s) {
          return {
            time: hhmm(s.starts_at_local), day: '', badge: hhmm(s.starts_at_local),
            place: s.arena_name, price: formatPrice(s.price_adult_minor, s.currency_code),
            arena_id: s.arena_id, session_id: s.session_id,
            href: 'arena?ref=' + s.arena_id + '&s=' + s.session_id,
          };
        });
        moreHref = 'ice';
      }
    }
    if (!rows.length) { els.iceSec.hidden = true; return; }
    els.iceSec.hidden = false;
    els.iceMore.setAttribute('href', moreHref);
    els.iceMore.textContent = moreLabel;
    els.ice.innerHTML = '<div class="hv2-rows hv2-fade-in">' + rows.map(function (r) {
      var when = r.badge || r.time;
      var sub = [r.day, r.price].filter(Boolean).join(' · ');
      return '<a class="hv2-row" href="' + esc(r.href || 'ice') + '">' +
        '<span class="hv2-row__time">' + esc(when) + '</span>' +
        '<span class="hv2-row__body"><span class="hv2-row__title">' + esc(r.place) + '</span>' +
        (sub ? '<span class="hv2-row__sub">' + esc(sub) + '</span>' : '') + '</span>' +
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="hv2-row__chev" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></a>';
    }).join('') + '</div>';
  }

  /* ── «Матчи» ─────────────────────────────────────────────── */
  function renderMatches() {
    var feed = (state.data.home && state.data.home.matches) || null;
    var items = (feed && feed.matches) || [];
    if (!items.length) { els.matchSec.hidden = true; return; }
    els.matchSec.hidden = false;
    if (feed.all_href) { els.matchMore.setAttribute('href', feed.all_href); }
    els.matches.innerHTML = '<div class="hv2-rows hv2-fade-in">' + items.slice(0, 4).map(function (m) {
      var logo = function (t) {
        return t && t.logo
          ? '<img class="hv2-match__logo" src="' + esc(t.logo) + '" alt="" loading="lazy">'
          : '<span class="hv2-match__logo hv2-match__logo--empty"></span>';
      };
      var when = '';
      try { when = new Date(m.starts_at).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); } catch (e) {}
      var score = m.result ? '<span style="font-weight:700">' + m.result.home_score + ' : ' + m.result.away_score + '</span> ' : '';
      return '<a class="hv2-match" href="' + esc(m.href || 'client-matches') + '">' +
        (m.sticker ? '<span class="hv2-match__sticker">' + esc(m.sticker) + '</span>' : '') +
        '<span class="hv2-match__time">' + esc(when) + '</span>' +
        '<span class="hv2-match__teams">' + logo(m.home) + esc(m.home && m.home.short || m.home && m.home.name || '') + ' ' + score + esc(m.away && m.away.short || m.away && m.away.name || '') + logo(m.away) + '</span>' +
        (m.city || m.arena ? '<span class="hv2-match__place">' + esc(m.city || m.arena) + '</span>' : '') +
      '</a>';
    }).join('') + '</div>';
  }

  /* ── «Ещё» ───────────────────────────────────────────────── */
  function renderMore() {
    var needs = (state.data.home && state.data.home.city && state.data.home.city.needs) || [];
    var coachRow = null;
    var cs = state.data.client_session || {};
    if (!cs.primary_trainer_id && cs.saved_trainers && cs.saved_trainers.length) {
      coachRow = { key: 'coach', title: 'Учиться с тренером', line: cs.saved_trainers.length + ' в избранном', href: 'client-saved-trainers' };
    }
    var rows = needs.slice(0, 5).map(function (n) {
      return { key: n.key, title: n.title, line: n.line, href: n.href };
    });
    if (coachRow) rows.push(coachRow);
    if (!rows.length) { els.moreSec.hidden = true; return; }
    els.moreSec.hidden = false;
    els.more.innerHTML = '<div class="hv2-rows">' + rows.map(function (r) {
      return '<a class="hv2-row" href="' + esc(r.href || 'ice') + '">' +
        '<span class="hv2-row__body"><span class="hv2-row__title">' + esc(r.title) + '</span>' +
        '<span class="hv2-row__sub">' + esc(r.line || '') + '</span></span>' +
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="hv2-row__chev" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></a>';
    }).join('') + '</div>';
  }

  /* ── Шапка ───────────────────────────────────────────────── */
  function renderHead() {
    var data = state.data;
    var city = data.home && data.home.city;
    var hour = new Date().getHours();
    var hello = hour < 5 ? 'Доброй ночи' : hour < 12 ? 'Доброе утро' : hour < 18 ? 'Добрый день' : 'Добрый вечер';
    els.kicker.textContent = hello;
    if (city && city.name) {
      els.cityLabel.textContent = city.name;
      els.title.textContent = city.kicker || ('Лёд в ' + city.name);
    } else {
      els.cityLabel.textContent = 'Город';
      els.title.textContent = 'Лёд рядом';
    }
  }

  /* ── Город: лист, геолокация ─────────────────────────────── */
  function openSheet() { els.sheet.hidden = false; loadCities(); }
  function closeSheet() { els.sheet.hidden = true; }

  function loadCities() {
    if (state.cities) { renderCityOpts(state.cities); return; }
    fetch('/api/public/ice/cities', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (d) {
        state.cities = (d && d.items) || [];
        renderCityOpts(state.cities);
      })
      .catch(function () { renderCityOpts([]); });
  }

  function cityCountLabel(c) {
    var n = Number(c.skate_count) || 0;
    if (n > 0) return n + ' ' + (n === 1 ? 'каток' : n < 5 ? 'катка' : 'катков');
    var tr = Number(c.trainer_count) || 0;
    return tr > 0 ? tr + ' ' + (tr === 1 ? 'тренер' : tr < 5 ? 'тренера' : 'тренеров') : '';
  }

  function renderCityOpts(cities) {
    var host = $('hv2CityOpts') || $('hv2CityList');
    if (!host) return;
    if (!cities.length) { host.innerHTML = '<div class="hv2-empty__text">Не удалось загрузить города.</div>'; return; }
    host.innerHTML = cities.map(function (c) {
      return '<button type="button" class="hv2-cityopt" data-city-id="' + c.id + '">' +
        '<span>' + esc(c.name) + '</span><span class="hv2-cityopt__count">' + esc(cityCountLabel(c)) + '</span></button>';
    }).join('');
    host.querySelectorAll('.hv2-cityopt').forEach(function (btn) {
      btn.addEventListener('click', function () {
        haptic('light');
        pickCity(Number(btn.getAttribute('data-city-id')));
      });
    });
  }

  function loadCitiesInto(hostId) {
    var host = $(hostId);
    if (!host) return;
    if (state.cities) { host.innerHTML = cityOptsHtml(state.cities); bindCityOpts(host); return; }
    fetch('/api/public/ice/cities', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (d) {
        state.cities = (d && d.items) || [];
        host.innerHTML = cityOptsHtml(state.cities);
        bindCityOpts(host);
      })
      .catch(function () { host.innerHTML = '<div class="hv2-empty__text">Не удалось загрузить города.</div>'; });
  }
  function cityOptsHtml(cities) {
    if (!cities.length) return '<div class="hv2-empty__text">Города не найдены.</div>';
    return cities.map(function (c) {
      return '<button type="button" class="hv2-cityopt" data-city-id="' + c.id + '">' +
        '<span>' + esc(c.name) + '</span><span class="hv2-cityopt__count">' + esc(cityCountLabel(c)) + '</span></button>';
    }).join('');
  }
  function bindCityOpts(host) {
    host.querySelectorAll('.hv2-cityopt').forEach(function (btn) {
      btn.addEventListener('click', function () { haptic('light'); pickCity(Number(btn.getAttribute('data-city-id'))); });
    });
  }

  function pickCity(cityId) {
    fetch('/api/webapp/client/session/catalog-filters', {
      method: 'PATCH',
      headers: headersJson(),
      body: JSON.stringify({ city_id: cityId }),
    }).then(function (r) {
      if (!r.ok) throw new Error('city ' + r.status);
      haptic('success');
      boot();
    }).catch(function () {
      var w = tg();
      try { if (w && w.HapticFeedback && w.HapticFeedback.notificationOccurred) w.HapticFeedback.notificationOccurred('error'); } catch (e) {}
    });
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

  /* ── Загрузка ────────────────────────────────────────────── */
  function boot() {
    els.skel.style.display = '';
    fetchBootstrap().then(function (data) {
      state.data = data;
      renderHead();
      renderTop();
      renderIce();
      renderMatches();
      renderMore();
      els.skel.style.display = 'none';
      els.top.classList.add('hv2-fade-in');
    }).catch(function () {
      els.skel.innerHTML = '<div class="hv2-empty"><div class="hv2-empty__title">Нет сети</div><div class="hv2-empty__text">Проверьте подключение и попробуйте ещё раз.</div><button type="button" class="hv2-btn hv2-btn--dark" id="hv2Retry" style="max-width:220px">Повторить</button></div>';
      var b = $('hv2Retry');
      if (b) b.addEventListener('click', function () { els.skel.innerHTML = '<div class="hv2-skel__card"></div><div class="hv2-skel__row"></div>'; boot(); });
    });
  }

  function init() {
    els.top = $('hv2Top'); els.ice = $('hv2Ice'); els.iceSec = $('hv2IceSec'); els.iceMore = $('hv2IceMore');
    els.matchSec = $('hv2MatchSec'); els.matchMore = $('hv2MatchMore'); els.matches = $('hv2Matches');
    els.moreSec = $('hv2MoreSec'); els.more = $('hv2More'); els.skel = $('hv2Skel');
    els.cityLabel = $('hv2CityLabel'); els.hello = $('hv2Hello'); els.kicker = $('hv2Kicker'); els.title = $('hv2Title');
    els.sheet = $('hv2Sheet'); els.cityList = $('hv2CityList');
    $('hv2City').addEventListener('click', function () { haptic('light'); openSheet(); });
    $('hv2Geo').addEventListener('click', function () { haptic('light'); geoPick(); });
    $('hv2Sheet').addEventListener('click', function (ev) { if (ev.target === els.sheet) closeSheet(); });
    els.sheet.querySelectorAll('[data-close]').forEach(function (b) { b.addEventListener('click', closeSheet); });
    // Тап по строкам/карточкам — навигация через ClientShell (плавный переход оболочки).
    document.addEventListener('click', function (ev) {
      var a = ev.target.closest && ev.target.closest('a.hv2-row, a.hv2-match, a.hv2-sec__more');
      if (!a) return;
      var path = a.getAttribute('href');
      if (!path || path.indexOf('http') === 0 || path.indexOf('#') === 0) return;
      if (window.ClientShell && typeof window.ClientShell.navigate === 'function') {
        ev.preventDefault();
        navigate(path);
      }
    });
    boot();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
