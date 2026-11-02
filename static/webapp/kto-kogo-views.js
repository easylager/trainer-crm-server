/**
 * «Кто кого» — экраны матча (TASK-334 S5): ход в один тап с «Если угадаешь» и козырем, матч идёт с живыми
 * очками, итог с движением по срезам и следующим ходом, края (отмена, итог на проверке, матч не найден).
 * Холст: Main, Live, Result, Edge.
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
  var missing = {};

  function phase(m) {
    if (m.status === 'cancelled') return 'cancelled';
    if (m.status === 'final') return 'final';
    if (m.open) return 'open';
    return 'live';
  }

  function name(team) {
    return S.clubName(team.name);
  }

  function leagueTag(m) {
    return m.league === 'extraliga' ? 'ЭКСТРАЛИГА' : 'КХЛ';
  }

  /** Шапка матча: половинки в цветах клубов, логотипы, центр — время или счёт. */
  function hero(m, center) {
    var c = M.pairColors(m.home, m.away);
    function team(t) {
      return h('div', { class: 'kk-hero__team' }, [K.logoDisc(t, 68), h('span', { class: 'kk-hero__name', text: name(t) })]);
    }
    return h('header', { class: 'kk-hero' }, [
      h('div', { class: 'kk-hero__bg', 'aria-hidden': 'true' }, [h('span', { style: 'background:' + c.home }), h('span', { style: 'background:' + c.away })]),
      h('div', { class: 'kk-hero__in' }, [
        h('div', { class: 'kk-hero__bar' }, [
          h('button', { type: 'button', class: 'kk-round kk-round--glass', 'aria-label': 'Назад', onclick: K.back }, [icon(I.back)]),
          h('span', { class: 'kk-pill kk-pill--glass', text: leagueTag(m) }),
        ]),
        h('div', { class: 'kk-hero__teams' }, [team(m.home), center, team(m.away)]),
      ]),
    ]);
  }

  function metaLine(m) {
    var place = [m.arena, m.city && (!m.arena || m.arena.indexOf(m.city) < 0) ? m.city : null].filter(Boolean).join(', ');
    return M.whenLabel(m.starts_at, new Date()) + (place ? ' · ' + place : '');
  }

  /** Пометка переноса под строкой «когда и где»; ход при переносе сохраняется. */
  function movedNote(m) {
    var line = M.movedLine(m);
    return line ? h('span', { class: 'kk-moved', text: line }) : null;
  }

  /** Страница матча в Mini App: «Иду / Позвать / Билеты» живут там — здесь только вход, кнопок не дублируем. */
  function matchPageLink(m) {
    if (!m.has_page) return null;
    return h('button', { type: 'button', class: 'kk-mini kk-mini--link', onclick: function () { K.openMatchPage(m.id); } }, ['Страница матча: иду, позвать, билеты']);
  }

  function sideButton(m, side, colors, mine) {
    var sel = mine && mine.side === side;
    return h('button', {
      type: 'button',
      class: 'kk-side' + (sel ? ' is-on' : ''),
      'aria-pressed': sel ? 'true' : 'false',
      style: sel ? 'background:' + colors[side] : '',
      onclick: function () { K.pickSide(m, side); },
      text: name(m[side]),
    });
  }

  // ---------- 1. Матч с ходом ----------

  function stakesBlock(m) {
    var mine = m.my_pick;
    var sk = state.stakes[m.id];
    var rows;
    if (!mine) rows = [h('span', { class: 'kk-st kk-st--mute', text: S.stakesEmpty(false) })];
    else if (!sk || (sk.loading && !sk.data)) rows = [h('span', { class: 'kk-skel kk-skel--line' })];
    else {
      var lines = sk.data ? S.stakeLines(sk.data.items) : [];
      rows = lines.length
        ? lines.map(function (l) {
            return h('span', { class: 'kk-st' + (l.gold ? ' kk-st--gold' : '') }, [
              l.gold ? K.crownIcon(18) : icon(l.icon === 'duel' ? I.swap : I.up, 18),
              h('span', { text: l.text }),
            ]);
          }).concat([h('span', { class: 'kk-st kk-st--note', text: 'Оценка по таблице на сейчас: чужие ходы ещё меняются.' })])
        : [h('span', { class: 'kk-st kk-st--mute', text: S.stakesEmpty(true) })];
    }
    return h('div', { class: 'kk-block' }, [h('span', { class: 'kk-lbl kk-lbl--gold', text: 'ЕСЛИ УГАДАЕШЬ' })].concat(rows));
  }

  function friendsBlock(m) {
    var mine = m.my_pick;
    var list = [];
    ['home', 'away'].forEach(function (side) {
      ((m.friends && m.friends[side]) || []).forEach(function (n) { list.push({ name: n, side: side }); });
    });
    if (!list.length) return null;
    if (!mine) {
      return h('div', { class: 'kk-block' }, [h('span', { class: 'kk-st kk-st--mute', text: M.nudgeLine(m.friends, { home: name(m.home), away: name(m.away) }) })]);
    }
    var shown = list.slice(0, 3).map(function (f) {
      var pill = S.duelPill(mine.side, f.side);
      return h('div', { class: 'kk-st' }, [
        K.ava(f.name, 28),
        h('span', { class: 'kk-grow', text: f.name + ' за ' + name(m[f.side]) }),
        h('span', { class: 'kk-pill' + (pill.hot ? ' kk-pill--gold' : ''), text: pill.label }),
      ]);
    });
    if (list.length > 3) shown.push(h('span', { class: 'kk-st kk-st--mute', text: 'и ещё ' + (list.length - 3) }));
    return h('div', { class: 'kk-block' }, shown);
  }

  function openView(m) {
    var mine = m.my_pick;
    var colors = M.pairColors(m.home, m.away);
    var trump = S.trumpState(m, state.doubles, new Date().toISOString());
    var team = mine ? name(m[mine.side]) : '';
    var pts = mine ? S.pointsLine(mine) : S.pointsLine(null) + '. Меняй до ' + S.timeOnly(m.starts_at) + '.';
    var center = h('div', { class: 'kk-hero__mid' }, [
      h('span', { class: 'kk-hero__time', text: S.timeOnly(m.starts_at) }),
      h('span', { class: 'kk-hero__day', text: M.whenLabel(m.starts_at, new Date()).split(',')[0] }),
    ]);
    return [
      hero(m, center),
      h('main', { class: 'kk-main' }, [
        h('span', { class: 'kk-meta', text: metaLine(m) }),
        movedNote(m),
        h('section', { class: 'kk-card kk-card--play' }, [
          K.sticker(m.race_final ? 'ФИНАЛ МЕСЯЦА' : mine ? 'ХОД СДЕЛАН' : 'КТО КОГО?'),
          h('div', { class: 'kk-q' }, [h('span', { class: 'kk-q__t', text: S.questionLine(mine, team) }), h('span', { class: 'kk-sub', text: pts })]),
          h('div', { class: 'kk-two' }, [sideButton(m, 'home', colors, mine), sideButton(m, 'away', colors, mine)]),
          h('div', { class: 'kk-two' }, [
            h('button', { type: 'button', class: 'kk-mini', onclick: function () { openScore(m); } }, [mine && mine.home_score != null ? 'Счёт ' + mine.home_score + ':' + mine.away_score : 'Точный счёт']),
            h('button', {
              type: 'button',
              class: 'kk-mini' + (trump.on ? ' is-gold' : '') + (trump.usable ? '' : ' is-off'),
              'aria-pressed': trump.on ? 'true' : 'false',
              onclick: function () { K.toggleTrump(m); },
            }, [icon(I.bolt, 16), trump.label]),
          ]),
          h('span', { class: 'kk-sub kk-sub--tight', text: 'Козырь: один на неделю, очки за матч ×2 · ' + trump.note }),
          stakesBlock(m),
          friendsBlock(m),
        ]),
        m.race_final ? h('span', { class: 'kk-sub', text: 'Последний матч этого месяца: корона решится после него.' }) : null,
        matchPageLink(m),
      ]),
    ];
  }

  function openScore(m) {
    var mine = m.my_pick || {};
    var home = mine.home_score != null ? mine.home_score : mine.side === 'home' ? 3 : 1;
    var away = mine.away_score != null ? mine.away_score : mine.side === 'away' ? 3 : 1;
    if (home === away) away = home + 1;
    state.sheet = { kind: 'score', matchId: m.id, home: home, away: away };
    K.render();
  }

  function scoreSheet(s) {
    var m = K.findMatch(s.matchId);
    if (!m) return null;
    var colors = M.pairColors(m.home, m.away);
    var tie = s.home === s.away;
    function stepper(key, side) {
      return h('div', { class: 'kk-step', style: 'background:' + colors[side] }, [
        h('span', { class: 'kk-step__n', text: name(m[side]) }),
        h('div', { class: 'kk-step__row' }, [
          h('button', { type: 'button', class: 'kk-stp', 'aria-label': 'Меньше шайб: ' + name(m[side]), onclick: function () { s[key] = M.clampGoals(s[key] - 1); K.render(); } }, ['−']),
          h('span', { class: 'kk-step__v', text: String(s[key]), 'aria-live': 'polite' }),
          h('button', { type: 'button', class: 'kk-stp', 'aria-label': 'Больше шайб: ' + name(m[side]), onclick: function () { s[key] = M.clampGoals(s[key] + 1); K.render(); } }, ['+']),
        ]),
      ]);
    }
    var hint = tie
      ? 'Ничьих нет: после овертайма или буллитов у победителя на одну шайбу больше.'
      : 'Победитель по счёту — ' + name(m[s.home > s.away ? 'home' : 'away']) + '. Очки за шайбы каждой команды считаются, даже если победителя не угадаешь. ' + M.scoreHint(s.home, s.away) + '.';
    return K.sheet('Точный счёт', null, [
      h('div', { class: 'kk-two' }, [stepper('home', 'home'), stepper('away', 'away')]),
      h('span', { class: 'kk-sub', text: hint }),
      h('button', { type: 'button', class: 'kk-btn kk-btn--gold', disabled: tie ? 'true' : null, 'aria-disabled': tie ? 'true' : 'false', onclick: function () { if (!tie) K.saveScore(m, s.home, s.away); }, text: tie ? 'Нужен победитель' : 'Сохранить ' + s.home + ':' + s.away }),
    ]);
  }

  // ---------- 2. Матч идёт ----------

  function liveView(m) {
    var live = m.live;
    var mine = m.my_pick;
    var review = m.status === 'review';
    var colors = M.pairColors(m.home, m.away);
    var stamp = S.liveStamp(live);
    var points = live && mine ? S.livePoints(mine, live) : null;
    var score = h('span', { class: 'kk-score', 'aria-live': 'polite', text: live ? live.home_score + ' : ' + live.away_score : '– : –' });
    var out = [
      h('main', { class: 'kk-main' }, [
        h('div', { class: 'kk-top' }, [h('button', { type: 'button', class: 'kk-round', 'aria-label': 'Назад', onclick: K.back }, [icon(I.back)]), h('span', { class: 'kk-sub', text: leagueTag(m) })]),
        h('section', { class: 'kk-card' }, [
          h('div', { class: 'kk-live' }, [
            h('span', { class: 'kk-live__st' }, [h('span', { class: 'kk-dot', 'aria-hidden': 'true' }), review ? 'ИТОГ ПРОВЕРЯЕМ' : live ? 'ИДЁТ' : 'ХОДЫ ЗАКРЫТЫ']),
            h('span', { class: 'kk-sub', text: stamp }),
          ]),
          movedNote(m),
          h('div', { class: 'kk-board' }, [
            h('span', { class: 'kk-board__t' }, [K.logoDisc(m.home, 44), h('span', { text: name(m.home) })]),
            score,
            h('span', { class: 'kk-board__t kk-board__t--r' }, [h('span', { text: name(m.away) }), K.logoDisc(m.away, 44)]),
          ]),
        ]),
      ]),
    ];
    var body = out[0];
    if (mine) {
      var bg = colors[mine.side];
      body.appendChild(h('section', { class: 'kk-card kk-card--hero', style: 'background:' + bg }, [
        K.sticker('ТЫ ЗА ' + name(m[mine.side]).toUpperCase() + (mine.home_score != null ? ' · ' + mine.home_score + ':' + mine.away_score : '')),
        h('span', { class: 'kk-lbl kk-lbl--on', text: 'ЕСЛИ ТАК И ЗАКОНЧИТСЯ' }),
        h('span', { class: 'kk-big', text: points == null ? '—' : '+' + points }),
        h('span', { class: 'kk-hero-tx', text: S.liveWhy(mine, live) }),
      ]));
      body.appendChild(placesBlock(m, points));
      body.appendChild(duelsBlock(m));
    } else {
      body.appendChild(K.emptyCard('ХОДЫ ЗАКРЫТЫ', 'Этот матч без твоего хода. Следующий — в хабе игры.'));
    }
    body.appendChild(crowdBlock(m, colors));
    var pageLink = matchPageLink(m);
    if (pageLink) body.appendChild(pageLink);
    return out;
  }

  function placesBlock(m, points) {
    var sk = state.stakes[m.id];
    if (!sk || !sk.data) return h('span');
    var rows = S.livePlaces(sk.data.items, points != null && points >= 20);
    if (!rows.length) return h('span');
    return h('div', { class: 'kk-sec' }, [
      h('span', { class: 'kk-lbl', text: 'ТВОИ МЕСТА ПРЯМО СЕЙЧАС' }),
      h('div', { class: 'kk-rows' }, rows.map(moveRow)),
      h('span', { class: 'kk-sub', text: 'Места — по таблице до матча, если так закончится.' }),
    ]);
  }

  function moveRow(r) {
    return h('div', { class: 'kk-mv' }, [
      h('span', { class: 'kk-mv__l', text: r.label }),
      h('span', { class: 'kk-mv__r' }, [
        h('span', { class: 'kk-mute', text: r.from }),
        icon(I.arrow, 14),
        h('span', { class: 'kk-tone kk-tone--' + r.tone, text: r.to }),
        r.crown ? K.crownIcon(16, 'место короны') : null,
      ]),
    ]);
  }

  function duelsBlock(m) {
    var mine = m.my_pick;
    var moves = m.friend_moves || [];
    if (!moves.length || !m.live) return h('span');
    return h('div', { class: 'kk-sec' }, [
      h('span', { class: 'kk-lbl', text: 'ДУЭЛИ' }),
      h('div', { class: 'kk-rows' }, moves.slice(0, 5).map(function (f) {
        var d = S.duelLive(mine, f, m.live);
        var scoreText = d.me == null || d.they == null ? '—' : d.me + ' : ' + d.they;
        return h('div', { class: 'kk-mv' }, [
          h('span', { class: 'kk-mv__l', text: 'с ' + f.display_name + ' · за ' + name(m[f.side]) }),
          h('span', { class: 'kk-mv__r' }, [h('b', { text: scoreText }), h('span', { class: 'kk-pill' + (d.state === 'lead' ? ' kk-pill--gold' : ''), text: d.label })]),
        ]);
      })),
    ]);
  }

  function crowdBlock(m, colors) {
    var c = S.crowdShare(m.sides, null, function (side) { return m[side].name; });
    if (!c) return h('span');
    return h('div', { class: 'kk-sec' }, [
      h('div', { class: 'kk-bar', 'aria-hidden': 'true' }, [h('span', { style: 'width:' + c.home + '%;background:' + colors.home }), h('span', { style: 'width:' + c.away + '%;background:' + colors.away })]),
      h('span', { class: 'kk-sub', text: c.text + ' · проценты открылись со стартом матча' }),
    ]);
  }

  // ---------- 3. Итог ----------

  function loadMovement(m) {
    var cur = state.movement[m.id];
    if (cur) return Promise.resolve();
    state.movement[m.id] = { loading: true, data: null };
    return K.api('GET', '/client/hockey/matches/' + m.id + '/movement')
      .then(function (d) { state.movement[m.id] = { loading: false, data: d }; })
      .catch(function () { state.movement[m.id] = { loading: false, data: null }; });
  }

  function duelCard(m) {
    var mine = m.my_pick;
    var mineTotal = M.totalPoints(mine);
    var done = (m.friend_moves || []).filter(function (f) { return f.points != null; });
    if (!done.length || mineTotal == null) return null;
    var f = done[0];
    var res = S.duelFinal(mineTotal, f.points);
    var head = res === 'win' ? 'Дуэль с ' + f.display_name + ' — твоя' : res === 'lose' ? 'Дуэль с ' + f.display_name + ' — не твоя' : 'Дуэль с ' + f.display_name + ' — ничья';
    return h('section', { class: 'kk-card kk-duel' }, [
      K.ava(f.display_name, 36),
      h('span', { class: 'kk-grow kk-col' }, [h('b', { text: head }), h('span', { class: 'kk-sub', text: mineTotal + ' : ' + f.points + ' · ' + f.display_name + ' был за ' + name(m[f.side]) })]),
    ]);
  }

  function nextCard(m) {
    var nm = S.nextMatch(state.matches, m);
    if (!nm) {
      return K.emptyCard('СЛЕДУЮЩИЙ ХОД', 'Новые матчи появятся, как только их поставят в календарь.');
    }
    var colors = M.pairColors(nm.home, nm.away);
    var mine = nm.my_pick;
    function pk(side) {
      var sel = mine && mine.side === side;
      return h('button', { type: 'button', class: 'kk-pk' + (sel ? ' is-on' : ''), 'aria-pressed': sel ? 'true' : 'false', style: sel ? 'background:' + colors[side] : '', onclick: function () { K.pickSide(nm, side); } }, [K.logoDisc(nm[side], 24), name(nm[side])]);
    }
    return h('section', { class: 'kk-card kk-card--play' }, [
      K.sticker('СЛЕДУЮЩИЙ ХОД'),
      h('button', { type: 'button', class: 'kk-link-row', onclick: function () { K.go('match', { id: nm.id }); } }, [
        h('span', { class: 'kk-col' }, [h('b', { text: name(nm.home) + ' — ' + name(nm.away) }), h('span', { class: 'kk-sub', text: M.whenLabel(nm.starts_at, new Date()) + (mine ? ' · ход сделан, меняй до старта' : ' · тапни — и ход сделан') })]),
        icon(I.arrow, 16),
      ]),
      h('div', { class: 'kk-two' }, [pk('home'), pk('away')]),
    ]);
  }

  function finalView(m) {
    var mine = m.my_pick;
    var r = m.result;
    var pts = mine && mine.points != null ? mine.points : null;
    var v = M.verdict(pts == null ? 0 : pts);
    var total = pts == null ? null : M.totalPoints(mine);
    var mv = state.movement[m.id];
    var items = mv && mv.data ? mv.data.items : [];
    var center = h('div', { class: 'kk-hero__mid' }, [
      h('span', { class: 'kk-hero__score', text: r.home_score + ' : ' + r.away_score }),
      h('span', { class: 'kk-hero__day', text: M.decidedLabel(r.decided_in) }),
    ]);
    var main = h('main', { class: 'kk-main' });
    if (!mine) {
      main.appendChild(K.emptyCard('ЭТОТ МАТЧ БЕЗ ТЕБЯ', 'Хода на матч не было, очков нет. Следующий матч — в хабе игры.'));
    } else {
      var stk = pts == null ? '…' : (total ? '+' + total : '0') + (mine.doubled && total ? ' ×2' : '');
      main.appendChild(h('div', { class: 'kk-resh' }, [
        h('div', { class: 'kk-col' }, [
          h('span', { class: 'kk-lbl', text: 'ТВОЙ ХОД ' + (mine.home_score != null ? mine.home_score + ':' + mine.away_score : 'ЗА ' + name(m[mine.side]).toUpperCase()) }),
          h('h2', { class: 'kk-h2 kk-h2--xl', text: pts == null ? 'Считаем очки' : S.resultHead(pts) }),
        ]),
        h('span', { class: 'kk-stk kk-stk--' + v.tone, 'aria-label': pts == null ? 'очки считаются' : M.points(total || 0), text: stk }),
      ]));
      if (pts != null) {
        var rows = S.movementRows(items);
        main.appendChild(h('div', { class: 'kk-sec' }, [
          h('span', { class: 'kk-lbl', text: 'КУДА СДВИНУЛОСЬ ТВОЁ МЕСТО' }),
          mv && mv.loading ? h('span', { class: 'kk-skel kk-skel--line' }) : rows.length ? h('div', { class: 'kk-rows' }, rows.map(moveRow)) : h('span', { class: 'kk-sub', text: 'Срезов, где уже соревнуются трое, пока нет — места появятся, когда игроков станет больше.' }),
          S.crownLineAfter(items) ? h('span', { class: 'kk-crownline', text: S.crownLineAfter(items) }) : null,
        ]));
        var duel = duelCard(m);
        if (duel) main.appendChild(duel);
      }
      main.appendChild(h('div', { class: 'kk-two' }, [
        h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { brag(m, v); }, text: pts >= 20 ? 'Похвастаться' : 'Позвать на реванш' }),
        h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.go('table', {}); }, text: 'Таблица' }),
      ]));
    }
    main.appendChild(nextCard(m));
    return [hero(m, center), main];
  }

  function brag(m, v) {
    var league = (state.leagues || [])[0];
    var r = m.result;
    var text = S.resultHead(m.my_pick.points) + ' ' + name(m.home) + ' — ' + name(m.away) + ' ' + r.home_score + ':' + r.away_score + ', ' + v.sticker + '. А ты угадаешь?';
    K.shareCard({ card: 'result', match_id: m.id }, league ? league.invite_url : null, text);
  }

  // ---------- 10. Края ----------

  function cancelledView(m) {
    var center = h('div', { class: 'kk-hero__mid' }, [h('span', { class: 'kk-hero__day', text: 'отменён' })]);
    return [
      hero(m, center),
      h('main', { class: 'kk-main' }, [
        h('section', { class: 'kk-card kk-note' }, [
          K.sticker('ОТМЕНА', 'kk-tag--soft'),
          h('span', { class: 'kk-lbl', text: 'ОТМЕНА' }),
          h('b', { class: 'kk-hd', text: name(m.home) + ' — ' + name(m.away) + ' отменён' }),
          h('span', { class: 'kk-tx', text: 'Ход без очков, дуэли не считаются. Козырь вернулся — используй его на другом матче недели.' }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.back(); }, text: 'К матчам' }),
        ]),
      ]),
    ];
  }

  function notFound() {
    return [h('main', { class: 'kk-main' }, [K.topbar('Матч', null), K.emptyCard('МАТЧ НЕ НАЙДЕН', 'Такого матча нет или ссылка устарела. Ближайшие матчи — в хабе игры.')])];
  }

  // ---------- регистрация ----------

  K.register('match', {
    enter: function (a) {
      var id = a.id;
      delete missing[id];
      K.fetchMatch(id).then(function (m) {
        K.render();
        if (!m) return;
        var ph = phase(m);
        if (m.my_pick && (ph === 'open' || ph === 'live')) K.loadStakes(m.id).then(K.render);
        if (ph === 'final' && m.my_pick) {
          loadMovement(m).then(K.render);
          K.api('POST', '/client/hockey/matches/' + m.id + '/seen').catch(function () {});
          if (!state.leagues) K.loadLeagues().catch(function () {});
        }
        if (ph === 'live') {
          K.poll('match', 45000, function (args) {
            K.fetchMatch(args.id).then(function (fresh) {
              if (fresh && phase(fresh) === 'final') K.replace('match', args);
              else K.render();
            }, function () {});
          });
        }
        if (ph === 'open' && !state.matches.length) K.loadMatches().then(K.render, function () {});
      }, function (e) {
        if (e && e.status === 404) missing[id] = true;
        else K.fail(e);
        K.render();
      });
    },
    render: function (a) {
      if (missing[a.id]) return notFound();
      var m = K.findMatch(a.id);
      if (!m) return [h('main', { class: 'kk-main' }, [K.topbar('Матч', null), K.loading()])];
      var ph = phase(m);
      if (ph === 'cancelled') return cancelledView(m);
      if (ph === 'final') return finalView(m);
      if (ph === 'live') return liveView(m);
      return openView(m);
    },
    sheet: function (s) {
      return s.kind === 'score' ? scoreSheet(s) : null;
    },
  });
})();
