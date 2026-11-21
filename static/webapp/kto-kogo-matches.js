/**
 * «Кто кого» — экран «Матчи и мои ходы» (TASK-359). Макет: .ai/handoff/design-kk/matches (Main, All, Empty, Hub, States),
 * копия — claude.ai/artifact/Bsaqpjce4oXrtvxo7vTUhm.
 *
 * Всё, что решает, какой статус у строки, лежит в kto-kogo-screens-model.js (rowModel, groupMatches, mergeMatchList);
 * здесь только запросы, вёрстка и поведение. Строка матча (K.matchRows.row) общая: ту же рисует блок «ждём итог» в хабе.
 * Список грузится страницами: первая — идёт и ждём итог, впереди и последние сыгранные, «Показать раньше» — дальше по сезону.
 * Чужие имена попадают в DOM только через textContent.
 */
(function () {
  'use strict';

  var K = window.KK;
  var h = K.h;
  var S = K.S;
  var I = K.I;
  var state = K.state;
  var icon = K.icon;

  // Пока есть что ждать, список обновляется сам; без идущих и ближайших стартов запросов нет, но часы идут.
  var POLL_MS = 45000;
  var SOON_MS = 10 * 60 * 1000;
  // Множитель козыря показывается только у очков уже сыгранного матча (до матча в игре чисел и «×2» нет).
  var TRUMP_MARK = String.fromCharCode(215) + '2';
  var LIST_ICON = ['M4 6h16', 'M4 12h16', 'M4 18h10'];
  var CLOCK_ICON = ['M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z', 'M12 7v5l3 2'];
  var LEAGUES = [{ key: 'all', label: 'Все лиги' }, { key: 'khl', label: 'КХЛ' }, { key: 'extraliga', label: 'Экстралига' }];

  // Выбор игрока живёт, пока открыта игра: вернулся с матча — тот же режим и фильтр.
  var ml = { mode: 'mine', league: 'all', pages: {} };

  function league() {
    // Фильтр лиги есть только у «Все матчи»; в «Мои ходы» запрос идёт по всем лигам.
    return ml.mode === 'mine' ? 'all' : ml.league;
  }

  function key() {
    return ml.mode + '|' + league();
  }

  function page() {
    return ml.pages[key()] || (ml.pages[key()] = { items: null, hasMore: false, cursor: null, awaiting: null, me: null, failed: false, more: '' });
  }

  function path(before) {
    return '/client/hockey/matches?league=' + league() + '&mode=' + ml.mode + (before ? '&before=' + encodeURIComponent(before) : '');
  }

  /** Матч открывается страницей игры сразу, без пустого кадра: берём то, что уже пришло в списке. */
  function seed(items) {
    var known = {};
    state.matches.forEach(function (m) { known[m.id] = true; });
    items.forEach(function (m) {
      if (!known[m.id]) state.matchCache[m.id] = m;
    });
  }

  function loadHead() {
    var p = page();
    return K.api('GET', path()).then(function (d) {
      var merged = S.mergeMatchList(p.items ? p : null, (d && d.items) || [], d && d.history, new Date());
      p.items = merged.items;
      p.hasMore = merged.hasMore;
      p.cursor = merged.cursor;
      p.awaiting = d && d.awaiting != null ? d.awaiting : null;
      p.me = (d && d.me) || null;
      p.failed = false;
      if (d && d.me !== undefined) state.me = d.me;
      seed(p.items);
    }, function (e) {
      // Уже есть что показать — ошибка обновления не стирает список.
      if (!p.items) p.failed = true;
      throw e;
    });
  }

  function refresh() {
    var p = page();
    p.failed = false;
    return loadHead().then(K.render, function () { K.render(); });
  }

  function loadMore() {
    var p = page();
    if (!p.hasMore || p.more === 'loading') return;
    p.more = 'loading';
    K.render();
    K.api('GET', path(p.cursor)).then(function (d) {
      var next = S.appendMatchPage(p, (d && d.items) || [], d && d.history);
      p.items = next.items;
      p.hasMore = next.hasMore;
      p.cursor = next.cursor;
      p.more = '';
      seed(p.items);
      K.render();
    }, function (e) {
      p.more = 'failed';
      K.render();
      K.fail(e);
    });
  }

  function needsPoll(p) {
    if (!p.items) return true;
    var now = new Date();
    if (S.groupMatches(p.items, now).active.length) return true;
    return p.items.some(function (m) {
      var t = new Date(m.starts_at).getTime() - now.getTime();
      return m.status === 'scheduled' && t > 0 && t < SOON_MS;
    });
  }

  function startPoll() {
    K.poll('matches', POLL_MS, function () {
      var p = page();
      if (!needsPoll(p)) {
        K.render(); // часы идут: впереди → идёт → ждём итог меняется и без запроса
        return;
      }
      return loadHead().then(K.render);
    });
  }

  // ---------- строка матча ----------

  function open(m) {
    K.go('match', { id: m.id });
  }

  function chipEl(c) {
    if (!c) return null;
    var kids = [];
    if (c.kind === 'live') kids.push(h('span', { class: 'kk-mc__dot', 'aria-hidden': 'true' }));
    if (c.kind === 'wait') kids.push(icon(CLOCK_ICON, 14));
    kids.push(c.text);
    return h('span', { class: 'kk-mc__chip kk-mc__chip--' + c.kind }, kids);
  }

  function teamEl(team, right, struck) {
    var name = h('span', { class: 'kk-mc__n' + (struck ? ' is-struck' : ''), text: S.clubShort(team.name) });
    var disc = K.logoDisc(team, 28);
    return h('span', { class: 'kk-mc__t' + (right ? ' kk-mc__t--r' : '') }, right ? [name, disc] : [disc, name]);
  }

  function rightEl(m, r) {
    var x = r.right;
    if (x.kind === 'button') {
      return h('button', {
        type: 'button',
        class: 'kk-mc__btn' + (x.gold ? ' is-gold' : ''),
        'aria-label': x.text + ': ' + S.clubName(m.home.name) + ' — ' + S.clubName(m.away.name),
        onclick: function () { open(m); },
        text: x.text,
      });
    }
    if (x.kind === 'note') return h('span', { class: 'kk-mc__note', text: x.text });
    if (x.kind === 'points') {
      return h('span', { class: 'kk-mc__pts' }, [
        h('span', { class: 'kk-mc__p kk-mc__p--' + x.tone, text: x.text }),
        x.trump ? h('span', { class: 'kk-mc__x', role: 'img', 'aria-label': 'с козырем' }, [icon(I.bolt, 14), TRUMP_MARK]) : null,
      ]);
    }
    return null;
  }

  /** Пустое место под монетку (TASK-360): её кнопку рисует K.coin, если он подключён; без него слот пуст и скрыт. */
  function coinSlot(m) {
    var slot = h('span', { class: 'kk-mc__coin' });
    if (K.coin && typeof K.coin.button === 'function') {
      var btn = K.coin.button(m);
      if (btn) slot.appendChild(btn);
    }
    return slot;
  }

  function rowEl(m, now) {
    // Ход, сделанный в этой сессии (в том числе монеткой), лежит в копии матча, которую знает K.saveScore.
    var own = typeof K.findMatch === 'function' ? K.findMatch(m.id) : null;
    if (own && own !== m && own.pickSeq) m.my_pick = own.my_pick;
    var r = S.rowModel(m, now || new Date());
    var head = h('button', { type: 'button', class: 'kk-mc__open', onclick: function () { open(m); } }, [
      h('span', { class: 'kk-mc__bar' }, [h('span', { class: 'kk-mc__lbl', text: r.label }), chipEl(r.chip)]),
      h('span', { class: 'kk-mc__teams' }, [
        teamEl(m.home, false, r.struck),
        h('span', { class: 'kk-mc__c' }, [h('b', { class: 'kk-mc__big', text: r.center.big }), h('span', { class: 'kk-mc__cap', text: r.center.cap })]),
        teamEl(m.away, true, r.struck),
      ]),
    ]);
    var foot = h('div', { class: 'kk-mc__foot' }, [
      h('span', { class: 'kk-mc__mv' }, [
        h('span', { class: 'kk-mc__ml', text: r.move.label }),
        h('span', { class: 'kk-mc__mt' + (r.move.muted ? ' is-muted' : ''), text: r.move.text }),
      ]),
      r.phase === 'upcoming' && m.open ? coinSlot(m) : null,
      rightEl(m, r),
    ]);
    // Барабаны, «ВЫПАЛО» и «Монетка выбрала» — часть контракта K.coin; без панели монета крутилась бы вхолостую.
    var panel = r.phase === 'upcoming' && m.open && K.coin && typeof K.coin.panel === 'function' ? K.coin.panel(m) : null;
    return h('article', { class: 'kk-mc kk-mc--' + r.phase }, [head, foot, panel]);
  }

  // ---------- вход из хаба и профиля ----------

  function entryLink() {
    var pending = S.pendingMatches(state.matches, new Date()).length;
    return h('button', { type: 'button', class: 'kk-ml-go', onclick: function () { K.go('matches', {}); } }, [
      h('span', { class: 'kk-ml-go__ic', 'aria-hidden': 'true' }, [icon(LIST_ICON, 22)]),
      h('span', { class: 'kk-ml-go__t' }, [h('b', { text: S.ENTRY_TITLE }), h('span', { text: S.entryLine(pending, state.me) })]),
      pending ? h('span', { class: 'kk-ml-go__n', role: 'img', 'aria-label': pending + ' ' + (pending === 1 ? 'ждёт итога' : 'ждут итога'), text: String(pending) }) : null,
      icon(I.chev, 20),
    ]);
  }

  K.matchRows = { row: rowEl, link: entryLink };

  // ---------- экран ----------

  function setMode(mode) {
    if (ml.mode === mode) return;
    ml.mode = mode;
    K.render();
    refresh();
  }

  function setLeague(l) {
    if (ml.league === l) return;
    ml.league = l;
    K.render();
    refresh();
  }

  function tabs() {
    function tab(mode, text) {
      var on = ml.mode === mode;
      return h('button', { type: 'button', class: 'kk-ml-tab' + (on ? ' is-on' : ''), 'aria-pressed': on ? 'true' : 'false', onclick: function () { setMode(mode); }, text: text });
    }
    return h('div', { class: 'kk-ml-tabs', role: 'group', 'aria-label': 'Что показывать' }, [tab('mine', 'Мои ходы'), tab('all', 'Все матчи')]);
  }

  function chips() {
    return h('div', { class: 'kk-ml-chips', role: 'group', 'aria-label': 'Лига' }, LEAGUES.map(function (l) {
      var on = ml.league === l.key;
      return h('button', { type: 'button', class: 'kk-ml-chip' + (on ? ' is-on' : ''), 'aria-pressed': on ? 'true' : 'false', onclick: function () { setLeague(l.key); }, text: l.label });
    }));
  }

  function summary(p) {
    if (!p.me && !p.awaiting) return null;
    var s = S.matchesSummary(p.me, p.awaiting);
    return h('section', { class: 'kk-ml-sum', 'aria-label': 'Сводка', 'aria-live': 'polite' }, [
      h('div', { class: 'kk-ml-sum__c' }, [h('b', { text: s.awaiting }), h('span', { text: s.awaitingLabel })]),
      h('div', { class: 'kk-ml-sum__c' }, [h('b', { text: s.points }), h('span', { text: s.pointsLabel })]),
    ]);
  }

  function sectionHead(title, count, note) {
    return h('div', { class: 'kk-ml-sec' }, [
      h('div', { class: 'kk-ml-sh' }, [h('h2', { class: 'kk-ml-h2', text: title }), count ? h('span', { class: 'kk-ml-cnt', text: count }) : null]),
      note ? h('p', { class: 'kk-ml-note', text: note }) : null,
    ]);
  }

  function days(groups, now) {
    var out = [];
    groups.forEach(function (g) {
      out.push(h('div', { class: 'kk-ml-day', text: g.head }));
      out.push(h('div', { class: 'kk-ml-list' }, g.items.map(function (m) { return rowEl(m, now); })));
    });
    return out;
  }

  function total(groups) {
    return groups.reduce(function (n, g) { return n + g.items.length; }, 0);
  }

  /* Кнопка «К ближайшему матчу» — только когда такой матч есть (TASK-437); список матчей не загрузился — ведём на хаб,
     там «Повторить». */
  function emptyCard() {
    var next = S.nearestOpen((page().items || []).concat(state.matches || []));
    var e = S.matchesEmptyCopy(next || state.matchesFailed);
    return h('section', { class: 'kk-card kk-ml-empty' }, [
      h('span', { class: 'kk-ml-empty__tag', text: e.label }),
      h('b', { class: 'kk-ml-empty__h', text: e.head }),
      h('span', { class: 'kk-tx', text: e.text }),
      e.cta ? h('button', {
        type: 'button',
        class: 'kk-btn kk-btn--gold kk-btn--sm',
        onclick: function () {
          if (next) open(next);
          else K.reset('hub', {});
        },
        text: e.cta,
      }) : null,
    ]);
  }

  function moreButton(p) {
    var busy = p.more === 'loading';
    return h('button', {
      type: 'button',
      class: 'kk-ml-more',
      disabled: busy ? 'true' : null,
      'aria-busy': busy ? 'true' : null,
      'aria-live': 'polite',
      onclick: loadMore,
      text: busy ? 'Загружаем…' : p.more === 'failed' ? 'Не загрузилось. Повторить' : 'Показать раньше',
    });
  }

  function body(p) {
    if (p.failed && !p.items) return [K.retryCard(function () { p.failed = false; K.render(); refresh(); })];
    if (!p.items) return [K.loading()];
    if (ml.mode === 'mine' && S.matchesEmpty(p.items, p.hasMore)) return [emptyCard()];
    var now = new Date();
    var g = S.groupMatches(p.items, now);
    var out = [];
    if (g.active.length) {
      out.push(sectionHead('ИДЁТ И ЖДЁМ ИТОГ', String(g.active.length), S.waitNote(state.remind === true)));
      out.push(h('div', { class: 'kk-ml-list' }, g.active.map(function (m) { return rowEl(m, now); })));
    }
    if (g.recent.length) {
      out.push(sectionHead('ИТОГ ЕСТЬ', String(g.recent.length)));
      out.push(h('div', { class: 'kk-ml-list' }, g.recent.map(function (m) { return rowEl(m, now); })));
    }
    if (g.upcoming.length) {
      out.push(sectionHead('ВПЕРЕДИ', String(total(g.upcoming))));
      out = out.concat(days(g.upcoming, now));
    }
    if (g.done.length) {
      // «N ходов» — ходы сезона с очками (me.played); у фильтра по лиге такое число соврало бы, поэтому там его нет.
      out.push(sectionHead('СЫГРАЛИ', league() === 'all' ? S.playedCount(p.me) : ''));
      out = out.concat(days(g.done, now));
    }
    if (!out.length) out.push(K.emptyCard('ПОКА ПУСТО', 'Матчей в этом списке пока нет.'));
    if (p.hasMore) out.push(moreButton(p));
    return out;
  }

  var SUB = { all: 'Все лиги', khl: 'КХЛ', extraliga: 'Экстралига' };

  K.register('matches', {
    enter: function (a) {
      if (a && (a.mode === 'mine' || a.mode === 'all')) ml.mode = a.mode;
      refresh();
      startPoll();
    },
    render: function () {
      var p = page();
      var kids = [K.topbar(S.MATCHES_TITLE, SUB[league()] + ' · сезон'), summary(p), tabs()];
      if (ml.mode === 'all') kids.push(chips());
      return [h('main', { class: 'kk-main kk-ml' }, kids.concat(body(p)))];
    },
  });
})();
