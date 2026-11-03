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

  function setRemind(on) {
    function save() {
      K.api('PUT', '/client/hockey/remind', { on: on })
        .then(function (r) {
          state.remind = !!(r && r.on);
          K.haptic('success');
          K.toast(on ? 'Напомню о ходе за 3 часа до матча твоей команды' : 'Напоминания выключены');
        })
        .catch(K.fail);
    }
    var tg = K.tg;
    if (!on || !tg || typeof tg.requestWriteAccess !== 'function') return save();
    try {
      tg.requestWriteAccess(function (granted) {
        if (granted === true) save();
        else K.toast('Без разрешения бот не сможет напомнить');
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
        h('b', { text: state.remind ? 'Напомню о ходе за 3 часа до матча' : 'Напомнить о ходе за 3 часа до матча' }),
        h('span', { class: 'kk-sub', text: 'Если хода ещё нет — по матчу твоей команды. После матча пришлю итог и твоё место в таблице.' }),
      ]),
      h('button', { type: 'button', class: 'kk-toggle' + (state.remind ? ' is-on' : ''), role: 'switch', 'aria-checked': state.remind ? 'true' : 'false', 'aria-label': 'Напоминать о ходе за 3 часа до матча', onclick: function () { setRemind(!state.remind); } }, [h('span')]),
    ]);
  }

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

  function fanCard() {
    var p = state.profile;
    if (!p) return h('div', { class: 'kk-skel kk-skel--card' });
    if (!p.played) {
      return h('section', { class: 'kk-card kk-card--fan kk-card--intro' }, [
        K.sticker('КТО КОГО'),
        h('b', { class: 'kk-hd', text: 'Угадай матч — один тап' }),
        h('span', { class: 'kk-tx', text: 'Тап за команду в карточке матча — и ты в игре, регистрации нет. В таблице появишься после первого итога.' }),
      ]);
    }
    var club = p.club;
    var trump = state.double;
    var trumpText = !trump || !trump.match_id ? 'козырь есть' : trump.locked ? 'козырь сыграл' : 'козырь на матче';
    var crowns = (p.crowns || []).length;
    return h('button', { type: 'button', class: 'kk-card kk-card--fan', style: club ? 'background:' + club.color : '', onclick: function () { K.go('profile', {}); } }, [
      K.sticker('КТО КОГО'),
      club ? K.logoDisc(club, 52) : K.worldDisc(52),
      h('span', { class: 'kk-col kk-grow' }, [
        h('span', { class: 'kk-fan__t' }, [(p.display_name || 'Ты'), club ? ' · ' : null, club ? h('span', { class: 'kk-nowrap', text: 'за ' + name(club) }) : null]),
        h('span', { class: 'kk-fan__s' }, [
          crowns ? h('span', { class: 'kk-crownw kk-crownw--on' }, [K.crownIcon(14), S.crownCount(crowns)]) : null,
          p.streak ? h('span', { text: 'серия ' + p.streak }) : null,
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
          h('span', { class: 'kk-peak__l', text: t.label }),
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
              h('span', { class: 'kk-col kk-grow' }, [h('b', { text: l.name }), h('span', { class: 'kk-sub', text: S.leagueSub(l) + (l.active ? '' : ' · закончилась') })]),
              h('span', { class: 'kk-lg__r' + (l.my_rank === 1 ? ' is-gold' : '') }, [l.my_rank === 1 ? K.crownIcon(15) : null, l.my_rank ? String(l.my_rank) : '—']),
            ]);
          }))
          : h('span', { class: 'kk-sub', text: 'Лига — это ты, твои люди и выбранные команды. Очки за матчи идут и в общую таблицу.' }),
    ]);
  }

  K.register('hub', {
    enter: function () {
      Promise.all([K.loadProfile(), K.loadPeaks(), K.loadLeagues(true).catch(function () {}), K.loadMatches().then(function () { state.matchesFailed = false; }, function () { state.matchesFailed = true; })])
        .then(K.loadClubMatches)
        .then(function () { state.hubReady = true; K.render(); }, function (e) { state.hubReady = true; K.fail(e); });
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
          K.hubCards.day(),
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

  function rowEl(r) {
    return h('div', { class: 'kk-r' + (r.is_me ? ' is-me' : '') }, [
      h('span', { class: 'kk-r__n' + (r.rank === 1 ? ' is-gold' : ''), text: String(r.rank) }),
      h('span', { class: 'kk-col kk-r__w' }, [
        h('span', { class: 'kk-r__name' }, [h('span', { class: 'kk-r__nm', text: r.display_name }), r.is_me ? h('span', { class: 'kk-me', text: 'ты' }) : null, K.crownTag(r.crowns)]),
        h('span', { class: 'kk-sub', text: S.rowSub(r) }),
      ]),
      h('span', { class: 'kk-r__pt', text: S.spaced(r.points) }),
    ]);
  }

  K.register('table', {
    enter: function (a) {
      a.club = a.club || null;
      a.period = a.period || 'season';
      a.failed = false;
      Promise.all([loadTable(a), K.loadClubs().catch(function () {}), K.loadPeaks(), K.loadProfile()]).then(K.render, function (e) { a.failed = true; K.render(); K.fail(e); });
    },
    render: function (a) {
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
        peaks.length ? h('div', { class: 'kk-scs' }, [h('span', { class: 'kk-sub kk-nowrap', text: 'Твои вершины:' })].concat(peaks)) : null,
      ]);
      if (!view) {
        main.appendChild(a.failed ? K.retryCard('Таблица не загрузилась.', function () { a.failed = false; K.render(); load(a); }) : K.loading());
        return [main];
      }
      main.appendChild(h('div', { class: 'kk-crownbar' }, [K.crownIcon(18), h('span', { text: S.tableCrownLine(view, a.club, a.period, view.period && view.period.kind === 'season' ? view.period.title : seasonTitle) })]));
      var few = S.fewPlayers(view, a.club, a.period);
      if (few) {
        main.appendChild(h('section', { class: 'kk-card kk-note' }, [
          h('span', { class: 'kk-lbl', text: 'МАЛО ИГРОКОВ' }),
          h('b', { class: 'kk-hd', text: few.head }),
          h('span', { class: 'kk-tx', text: few.body }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { K.go('leagueNew', { club: a.club }); }, text: few.invite }),
        ]));
      }
      var rows = S.tableRows(view).map(function (x) {
        return x.type === 'gap' ? h('div', { class: 'kk-gap', 'aria-hidden': 'true', text: '···' }) : rowEl(x.r);
      });
      if (rows.length) main.appendChild(h('div', { class: 'kk-tbl' }, rows));
      if (!view.me) {
        main.appendChild(h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { K.reset('hub', {}); }, text: S.noMeLine(a.club, a.period, nowIso()) }));
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
    K.render();
    if (!state.tables[tableKey(a)]) loadTable(a).then(K.render, function (e) { a.failed = true; K.render(); K.fail(e); });
  }

  // ---------- Карточка болельщика ----------

  K.register('profile', {
    enter: function () {
      state.profileFailed = false;
      Promise.all([K.loadProfile(true), K.loadPeaks(), K.loadLeagues().catch(function () {})]).then(function () { state.profileFailed = !state.profile; K.render(); }, function (e) { state.profileFailed = true; K.render(); K.fail(e); });
    },
    render: function () {
      var p = state.profile;
      if (!p) return [h('main', { class: 'kk-main' }, [K.topbar('Болельщик', null), state.profileFailed ? K.retryCard('Карточка болельщика не загрузилась.', function () { K.replace('profile', {}); }) : K.loading()])];
      var club = p.club;
      var best = (state.peaks || [])[0];
      var main = h('main', { class: 'kk-main' }, [K.topbar('Болельщик', 'сезон ' + p.season)]);
      main.appendChild(h('section', { class: 'kk-card kk-card--fan kk-card--big', style: club ? 'background:' + club.color : '' }, [
        K.sticker('КТО КОГО · ' + p.season),
        h('div', { class: 'kk-fan' }, [
          club ? K.logoDisc(club, 60) : K.worldDisc(60),
          h('span', { class: 'kk-col' }, [h('span', { class: 'kk-lbl kk-lbl--on', text: club ? 'БОЛЕЮ ЗА ' + name(club).toUpperCase() : 'КТО КОГО' }), h('span', { class: 'kk-fan__name', text: p.display_name || 'Ты' })]),
        ]),
        h('div', { class: 'kk-stats' }, [
          stat(String(p.played), M.plural(p.played, 'ход', 'хода', 'ходов')),
          stat(p.correct_percent == null ? '—' : p.correct_percent + '%', 'угадано'),
          stat(String(p.exact), M.plural(p.exact, 'точный', 'точных', 'точных')),
          stat(String(p.streak), 'серия · лучшая ' + p.best_streak),
        ]),
        best ? h('span', { class: 'kk-fan__line', text: 'Лучшее место: ' + S.sliceLabel(best.club, best.period_title) + ' — ' + best.rank + NBSP + 'из' + NBSP + S.spaced(best.players) }) : null,
      ]));
      var crowns = (p.crowns || []).slice(0, 6);
      main.appendChild(h('div', { class: 'kk-sec' }, [
        h('span', { class: 'kk-lbl', text: 'КОРОНЫ' }),
        crowns.length
          ? h('div', { class: 'kk-rows' }, crowns.map(function (c) { return h('div', { class: 'kk-cr' }, [K.crownIcon(20), h('span', { class: 'kk-grow', text: S.crownLabel(c) })]); }))
          : h('div', { class: 'kk-cr kk-cr--empty' }, [K.crownIcon(20), h('span', { class: 'kk-grow', text: 'Корона — за первое место месяца, если очки хотя бы у троих' })]),
      ]));
      var lines = S.seasonTitleLine(p, p.season);
      var earned = (p.titles || []).map(function (t) {
        return h('div', { class: 'kk-cr' }, [icon(I.check, 18), h('span', { class: 'kk-grow', text: 'Знаток ' + (t.club ? S.clubGen(t.club) : 'сезона') + ' ' + t.season })]);
      });
      if (lines.length || earned.length) {
        main.appendChild(h('div', { class: 'kk-sec' }, [
          h('span', { class: 'kk-lbl', text: 'ЗВАНИЯ СЕЗОНА · ПОСЛЕ ФИНАЛА' }),
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
      var league = (state.leagues || []).filter(function (l) { return l.active; })[0];
      main.appendChild(h('div', { class: 'kk-two' }, [
        h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { if (league) K.shareCard({ card: 'league', league_id: league.id }, league.invite_url, S.inviteText(league.name, league)); else K.go('leagueNew', {}); }, text: league ? 'Позвать в лигу' : 'Создать лигу' }),
        h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.go('table', {}); }, text: 'Таблица' }),
      ]));
      return [main];
    },
  });

  function stat(v, l) {
    return h('span', { class: 'kk-stat' }, [h('span', { class: 'kk-stat__v', text: v }), h('span', { class: 'kk-stat__l', text: l })]);
  }
})();
