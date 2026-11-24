/* TASK-446 (5.2): «Я здесь» на страницах Лёд / каток / «Я» — грузится оболочкой
   только при redesign_s5. Живые строки загрузки, блок «Сейчас» на карточке катка,
   карточка сезона в «Я». Страница без флага не видит этого файла вообще. */
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
  function stateApi(ids, focus) {
    var q = '/api/webapp/client/checkins/state?session_ids=' + encodeURIComponent(ids.join(','));
    if (focus != null) q += '&focus=' + encodeURIComponent(String(focus));
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
  function openSheet(sessionId, arenaName, st) {
    if (!window.GlideCheckin) return;
    window.GlideCheckin.open({
      session_id: sessionId,
      arena_name: arenaName,
      checkin_id: st && st.checkin_id || null,
      load_level: st && st.load_level || null,
      season_days: st && st.checked_in ? st.season_days : null,
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
      stateApi(ids, urlSessionId()).then(function (j) { if (j) decorateArena(j); });
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

  /* ── «Я»: карточка сезона ───────────────────────────────────────────── */

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

  function bootMe() {
    var run = function () {
      stateApi([], null).then(function (j) { if (j) decorateMe(j); });
    };
    /* client-me перерисовывает meRoot — карточку возвращаем после каждого рендера. */
    var t = null;
    var mo = new MutationObserver(function () {
      if (t) clearTimeout(t);
      t = setTimeout(run, 200);
    });
    var root = document.getElementById('meRoot');
    if (root) mo.observe(root, { childList: true });
    run();
  }

  window.addEventListener('glide:checkin-done', function () {
    if (pageKey() === 'ice') iceRefresh(true);
    if (pageKey() === 'client-me') bootMe();
  });

  var key = pageKey();
  if (key === 'ice') bootIce();
  else if (key === 'arena') bootArena();
  else if (key === 'client-me') bootMe();
})();
