/**
 * «Кто кого» — Mini App, зимняя модель (TASK-334 S5, PDEC-031). Холст: claude.ai/artifact/R3u6sQZmooPxteuTWcfiKd.
 *
 * Здесь — ядро: состояние, запросы, навигация по экранам, ход и козырь, общие кирпичики вёрстки.
 * Экраны подключаются по одному и регистрируются через KK.register:
 *   kto-kogo-views.js   — матч с ходом, матч идёт, итог, края;
 *   kto-kogo-board.js   — хаб игры, таблица, карточка болельщика;
 *   kto-kogo-leagues.js — новая лига, лига изнутри, вход по ссылке, итоги месяца.
 * Чужие имена попадают в DOM только через textContent.
 */
(function () {
  'use strict';

  var M = window.KtoKogoModel;
  var S = window.KtoKogoScreens;
  var tg = window.Telegram && window.Telegram.WebApp;
  var root = document.getElementById('kk');
  var params = new URLSearchParams(location.search);
  var initData = (tg && tg.initData) || params.get('init_data') || '';

  var state = {
    stack: [],
    loading: true,
    matches: [], // ближайшие матчи Динамо и Экстралиги (/matches?league=all)
    matchCache: {}, // матчи вне окна списка: по ссылке, отменённые
    me: null,
    race: null,
    double: null,
    doubles: [],
    drafts: {}, // id матча → черновик счёта [дома, в гостях], пока он не ушёл на сервер или это ничья
    scoreOpen: {}, // id матча → раскрыты степперы в строке дня
    matchesFailed: false, // список матчей не загрузился (нет сети) — хаб показывает «Повторить»
    hubReady: false, // хаб прошёл первую загрузку (профиль, матчи, матчи клуба)
    stakes: {}, // id матча → {loading, data}
    movement: {}, // id матча → {loading, data}
    peaks: null,
    profile: null,
    clubs: null,
    leagues: null,
    leagueTables: {}, // 'id|month' | 'id|all'
    tables: {}, // 'клуб|период'
    created: null,
    joinCode: '',
    joinPreview: null,
    joinError: '',
    month: null,
    remind: null,
    kkHidden: false,
    fromCard: '',
    sheet: null,
    toast: '',
    busy: false,
    sharing: false,
  };

  var screens = {};
  var pollTimer = null;

  // ---------- среда ----------

  function applyTheme() {
    // Тему сообщает Telegram; вне его (браузер, превью) — системная.
    var dark = tg && tg.initData ? tg.colorScheme === 'dark' : !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.body.classList.toggle('kk-dark', !!dark);
    if (tg && tg.setHeaderColor) {
      try {
        tg.setHeaderColor(dark ? '#17212b' : '#f2f5fa');
        tg.setBackgroundColor(dark ? '#17212b' : '#f2f5fa');
      } catch (e) { /* старые клиенты */ }
    }
  }

  function haptic(kind) {
    try {
      if (!tg || !tg.HapticFeedback) return;
      if (kind === 'success') tg.HapticFeedback.notificationOccurred('success');
      else tg.HapticFeedback.selectionChanged();
    } catch (e) { /* */ }
  }

  function api(method, path, body, isPublic) {
    var opts = { method: method, headers: {} };
    if (!isPublic) opts.headers['X-Telegram-Init-Data'] = initData;
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch((isPublic ? '/api/public' : '/api/webapp') + path, opts).catch(function () {
      // Нет сети: браузер отдаёт «Failed to fetch» по-английски, игроку это показывать нельзя.
      var offline = new Error('Нет связи. Проверь интернет и попробуй ещё раз');
      offline.status = 0;
      throw offline;
    }).then(function (r) {
      if (r.status === 204) return null;
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var e = new Error((data && typeof data.detail === 'string' && data.detail) || 'Не получилось. Попробуй ещё раз');
          e.status = r.status;
          throw e;
        }
        return data;
      });
    });
  }

  function toast(text) {
    state.toast = text;
    render();
    setTimeout(function () {
      if (state.toast === text) {
        state.toast = '';
        render();
      }
    }, 2600);
  }

  function fail(e) {
    toast((e && e.message) || 'Не получилось загрузить');
  }

  // ---------- DOM ----------

  function h(tag, attrs, kids) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') el.className = v;
        else if (k === 'text') el.textContent = v;
        else if (k === 'style') el.setAttribute('style', v);
        else if (k.indexOf('on') === 0) el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, v === true ? '' : v);
      });
    }
    (kids || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return el;
  }

  var SVG_NS = 'http://www.w3.org/2000/svg';
  function icon(paths, size, label, filled) {
    var s = document.createElementNS(SVG_NS, 'svg');
    s.setAttribute('width', size || 20);
    s.setAttribute('height', size || 20);
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('fill', filled ? 'currentColor' : 'none');
    s.setAttribute('stroke', filled ? 'none' : 'currentColor');
    s.setAttribute('stroke-width', '2.2');
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    if (label) {
      s.setAttribute('role', 'img');
      s.setAttribute('aria-label', label);
    } else s.setAttribute('aria-hidden', 'true');
    paths.forEach(function (d) {
      var p = document.createElementNS(SVG_NS, 'path');
      p.setAttribute('d', d);
      s.appendChild(p);
    });
    return s;
  }
  var I = {
    back: ['M15 18l-6-6 6-6'],
    close: ['M6 6l12 12', 'M18 6L6 18'],
    more: ['M5 12h.01', 'M12 12h.01', 'M19 12h.01'],
    down: ['M6 9l6 6 6-6'],
    bolt: ['M13 2L4 14h7l-1 8 9-12h-7z'],
    up: ['M12 19V5', 'M5 12l7-7 7 7'],
    swap: ['M7 4v16', 'M17 20V4', 'M3 8l4-4 4 4', 'M13 16l4 4 4-4'],
    arrow: ['M5 12h14', 'M13 6l6 6-6 6'],
    chev: ['M9 6l6 6-6 6'],
    check: ['M5 12l5 5 9-10'],
    send: ['M21 4L3 11l6 2 2 6 3-4 5 4z'],
    plus: ['M12 5v14', 'M5 12h14'],
    bell: ['M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9', 'M10.3 21a1.9 1.9 0 0 0 3.4 0'],
    globe: ['M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z', 'M3 12h18', 'M12 3a14 14 0 0 1 0 18', 'M12 3a14 14 0 0 0 0 18'],
    invite: ['M16 11a4 4 0 1 0-8 0', 'M4 20c1.5-3 4.5-4.5 8-4.5s6.5 1.5 8 4.5', 'M19 3v4', 'M17 5h4'],
  };

  /** Корона — залитая, чтобы читалась мелко и на жёлтом. */
  var CROWN = 'M3 18h18l-1.5-10-4.5 4-3-6-3 6-4.5-4z';
  function crownIcon(size, label) {
    var s = icon([CROWN], size, label, true);
    s.setAttribute('class', 'kk-crown-ic');
    return s;
  }

  /** Значок «корон у имени»: корона и число. */
  function crownTag(n) {
    if (!n) return null;
    return h('span', { class: 'kk-crownw', role: 'img', 'aria-label': S.crownCount(n) }, [crownIcon(14), String(n)]);
  }

  function initials(name) {
    var parts = String(name || '').trim().split(/\s+/);
    return ((parts[0] || '?').charAt(0) + (parts[1] ? parts[1].charAt(0) : '')).toUpperCase();
  }

  /** Белый круг с логотипом клуба; без логотипа — две буквы. */
  function logoDisc(team, size) {
    var t = team || {};
    var px = 'width:' + size + 'px;height:' + size + 'px';
    if (t.logo) return h('span', { class: 'kk-disc', style: px }, [h('img', { src: t.logo, alt: '', loading: 'lazy', style: 'width:' + Math.round(size * 0.72) + 'px;height:' + Math.round(size * 0.72) + 'px' })]);
    return h('span', { class: 'kk-disc kk-disc--txt', style: px + ';font-size:' + Math.round(size * 0.34) + 'px', 'aria-hidden': 'true', text: t.short || initials(t.name) });
  }

  function worldDisc(size) {
    return h('span', { class: 'kk-disc kk-disc--world', style: 'width:' + size + 'px;height:' + size + 'px', 'aria-hidden': 'true' }, [icon(I.globe, Math.round(size * 0.58))]);
  }

  function ava(name, size, cls) {
    return h('span', { class: 'kk-ava' + (cls ? ' ' + cls : ''), style: 'width:' + size + 'px;height:' + size + 'px;font-size:' + Math.round(size * 0.42) + 'px', 'aria-hidden': 'true', text: initials(name) });
  }

  /** Знак игры — шайба: чёрный овал с бликом, чистый CSS. */
  function puck(cls) {
    return h('span', { class: 'kk-puck' + (cls ? ' ' + cls : ''), 'aria-hidden': 'true' });
  }

  var INTRO_MS = 700;
  var introStart = null;

  /**
   * Заставка с шайбой: один раз за сессию. Пока она идёт, возвращает, сколько миллисекунд уже прошло
   * (экран перерисовывается целиком, и анимация должна продолжаться, а не начинаться заново); иначе null.
   */
  function introElapsed() {
    if (introStart === null) {
      var seen = false;
      try {
        seen = sessionStorage.getItem('kk_puck') === '1';
        sessionStorage.setItem('kk_puck', '1');
      } catch (e) { /* хранилище недоступно: играем заставку, она короткая */ }
      introStart = seen ? -1 : Date.now();
    }
    if (introStart < 0) return null;
    var el = Date.now() - introStart;
    return el < INTRO_MS ? el : null;
  }

  function sticker(text, cls) {
    return h('span', { class: 'kk-tag' + (cls ? ' ' + cls : ''), 'aria-hidden': 'true', text: text });
  }

  function topbar(title, sub, opts) {
    opts = opts || {};
    return h('div', { class: 'kk-top' }, [
      h('button', { type: 'button', class: 'kk-round', 'aria-label': 'Назад', onclick: back }, [icon(I.back)]),
      h('span', { class: 'kk-top__t' }, [h('h1', { class: 'kk-h1', text: title }), sub ? h('span', { class: 'kk-sub', text: sub }) : null]),
      opts.right || null,
    ]);
  }

  function loading() {
    return h('div', { class: 'kk-skel', role: 'status', 'aria-label': 'Загружаем' });
  }

  /** Загрузка не удалась: объясняем и даём повторить, а не оставляем вечную заглушку. */
  function retryCard(text, onRetry) {
    return emptyCard('НЕ ЗАГРУЗИЛОСЬ', text || 'Проверь интернет и попробуй ещё раз.', h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: onRetry, text: 'Повторить' }));
  }

  function emptyCard(head, text, cta) {
    return h('section', { class: 'kk-card kk-note' }, [
      h('span', { class: 'kk-lbl', text: head }),
      h('span', { class: 'kk-tx', text: text }),
      cta || null,
    ]);
  }

  /** Шторка снизу: тап по затемнению закрывает. */
  function sheet(title, subtitle, children, cls) {
    var panel = h('div', { class: 'kk-sheet' + (cls ? ' ' + cls : ''), role: 'dialog', 'aria-modal': 'true', 'aria-label': title, tabindex: '-1' }, [
      h('div', { class: 'kk-sheet__head' }, [
        h('span', { class: 'kk-sheet__t' }, [h('span', { class: 'kk-h2', text: title }), subtitle ? h('span', { class: 'kk-sub', text: subtitle }) : null]),
        h('button', { type: 'button', class: 'kk-round kk-round--alt', 'aria-label': 'Закрыть', onclick: closeSheet }, [icon(I.close, 18)]),
      ]),
    ].concat(children));
    return h('div', { class: 'kk-scrim', onclick: function (e) { if (e.target === e.currentTarget) closeSheet(); } }, [panel]);
  }

  function closeSheet() {
    state.sheet = null;
    render();
  }

  // ---------- навигация ----------

  function current() {
    return state.stack[state.stack.length - 1];
  }

  function stopPoll() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  /** Периодический опрос, пока открыт экран: сам останавливается, когда экран ушёл. */
  function poll(name, ms, fn) {
    stopPoll();
    pollTimer = setInterval(function () {
      var c = current();
      if (!c || c.name !== name) return stopPoll();
      fn(c.args);
    }, ms);
  }

  function enter() {
    var c = current();
    var sc = screens[c.name];
    stopPoll();
    render();
    if (sc && sc.enter) sc.enter(c.args);
  }

  function go(name, args) {
    state.sheet = null;
    state.stack.push({ name: name, args: args || {} });
    enter();
    window.scrollTo(0, 0);
  }

  function replace(name, args) {
    state.sheet = null;
    state.stack[Math.max(0, state.stack.length - 1)] = { name: name, args: args || {} };
    enter();
    window.scrollTo(0, 0);
  }

  function reset(name, args) {
    state.sheet = null;
    state.stack = [{ name: name, args: args || {} }];
    enter();
    window.scrollTo(0, 0);
  }

  function back() {
    if (state.sheet) return closeSheet();
    if (state.stack.length > 1) {
      state.stack.pop();
      return enter();
    }
    location.href = '/webapp/client-home' + (initData && !(tg && tg.initData) ? '?init_data=' + encodeURIComponent(initData) : '');
  }

  /** Страница матча (Иду / Позвать / Билеты) — отдельный экран Mini App; приложение игры её не повторяет. */
  function openMatchPage(id) {
    var shell = window.ClientShell;
    var path = 'client-match?id=' + encodeURIComponent(id);
    if (shell && typeof shell.navigate === 'function') return shell.navigate(path);
    location.href = '/webapp/' + path + (initData && !(tg && tg.initData) ? '&init_data=' + encodeURIComponent(initData) : '');
  }

  function register(name, screen) {
    screens[name] = screen;
  }

  // ---------- данные ----------

  function mergeMatches(items) {
    state.matches = items;
    items.forEach(function (m) { delete state.matchCache[m.id]; });
  }

  function loadMatches() {
    return api('GET', '/client/hockey/matches?league=all').then(function (data) {
      mergeMatches((data && data.items) || []);
      state.me = data && data.me;
      state.race = (data && data.race) || null;
      state.double = (data && data.double) || null;
      state.doubles = (data && data.doubles) || [];
    });
  }

  /**
   * Ближайшие матчи любимого клуба игрока, дома и в гостях: общий список ограничен по числу и может их не вместить.
   * Недостающие дописываются в state.matches, чтобы ход и козырь работали с теми же объектами.
   */
  function loadClubMatches() {
    var club = state.profile && state.profile.club && state.profile.club.name;
    if (!club) return Promise.resolve();
    return api('GET', '/client/hockey/matches?league=all&club=' + encodeURIComponent(club))
      .then(function (data) {
        var have = {};
        state.matches.forEach(function (m) { have[m.id] = true; });
        var extra = ((data && data.items) || []).filter(function (m) { return !have[m.id]; });
        if (!extra.length) return;
        state.matches = state.matches.concat(extra).sort(function (a, b) { return a.starts_at < b.starts_at ? -1 : a.starts_at > b.starts_at ? 1 : a.id - b.id; });
      })
      .catch(function () {});
  }

  function findMatch(id) {
    for (var i = 0; i < state.matches.length; i++) if (state.matches[i].id === id) return state.matches[i];
    return state.matchCache[id] || null;
  }

  /** Матч целиком: из списка или отдельным запросом (давний, отменённый, по ссылке). */
  function fetchMatch(id) {
    return api('GET', '/client/hockey/matches/' + id).then(function (m) {
      var own = findMatch(id);
      if (own && state.matches.indexOf(own) >= 0) {
        // Итог мог поправить админ: сменился счёт — накопленное «куда сдвинулось» переспрашиваем.
        var r0 = own.result, r1 = m.result;
        if (JSON.stringify(r0 || null) !== JSON.stringify(r1 || null)) delete state.movement[id];
        Object.keys(own).forEach(function (k) { if (k !== 'pickSeq' && !(k in m)) delete own[k]; });
        Object.keys(m).forEach(function (k) { own[k] = m[k]; });
      } else state.matchCache[id] = m;
      return findMatch(id);
    });
  }

  function loadStakes(id, force) {
    var cur = state.stakes[id];
    if (cur && (cur.loading || (cur.data && !force))) return Promise.resolve();
    state.stakes[id] = { loading: true, data: cur && cur.data };
    return api('GET', '/client/hockey/matches/' + id + '/stakes')
      .then(function (data) { state.stakes[id] = { loading: false, data: data }; })
      .catch(function () { state.stakes[id] = { loading: false, data: null }; });
  }

  function loadPeaks() {
    if (state.peaks) return Promise.resolve();
    return api('GET', '/client/hockey/peaks').then(function (d) { state.peaks = (d && d.items) || []; }).catch(function () { state.peaks = []; });
  }

  function loadProfile(force) {
    if (state.profile && !force) return Promise.resolve();
    return api('GET', '/client/hockey/profile').then(function (d) { state.profile = d; }).catch(function () { state.profile = state.profile || null; });
  }

  function loadClubs() {
    if (state.clubs) return Promise.resolve();
    return api('GET', '/client/hockey/clubs').then(function (d) {
      state.clubs = (d && d.items) || [];
      state.maxClubs = (d && d.max_clubs) || null;
    });
  }

  function loadTermOptions() {
    if (state.termOptions) return Promise.resolve();
    return api('GET', '/client/hockey/leagues/term-options').then(function (d) { state.termOptions = d || { items: [] }; });
  }

  function loadLeagues(force) {
    if (state.leagues && !force) return Promise.resolve();
    return api('GET', '/client/hockey/leagues').then(function (d) { state.leagues = (d && d.items) || []; });
  }

  function loadRemind() {
    return api('GET', '/client/hockey/remind').then(function (d) { state.remind = !!(d && d.on); }, function () { state.remind = null; });
  }

  function loadPrefs() {
    return api('GET', '/client/hockey/prefs').then(function (d) { state.kkHidden = !!(d && d.kk_hidden); }, function () { state.kkHidden = false; });
  }

  // ---------- ход ----------

  function sendPick(match, body, optimistic) {
    var before = match.my_pick;
    // Ответы могут прийти не по порядку: учитываем только последний отправленный ход.
    var seq = (match.pickSeq = (match.pickSeq || 0) + 1);
    // Козырь живёт на ходе: смена стороны или счёта его не снимает.
    if (before && before.doubled) optimistic.doubled = true;
    match.my_pick = optimistic;
    haptic();
    render();
    return api('PUT', '/client/hockey/matches/' + match.id + '/pick', body)
      .then(function (data) {
        if (match.pickSeq !== seq) return;
        match.my_pick = data && data.my_pick;
        delete state.stakes[match.id];
        haptic('success');
        render();
        if (current() && current().name === 'match') loadStakes(match.id, true).then(render);
      })
      .catch(function (e) {
        if (match.pickSeq === seq) match.my_pick = before;
        if (e.status === 409) match.open = false;
        toast(e.message);
      });
  }

  function pickSide(match, side) {
    if (!match.open) return Promise.resolve();
    var mine = match.my_pick;
    if (mine && mine.side === side && mine.home_score === null) return Promise.resolve();
    return sendPick(match, { side: side }, { side: side, home_score: null, away_score: null, points: null, doubled: false });
  }

  function saveScore(match, home, away) {
    if (M.scoreError(home, away)) return;
    state.sheet = null;
    var side = home > away ? 'home' : 'away';
    return sendPick(match, { home_score: home, away_score: away }, { side: side, home_score: home, away_score: away, points: null, doubled: false });
  }

  /** Козырь недели: поставить, перенести с другого матча недели или снять — до начала матча. */
  function toggleTrump(match) {
    var st = S.trumpState(match, state.doubles, new Date().toISOString());
    if (st.kind === 'nopick') return toast('Сначала тапни за команду');
    if (!st.usable) return toast(st.note.charAt(0).toUpperCase() + st.note.slice(1));
    var on = !(match.my_pick && match.my_pick.doubled);
    var wk = S.weekKey(match.starts_at);
    var touched = [];
    state.matches.forEach(function (x) {
      if (!x.my_pick) return;
      if (x.id === match.id) touched.push([x, x.my_pick.doubled]);
      else if (on && x.my_pick.doubled && S.weekKey(x.starts_at) === wk && x.open) touched.push([x, x.my_pick.doubled]);
    });
    var prevDoubles = state.doubles;
    touched.forEach(function (t) { t[0].my_pick.doubled = t[0].id === match.id ? on : false; });
    state.doubles = state.doubles.map(function (d) { return d.week_start === wk ? { week_start: d.week_start, match_id: on ? match.id : null, locked: false } : d; });
    haptic();
    render();
    return api('PUT', '/client/hockey/matches/' + match.id + '/double', { on: on })
      .then(function (r) {
        state.double = (r && r.double) || state.double;
        state.doubles = (r && r.doubles) || state.doubles;
        delete state.stakes[match.id];
        render();
        loadStakes(match.id, true).then(render);
      })
      .catch(function (e) {
        touched.forEach(function (t) { t[0].my_pick.doubled = t[1]; });
        state.doubles = prevDoubles;
        toast(e.message);
        render();
      });
  }

  // ---------- шаринг ----------

  function share(inviteUrl, text) {
    if (!inviteUrl) {
      toast('Ссылка появится, когда бот будет настроен');
      return;
    }
    var url = 'https://t.me/share/url?url=' + encodeURIComponent(inviteUrl) + '&text=' + encodeURIComponent(text);
    if (tg && tg.openTelegramLink) tg.openTelegramLink(url);
    else window.open(url, '_blank');
  }

  /**
   * Карточка в чат: сервер готовит фото с кнопкой, Telegram даёт выбрать чат.
   * Старый клиент или сбой — та же ссылка текстом через t.me/share.
   */
  function shareCard(req, fallbackUrl, fallbackText) {
    if (state.sharing) return;
    state.sharing = true;
    api('POST', '/client/hockey/share', req)
      .then(function (r) {
        state.sharing = false;
        var canShare = tg && tg.shareMessage && (!tg.isVersionAtLeast || tg.isVersionAtLeast('8.0'));
        if (r.prepared_message_id && canShare) {
          try {
            tg.shareMessage(r.prepared_message_id, function (sent) { if (sent) haptic('success'); });
            return;
          } catch (e) { /* ниже — запасной путь */ }
        }
        share(r.url, r.text);
      })
      .catch(function (e) {
        state.sharing = false;
        if (fallbackUrl) share(fallbackUrl, fallbackText);
        else toast(e.message);
      });
  }

  function copy(url) {
    if (!url) return toast('Ссылка появится, когда бот будет настроен');
    var done = function () { toast('Ссылка скопирована'); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, function () { legacyCopy(url); });
    else legacyCopy(url);
  }

  /** Старые WebView без Clipboard API: textarea + execCommand, иначе показываем ссылку — не врём про «скопировано». */
  function legacyCopy(url) {
    var ta = document.createElement('textarea');
    ta.value = url;
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { /* */ }
    ta.remove();
    if (ok) toast('Ссылка скопирована');
    else window.prompt('Скопируй ссылку', url);
  }

  // ---------- сборка ----------

  var sheetReturnId = null;

  function render() {
    var c = current();
    var sc = c && screens[c.name];
    var nodes = [];
    var body = sc ? sc.render(c.args) : null;
    if (body) nodes = nodes.concat(body);
    var prevSheet = root.querySelector('.kk-sheet');
    if (state.sheet && sc && sc.sheet) {
      var s = sc.sheet(state.sheet, c.args);
      if (s) {
        nodes.push(s);
        sheetReturnId = state.sheet.returnId || null;
      }
    }
    if (state.toast) nodes.push(h('div', { class: 'kk-toast', role: 'status', text: state.toast }));
    var focusId = document.activeElement && document.activeElement.id;
    root.replaceChildren.apply(root, nodes);
    var panel = root.querySelector('.kk-sheet');
    if (panel && !prevSheet) panel.focus();
    else if (!panel && prevSheet && sheetReturnId) {
      // Шторка закрылась: фокус возвращается на кнопку, которая её открыла.
      var opener = document.getElementById(sheetReturnId);
      sheetReturnId = null;
      if (opener) opener.focus();
    } else if (focusId) {
      var again = document.getElementById(focusId);
      if (again && (again.tagName === 'INPUT' || again.hasAttribute('data-keep'))) {
        again.focus();
        if (again.tagName === 'INPUT') {
          try { again.setSelectionRange(again.value.length, again.value.length); } catch (e) { /* */ }
        }
      }
    }
    if (tg && tg.BackButton) tg.BackButton.show();
  }

  function startParam() {
    var sp = tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
    return sp || params.get('tgWebAppStartParam') || params.get('startapp') || '';
  }

  /** Сообщение, когда игру открыли не из Telegram. */
  function outsideTelegram() {
    root.replaceChildren(h('main', { class: 'kk-main' }, [
      emptyCard('Кто кого — в Telegram', 'Игра открывается из Glide в Telegram: там видно, кто из друзей за кого.'),
    ]));
  }

  function boot() {
    if (tg) {
      try {
        tg.ready();
        tg.expand();
      } catch (e) { /* */ }
      if (tg.onEvent) tg.onEvent('themeChanged', function () { applyTheme(); render(); });
      if (tg.BackButton && tg.BackButton.onClick) tg.BackButton.onClick(back);
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && state.sheet) return closeSheet();
      if (e.key !== 'Tab' || !state.sheet) return;
      // Фокус не уходит из открытой шторки на страницу под ней.
      var panel = root.querySelector('.kk-sheet');
      if (!panel) return;
      var items = Array.prototype.slice.call(panel.querySelectorAll('button, [href], input, [tabindex]:not([tabindex="-1"])'));
      if (!items.length) return;
      var first = items[0];
      var last = items[items.length - 1];
      var active = document.activeElement;
      if (e.shiftKey && (active === first || active === panel)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      } else if (!panel.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    });
    applyTheme();
    state.stack = [{ name: 'hub', args: {} }];
    if (!initData) return outsideTelegram();
    render();
    state.fromCard = M.cardFrom(startParam(), params.get('from'));
    if (state.fromCard) api('POST', '/client/hockey/card-opened', { card: state.fromCard }).catch(function () {});
    var code = (params.get('join') || M.inviteCode(startParam()) || '').toUpperCase();
    var matchId = Number(params.get('reveal') || params.get('match')) || null;
    var month = Number(params.get('month')) || null;
    var pickId = Number(params.get('pick')) || null;
    var pickSideParam = params.get('side');
    if (params.get('remind') === 'off') {
      api('PUT', '/client/hockey/remind', { on: false }).then(function () {
        state.remind = false;
        toast('Напоминания выключены');
      }, function () {});
    }
    var loadError = null;
    // Список матчей не загрузился — всё равно открываем нужный экран: у каждого есть своё «Повторить».
    Promise.all([loadMatches().catch(function (e) { loadError = e; state.matchesFailed = true; }), loadPrefs(), loadRemind()])
      .then(function () {
        state.loading = false;
        if (loadError) fail(loadError);
        var openId = matchId || pickId;
        // Ссылка «сделать ход» из бота может указать на матч вне списка — догружаем его отдельно.
        var ensure = pickId && !findMatch(pickId) ? fetchMatch(pickId).catch(function () {}) : Promise.resolve();
        return ensure.then(function () {
          var target = pickId && findMatch(pickId);
          // Кнопка «За команду» из напоминания в боте: ход сразу, если его ещё нет и матч не начался.
          if (target && target.open && !target.my_pick && (pickSideParam === 'home' || pickSideParam === 'away')) {
            pickSide(target, pickSideParam);
            toast('Ход принят: за ' + S.clubName(target[pickSideParam].name));
          }
          enter();
          if (code) go('join', { code: code });
          else if (openId) go('match', { id: openId });
          else if (params.get('tab') === 'table') go('table', {});
          if (month) {
            api('GET', '/client/hockey/races/' + month + '/result').then(function (data) {
              state.month = data;
              go('month', {});
              api('POST', '/client/hockey/races/' + month + '/seen').catch(function () {});
            }, function () {});
          }
        });
      })
      .catch(function (e) {
        state.loading = false;
        render();
        fail(e);
      });
  }

  window.KK = {
    M: M, S: S, tg: tg, params: params, state: state, h: h, icon: icon, I: I, CROWN: CROWN, crownIcon: crownIcon, crownTag: crownTag,
    ava: ava, puck: puck, introElapsed: introElapsed, logoDisc: logoDisc, worldDisc: worldDisc, sticker: sticker, topbar: topbar, loading: loading, emptyCard: emptyCard, retryCard: retryCard,
    sheet: sheet, closeSheet: closeSheet, api: api, toast: toast, fail: fail, haptic: haptic, render: render, register: register,
    go: go, replace: replace, reset: reset, back: back, current: current, poll: poll, stopPoll: stopPoll,
    loadMatches: loadMatches, loadClubMatches: loadClubMatches, findMatch: findMatch, fetchMatch: fetchMatch, loadStakes: loadStakes, loadPeaks: loadPeaks,
    loadProfile: loadProfile, loadClubs: loadClubs, loadLeagues: loadLeagues, loadRemind: loadRemind, loadTermOptions: loadTermOptions,
    openMatchPage: openMatchPage, sendPick: sendPick, pickSide: pickSide, saveScore: saveScore, toggleTrump: toggleTrump,
    share: share, shareCard: shareCard, copy: copy, boot: boot,
  };
})();
