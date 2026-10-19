/**
 * «Кто кого» — экран игры в Mini App (TASK-299). Макет: claude.ai/artifact/QxDWNDDKXcHYJdZFv6uPvt, экраны 1–5, 10–14.
 *
 * Вкладки: матчи, таблица, лиги. Поверх них — лига изнутри, создание лиги, вход по ссылке (?join=КОД или
 * startapp=kk_КОД), итог матча (?reveal=<id матча>, открывается из строки на главной).
 * Чужие имена попадают в DOM только через textContent.
 */
(function () {
  'use strict';

  var M = window.KtoKogoModel;
  var tg = window.Telegram && window.Telegram.WebApp;
  var root = document.getElementById('kk');
  var params = new URLSearchParams(location.search);
  var initData = (tg && tg.initData) || params.get('init_data') || '';

  var IDEAS = ['Раздевалка', 'Офис', 'Двор', 'Субботний лёд'];

  var state = {
    tab: 'matches',
    view: null, // null | 'league' | 'create' | 'created' | 'join' | 'joined' | 'reveal'
    loading: true,
    matches: [],
    me: null,
    standings: null,
    leagues: null,
    tableKey: null, // id лиги или 'all'
    leagueTables: {},
    leagueId: null,
    created: null,
    joinCode: '',
    joinPreview: null,
    joinError: '',
    revealId: null,
    sheet: null, // {kind:'score', matchId, home, away} | {kind:'menu'} | {kind:'rename', draft} | {kind:'leave'}
    draftName: '',
    createError: '',
    busy: false,
    sharing: false,
    fromCard: '', // 'league' | 'result' — открыли с карточки в чате
    toast: '',
  };

  // ---------- среда ----------

  function applyTheme() {
    // Тему сообщает Telegram; вне его (браузер, превью) — системная.
    var dark = tg && tg.initData ? tg.colorScheme === 'dark' : !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.body.classList.toggle('kk-dark', !!dark);
    if (tg && tg.setHeaderColor) {
      try {
        tg.setHeaderColor(dark ? '#0b1220' : '#f2f5fa');
        tg.setBackgroundColor(dark ? '#0b1220' : '#f2f5fa');
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
    return fetch((isPublic ? '/api/public' : '/api/webapp') + path, opts).then(function (r) {
      if (r.status === 204) return null;
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var e = new Error((data && typeof data.detail === 'string' && data.detail) || 'Не получилось. Попробуйте ещё раз');
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
  function icon(paths, size, label) {
    var s = document.createElementNS(SVG_NS, 'svg');
    s.setAttribute('width', size || 20);
    s.setAttribute('height', size || 20);
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
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
  var I_BACK = ['M15 18l-6-6 6-6'];
  var I_MORE = ['M5 12h.01', 'M12 12h.01', 'M19 12h.01'];
  var I_INVITE = ['M16 11a4 4 0 1 0-8 0', 'M4 20c1.5-3 4.5-4.5 8-4.5s6.5 1.5 8 4.5', 'M19 3v4', 'M17 5h4'];
  var I_LOCK = ['M7 11V8a5 5 0 0 1 10 0v3', 'M5 11h14v9H5z'];
  var I_PLUS = ['M12 5v14', 'M5 12h14'];

  function initials(name) {
    var parts = String(name || '').trim().split(/\s+/);
    return ((parts[0] || '?').charAt(0) + (parts[1] ? parts[1].charAt(0) : '')).toUpperCase();
  }

  function ava(name, size, me) {
    return h('span', {
      class: 'kk-ava' + (me ? ' kk-ava--me' : ''),
      style: 'width:' + size + 'px;height:' + size + 'px;font-size:' + Math.round(size * 0.36) + 'px',
      'aria-hidden': 'true',
      text: me ? 'Я' : initials(name),
    });
  }

  function badge(team, color) {
    var t = team || {};
    var style = '--team:' + color;
    if (t.logo) {
      return h('span', { class: 'kk-badge kk-badge--logo', style: style }, [h('img', { src: t.logo, alt: '', loading: 'lazy' })]);
    }
    return h('span', { class: 'kk-badge', style: style, 'aria-hidden': 'true', text: t.short || initials(t.name) });
  }

  // ---------- данные ----------

  function loadMatches() {
    return api('GET', '/client/hockey/matches').then(function (data) {
      state.matches = (data && data.items) || [];
      state.me = data && data.me;
    });
  }

  function loadStandings() {
    return api('GET', '/client/hockey/standings').then(function (data) {
      state.standings = data;
    });
  }

  function loadLeagues() {
    return api('GET', '/client/hockey/leagues').then(function (data) {
      state.leagues = (data && data.items) || [];
    });
  }

  var leagueLoading = {};
  function loadLeague(id) {
    if (leagueLoading[id]) return leagueLoading[id];
    leagueLoading[id] = api('GET', '/client/hockey/leagues/' + id)
      .then(function (data) {
        state.leagueTables[id] = data;
      })
      .finally(function () {
        delete leagueLoading[id];
      });
    return leagueLoading[id];
  }

  function findMatch(id) {
    for (var i = 0; i < state.matches.length; i++) if (state.matches[i].id === id) return state.matches[i];
    return null;
  }

  // ---------- ход ----------

  function sendPick(match, body, optimistic) {
    var before = match.my_pick;
    match.my_pick = optimistic;
    haptic();
    render();
    return api('PUT', '/client/hockey/matches/' + match.id + '/pick', body)
      .then(function (data) {
        match.my_pick = data && data.my_pick;
        render();
      })
      .catch(function (e) {
        match.my_pick = before;
        if (e.status === 409) match.open = false;
        toast(e.message);
      });
  }

  function pickSide(match, side) {
    if (!match.open) return;
    var mine = match.my_pick;
    if (mine && mine.side === side && mine.home_score === null) return;
    sendPick(match, { side: side }, { side: side, home_score: null, away_score: null, points: null });
  }

  function openScore(match) {
    var mine = match.my_pick || {};
    var home = mine.home_score != null ? mine.home_score : mine.side === 'home' ? 3 : 1;
    var away = mine.away_score != null ? mine.away_score : mine.side === 'away' ? 3 : 1;
    if (home === away) away = home + 1;
    state.sheet = { kind: 'score', matchId: match.id, home: home, away: away };
    render();
  }

  function saveScore() {
    var s = state.sheet;
    var match = findMatch(s.matchId);
    if (!match || M.scoreError(s.home, s.away)) return;
    state.sheet = null;
    var side = s.home > s.away ? 'home' : 'away';
    sendPick(match, { home_score: s.home, away_score: s.away }, { side: side, home_score: s.home, away_score: s.away, points: null });
  }

  // ---------- шапка и меню ----------

  function top() {
    var pts = state.me ? state.me.points : 0;
    var sub = state.me ? state.me.rank + '-й' : 'в игре';
    return h('header', { class: 'kk-top' }, [
      h('h1', { class: 'kk-logo', text: 'кто кого' }),
      h('button', { class: 'kk-pill', type: 'button', onclick: function () { go('table'); }, 'aria-label': 'Мои очки и место' }, [
        h('span', { class: 'kk-pill__pts', text: String(pts) }),
        h('span', { text: sub }),
      ]),
    ]);
  }

  function nav() {
    var items = [['matches', 'Матчи'], ['table', 'Таблица'], ['leagues', 'Лиги']];
    return h('nav', { class: 'kk-nav', 'aria-label': 'Разделы игры' }, items.map(function (it) {
      return h('button', {
        type: 'button',
        'aria-current': state.tab === it[0] && !state.view ? 'page' : null,
        onclick: function () { go(it[0]); },
        text: it[1],
      });
    }));
  }

  function go(tab) {
    state.tab = tab;
    state.view = null;
    state.sheet = null;
    render();
    if (tab === 'table' && !state.standings) Promise.all([loadStandings(), state.leagues ? null : loadLeagues()]).then(render, fail);
    if (tab === 'leagues' && !state.leagues) loadLeagues().then(render, fail);
    window.scrollTo(0, 0);
  }

  function fail(e) {
    toast((e && e.message) || 'Не получилось загрузить');
  }

  // ---------- матчи ----------

  function orderMatches(list) {
    var open = [];
    var live = [];
    var done = [];
    list.forEach(function (m) {
      if (m.result) done.push(m);
      else if (m.open) open.push(m);
      else live.push(m);
    });
    done.sort(function (a, b) { return a.starts_at < b.starts_at ? 1 : -1; });
    return open.concat(live, done);
  }

  function matchCard(m, now) {
    var colors = M.pairColors(m.home, m.away);
    var mine = m.my_pick;
    var side = M.pickSide(mine);
    var friends = m.friends || { home: [], away: [] };

    if (m.result) return finalCard(m, colors, mine);

    var started = !m.open;
    var long = started && now - new Date(m.starts_at).getTime() > 3 * 3600 * 1000;
    if (long) {
      return h('div', { class: 'kk-row-card' }, [
        h('span', { class: 'kk-dot', 'aria-hidden': 'true' }),
        h('div', { class: 'kk-row-card__main' }, [
          h('span', { class: 'kk-row-card__title', text: m.home.name + ' — ' + m.away.name }),
          h('span', { class: 'kk-row-card__sub', text: 'считаем очки — придут, как только сверим итог' }),
        ]),
      ]);
    }

    function half(which) {
      var team = m[which];
      var on = side === which;
      var dim = !!side && !on;
      return h('button', {
        type: 'button',
        class: 'kk-half' + (dim ? ' kk-half--dim' : ''),
        style: '--team:' + colors[which],
        'aria-pressed': on ? 'true' : 'false',
        'aria-label': (started ? '' : 'Я за ') + team.name,
        disabled: started,
        onclick: function () { pickSide(m, which); },
      }, [
        badge(team, colors[which]),
        h('span', { class: 'kk-team', text: team.name }),
        h('span', { class: 'kk-fans', text: M.fansLine(friends[which], on) }),
      ]);
    }

    var kids = [
      h('div', { class: 'kk-kicker' }, started
        ? [h('span', { class: 'kk-kicker__live', 'aria-hidden': 'true' }), 'матч идёт · ходы закрыты']
        : [M.kicker(m.starts_at)]),
      h('div', { class: 'kk-halves' }, [half('home'), half('away')]),
    ];
    if (started) {
      var note = mine && mine.home_score != null ? 'твой счёт ' + mine.home_score + ':' + mine.away_score + ' · ' : '';
      kids.push(h('p', { class: 'kk-note', text: note + (mine ? 'итог после финальной сирены' : 'на этот матч хода нет') }));
    } else if (side) {
      var has = mine.home_score != null;
      kids.push(h('button', { type: 'button', class: 'kk-btn-soft', onclick: function () { openScore(m); } }, [
        has ? 'Мой счёт ' + mine.home_score + ':' + mine.away_score : 'Угадать счёт',
        h('span', { class: 'kk-chip', text: has ? 'изменить' : '+' + M.EXACT }),
      ]));
    }
    return h('article', { class: 'kk-card', 'aria-label': m.home.name + ' — ' + m.away.name }, kids);
  }

  function finalCard(m, colors, mine) {
    var r = m.result;
    if (!mine) {
      return h('div', { class: 'kk-row-card' }, [
        h('div', { class: 'kk-row-card__main' }, [
          h('span', { class: 'kk-row-card__title', text: m.home.name + ' — ' + m.away.name + ' · ' + r.home_score + ':' + r.away_score }),
          h('span', { class: 'kk-row-card__sub', text: M.whenLabel(m.starts_at, new Date()).split(',')[0] + ' · ты пропустил' }),
        ]),
        h('span', { class: 'kk-list__pts', style: 'color:var(--kk-muted)', text: '0' }),
      ]);
    }
    var homeWon = r.home_score > r.away_score;
    function side(which) {
      var won = (which === 'home') === homeWon;
      return h('div', {
        class: 'kk-half kk-half--small' + (won ? '' : ' kk-half--dim'),
        style: '--team:' + colors[which] + (won ? ';background:' + colors[which] + ';color:#fff' : ''),
      }, [badge(m[which], colors[which]), h('span', { class: 'kk-team', text: m[which].name })]);
    }
    var pts = mine.points;
    var tail = pts == null ? 'считаем очки' : M.verdict(pts).tail + (pts ? ' · +' + pts : '');
    return h('article', { class: 'kk-card', 'aria-label': m.home.name + ' — ' + m.away.name + ', ' + r.home_score + ':' + r.away_score }, [
      h('div', { class: 'kk-kicker', text: M.whenLabel(m.starts_at, new Date()).split(',')[0] + ' · ' + M.decidedLabel(r.decided_in) }),
      h('div', { class: 'kk-halves kk-halves--result' }, [
        side('home'),
        h('span', { class: 'kk-score-big', text: r.home_score + ':' + r.away_score }),
        side('away'),
      ]),
      h('p', { class: 'kk-note', text: tail }),
      pts != null ? h('span', { class: 'kk-sticker', 'aria-label': M.points(pts), text: pts ? '+' + pts : '0' }) : null,
    ]);
  }

  function matchesView() {
    if (state.loading) return [h('div', { class: 'kk-skeleton' }), h('div', { class: 'kk-skeleton' })];
    if (!state.matches.length) {
      return [empty('на этой неделе Динамо не играет', 'Следующий матч появится здесь, как только клуб поставит его в календарь. Пока — загляни в таблицу.', 'Открыть таблицу', function () { go('table'); }, ['#dce2ec', '#1747b5'])];
    }
    var now = Date.now();
    return orderMatches(state.matches).map(function (m) { return matchCard(m, now); });
  }

  function empty(head, body, cta, onCta, art, second, onSecond) {
    return h('div', { class: 'kk-empty' }, [
      h('div', { class: 'kk-empty__art', 'aria-hidden': 'true' }, [
        h('span', { style: 'background:' + art[0] }),
        h('span', { style: 'background:' + art[1] }),
      ]),
      h('div', { class: 'kk-empty__text' }, [
        h('p', { class: 'kk-empty__head', text: head }),
        h('p', { class: 'kk-hint', style: 'max-width:300px', text: body }),
      ]),
      h('div', { style: 'display:flex;flex-direction:column;gap:8px' }, [
        h('button', { type: 'button', class: 'kk-btn kk-btn--dark', onclick: onCta, text: cta }),
        second ? h('button', { type: 'button', class: 'kk-btn kk-btn--ghost', onclick: onSecond, text: second }) : null,
      ]),
    ]);
  }

  // ---------- шторка счёта ----------

  function scoreSheet() {
    var s = state.sheet;
    var match = findMatch(s.matchId);
    if (!match) return null;
    var colors = M.pairColors(match.home, match.away);
    function stepper(which) {
      return h('div', { class: 'kk-stepper', style: '--team:' + colors[which] }, [
        h('span', { style: 'font-size:14px;font-weight:800;text-align:center', text: match[which].name }),
        h('span', { class: 'kk-stepper__num', 'aria-live': 'polite', text: String(s[which]) }),
        h('div', { class: 'kk-stepper__btns' }, [
          h('button', { type: 'button', 'aria-label': 'Меньше — ' + match[which].name, text: '−', onclick: function () { s[which] = M.clampGoals(s[which] - 1); haptic(); render(); } }),
          h('button', { type: 'button', 'aria-label': 'Больше — ' + match[which].name, text: '+', onclick: function () { s[which] = M.clampGoals(s[which] + 1); haptic(); render(); } }),
        ]),
      ]);
    }
    var err = M.scoreError(s.home, s.away);
    return sheet([
      h('div', { style: 'display:flex;flex-direction:column;align-items:center;gap:4px' }, [
        h('h2', { class: 'kk-display', style: 'font-size:20px;margin:0', text: 'Какой счёт?' }),
        h('p', { class: 'kk-hint', text: 'точный счёт — 50 очков, близкий — тоже очки' }),
      ]),
      h('div', { class: 'kk-steppers' }, [stepper('home'), stepper('away')]),
      h('button', { type: 'button', class: 'kk-btn kk-btn--dark', disabled: !!err, onclick: saveScore, text: err || 'Готово' }),
    ]);
  }

  function sheet(children, menu) {
    return h('div', { class: 'kk-sheet', role: 'dialog', 'aria-modal': 'true' }, [
      h('button', { type: 'button', class: 'kk-sheet__scrim', 'aria-label': 'Закрыть', onclick: function () { state.sheet = null; render(); } }),
      h('div', { class: 'kk-sheet__panel' + (menu ? ' kk-sheet__menu' : '') }, children),
    ]);
  }

  // ---------- таблица ----------

  function tableView() {
    var leagues = state.leagues || [];
    // Пока игрок сам не выбрал вкладку — своя лига важнее общей таблицы.
    if (!state.tableKeyChosen) state.tableKey = leagues.length ? leagues[0].id : 'all';
    var key = state.tableKey;
    var chips = leagues.map(function (l) { return [l.id, l.name]; }).concat([['all', 'Все']]);
    var out = [
      h('h2', { class: 'kk-h2', text: 'таблица' }),
      h('div', { class: 'kk-seg', role: 'tablist' }, chips.map(function (c) {
        return h('button', {
          type: 'button',
          role: 'tab',
          'aria-selected': key === c[0] ? 'true' : 'false',
          text: c[1],
          onclick: function () {
            state.tableKey = c[0];
            state.tableKeyChosen = true;
            render();
            if (c[0] !== 'all' && !state.leagueTables[c[0]]) loadLeague(c[0]).then(render, fail);
          },
        });
      })),
    ];
    var rows;
    if (key === 'all') {
      if (!state.standings) return out.concat([h('div', { class: 'kk-skeleton' })]);
      rows = state.standings.items || [];
      var me = state.standings.me;
      if (me && !rows.some(function (r) { return r.is_me; })) {
        rows = rows.concat([{ rank: me.rank, display_name: 'Ты', points: me.points, exact: me.exact, is_me: true, gap: true }]);
      }
    } else {
      var t = state.leagueTables[key];
      if (!t) {
        loadLeague(key).then(render, fail);
        return out.concat([h('div', { class: 'kk-skeleton' })]);
      }
      rows = t.items || [];
    }
    if (!rows.length) {
      return out.concat([empty('таблица заполнится после первого матча', 'Тапни за команду — и после финальной сирены ты уже в ней.', 'К матчам', function () { go('matches'); }, ['#e2502c', '#1747b5'])]);
    }
    return out.concat([podium(rows.slice(0, 3)), list(rows.slice(3))]);
  }

  function nameOf(r) {
    return r.is_me ? 'Ты' : r.display_name;
  }

  function podium(top3) {
    var order = [top3[1], top3[0], top3[2]];
    return h('div', { class: 'kk-podium' }, order.map(function (r, i) {
      if (!r) return h('div');
      var place = i === 1 ? 1 : i === 0 ? 2 : 3;
      return h('div', { class: 'kk-podium__col' }, [
        ava(r.display_name, place === 1 ? 60 : 48, r.is_me),
        h('span', { class: 'kk-podium__name', text: nameOf(r) }),
        h('div', { class: 'kk-podium__block kk-podium__block--' + place }, [
          h('span', { class: 'kk-display', style: 'font-size:22px', text: String(r.rank) }),
          h('span', { style: 'font-size:13px;font-weight:700', text: M.points(r.points) }),
        ]),
      ]);
    }));
  }

  function list(rows) {
    if (!rows.length) return null;
    return h('ol', { class: 'kk-list' }, rows.map(function (r) {
      return h('li', { class: r.is_me ? 'kk-me' : '' }, [
        h('span', { class: 'kk-list__pos', text: String(r.rank) }),
        ava(r.display_name, 34, r.is_me),
        h('span', { class: 'kk-list__name', style: r.is_me ? 'font-weight:800' : '', text: nameOf(r) }),
        r.exact ? h('span', { class: 'kk-list__meta', text: r.exact + ' ' + M.plural(r.exact, 'точный', 'точных', 'точных') }) : null,
        h('span', { class: 'kk-list__pts', text: String(r.points) }),
      ]);
    }));
  }

  // ---------- лиги ----------

  function leaguesView() {
    var out = [h('h2', { class: 'kk-h2', text: 'лиги' })];
    if (!state.leagues) return out.concat([h('div', { class: 'kk-skeleton' })]);
    if (!state.leagues.length) {
      return out.concat([empty('с друзьями веселее', 'Собери лигу — у вас будет своя таблица. Очки те же, что в общей.', 'Создать лигу', startCreate, ['#ffd23f', '#1747b5'], 'У меня есть ссылка от друга', function () { openJoin(''); })]);
    }
    state.leagues.forEach(function (l) {
      out.push(h('button', { type: 'button', class: 'kk-league', onclick: function () { openLeague(l.id); } }, [
        h('span', { class: 'kk-league__mark', 'aria-hidden': 'true', text: initials(l.name) }),
        h('span', { style: 'flex:1;display:flex;flex-direction:column;gap:2px;min-width:0' }, [
          h('span', { class: 'kk-league__name', text: l.name }),
          h('span', { class: 'kk-league__sub', text: l.members + ' ' + M.plural(l.members, 'человек', 'человека', 'человек') + ' · ты ' + l.my_rank + '-й' }),
        ]),
        h('span', { class: 'kk-list__pts', text: String(l.my_points) }),
      ]));
    });
    out.push(h('button', { type: 'button', class: 'kk-add', onclick: startCreate }, [icon(I_PLUS, 22), 'Создать лигу']));
    return out;
  }

  function startCreate() {
    state.view = 'create';
    state.draftName = '';
    state.createError = '';
    render();
  }

  function createView() {
    var ok = state.draftName.trim().length > 1;
    var input = h('input', {
      id: 'kk-league-name',
      class: 'kk-field',
      maxlength: '28',
      value: state.draftName,
      autocomplete: 'off',
      oninput: function (e) {
        state.draftName = e.target.value;
        state.createError = '';
        var btn = document.getElementById('kk-create-go');
        if (btn) btn.disabled = state.draftName.trim().length < 2 || state.busy;
      },
    });
    return [
      h('div', { style: 'display:flex;flex-direction:column;gap:8px;padding-top:6px' }, [
        h('h2', { class: 'kk-display', style: 'font-size:28px;line-height:1.1;margin:0', text: 'как назовём лигу?' }),
        h('p', { class: 'kk-hint', text: 'Так её увидят друзья в приглашении' }),
      ]),
      h('label', { for: 'kk-league-name', class: 'kk-hint', style: 'font-weight:800', text: 'Название' }),
      input,
      h('div', { class: 'kk-ideas' }, IDEAS.map(function (idea) {
        return h('button', { type: 'button', text: idea, onclick: function () { state.draftName = idea; render(); } });
      })),
      state.createError ? h('p', { class: 'kk-err', text: state.createError }) : null,
      h('div', { style: 'margin-top:auto;padding-top:24px' }, [
        h('button', { id: 'kk-create-go', type: 'button', class: 'kk-btn kk-btn--dark', disabled: !ok || state.busy, onclick: createLeague, text: 'Создать и позвать друзей' }),
      ]),
    ];
  }

  function createLeague() {
    state.busy = true;
    render();
    api('POST', '/client/hockey/leagues', { name: state.draftName })
      .then(function (l) {
        state.busy = false;
        state.created = l;
        state.view = 'created';
        state.leagues = null;
        haptic('success');
        render();
      })
      .catch(function (e) {
        state.busy = false;
        state.createError = e.message;
        render();
      });
  }

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
   * Карточка в чат (TASK-300): сервер готовит фото с кнопкой, Telegram даёт выбрать чат.
   * Старый клиент или сбой — та же ссылка текстом через t.me/share, как раньше.
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

  function copy(inviteUrl) {
    if (!inviteUrl) return toast('Ссылка появится, когда бот будет настроен');
    var done = function () { toast('Ссылка скопирована'); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(inviteUrl).then(done, done);
    else done();
  }

  function inviteText(name) {
    return 'Угадываем матчи Динамо-Минск в лиге «' + name + '». Тапни за команду — посмотрим, кто кого.';
  }

  function createdView() {
    var l = state.created;
    return h('div', { class: 'kk-hero kk-hero--dark' }, [
      h('div', { class: 'kk-hero__body', style: 'align-items:center;text-align:center' }, [
        h('span', { class: 'kk-display', style: 'width:96px;height:96px;border-radius:32px;background:#ffd23f;color:#0d1424;display:flex;align-items:center;justify-content:center;font-size:30px;transform:rotate(-6deg)', 'aria-hidden': 'true', text: initials(l.name) }),
        h('p', { class: 'kk-hero__title', style: 'font-size:28px', text: '«' + l.name + '» готова' }),
        h('p', { class: 'kk-hero__text', style: 'max-width:280px', text: 'Пока в лиге только ты. Позови друзей — очки за матчи пойдут и сюда, и в общую таблицу.' }),
      ]),
      h('button', { type: 'button', class: 'kk-btn kk-btn--sticker', onclick: function () { shareCard({ card: 'league', league_id: l.id }, l.invite_url, inviteText(l.name)); }, text: 'Позвать в Telegram' }),
      h('button', { type: 'button', class: 'kk-btn kk-btn--ghost', onclick: function () { copy(l.invite_url); }, text: 'Скопировать ссылку' }),
      h('button', { type: 'button', class: 'kk-btn kk-btn--ghost', onclick: function () { go('leagues'); }, text: 'К лигам' }),
    ]);
  }

  function openLeague(id) {
    state.view = 'league';
    state.leagueId = id;
    render();
    loadLeague(id).then(render, fail);
  }

  function leagueView() {
    var t = state.leagueTables[state.leagueId];
    var head = [
      h('div', { style: 'display:flex;justify-content:space-between;align-items:center;padding-top:6px' }, [
        h('button', { type: 'button', class: 'kk-icon-btn', 'aria-label': 'Назад', onclick: function () { go('leagues'); } }, [icon(I_BACK)]),
        h('button', { type: 'button', class: 'kk-icon-btn', 'aria-label': 'Настройки лиги', onclick: function () { state.sheet = { kind: 'menu' }; render(); } }, [icon(I_MORE)]),
      ]),
    ];
    if (!t) return head.concat([h('div', { class: 'kk-skeleton' })]);
    var me = (t.items || []).filter(function (r) { return r.is_me; })[0];
    var n = (t.items || []).length;
    return head.concat([
      h('div', { style: 'display:flex;flex-direction:column;gap:6px' }, [
        h('h2', { class: 'kk-display', style: 'font-size:28px;line-height:1.1;margin:0;overflow-wrap:anywhere', text: t.name }),
        h('p', { class: 'kk-hint', style: 'font-weight:700', text: n + ' ' + M.plural(n, 'человек', 'человека', 'человек') + (me ? ' · ты ' + me.rank + '-й · ' + M.points(me.points) : '') }),
      ]),
      h('button', { type: 'button', class: 'kk-btn kk-btn--sticker', style: 'min-height:52px;font-size:16px', onclick: function () { shareCard({ card: 'league', league_id: t.id }, t.invite_url, inviteText(t.name)); } }, [icon(I_INVITE), 'Позвать друзей']),
      n > 1 ? list(t.items) : h('p', { class: 'kk-hint', text: 'Пока в лиге только ты. Позови друзей — таблица оживёт после первого матча.' }),
    ]);
  }

  function leagueMenu() {
    var t = state.leagueTables[state.leagueId] || {};
    return sheet([
      t.is_owner ? h('button', { type: 'button', text: 'Переименовать', onclick: function () { state.sheet = { kind: 'rename', draft: t.name || '' }; render(); } }) : null,
      h('button', { type: 'button', text: 'Скопировать ссылку', onclick: function () { state.sheet = null; render(); copy(t.invite_url); } }),
      h('button', { type: 'button', style: 'color:var(--kk-danger)', text: 'Выйти из лиги', onclick: function () { state.sheet = { kind: 'leave' }; render(); } }),
    ], true);
  }

  function renameSheet() {
    var s = state.sheet;
    return sheet([
      h('h2', { class: 'kk-display', style: 'font-size:20px;margin:0', text: 'новое название' }),
      h('label', { for: 'kk-rename', class: 'kk-hint', text: 'Друзья увидят новое название сразу' }),
      h('input', { id: 'kk-rename', class: 'kk-field', style: 'background:var(--kk-surface-2)', maxlength: '28', value: s.draft, oninput: function (e) { s.draft = e.target.value; } }),
      s.error ? h('p', { class: 'kk-err', text: s.error }) : null,
      h('button', { type: 'button', class: 'kk-btn kk-btn--dark', text: 'Сохранить', onclick: function () {
        api('PATCH', '/client/hockey/leagues/' + state.leagueId, { name: s.draft })
          .then(function () {
            state.sheet = null;
            state.leagues = null;
            return loadLeague(state.leagueId);
          })
          .then(render)
          .catch(function (e) { s.error = e.message; render(); });
      } }),
    ]);
  }

  function leaveSheet() {
    var t = state.leagueTables[state.leagueId] || {};
    var others = (t.items || []).filter(function (r) { return !r.is_me; });
    var text = 'Твои очки останутся в общей таблице. Вернуться можно по той же ссылке.';
    if (t.is_owner && others.length) text = 'Твои очки останутся в общей таблице. Лига перейдёт тому, кто здесь дольше всех. Вернуться можно по той же ссылке.';
    if (!others.length) text = 'Ты здесь один — лига исчезнет. Твои очки останутся в общей таблице.';
    return sheet([
      h('h2', { class: 'kk-display', style: 'font-size:20px;line-height:1.2;margin:0;overflow-wrap:anywhere', text: 'выйти из «' + (t.name || '') + '»?' }),
      h('p', { class: 'kk-hint', style: 'font-size:15px', text: text }),
      h('button', { type: 'button', class: 'kk-btn kk-btn--dark', text: 'Остаться', onclick: function () { state.sheet = null; render(); } }),
      h('button', { type: 'button', class: 'kk-btn kk-btn--danger', text: 'Выйти', onclick: function () {
        api('DELETE', '/client/hockey/leagues/' + state.leagueId + '/membership')
          .then(function () {
            delete state.leagueTables[state.leagueId];
            state.leagues = null;
            state.tableKey = null;
            state.tableKeyChosen = false;
            go('leagues');
          })
          .catch(fail);
      } }),
    ]);
  }

  // ---------- вход по ссылке ----------

  function openJoin(code) {
    state.view = 'join';
    state.joinCode = code;
    state.joinPreview = null;
    state.joinError = '';
    render();
    if (code) {
      api('GET', '/hockey/leagues/' + encodeURIComponent(code), undefined, true)
        .then(function (p) { state.joinPreview = p; render(); })
        .catch(function (e) { state.joinError = e.status === 404 ? 'gone' : e.message; render(); });
    }
  }

  function joinView() {
    if (!state.joinCode) return joinByCodeView();
    if (state.joinError === 'gone') {
      return h('div', { class: 'kk-hero kk-hero--dark' }, [
        h('span', { class: 'kk-hero__brand', text: 'кто кого' }),
        h('div', { class: 'kk-hero__body' }, [
          h('p', { class: 'kk-hero__title', style: 'font-size:26px', text: 'Этой лиги больше нет' }),
          h('p', { class: 'kk-hero__text', text: 'Все из неё вышли. Можно угадывать самому или собрать свою.' }),
        ]),
        h('button', { type: 'button', class: 'kk-btn kk-btn--sticker', text: 'Создать свою лигу', onclick: startCreate }),
        h('button', { type: 'button', class: 'kk-btn kk-btn--ghost', text: 'Угадывать самому', onclick: function () { go('matches'); } }),
      ]);
    }
    var p = state.joinPreview;
    var next = state.matches.filter(function (m) { return m.open; })[0];
    return h('div', { class: 'kk-hero kk-hero--dark' }, [
      h('span', { class: 'kk-hero__brand', text: 'кто кого' }),
      h('div', { class: 'kk-hero__body' }, p ? [
        h('div', { class: 'kk-faces', 'aria-hidden': 'true' }, (p.names || []).slice(0, 5).map(function (n) { return ava(n, 48); })),
        h('div', { style: 'display:flex;flex-direction:column;gap:10px' }, [
          h('p', { class: 'kk-hero__text', style: 'font-size:17px', text: (p.names && p.names[0] ? p.names[0] + ' зовёт тебя в лигу' : 'Тебя зовут в лигу') }),
          h('p', { class: 'kk-hero__title', text: p.name }),
          h('p', { class: 'kk-hero__text', text: p.members + ' ' + M.plural(p.members, 'человек', 'человека', 'человек') + ' уже ' + M.plural(p.members, 'угадывает', 'угадывают', 'угадывают') }),
        ]),
        next ? h('div', { class: 'kk-hero__box' }, [
          h('span', { style: 'font-size:13px;font-weight:700;opacity:.7', text: 'ближайший матч' }),
          h('span', { style: 'font-size:16px;font-weight:800', text: next.home.name + ' — ' + next.away.name }),
          h('span', { style: 'font-size:13px;opacity:.75', text: M.whenLabel(next.starts_at, new Date()) }),
        ]) : null,
        h('p', { class: 'kk-hero__text', style: 'font-size:14px', text: 'Тапаешь за команду или угадываешь счёт. После матча очки приходят сами. ' + M.RULES }),
      ] : [state.joinError ? h('p', { class: 'kk-hero__text', text: state.joinError }) : h('div', { class: 'kk-skeleton', style: 'opacity:.2' })]),
      h('button', { type: 'button', class: 'kk-btn kk-btn--sticker', disabled: !p || state.busy, onclick: joinLeague, text: 'Вступить в лигу' }),
      h('button', { type: 'button', class: 'kk-btn kk-btn--ghost', onclick: function () { go('matches'); }, text: 'Посмотреть матчи' }),
    ]);
  }

  function joinByCodeView() {
    var value = { v: '' };
    return [
      h('div', { style: 'display:flex;flex-direction:column;gap:8px;padding-top:6px' }, [
        h('h2', { class: 'kk-display', style: 'font-size:28px;line-height:1.1;margin:0', text: 'код лиги' }),
        h('p', { class: 'kk-hint', text: 'Восемь букв и цифр из ссылки друга' }),
      ]),
      h('label', { for: 'kk-code', class: 'kk-hint', style: 'font-weight:800', text: 'Код' }),
      h('input', { id: 'kk-code', class: 'kk-field', maxlength: '16', autocomplete: 'off', autocapitalize: 'characters', oninput: function (e) { value.v = e.target.value; } }),
      h('button', { type: 'button', class: 'kk-btn kk-btn--dark', text: 'Найти лигу', onclick: function () {
        var code = String(value.v || '').replace(/[^A-Za-z0-9]/g, '').toUpperCase();
        if (code) openJoin(code);
      } }),
    ];
  }

  function joinLeague() {
    state.busy = true;
    render();
    api('POST', '/client/hockey/leagues/join', { code: state.joinCode, from_card: state.fromCard || null })
      .then(function (l) {
        state.busy = false;
        state.created = l;
        state.view = 'joined';
        state.leagues = null;
        haptic('success');
        render();
      })
      .catch(function (e) {
        state.busy = false;
        toast(e.message);
      });
  }

  function joinedView() {
    var l = state.created;
    var next = state.matches.filter(function (m) { return m.open; })[0];
    return h('div', { class: 'kk-hero kk-hero--blue' }, [
      h('div', { class: 'kk-hero__body', style: 'align-items:center;text-align:center' }, [
        h('span', { class: 'kk-display', style: 'background:#ffd23f;color:#0d1424;border-radius:20px;padding:10px 18px;font-size:22px;transform:rotate(-5deg)', text: 'ты в лиге' }),
        h('p', { class: 'kk-hero__title', style: 'font-size:28px', text: l.name }),
        h('p', { class: 'kk-hero__text', style: 'max-width:290px', text: next ? 'Первый ход — ' + M.whenLabel(next.starts_at, new Date()).split(',')[0] + ': ' + next.home.name + ' или ' + next.away.name + '?' : 'Как только Динамо поставят матч, тапни за команду.' }),
      ]),
      h('button', { type: 'button', class: 'kk-btn', style: 'background:#fff;color:#0d1424', onclick: function () { go('matches'); }, text: 'Тапнуть за команду' }),
    ]);
  }

  // ---------- итог матча ----------

  function revealView() {
    var m = findMatch(state.revealId);
    if (!m || !m.result) return null;
    var pts = m.my_pick ? m.my_pick.points : 0;
    var v = M.verdict(pts == null ? 0 : pts);
    var r = m.result;
    var homeWon = r.home_score > r.away_score;
    var colors = M.pairColors(m.home, m.away);
    var mine = m.my_pick;
    var myLine = mine ? (mine.home_score != null ? 'у тебя было ' + mine.home_score + ':' + mine.away_score : 'ты был за ' + m[mine.side].name) : 'ты пропустил этот матч';
    return h('div', { class: 'kk-hero ' + (v.tone === 'miss' ? 'kk-hero--miss' : 'kk-hero--blue') }, [
      h('div', { style: 'display:flex;justify-content:space-between;align-items:center' }, [
        h('button', { type: 'button', class: 'kk-icon-btn', style: 'background:rgba(255,255,255,.14);color:#fff', 'aria-label': 'Закрыть', onclick: function () { go('matches'); } }, [icon(['M6 6l12 12', 'M18 6L6 18'])]),
        h('span', { style: 'font-size:13px;font-weight:700;opacity:.8', text: M.whenLabel(m.starts_at, new Date()).split(',')[0] + ' · ' + M.decidedLabel(r.decided_in) }),
      ]),
      h('div', { class: 'kk-hero__body', style: 'justify-content:flex-start;padding-top:24px;gap:26px' }, [
        h('p', { class: 'kk-hero__title', style: 'text-align:center;font-size:42px', text: v.head }),
        h('div', { class: 'kk-result-card' }, [
          h('div', { class: 'kk-result-teams' }, [
            h('div', { class: 'kk-result-team' + (homeWon ? '' : ' kk-result-team--lost') }, [badge(m.home, colors.home), m.home.name]),
            h('span', { class: 'kk-display', style: 'font-size:46px;text-align:center', text: r.home_score + ':' + r.away_score }),
            h('div', { class: 'kk-result-team' + (homeWon ? ' kk-result-team--lost' : '') }, [badge(m.away, colors.away), m.away.name]),
          ]),
          h('p', { class: 'kk-note', style: 'color:#4b5568', text: myLine }),
          h('span', { class: 'kk-sticker', 'aria-label': M.points(pts || 0), text: v.sticker }),
        ]),
        friendsBlock(),
      ]),
      h('button', { type: 'button', class: 'kk-btn kk-btn--ghost', style: 'background:rgba(255,255,255,.12);opacity:1', onclick: function () { go('table'); }, text: 'Таблица' }),
      pts >= 20 ? h('button', { type: 'button', class: 'kk-btn kk-btn--sticker', onclick: brag, text: 'Похвастаться в чате' }) : h('button', { type: 'button', class: 'kk-btn kk-btn--sticker', onclick: function () { go('matches'); }, text: 'Отыграться в следующем' }),
    ]);

    // Друзья из лиг: за кого были. Очков друзей API пока не отдаёт — только сторона.
    function friendsBlock() {
      var f = m.friends || { home: [], away: [] };
      var rows = [];
      ['home', 'away'].forEach(function (which) {
        var won = (which === 'home') === homeWon;
        (f[which] || []).forEach(function (name) { rows.push({ name: name, won: won, team: m[which].name }); });
      });
      if (!rows.length) return null;
      rows.sort(function (a, b) { return a.won === b.won ? 0 : a.won ? -1 : 1; });
      return h('div', { style: 'display:flex;flex-direction:column;gap:10px' }, [
        h('span', { style: 'font-size:13px;font-weight:800;opacity:.8;letter-spacing:.04em', text: 'А ДРУЗЬЯ' }),
        h('div', { class: 'kk-friends' }, rows.slice(0, 8).map(function (r) {
          return h('div', { class: 'kk-friend', style: r.won ? '' : 'opacity:.55' }, [
            ava(r.name, 36),
            h('span', { text: r.name }),
            h('span', { style: 'font-size:12px;opacity:.85', text: 'за ' + r.team }),
          ]);
        })),
      ]);
    }

    function brag() {
      var league = (state.leagues || [])[0];
      var text = v.head + ' ' + m.home.name + ' — ' + m.away.name + ' ' + r.home_score + ':' + r.away_score + ', ' + v.sticker + '. А ты угадаешь?';
      shareCard({ card: 'result', match_id: m.id }, league ? league.invite_url : null, text);
    }
  }

  // ---------- сборка ----------

  function render() {
    var nodes = [];
    var bare = state.view === 'created' || state.view === 'joined' || state.view === 'reveal' || (state.view === 'join' && state.joinCode);
    if (bare) {
      var v = state.view === 'created' ? createdView() : state.view === 'joined' ? joinedView() : state.view === 'reveal' ? revealView() : joinView();
      if (v) nodes.push(v);
      else {
        state.view = null;
        return render();
      }
    } else {
      var body;
      if (state.view === 'create') body = createView();
      else if (state.view === 'league') body = leagueView();
      else if (state.view === 'join') body = joinView();
      else if (state.tab === 'table') body = tableView();
      else if (state.tab === 'leagues') body = leaguesView();
      else body = matchesView();
      if (!state.view && state.tab === 'matches') nodes.push(top());
      nodes.push(h('main', { class: 'kk-main', style: state.view || state.tab !== 'matches' ? 'padding-top:18px' : '' }, [].concat(body)));
      nodes.push(nav());
    }
    if (state.sheet) {
      var s = state.sheet.kind === 'score' ? scoreSheet() : state.sheet.kind === 'menu' ? leagueMenu() : state.sheet.kind === 'rename' ? renameSheet() : leaveSheet();
      if (s) nodes.push(s);
    }
    if (state.toast) nodes.push(h('div', { class: 'kk-toast', role: 'status', text: state.toast }));
    var focusId = document.activeElement && document.activeElement.id;
    root.replaceChildren.apply(root, nodes);
    if (focusId) {
      var again = document.getElementById(focusId);
      if (again && again.tagName === 'INPUT') {
        again.focus();
        try { again.setSelectionRange(again.value.length, again.value.length); } catch (e) { /* */ }
      }
    }
    syncBackButton();
  }

  function syncBackButton() {
    if (!tg || !tg.BackButton) return;
    tg.BackButton.show();
  }

  function onBack() {
    if (state.sheet) {
      state.sheet = null;
      render();
      return;
    }
    if (state.view === 'league' || state.view === 'create' || state.view === 'created') return go('leagues');
    if (state.view) return go('matches');
    if (state.tab !== 'matches') return go('matches');
    location.href = '/webapp/client-home' + (initData && !(tg && tg.initData) ? '?init_data=' + encodeURIComponent(initData) : '');
  }

  function startParam() {
    var sp = tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
    return sp || params.get('tgWebAppStartParam') || params.get('startapp') || '';
  }

  function boot() {
    if (tg) {
      try {
        tg.ready();
        tg.expand();
      } catch (e) { /* */ }
      if (tg.onEvent) tg.onEvent('themeChanged', function () { applyTheme(); render(); });
      if (tg.BackButton && tg.BackButton.onClick) tg.BackButton.onClick(onBack);
    }
    applyTheme();
    var code = (params.get('join') || M.inviteCode(startParam()) || '').toUpperCase();
    var reveal = Number(params.get('reveal')) || null;
    var tab = params.get('tab');
    if (tab === 'table' || tab === 'leagues') state.tab = tab;
    render();
    if (!initData) {
      state.loading = false;
      root.replaceChildren(h('main', { class: 'kk-main', style: 'padding-top:40px' }, [
        empty('кто кого — в Telegram', 'Игра открывается из Glide в Telegram: там видно, кто из друзей за кого.', 'Понятно', function () {}, ['#e2502c', '#1747b5']),
      ]));
      return;
    }
    state.fromCard = M.cardFrom(startParam(), params.get('from'));
    if (state.fromCard) api('POST', '/client/hockey/card-opened', { card: state.fromCard }).catch(function () {});
    if (code) openJoin(code);
    loadMatches()
      .then(function () {
        state.loading = false;
        if (reveal && findMatch(reveal) && findMatch(reveal).result) {
          state.revealId = reveal;
          state.view = 'reveal';
          api('POST', '/client/hockey/matches/' + reveal + '/seen').catch(function () {});
        }
        render();
        if (state.tab === 'table') go('table');
        if (state.tab === 'leagues') go('leagues');
        if (!state.leagues) loadLeagues().then(render, function () {});
      })
      .catch(function (e) {
        state.loading = false;
        render();
        fail(e);
      });
  }

  boot();
})();
