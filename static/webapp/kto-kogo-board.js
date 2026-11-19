/**
 * «Кто кого» — хаб игры, таблица и карточка болельщика (TASK-334 S5). Холст: Hub, Table, Profile, Edge (пауза, мало игроков, новичок).
 * Таблица одна: фильтр «Команда» (Все или клуб) × фильтр «Период» (сезон или месяц), по умолчанию «Все · Сезон».
 */
(function () {
  'use strict';

  var K = window.KK;
  var h = K.h;
  var M = K.M;
  var S = K.S;
  var I = K.I;
  var state = K.state;
  var icon = K.icon;
  var NBSP = '\u00a0';

  function name(t) {
    return S.clubName(t.name);
  }

  function nowIso() {
    return new Date().toISOString();
  }

  // ---------- напоминания и «спрятать строку» (TASK-335) ----------

  function saveRemind(on) {
    K.api('PUT', '/client/hockey/remind', { on: on })
      .then(function (r) {
        state.remind = !!(r && r.on);
        K.haptic('success');
        K.toast(on ? 'Напомним о твоём ходе и пришлём итог' : 'Сообщения в чате выключены');
      })
      .catch(K.fail);
  }

  function setRemind(on) {
    function save() {
      saveRemind(on);
    }
    var tg = K.tg;
    if (!on || !tg || typeof tg.requestWriteAccess !== 'function') return save();
    try {
      tg.requestWriteAccess(function (granted) {
        if (granted === true) save();
        else K.toast('Без разрешения не получится написать в чат');
      });
    } catch (e) {
      save();
    }
  }

  function remindRow() {
    if (state.remind === null) return null;
    return h('div', { class: 'kk-card kk-remind' }, [
      icon(I.bell, 20),
      h('span', { class: 'kk-grow kk-col' }, [
        h('b', { text: 'Сообщения в чате' }),
        h('span', { class: 'kk-sub', text: 'Напомним о ходе, если его нет, а после матча пришлём итог и место в таблице. Напоминания — не чаще раза в день, ночью не пишем.' }),
      ]),
      h('button', { type: 'button', class: 'kk-toggle' + (state.remind ? ' is-on' : ''), role: 'switch', 'aria-checked': state.remind ? 'true' : 'false', 'aria-label': 'Сообщения в чате', onclick: function () { setRemind(!state.remind); } }, [h('span')]),
    ]);
  }

  // ---------- «Итог — в чат»: после первого хода просим разрешить боту писать первым ----------
  // Ход уже сохранён; всё ниже — необязательная надстройка: любой сбой молча пропускается.

  var ASK_DELAY_MS = 900; // выбор команды успевает подсветиться
  var ASK_RETRY_MS = 600; // монета, черновик счёта, ход в пути или тост — ждём, поверх не показываем
  var ASK_TRIES = 15;
  var askMemo = S.writeAskMemo((function () {
    try { return window.localStorage; } catch (e) { return null; }
  })());
  var askPlanned = false; // за сессию — не больше одной попытки

  function askCtx() {
    return { first: true, tg: K.tg, wa: window.GlideWriteAccess || null, asked: askMemo.asked(), remind: state.remind, sheet: state.sheet };
  }

  function settling() {
    if (K.coin && typeof K.coin.animating === 'function' && K.coin.animating()) return true;
    if (state.toast) return true;
    if (Object.keys(state.drafts || {}).length) return true;
    return (state.matches || []).some(function (m) { return m && m.pickPending > 0; });
  }

  /** Сервер принял первый ход игрока на экране owner. */
  function afterFirstPick(owner) {
    if (askPlanned || !S.shouldAskWrite(askCtx())) return;
    askPlanned = true;
    var tries = 0;
    function check() {
      try {
        // Игрок ушёл с экрана или открыл другую шторку — не перебиваем.
        if (K.current() !== owner || state.sheet) return;
        if (!S.shouldAskWrite(askCtx())) return;
        if (settling()) {
          if (++tries < ASK_TRIES) setTimeout(check, ASK_RETRY_MS);
          return;
        }
        askMemo.mark();
        state.sheet = { kind: 'writeAsk' };
        K.render();
      } catch (e) { /* */ }
    }
    setTimeout(check, ASK_DELAY_MS);
  }

  function answerWriteAsk(choice) {
    state.sheet = null;
    K.render();
    // «Не сейчас» — явно выключаем напоминания, иначе на сервере по умолчанию «вкл» без права писать.
    if (choice !== 'allow') {
      saveRemind(false);
      S.answerWriteAsk(choice, { memo: askMemo, tg: K.tg, wa: window.GlideWriteAccess || null });
      return;
    }
    S.answerWriteAsk(choice, { memo: askMemo, tg: K.tg, wa: window.GlideWriteAccess || null, save: function () { saveRemind(true); } });
  }

  function writeAskSheet() {
    var T = S.WRITE_ASK;
    return K.sheet(T.title, null, [
      h('span', { class: 'kk-tx', text: T.text }),
      h('div', { class: 'kk-two' }, [
        h('button', { type: 'button', class: 'kk-btn kk-btn--alt', text: T.later, onclick: function () { answerWriteAsk('later'); } }),
        h('button', { type: 'button', class: 'kk-btn kk-btn--gold', text: T.allow, onclick: function () { answerWriteAsk('allow'); } }),
      ]),
    ], 'kk-sheet--pts');
  }

  K.afterFirstPick = afterFirstPick;
  K.writeAskSheet = writeAskSheet;

  function showOnMatches() {
    K.api('PUT', '/client/hockey/prefs', { kk_hidden: false })
      .then(function () {
        state.kkHidden = false;
        K.haptic('success');
        K.toast('Строка игры снова на главной');
      })
      .catch(K.fail);
  }

  // ---------- Хаб ----------

  /** Знак игры: шайба влетает в стикер «КТО КОГО?». Заставка один раз за сессию, дальше шайба просто стоит рядом. */
  function brand() {
    var el = K.introElapsed();
    return h('h1', { class: 'kk-brand kk-grow' + (el === null ? '' : ' is-intro'), 'aria-label': 'Кто кого', style: el === null ? null : '--kk-el:' + el + 'ms' }, [
      K.puck('kk-puck--lg'),
      h('span', { class: 'kk-brand__tag', 'aria-hidden': 'true', text: 'КТО КОГО?' }),
    ]);
  }

  /** Козырь одной фразой: свободен · на матче «Динамо — Торпедо» · сыгран. */
  function trumpStatus(trump) {
    if (!trump || !trump.match_id) return 'козырь свободен';
    if (trump.locked) return 'козырь сыгран';
    var m = K.findMatch(trump.match_id);
    return m ? 'козырь на ' + S.clubShort(m.home.name) + ' — ' + S.clubShort(m.away.name) : 'козырь на матче';
  }

  function fanCard() {
    var p = state.profile;
    if (!p) return h('div', { class: 'kk-skel kk-skel--card' });
    if (!p.played) {
      return h('section', { class: 'kk-card kk-card--fan kk-card--intro' }, [
        K.sticker('КТО КОГО?'),
        h('b', { class: 'kk-hd', text: 'Угадай матч — один тап' }),
        h('span', { class: 'kk-tx', text: 'Тап за команду в карточке матча — и ты в игре, регистрации нет. Очки придут после матча — тогда появишься в таблице.' }),
      ]);
    }
    var club = p.club;
    var trump = state.double;
    var trumpText = trumpStatus(trump);
    var crowns = (p.crowns || []).length;
    return h('button', { type: 'button', class: 'kk-card kk-card--fan', style: club ? 'background:' + club.color : '', onclick: function () { K.go('profile', {}); } }, [
      K.sticker('КТО КОГО?'),
      club ? K.logoDisc(club, 52) : K.worldDisc(52),
      h('span', { class: 'kk-col kk-grow' }, [
        h('span', { class: 'kk-fan__t' }, [(p.display_name || 'Ты'), club ? ' · ' : null, club ? h('span', { class: 'kk-nowrap', text: 'за ' + name(club) }) : null]),
        h('span', { class: 'kk-fan__s' }, [
          crowns ? h('span', { class: 'kk-crownw kk-crownw--on' }, [K.crownIcon(14), S.crownCount(crowns)]) : null,
          p.streak ? h('span', { text: 'угадано подряд: ' + p.streak }) : null,
          h('span', { class: 'kk-fan__bolt' }, [icon(I.bolt, 13), trumpText]),
        ]),
      ]),
    ]);
  }

  function peaksBlock() {
    var p = state.profile;
    if (!p || !p.played || !state.peaks || !state.peaks.length) return null;
    return h('div', { class: 'kk-sec' }, [
      h('span', { class: 'kk-lbl', text: 'ТВОИ ВЕРШИНЫ' }),
      h('div', { class: 'kk-peaks' }, state.peaks.map(function (pk) {
        var t = S.peakTile(pk, p.crowns);
        return h('button', { type: 'button', class: 'kk-peak' + (t.gold ? ' is-gold' : ''), onclick: function () { K.go('table', { club: pk.club, period: pk.period }); } }, [
          h('span', { class: 'kk-peak__n', text: t.rank }),
          h('span', { class: 'kk-peak__l', text: t.name }),
          h('span', { class: 'kk-peak__w', text: t.slice }),
          h('span', { class: 'kk-peak__s', text: t.note }),
        ]);
      })),
    ]);
  }

  function leaguesSection() {
    var list = state.leagues;
    return h('div', { class: 'kk-sec' }, [
      h('div', { class: 'kk-sec__head' }, [
        h('span', { class: 'kk-lbl', text: 'ЛИГИ' }),
        h('button', { type: 'button', class: 'kk-linkbtn', onclick: function () { K.go('leagueNew', {}); } }, ['+ Создать']),
      ]),
      !list ? h('div', { class: 'kk-skel kk-skel--line' })
        : list.length ? h('div', { class: 'kk-rows' }, list.map(function (l) {
            return h('button', { type: 'button', class: 'kk-lg' + (l.active ? '' : ' is-ended'), onclick: function () { K.go('league', { id: l.id }); } }, [
              K.leagueThumb ? K.leagueThumb(l) : null,
              h('span', { class: 'kk-col kk-grow' }, [h('b', { text: l.name }), h('span', { class: 'kk-sub', text: S.leagueSub(l) + (l.active ? '' : ' · закончилась') })]),
              h('span', { class: 'kk-lg__r' + (l.my_rank === 1 ? ' is-gold' : '') }, [l.my_rank === 1 ? K.crownIcon(15) : null, l.my_rank ? String(l.my_rank) : '—']),
            ]);
          }))
          : h('span', { class: 'kk-sub', text: 'Лига — своя таблица с друзьями. Очки за матчи идут и в общую таблицу.' }),
    ]);
  }

  K.register('hub', {
    enter: function () {
      // Главная карточка ждёт только матчи и профиль (клуб игрока нужен для его матчей); вершины и лиги дорисовываются сами,
      // и медленный второстепенный запрос её не задерживает.
      var matches = state.matchesFresh
        ? Promise.resolve()
        : K.loadMatches().then(function () { state.matchesFailed = false; }, function () { state.matchesFailed = true; });
      state.matchesFresh = false;
      Promise.all([K.loadProfile(), matches])
        .then(K.loadClubMatches)
        .then(function () { state.hubReady = true; K.render(); }, function (e) { state.hubReady = true; K.fail(e); });
      K.loadPeaks().then(K.render, function () {});
      K.loadLeagues(true).then(K.render, function () {});
    },
    render: function () {
      return [
        h('main', { class: 'kk-main' }, [
          h('div', { class: 'kk-top' }, [
            brand(),
            h('button', { type: 'button', class: 'kk-btn kk-btn--alt kk-btn--sm', onclick: function () { K.go('table', {}); }, text: 'Таблица' }),
          ]),
          fanCard(),
          K.hubCards.hero(),
          K.hubCards.pending(),
          K.hubCards.day(),
          state.hubReady && K.matchRows ? K.matchRows.link() : null,
          K.hubCards.pointsLink(),
          peaksBlock(),
          leaguesSection(),
          remindRow(),
          state.kkHidden ? h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: showOnMatches, text: 'Вернуть строку игры на главную' }) : null,
        ]),
      ];
    },
    sheet: function (s) {
      return s.kind === 'points' ? K.hubCards.pointsSheet() : null;
    },
  });

  // ---------- Таблица ----------

  function tableKey(a) {
    return (a.club || '') + '|' + (a.period || 'season');
  }

  function loadTable(a) {
    var key = tableKey(a);
    var url = '/client/hockey/standings?period=' + encodeURIComponent(a.period || 'season') + (a.club ? '&club=' + encodeURIComponent(a.club) : '');
    return K.api('GET', url).then(function (d) {
      state.tables[key] = d;
      if (d && d.period && d.period.kind === 'season') state.seasonTitle = d.period.title;
    });
  }

  function chipTeam(a) {
    var club = a.club && (state.clubs || []).filter(function (c) { return c.name === a.club; })[0];
    return h('button', { type: 'button', class: 'kk-chip', 'aria-haspopup': 'dialog', style: club ? 'background:' + club.color + ';color:#fff' : '', onclick: function () { state.sheet = { kind: 'team' }; K.render(); } }, [
      club ? K.logoDisc(club, 28) : K.worldDisc(28),
      h('span', { class: 'kk-chip__t', text: a.club ? S.clubName(a.club) : 'Все матчи' }),
      icon(I.down, 16),
    ]);
  }

  /**
   * Строка общей таблицы. Тап по строке открывает стенд игрока (TASK-430); у строки без pid (лиги, старый ответ) строка
   * просто текст. Экипировка от капитанов лиг (TASK-432): у того, на ком она есть, — аватар с вещью и строка «что и от
   * кого» вместо числа ходов; остальные строки как были (владелец 2026-11-19: значок у имени не читался).
   */
  function rowEl(r) {
    var open = r.pid ? function () { if (r.is_me) K.go('stand', {}); else K.go('player', { pid: r.pid }); } : null;
    var kit = r.outfit && K.Kit.outfit(r.outfit.item) ? r.outfit : null;
    return h(open ? 'button' : 'div', open ? { type: 'button', class: 'kk-r kk-r--btn' + (r.is_me ? ' is-me' : ''), onclick: open } : { class: 'kk-r' + (r.is_me ? ' is-me' : '') }, [
      h('span', { class: 'kk-r__n' + (r.rank === 1 ? ' is-gold' : ''), text: String(r.rank) }),
      h('span', { class: 'kk-r__w' + (kit ? ' kk-r__w--kit' : ' kk-col') }, (function () {
        var col = [
          h('span', { class: 'kk-r__name' }, [h('span', { class: 'kk-r__nm', text: r.display_name }), r.is_me ? h('span', { class: 'kk-me', text: 'ты' }) : null, K.crownTag(r.crowns)]),
          kit ? h('span', { class: 'kk-r__kit', text: K.Kit.outsideNote(kit) }) : h('span', { class: 'kk-sub', text: S.rowSub(r) }),
        ];
        if (!kit) return col;
        return [K.kitAva(r.display_name, 36, { head: kit, cls: r.is_me ? '' : 'kk-ava--soft', wrap: 'kk-kit--room' }), h('span', { class: 'kk-col kk-r__wt' }, col)];
      })()),
      h('span', { class: 'kk-r__pt', text: S.spaced(r.points) }),
    ]);
  }

  /**
   * Кнопка «Таблица» приходит без среза (auto): срез выбираем, когда известны вершины. Первый кадр рисуется до enter:
   * без умолчаний закешированная таблица падала на period === undefined.
   */
  function settle(a) {
    if (a.auto === undefined) a.auto = !('club' in a) && !('period' in a);
    if (a.auto && state.peaks) {
      var s = S.tableStartArgs(state.tableChoice, state.tableStart);
      a.club = s.club;
      a.period = s.period;
      a.auto = false;
    }
    if (a.auto) return;
    a.club = a.club || null;
    a.period = a.period || 'season';
  }

  K.register('table', {
    enter: function (a) {
      settle(a);
      a.failed = false;
      var table = a.auto ? K.loadPeaks().then(function () { settle(a); return loadTable(a); }) : loadTable(a);
      Promise.all([table, K.loadClubs().catch(function () {}), K.loadPeaks(), K.loadProfile()]).then(K.render, function (e) { a.failed = true; K.render(); K.fail(e); });
    },
    render: function (a) {
      settle(a);
      if (a.auto) return [h('main', { class: 'kk-main' }, [K.topbar('Таблица', ' '), K.loading()])];
      var view = state.tables[tableKey(a)];
      var seasonTitle = state.seasonTitle || S.seasonTitleFor(nowIso());
      var peaks = (state.peaks || []).map(function (p) {
        var sel = (p.club || null) === (a.club || null) && p.period === a.period;
        return h('button', { type: 'button', class: 'kk-sc' + (sel ? ' is-on' : ''), 'aria-pressed': sel ? 'true' : 'false', onclick: function () { a.club = p.club; a.period = p.period; load(a); }, text: S.peakChip(p) });
      });
      var main = h('main', { class: 'kk-main' }, [
        K.topbar('Таблица', view ? S.tableCaption(view, a.club) : ' '),
        h('div', { class: 'kk-two kk-two--flex' }, [
          chipTeam(a),
          h('button', { type: 'button', class: 'kk-chip kk-chip--alt', 'aria-haspopup': 'dialog', onclick: function () { state.sheet = { kind: 'period' }; K.render(); } }, [S.periodLabel(a.period, seasonTitle), icon(I.down, 16)]),
        ]),
        S.isGeneralTable(a) ? null : h('button', { type: 'button', class: 'kk-btn kk-btn--alt kk-btn--sm', onclick: function () { a.club = null; a.period = 'season'; load(a); }, text: 'Общая таблица' }),
        peaks.length ? h('div', { class: 'kk-scs' }, [h('span', { class: 'kk-sub kk-nowrap', text: 'Твои вершины:' })].concat(peaks)) : null,
        state.profile ? K.standStrip('Мои награды') : null,
      ]);
      if (!view) {
        main.appendChild(a.failed ? K.retryCard('Таблица не загрузилась.', function () { a.failed = false; K.render(); load(a); }) : K.loading());
        return [main];
      }
      main.appendChild(h('div', { class: 'kk-crownbar' + (S.tableCrownMuted(view, a.period) ? ' kk-crownbar--muted' : '') }, [K.crownIcon(18), h('span', { text: S.tableCrownLine(view, a.club, a.period, view.period && view.period.kind === 'season' ? view.period.title : seasonTitle) })]));
      var few = S.fewPlayers(view, a.club, a.period);
      if (few) {
        main.appendChild(h('section', { class: 'kk-card kk-note' }, [
          h('span', { class: 'kk-lbl', text: 'МАЛО ИГРОКОВ' }),
          h('b', { class: 'kk-hd', text: few.head }),
          h('span', { class: 'kk-tx', text: few.body }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { K.go('leagueNew', { club: a.club }); }, text: few.invite }),
        ]));
      }
      var rows = S.tableRows(view, a.full).map(function (x) {
        return x.type === 'gap' ? h('div', { class: 'kk-gap', 'aria-hidden': 'true', text: '···' }) : rowEl(x.r);
      });
      if (rows.length) main.appendChild(h('div', { class: 'kk-tbl' }, rows));
      var more = S.tableMore(view, a.full);
      if (more) main.appendChild(h('button', { type: 'button', class: 'kk-ml-more', onclick: function () { a.full = true; K.render(); }, text: more }));
      if (!view.me) {
        main.appendChild(h('span', { class: 'kk-tx', text: S.noMeLine(a.club, a.period, nowIso()) }));
        main.appendChild(h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { K.reset('hub', {}); }, text: 'Сделать ход' }));
      }
      return [main];
    },
    sheet: function (s, a) {
      if (s.kind === 'team') {
        var clubs = state.clubs || [];
        var cells = [{ name: null, short: 'Все матчи', all: true }].concat(clubs);
        return K.sheet('Чьи матчи считать', 'Только матчи выбранного клуба — дома и в гостях', [
          h('div', { class: 'kk-grid4' }, cells.map(function (c) {
            var sel = (c.name || null) === (a.club || null);
            return h('button', { type: 'button', class: 'kk-tm' + (sel ? ' is-on' : ''), 'aria-pressed': sel ? 'true' : 'false', onclick: function () { a.club = c.name; state.sheet = null; load(a); } }, [
              c.all ? K.worldDisc(36) : K.logoDisc(c, 36),
              h('span', { text: c.all ? 'Все' : S.clubShort(c.name) }),
            ]);
          })),
        ]);
      }
      if (s.kind === 'period') {
        var crowns = (state.profile && state.profile.crowns) || [];
        var choices = S.periodChoices(state.seasonTitle || S.seasonTitleFor(nowIso()), nowIso(), crowns);
        return K.sheet('Период', null, choices.map(function (p) {
          var sel = p.key === a.period;
          return h('button', { type: 'button', class: 'kk-pr' + (sel ? ' is-on' : ''), 'aria-pressed': sel ? 'true' : 'false', onclick: function () { a.period = p.key; state.sheet = null; load(a); } }, [
            h('span', { text: p.label }),
            h('span', { class: 'kk-pr__n' }, [p.note, p.crown ? K.crownIcon(15, 'у тебя корона') : null]),
          ]);
        }));
      }
      return null;
    },
  });

  /** Сменили фильтр: показываем то, что есть, и догружаем таблицу. */
  function load(a) {
    state.tableChoice = { club: a.club, period: a.period };
    K.render();
    if (!state.tables[tableKey(a)]) loadTable(a).then(K.render, function (e) { a.failed = true; K.render(); K.fail(e); });
  }

  // ---------- Карточка болельщика ----------

  K.register('profile', {
    enter: function () {
      state.profileFailed = false;
      Promise.all([K.loadProfile(true), K.loadPeaks(), K.loadLeagues().catch(function () {}), K.loadClubs().catch(function () {})]).then(function () { state.profileFailed = !state.profile; K.render(); }, function (e) { state.profileFailed = true; K.render(); K.fail(e); });
    },
    render: function () {
      var p = state.profile;
      if (!p) return [h('main', { class: 'kk-main' }, [K.topbar('Болельщик', null), state.profileFailed ? K.retryCard('Карточка болельщика не загрузилась.', function () { K.replace('profile', {}); }) : K.loading()])];
      var club = p.club;
      var best = (state.peaks || [])[0];
      var main = h('main', { class: 'kk-main' }, [K.topbar('Болельщик', 'сезон ' + p.season)]);
      main.appendChild(h('section', { class: 'kk-card kk-card--fan kk-card--big', style: club ? 'background:' + club.color : '' }, [
        K.sticker('КТО КОГО? · ' + p.season),
        h('div', { class: 'kk-fan' }, [
          club ? K.logoDisc(club, 60) : K.worldDisc(60),
          h('span', { class: 'kk-col' }, [h('span', { class: 'kk-lbl kk-lbl--on', text: club ? 'БОЛЕЮ ЗА ' + name(club).toUpperCase() : 'КТО КОГО?' }), h('span', { class: 'kk-fan__name', text: p.display_name || 'Ты' })]),
        ]),
        h('div', { class: 'kk-stats' }, [
          stat(String(p.played), M.plural(p.played, 'ход', 'хода', 'ходов')),
          stat(String(p.exact), 'в точку'),
          stat(String(p.streak), 'угадано подряд', 'рекорд — ' + p.best_streak),
        ]),
        best ? h('span', { class: 'kk-fan__line', text: 'Лучшее место: ' + S.sliceLabel(best.club, best.period_title) + ' — ' + best.rank + NBSP + 'из' + NBSP + S.spaced(best.players) }) : null,
      ]));
      main.appendChild(K.standStrip('Короны и награды'));
      var lines = S.seasonTitleLine(p, p.season);
      var earned = (p.titles || []).map(function (t) {
        return h('div', { class: 'kk-cr' }, [icon(I.check, 18), h('span', { class: 'kk-grow', text: 'Знаток ' + (t.club ? S.clubGen(t.club) : 'сезона') + ' ' + t.season })]);
      });
      if (lines.length || earned.length) {
        main.appendChild(h('div', { class: 'kk-sec' }, [
          h('span', { class: 'kk-lbl', text: 'ЗВАНИЯ СЕЗОНА · ПОСЛЕ ПОСЛЕДНЕГО МАТЧА' }),
          h('div', { class: 'kk-rows' }, earned.concat(lines.map(function (l) {
            return h('div', { class: 'kk-cr' }, [h('span', { class: 'kk-cr__n', text: String(l.rank) }), h('span', { class: 'kk-grow', text: l.label }), h('span', { class: 'kk-mute', text: l.note })]);
          }))),
        ]));
      }
      if ((p.duels || []).length) {
        main.appendChild(h('div', { class: 'kk-sec' }, [
          h('span', { class: 'kk-lbl', text: 'ДУЭЛИ ЗА СЕЗОН' }),
          h('span', { class: 'kk-sub', text: S.DUEL_HINT }),
          h('div', { class: 'kk-duels' }, p.duels.map(function (d) { return h('span', { class: 'kk-cr kk-cr--c' }, [d.display_name, h('b', { text: d.won + ':' + d.lost })]); })),
        ]));
      }
      if (K.matchRows) main.appendChild(K.matchRows.link());
      var league = (state.leagues || []).filter(function (l) { return l.active; })[0];
      main.appendChild(h('div', { class: 'kk-two' }, [
        h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { if (league) K.shareCard({ card: 'league', league_id: league.id }, league.invite_url, S.inviteText(league.name, league)); else K.go('leagueNew', {}); }, text: league ? 'Позвать в лигу' : 'Создать лигу' }),
        h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.go('table', {}); }, text: 'Таблица' }),
      ]));
      return [main];
    },
  });

  function stat(v, l, extra) {
    return h('span', { class: 'kk-stat' }, [h('span', { class: 'kk-stat__v', text: v }), h('span', { class: 'kk-stat__l', text: l }), extra ? h('span', { class: 'kk-stat__l kk-stat__l--sub', text: extra }) : null]);
  }
})();
