/* TASK-446 (5.2): «Я здесь» на страницах Лёд / каток / «Я» / главная — грузится
   оболочкой только при redesign_s5. Живые строки загрузки, блок «Сейчас» на
   карточке катка, карточка сезона в «Я». PDEC-040 батч C: карточки «Ты на
   катке?» и «Твоя компания» на старой главной (слот #hubNow, данные —
   glide:hub-bootstrap / __hubBootstrap) и полка значков на старом «Я»
   (glide:me-data / __clientMeData). Страница без флага не видит файла вообще. */
(function () {
  'use strict';

  var LOAD_WORDS = { 1: 'Сейчас свободно', 2: 'Сейчас в меру', 3: 'Сейчас людно' };
  var REFRESH_MS = 60000;

  function tg() { return window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null; }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function headers() {
    var h = { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': (tg() && tg().initData) || '' };
    if (window.GlideProfileId) h['X-Profile-Id'] = String(window.GlideProfileId);
    return h;
  }
  function stateApi(ids, focus, arenaId) {
    var q = '/api/webapp/client/checkins/state?session_ids=' + encodeURIComponent(ids.join(','));
    if (focus != null) q += '&focus=' + encodeURIComponent(String(focus));
    if (arenaId != null) q += '&arena_id=' + encodeURIComponent(String(arenaId));
    return fetch(q, { headers: headers() }).then(function (r) {
      return r.ok ? r.json() : null;
    }).catch(function () { return null; });
  }
  function postIntent(sessionId, kind) {
    try {
      fetch('/api/webapp/client/checkins/intent', {
        method: 'POST', headers: headers(), keepalive: true,
        body: JSON.stringify({ session_id: sessionId, kind: kind }),
      }).catch(function () {});
    } catch (e) { /* не мешаем «Маршруту» */ }
  }
  function plural(n, one, few, many) {
    n = Math.abs(n) % 100;
    var n10 = n % 10;
    if (n > 10 && n < 20) return many;
    if (n10 > 1 && n10 < 5) return few;
    if (n10 === 1) return one;
    return many;
  }
  function agoText(min) {
    if (min == null) return '';
    if (min < 1) return 'только что';
    return min + ' ' + plural(min, 'минуту', 'минуты', 'минут') + ' назад';
  }
  function liveText(live) {
    if (!live || !live.level) return '';
    var t = LOAD_WORDS[live.level] || '';
    if (!t) return '';
    var n = live.count || 0;
    t += ' · ' + n + ' ' + plural(n, 'отметка', 'отметки', 'отметок');
    var ago = agoText(live.last_min);
    if (ago) t += ', ' + ago;
    return t;
  }
  function barsHtml(level) {
    var out = '<span class="cil__bars" aria-hidden="true">';
    for (var i = 1; i <= 3; i++) out += '<i class="' + (i <= level ? 'on' : '') + '"></i>';
    return out + '</span>';
  }
  function openSheet(sessionId, arenaName, st, extra) {
    if (!window.GlideCheckin) return;
    extra = extra || {};
    window.GlideCheckin.open({
      session_id: sessionId,
      arena_id: extra.arena_id || null,
      company: !!extra.company,
      streak_weeks: extra.streak_weeks || null,
      arena_name: arenaName,
      checkin_id: st && st.checkin_id || null,
      load_level: st && st.load_level || null,
      season_days: st && st.checked_in ? st.season_days : null,
      onDone: extra.onDone || null,
      onLive: extra.onLive || null,
    });
  }
  function pageKey() {
    var p = (location.pathname || '').replace(/\/$/, '');
    return (p.split('/').pop() || '').replace(/\.html$/, '');
  }

  /* ── Вкладка «Лёд»: строки сеансов ──────────────────────────────────── */

  var iceState = { at: 0, sessions: {}, me: null };

  function iceSessionIds() {
    var ids = [];
    document.querySelectorAll('a.ice-board[data-session-id]').forEach(function (a) {
      var id = parseInt(a.getAttribute('data-session-id'), 10);
      if (id && ids.indexOf(id) < 0) ids.push(id);
    });
    return ids;
  }

  function iceRefresh(force) {
    var ids = iceSessionIds();
    if (!ids.length) return Promise.resolve();
    if (!force && Date.now() - iceState.at < REFRESH_MS && iceState.done) {
      decorateIce();
      return Promise.resolve();
    }
    return stateApi(ids).then(function (j) {
      iceState.at = Date.now();
      iceState.done = true;
      if (j && j.sessions) iceState.sessions = j.sessions;
      if (j && j.me) iceState.me = j.me;
      decorateIce();
    });
  }

  function decorateIce() {
    document.querySelectorAll('a.ice-board[data-session-id]').forEach(function (a) {
      var id = a.getAttribute('data-session-id');
      var st = iceState.sessions[id];
      var wrap = a.closest('.ice-board-wrap') || a.parentNode;
      if (!wrap) return;
      var old = wrap.querySelector(':scope > .cil');
      if (old) old.remove();
      if (!st || !st.ongoing) return;
      var nameEl = a.querySelector('.ice-board__name, .ice-board__title');
      var arenaName = nameEl ? nameEl.textContent.trim() : 'катке';
      var live = liveText(st.live);
      var box = document.createElement('div');
      box.className = 'cil';
      box.innerHTML =
        (live ? '<div class="cil__live">' + barsHtml(st.live.level) + '<span>' + esc(live) + '</span></div>' : '') +
        '<button type="button" class="cil__btn ga-press">' + (st.checked_in ? 'Отмечено' : '✓ Я здесь') + '</button>';
      box.querySelector('.cil__btn').addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        openSheet(parseInt(id, 10), arenaName, st);
      });
      wrap.appendChild(box);
    });
  }

  function bootIce() {
    iceRefresh(true);
    var t = null;
    var mo = new MutationObserver(function () {
      if (t) clearTimeout(t);
      t = setTimeout(function () { iceRefresh(); }, 150);
    });
    mo.observe(document.body, { childList: true, subtree: true });
    setInterval(function () {
      if (!document.hidden) iceRefresh(true);
    }, REFRESH_MS);
  }

  /* ── Карточка катка: блок «Сейчас …» + «Маршрут» → intent ────────────── */

  function urlSessionId() {
    try {
      var v = new URLSearchParams(location.search).get('s');
      var n = parseInt(v, 10);
      return n > 0 ? n : null;
    } catch (e) { return null; }
  }

  function urlArenaId() {
    try {
      var v = new URLSearchParams(location.search).get('ref');
      var n = parseInt(v, 10);
      return n > 0 ? n : null;
    } catch (e) { return null; }
  }

  function arenaSessionIds() {
    var ids = [];
    document.querySelectorAll('[data-session-id]').forEach(function (el) {
      var n = parseInt(el.getAttribute('data-session-id'), 10);
      if (n > 0 && ids.indexOf(n) < 0) ids.push(n);
    });
    var focus = urlSessionId();
    if (focus && ids.indexOf(focus) < 0) ids.unshift(focus);
    return ids.slice(0, 50);
  }

  function arenaName() {
    var el = document.querySelector('.arena-hero__name, .arena-name, h1, .header-title');
    return el ? el.textContent.trim() : 'катке';
  }

  /* TASK-452 (5.5): «обычно» из истории отметок — сетка «Когда свободнее» +
     blended-уровень на шкалах сеансов (заменяет чистую admin-оценку). */
  var USUAL_METER_LABEL = {
    calm: 'Обычно свободно — можно без спешки',
    medium: 'Обычно народу в меру',
    busy: 'Обычно людно — билет лучше взять заранее',
  };
  var USUAL_WORD = { calm: 'свободно', medium: 'в меру', busy: 'людно' };

  function patchUsualMeters(sessions) {
    if (!sessions) return;
    document.querySelectorAll('[data-session-id]').forEach(function (el) {
      var st = sessions[el.getAttribute('data-session-id')];
      if (!st || !st.usual || !USUAL_WORD[st.usual.key]) return;
      el.querySelectorAll('.arena-load').forEach(function (m) {
        m.setAttribute('data-level', st.usual.key);
        m.setAttribute('aria-label', USUAL_METER_LABEL[st.usual.key] || '');
      });
      el.querySelectorAll('small').forEach(function (sm) {
        var t = (sm.textContent || '').trim();
        if (t.indexOf('обычно') === 0) sm.textContent = 'обычно ' + USUAL_WORD[st.usual.key];
      });
    });
  }

  var usualBlock = null;
  var usualBlockSig = '';
  function decorateUsual(g, anchor) {
    var sig = g ? JSON.stringify(g) : '';
    /* arena-card перерисовывает секцию сеансов и выносит наш блок из DOM:
       кэш по подписи считается, только пока блок реально на странице. */
    if (usualBlock && usualBlock.isConnected && sig === usualBlockSig) return;
    if (usualBlock) { usualBlock.remove(); usualBlock = null; usualBlockSig = ''; }
    if (!g || !anchor || !(g.cells || []).length) return;
    usualBlockSig = sig;
    var total = Number(g.total) || 0;
    var byN = total > 0
      ? 'по ' + total + ' ' + plural(total, 'отметке', 'отметкам', 'отметкам')
      : 'по правилам катка';
    var head = '<span></span>' + (g.weekdays || []).map(function (d) {
      return '<b>' + esc(d) + '</b>';
    }).join('');
    var body = (g.cells || []).map(function (row, i) {
      var label = (g.buckets || [])[i];
      return '<span>' + esc(label != null ? String(label) : '') + '</span>' +
        (row || []).map(function (lv) { return '<i class="h' + (lv || 0) + '"></i>'; }).join('');
    }).join('');
    usualBlock = document.createElement('div');
    usualBlock.className = 'cil-usual';
    usualBlock.innerHTML =
      '<div class="cil-usual__head"><div class="cil-usual__t">Когда свободнее</div>' +
      '<div class="cil-usual__n">' + esc(byN) + '</div></div>' +
      (g.best ? '<div class="cil-usual__best">' + esc(g.best) + '</div>' : '') +
      '<div class="cil-usual__grid">' + head + body + '</div>' +
      '<div class="cil-usual__legend">' +
      '<span><i class="h1"></i>свободно</span>' +
      '<span><i class="h2"></i>в меру</span>' +
      '<span><i class="h3"></i>людно</span>' +
      '<span><i class="h0"></i>мало данных</span></div>';
    anchor.parentNode.insertBefore(usualBlock, anchor);
  }

  var arenaBlock = null;
  function decorateArena(j) {
    var sessions = j && j.sessions ? j.sessions : {};
    var focus = urlSessionId();
    var picked = null;
    if (focus && sessions[String(focus)] && sessions[String(focus)].ongoing) picked = String(focus);
    if (!picked) {
      Object.keys(sessions).some(function (k) {
        if (sessions[k].ongoing) { picked = k; return true; }
        return false;
      });
    }
    var host = document.getElementById('arenaRows');
    var anchor = host ? host.parentNode : null;
    patchUsualMeters(sessions);
    /* «Когда свободнее» — до «Сейчас», и не зависит от идущего сеанса. */
    decorateUsual(j.arena_usual, anchor);
    if (arenaBlock) { arenaBlock.remove(); arenaBlock = null; }
    if (!picked || !anchor) return;
    var st = sessions[picked];
    var live = st.live;
    var title, parts = [];
    if (live && live.level) {
      title = LOAD_WORDS[live.level] || '';
      parts.push((live.count || 0) + ' ' + plural(live.count || 0, 'отметка', 'отметки', 'отметок') + ' за 40 минут');
    } else {
      title = 'Отметок пока нет';
    }
    if (st.ends_local) parts.push('сеанс до ' + st.ends_local);
    arenaBlock = document.createElement('div');
    arenaBlock.className = 'cil-arena';
    arenaBlock.innerHTML =
      '<div class="cil-arena__dot"></div>' +
      '<div class="cil-arena__txt"><div class="cil-arena__t">' + esc(title) + '</div>' +
      (parts.length ? '<div class="cil-arena__s">' + parts.map(function (s, i) { return '<span>' + (i ? '· ' : '') + esc(s) + '</span>'; }).join(' ') + '</div>' : '') + '</div>' +
      '<button type="button" class="cil__btn ga-press">' + (st.checked_in ? 'Отмечено' : '✓ Я здесь') + '</button>';
    arenaBlock.querySelector('.cil__btn').addEventListener('click', function () {
      openSheet(parseInt(picked, 10), arenaName(), st);
    });
    anchor.parentNode.insertBefore(arenaBlock, anchor);
    /* «Маршрут» → intent route (не мешаем переходу) */
    if (!decorateArena._routeBound) {
      decorateArena._routeBound = true;
      document.addEventListener('click', function (ev) {
        var a = ev.target && ev.target.closest ? ev.target.closest('a[href*="yandex.by/maps"], a[href*="yandex.ru/maps"], a[href*="maps.yandex"]') : null;
        if (!a) return;
        var sid = urlSessionId() || (arenaBlock && arenaBlock.getAttribute('data-sid'));
        if (sid) postIntent(parseInt(sid, 10), 'route');
      }, true);
    }
    arenaBlock.setAttribute('data-sid', picked);
  }

  function bootArena() {
    var run = function () {
      var ids = arenaSessionIds();
      if (!ids.length) return;
      stateApi(ids, urlSessionId(), urlArenaId()).then(function (j) { if (j) decorateArena(j); });
    };
    run();
    var t = null;
    var mo = new MutationObserver(function () {
      if (t) clearTimeout(t);
      t = setTimeout(run, 200);
    });
    mo.observe(document.body, { childList: true, subtree: true });
    setInterval(function () { if (!document.hidden) run(); }, REFRESH_MS);
  }

  /* ── Главная клиента (старая): «Ты на катке?» + «Твоя компания» ─────── */
  /* PDEC-040 батч C: карточки ставим в слот #hubNow над карточкой HubHome —
     тот же приоритет, что на главной v2 (on_ice главнее любой). hubNow
     перерисовывается HubHome (replaceChildren) — карточки возвращаем наблюдателем. */

  var hubCard = null;
  var compCard = null;
  var lastHub = null;
  var homeBadgeShown = false;

  function hubSlot() { return document.getElementById('hubNow'); }

  function fmtLeft(min) {
    if (min == null) return '';
    var h = Math.floor(min / 60), m = min % 60;
    if (h && m) return h + ' ч ' + m + ' мин';
    if (h) return h + ' ч';
    return m + ' мин';
  }

  function companyShare() {
    return !!((lastHub && lastHub.home) || {}).company_share;
  }

  /* «Позвать» — лист GlideShareSheet (заглушка share-sheet-lazy догружает
     настоящий); запасной путь — подготовленная ссылка invite_url. */
  function openInviteSheet(arenaId, sessionId, label, place) {
    var sheet = window.GlideShareSheet;
    if (!sheet || !arenaId) return false;
    try {
      sheet.open({
        ref: arenaId,
        sessionId: sessionId != null ? sessionId : null,
        slots: sessionId != null ? [{ id: sessionId, label: label || '' }] : [],
        invite: true,
        company: companyShare(),
        context: 'client_home',
        placeName: place || '',
      });
      return true;
    } catch (e) { return false; }
  }
  function openExternal(url) {
    if (!url) return;
    var t = tg();
    if (t && typeof t.openTelegramLink === 'function') { t.openTelegramLink(url); return; }
    if (t && typeof t.openLink === 'function') { t.openLink(url); return; }
    window.open(url, '_blank');
  }

  function onIceCardHtml(o) {
    var live = o.live;
    var bits = [];
    if (o.ends_local) bits.push('до ' + o.ends_local);
    var liveTxt = liveText(live);
    if (liveTxt) bits.push(liveTxt);
    var checked = !!o.checked_in;
    var stats =
      '<div class="cil-hub__stats">' +
        '<div class="cil-hub__row">' +
          '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><path d="M12 3c2 4-3 5-3 9a3 3 0 006 0c0-2-1-3-1-3s4 2 4 6a6 6 0 11-12 0c0-6 6-8 6-12z"/></svg>' +
          '<div class="cil-hub__tx"><div class="cil-hub__rt">Серия: ' + (o.streak_weeks || 0) + ' ' + plural(o.streak_weeks || 0, 'неделя', 'недели', 'недель') + ' подряд</div>' +
          '<div class="cil-hub__rs">' + (o.has_this_week ? 'Отметка этой недели засчитана' : 'Отметься сегодня — будет ' + ((o.streak_weeks || 0) + 1) + '-я') +
          (o.next_badge ? ' · до «' + esc(o.next_badge.name_gen || o.next_badge.name) + '» — ' + o.next_badge.remaining + ' ' + plural(o.next_badge.remaining, 'неделя', 'недели', 'недель') : '') +
          '</div></div>' +
          weekPills(o.streak_weeks || 0) +
        '</div>' +
        '<div class="cil-hub__row">' +
          '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" aria-hidden="true"><path d="M12 4v4m0 0-2 2m2-2 2 2M4 20l2-9h12l2 9z"/></svg>' +
          '<div class="cil-hub__tx"><div class="cil-hub__rt">На льду ' + (o.season_days || 0) + ' ' + plural(o.season_days || 0, 'раз', 'раза', 'раз') + ' за сезон</div>' +
          '<div class="cil-hub__rs">' + (checked ? 'Отметка засчитана' : 'Сегодня будет ' + ((o.season_days || 0) + 1) + '-й') + '</div></div>' +
        '</div>' +
      '</div>';
    return '<a class="cil-hub__hit" href="arena?ref=' + encodeURIComponent(o.arena_id || '') + '&s=' + encodeURIComponent(o.session_id || '') + '">' +
      '<span class="cil-hub__chip"><span class="cil-hub__dot"></span>Идёт сеанс' + (o.minutes_left != null ? ' · ещё ' + esc(fmtLeft(o.minutes_left)) : '') + '</span>' +
      '<span class="cil-hub__name">' + esc(o.arena_name || 'Каток') + '</span>' +
      (bits.length ? '<span class="cil-hub__sub">' + esc(bits.join(' · ')) + '</span>' : '') +
      '</a>' +
      stats +
      '<div class="cil-hub__btns">' +
        '<button type="button" class="cil-hub__btn' + (checked ? ' cil-hub__btn--soft' : ' cil-hub__btn--yellow') + ' ga-press" data-act="checkin">' +
          (checked ? 'Отмечено · ' + (o.season_days || 0) + '-й раз' : '✓ Я здесь') + '</button>' +
        (o.invite_url || o.arena_id
          ? '<button type="button" class="cil-hub__btn cil-hub__btn--soft ga-press" data-act="invite">Позвать сюда</button>'
          : '') +
      '</div>';
  }

  /* «Аня и Дима», «Аня, Дима и Света» — последнее имя через «и». */
  function namesJoin(arr) {
    return arr.length > 1 ? arr.slice(0, -1).join(', ') + ' и ' + arr[arr.length - 1] : (arr[0] || '');
  }

  function compCardHtml(c) {
    var names = (c.going_names || []).slice(0, 3);
    var avas = names.map(function (n) {
      return '<span class="cil-comp__ava">' + esc(String(n || '?').trim().charAt(0).toUpperCase()) + '</span>';
    }).join('');
    var count = c.going_count || names.length || 0;
    var namesLine = names.length
      ? (count > names.length ? names.join(', ') + ' и ещё ' + (count - names.length) : namesJoin(names)) +
        ' ' + plural(count, 'идёт', 'идут', 'идут')
      : 'Пока только ты — позови ещё';
    var btns;
    if (c.my_status === 'maybe') {
      btns = '<button type="button" class="cil-hub__btn cil-hub__btn--yellow ga-press" data-act="going">Иду</button>';
    } else if (c.my_status === 'going') {
      btns = '<button type="button" class="cil-hub__btn cil-hub__btn--soft ga-press" data-act="open">Ты идёшь ✓</button>' +
        '<button type="button" class="cil-hub__btn cil-hub__btn--soft ga-press" data-act="invite">Позвать ещё</button>' +
        '<button type="button" class="cil-hub__btn cil-hub__btn--soft ga-press" data-act="open">Открыть</button>';
    } else {
      btns = '<button type="button" class="cil-hub__btn cil-hub__btn--soft ga-press" data-act="invite">Позвать ещё</button>' +
        '<button type="button" class="cil-hub__btn cil-hub__btn--soft ga-press" data-act="open">Открыть</button>';
    }
    var meta = [c.arena_name, c.crowd_line].filter(Boolean).join(' · ');
    return '<div class="cil-comp__chip"><span class="cil-comp__dot"></span>Твоя компания' +
      (c.day_label || c.starts_local ? ' · ' + esc([c.day_label, c.starts_local].filter(Boolean).join(' ')) : '') + '</div>' +
      '<div class="cil-comp__names">' + esc(namesLine) + '</div>' +
      (meta ? '<div class="cil-comp__meta">' + esc(meta) + '</div>' : '') +
      (avas ? '<div class="cil-comp__avas">' + avas + '<span class="cil-comp__cnt">Идут ' + esc(count) + '</span></div>' : '') +
      '<div class="cil-hub__btns">' + btns + '</div>';
  }

  function wireCompCard(c) {
    if (!compCard) return;
    compCard.querySelectorAll('[data-act]').forEach(function (b) {
      b.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var act = b.getAttribute('data-act');
        if (act === 'going') {
          b.disabled = true;
          var u = tg() && tg().initDataUnsafe && tg().initDataUnsafe.user;
          fetch('/api/public/ice-companies/' + encodeURIComponent(c.code) + '/responses', {
            method: 'POST', headers: headers(),
            body: JSON.stringify({ status: 'going', display_name: (u && u.first_name) || 'Я' }),
          }).then(function (r) {
            if (!r.ok) { b.disabled = false; return; }
            c.my_status = 'going';
            compCard.innerHTML = compCardHtml(c);
            wireCompCard(c);
          }).catch(function () { b.disabled = false; });
        } else if (act === 'invite') {
          if (!openInviteSheet(c.arena_id, c.session_id, [c.day_label, c.starts_local].filter(Boolean).join(' '), c.arena_name)) {
            openExternal(c.page_url);
          }
        } else if (act === 'open') {
          openExternal(c.page_url);
        }
      });
    });
  }

  function wireHubCard(o) {
    if (!hubCard) return;
    hubCard.querySelectorAll('[data-act]').forEach(function (b) {
      b.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var act = b.getAttribute('data-act');
        if (act === 'checkin') {
          openSheet(o.session_id, o.arena_name || 'катке', {
            checkin_id: o.checked_in ? o.checkin_id : null,
            load_level: o.load_level,
            checked_in: o.checked_in,
            season_days: o.season_days,
          }, {
            arena_id: o.arena_id,
            company: companyShare(),
            streak_weeks: o.streak_weeks,
            onDone: function () { refreshHomeCheckin(o.session_id); },
            onLive: function (live) { o.live = live; decorateHome(lastHub); },
          });
        } else if (act === 'invite') {
          if (!openInviteSheet(o.arena_id, o.session_id, 'до ' + (o.ends_local || ''), o.arena_name)) {
            openExternal(o.invite_url);
          }
        }
      });
    });
  }

  /* Карточки — первыми в #hubNow: hub, затем компания, затем карточка HubHome.
     replaceChildren() хаба их выносит — наблюдатель возвращает на место. DOM
     трогаем только при реальном рассинхроне: insertBefore того же узла — тоже
     мутация, и наблюдатель зациклится на собственных вставках. */
  function pinHubCards() {
    var slot = hubSlot();
    if (!slot) return;
    var i = 0, ok = true;
    if (hubCard) { ok = slot.children[i] === hubCard; i++; }
    if (ok && compCard) ok = slot.children[i] === compCard;
    if (ok) return;
    if (compCard) slot.insertBefore(compCard, slot.firstChild);
    if (hubCard) slot.insertBefore(hubCard, slot.firstChild);
  }

  function maybeOpenHomeBadges(home) {
    var p = home && home.pending_badges;
    if (homeBadgeShown || !Array.isArray(p) || !p.length) return;
    homeBadgeShown = true;
    var go = function () {
      if (!window.GlideBadgeAward) return;
      window.GlideBadgeAward.open({
        badges: p,
        onClose: function (keys) {
          fetch('/api/webapp/client/badges/seen', {
            method: 'POST', headers: headers(),
            body: JSON.stringify({ keys: keys }),
          }).catch(function () {});
        },
      });
    };
    /* Ассеты едут тем же ленивым пакетом до этого файла — почти всегда уже есть. */
    if (window.GlideBadgeAward && window.GlideBadgeArt) { go(); return; }
    var tries = 0;
    var iv = setInterval(function () {
      tries++;
      if (window.GlideBadgeAward && window.GlideBadgeArt) { clearInterval(iv); go(); }
      else if (tries > 40) clearInterval(iv);
    }, 50);
  }

  function decorateHome(hub) {
    var slot = hubSlot();
    if (!slot) return;
    lastHub = hub;
    var home = (hub && hub.home) || {};
    var o = home.on_ice;
    if (o) {
      if (!hubCard) { hubCard = document.createElement('div'); hubCard.className = 'cil-hub'; }
      hubCard.innerHTML = onIceCardHtml(o);
      wireHubCard(o);
    } else if (hubCard) { hubCard.remove(); hubCard = null; }
    /* «Твоя компания» — сегодняшняя первая, как на главной v2. */
    var list = Array.isArray(home.companies) ? home.companies : [];
    var comp = null;
    for (var i = 0; i < list.length; i++) {
      if (list[i] && list[i].day_label === 'сегодня') { comp = list[i]; break; }
    }
    if (!comp) comp = list[0] || null;
    if (comp) {
      if (!compCard) { compCard = document.createElement('div'); compCard.className = 'cil-comp'; }
      compCard.innerHTML = compCardHtml(comp);
      wireCompCard(comp);
    } else if (compCard) { compCard.remove(); compCard = null; }
    pinHubCards();
    maybeOpenHomeBadges(home);
  }

  /* После отметки лист шлёт glide:checkin-done — карточку обновляем из state,
     без повторного bootstrap. */
  function refreshHomeCheckin(sessionId) {
    if (!lastHub || !lastHub.home || !lastHub.home.on_ice) return;
    var sid = sessionId || lastHub.home.on_ice.session_id;
    stateApi([sid], sid).then(function (j) {
      if (!j || !lastHub || !lastHub.home || !lastHub.home.on_ice) return;
      var st = (j.sessions || {})[sid] || {};
      var o = lastHub.home.on_ice;
      if ('checked_in' in st) o.checked_in = st.checked_in;
      if ('checkin_id' in st) o.checkin_id = st.checkin_id;
      if ('load_level' in st) o.load_level = st.load_level;
      if ('live' in st) o.live = st.live;
      if (j.me) {
        if ('season_days' in j.me) o.season_days = j.me.season_days;
        if ('streak_weeks' in j.me) o.streak_weeks = j.me.streak_weeks;
        if ('has_this_week' in j.me) o.has_this_week = j.me.has_this_week;
      }
      decorateHome(lastHub);
    });
  }

  function bootHome() {
    if (window.__hubBootstrap) decorateHome(window.__hubBootstrap);
    window.addEventListener('glide:hub-bootstrap', function (ev) {
      decorateHome((ev && ev.detail) || window.__hubBootstrap);
    });
    var slot = hubSlot();
    if (slot && window.MutationObserver) {
      new MutationObserver(function () { pinHubCards(); }).observe(slot, { childList: true });
    }
  }

  /* ── «Я»: карточка сезона + полка значков ───────────────────────────── */

  function weekPills(streak) {
    var out = '';
    for (var i = 0; i < 4; i++) out += '<i class="' + (i < Math.min(4, streak) ? 'on' : '') + '"></i>';
    return '<span class="cil-weeks">' + out + '</span>';
  }

  function decorateMe(j) {
    var root = document.getElementById('meRoot');
    if (!root) return;
    var old = root.querySelector(':scope > .cil-me');
    if (old) old.remove();
    var me = j && j.me ? j.me : {};
    var box = document.createElement('div');
    box.className = 'cil-me';
    if (!me.season_days) {
      box.innerHTML =
        '<div class="cil-me__card"><div class="cil-me__kick">Сезон</div>' +
        '<div class="cil-me__big cil-me__big--muted">Сезон ещё не начат</div>' +
        '<div class="cil-me__sub">Отметься «Я здесь» на сеансе — это будет первый раз</div></div>';
    } else {
      var helped = me.helped >= 3
        ? '<div class="cil-me__card cil-me__card--help">' +
          '<div class="cil-me__kick"><svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M5 3v18M5 4h12l-3 4 3 4H5"/></svg> Помог выбрать время ' + me.helped + ' ' + plural(me.helped, 'раз', 'раза', 'раз') + '</div>' +
          '<div class="cil-me__sub">Столько раз люди открывали сеанс, где была видна твоя отметка о загрузке</div></div>'
        : '';
      box.innerHTML =
        '<div class="cil-me__card"><div class="cil-me__kick">Сезон</div>' +
        '<div class="cil-me__big">' + me.season_days + ' ' + plural(me.season_days, 'раз', 'раза', 'раз') + ' на льду</div>' +
        '<div class="cil-me__streak">' + weekPills(me.streak_weeks || 0) +
        '<span>Серия ' + (me.streak_weeks || 0) + ' ' + plural(me.streak_weeks || 0, 'неделя', 'недели', 'недель') + ' подряд</span></div></div>' +
        helped;
    }
    root.insertBefore(box, root.firstChild);
  }

  /* Полка значков (PDEC-040 батч C): разметка — общий GlideBadgeShelf, данные —
     свежий ответ /client/me (client-me.js кладёт __clientMeData + шлёт событие).
     client-me перерисовывает meRoot — полку возвращаем тем же наблюдателем. */
  var meBadgesSig = '';
  var meBadgesBox = null;
  function decorateMeBadges() {
    var root = document.getElementById('meRoot');
    if (!root) return;
    var data = window.__clientMeData;
    var list = data && Array.isArray(data.badges) ? data.badges : [];
    var sig = JSON.stringify(list);
    if (meBadgesBox && meBadgesBox.isConnected && sig === meBadgesSig) return;
    if (meBadgesBox) { meBadgesBox.remove(); meBadgesBox = null; meBadgesSig = ''; }
    if (!window.GlideBadgeShelf || !list.length) return;
    var html = window.GlideBadgeShelf.shelfHtml(list);
    if (!html) return;
    meBadgesSig = sig;
    meBadgesBox = document.createElement('div');
    meBadgesBox.className = 'cil-badges';
    meBadgesBox.innerHTML = html;
    window.GlideBadgeShelf.wireShelf(meBadgesBox, list);
    /* После карточки сезона — тот же порядок блоков, что в «Я» v2. */
    var season = root.querySelector(':scope > .cil-me');
    if (season) root.insertBefore(meBadgesBox, season.nextSibling);
    else root.insertBefore(meBadgesBox, root.firstChild);
  }

  function bootMe() {
    var run = function () {
      stateApi([], null).then(function (j) { if (j) decorateMe(j); });
      decorateMeBadges();
    };
    /* client-me перерисовывает meRoot — карточки возвращаем после каждого рендера. */
    var t = null;
    var mo = new MutationObserver(function () {
      if (t) clearTimeout(t);
      t = setTimeout(run, 200);
    });
    var root = document.getElementById('meRoot');
    if (root) mo.observe(root, { childList: true });
    window.addEventListener('glide:me-data', function () { decorateMeBadges(); });
    run();
  }

  window.addEventListener('glide:checkin-done', function () {
    var k = pageKey();
    if (k === 'ice') iceRefresh(true);
    if (k === 'client-me') bootMe();
    if (k === 'client-home') refreshHomeCheckin();
  });

  var key = pageKey();
  if (key === 'ice') bootIce();
  else if (key === 'arena') bootArena();
  else if (key === 'client-me') bootMe();
  else if (key === 'client-home') bootHome();
})();
