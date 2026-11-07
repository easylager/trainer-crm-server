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
    return h('button', { type: 'button', class: 'kk-mini kk-mini--link', onclick: function () { K.openMatchPage(m.id); } }, ['Билеты и кто идёт']);
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
          }).concat([h('span', { class: 'kk-st kk-st--note', text: S.STAKES_NOTE })])
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
    shown.push(h('span', { class: 'kk-sub', text: S.DUEL_HINT }));
    return h('div', { class: 'kk-block' }, shown);
  }

  function openView(m) {
    var mine = m.my_pick;
    var colors = M.pairColors(m.home, m.away);
    var trump = S.trumpState(m, state.doubles, new Date().toISOString());
    var team = mine ? name(m[mine.side]) : '';
    var sub = mine ? S.changeUntil(m.starts_at, new Date()) : S.pointsLine(null) + '. Ходы — до\u00a0' + S.closeTime(m.starts_at) + '.';
    var center = h('div', { class: 'kk-hero__mid' }, [
      h('span', { class: 'kk-hero__time', text: S.timeOnly(m.starts_at) }),
      h('span', { class: 'kk-hero__day', text: M.whenLabel(m.starts_at, new Date()).split(',')[0] }),
    ]);
    var doubled = !!(mine && mine.doubled);
    return [
      hero(m, center),
      h('main', { class: 'kk-main' }, [
        h('span', { class: 'kk-meta', text: metaLine(m) }),
        movedNote(m),
        h('section', { class: 'kk-card kk-card--play' }, [
          K.sticker(m.race_final ? 'ПОСЛЕДНИЙ МАТЧ МЕСЯЦА' : mine ? 'ХОД СДЕЛАН' : 'КТО КОГО?'),
          h('div', { class: 'kk-q' }, [
            h('span', { class: 'kk-q__t' }, [S.questionLine(mine, team), doubled ? h('span', { class: 'kk-tag kk-tag--inline', text: 'с козырем' }) : null]),
            h('span', { class: 'kk-sub', text: sub }),
          ]),
          h('div', { class: 'kk-two' }, [sideButton(m, 'home', colors, mine), sideButton(m, 'away', colors, mine)]),
          h('button', { type: 'button', class: 'kk-mini kk-mini--wide', onclick: function () { openScore(m); } }, [mine && mine.home_score != null ? 'Изменить счёт ' + mine.home_score + ':' + mine.away_score : 'Угадать точный счёт']),
          h('button', {
            type: 'button',
            class: 'kk-mini kk-mini--wide' + (trump.on ? ' is-gold' : '') + (trump.usable ? '' : ' is-off'),
            'aria-pressed': trump.on ? 'true' : 'false',
            onclick: function () { K.toggleTrump(m); },
          }, [icon(I.bolt, 16), trump.label]),
          h('span', { class: 'kk-sub kk-sub--tight', text: S.trumpHint(m, state.doubles, state.matches, new Date().toISOString()) }),
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
      ? S.TIE_LINE + ': после овертайма или буллитов у победителя на одну шайбу больше.'
      : 'Победитель по счёту — ' + name(m[s.home > s.away ? 'home' : 'away']) + '. Шайбы каждой команды считаются, даже если победитель не угадан. ' + M.scoreHint(s.home, s.away) + '.';
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
    var points = live && mine ? S.livePoints(mine, live) : null; // только для мест в таблицах, на экране не показываем
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
        mine.doubled ? h('span', { class: 'kk-lbl kk-lbl--on', text: 'С КОЗЫРЕМ' }) : null,
        h('span', { class: 'kk-hero-tx kk-hero-tx--lg', text: S.liveWhy(mine, live, { home: name(m.home), away: name(m.away) }) }),
      ]));
      body.appendChild(placesBlock(m, points));
      body.appendChild(duelsBlock(m));
    } else {
      body.appendChild(K.emptyCard('ХОДЫ ЗАКРЫТЫ', 'Этот матч без твоего хода. Ближайшие матчи — на главной игры.'));
    }
    body.appendChild(crowdBlock(m));
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
      h('span', { class: 'kk-sub', text: 'Места по таблице до матча — если матч так и закончится.' }),
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
      h('span', { class: 'kk-sub', text: S.DUEL_HINT }),
      h('div', { class: 'kk-rows' }, moves.slice(0, 5).map(function (f) {
        var d = S.duelLive(mine, f, m.live);
        return h('div', { class: 'kk-mv' }, [
          h('span', { class: 'kk-mv__l', text: f.display_name + ' · за ' + name(m[f.side]) }),
          h('span', { class: 'kk-mv__r' }, [h('span', { class: 'kk-pill' + (d.state === 'lead' ? ' kk-pill--gold' : ''), text: d.label })]),
        ]);
      })),
    ]);
  }

  /** «Кто за кого»: по команде строка с логотипом и людьми. Одноцветно, без процентов. */
  function crowdBlock(m) {
    if (!((m.sides && (m.sides.home || m.sides.away)) || (m.friend_moves || []).length || m.my_pick)) return h('span');
    function row(side) {
      var c = S.crowdPeople(m, side);
      var faces = c.faces.map(function (f) {
        return h('span', { class: 'kk-cf' + (f.me ? ' is-me' : ''), text: f.initial });
      });
      if (c.more > 0) faces.push(h('span', { class: 'kk-cf kk-cf--more', text: '+' + c.more }));
      return h('div', { class: 'kk-crowd' }, [
        h('div', { class: 'kk-crowd__h' }, [K.logoDisc(m[side], 28), h('b', { text: 'За' + '\u00a0' + name(m[side]) })]),
        h('div', { class: 'kk-crowd__p' }, [
          faces.length ? h('span', { class: 'kk-cfs', 'aria-hidden': 'true' }, faces) : null,
          h('span', { class: 'kk-crowd__c', text: c.caption }),
        ]),
      ]);
    }
    return h('section', { class: 'kk-sec', 'aria-label': 'Кто за кого' }, [
      h('h2', { class: 'kk-lbl kk-lbl--h', text: 'КТО ЗА КОГО' }),
      row('home'),
      row('away'),
      h('span', { class: 'kk-sub', text: S.CROWD_NOTE }),
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
    var head = 'Дуэль: ' + (res === 'win' ? 'победа' : res === 'lose' ? 'поражение' : 'ничья');
    return h('section', { class: 'kk-card kk-duel' }, [
      K.ava(f.display_name, 36),
      h('span', { class: 'kk-grow kk-col' }, [h('b', { text: head }), h('span', { class: 'kk-sub', text: mineTotal + ' : ' + f.points + ' · ' + f.display_name + ' за ' + name(m[f.side]) })]),
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

  /** Цвет «угадал»: клуб игрока, а без клуба — жёлтый игры. */
  function winTone() {
    var club = state.profile && state.profile.club;
    return club && club.color ? { bg: club.color, ink: '#fff', club: true } : { bg: 'var(--kk-gold)', ink: 'var(--kk-on-gold)', club: false };
  }

  /** Салют для «в точку»: 8 частиц в цветах клуба, жёлтом игры и белом. Движение задаёт CSS, при reduced-motion его нет. */
  var BURST = [[-150, -110, 220], [140, -120, -160], [160, 40, 300], [-160, 60, -260], [-60, -150, 120], [70, -150, -90], [110, 100, 180], [-110, 110, -200]];
  function burst(tone) {
    var club = tone.club ? '#7fb2ff' : '#ffffff';
    var colors = ['#ffd23f', '#ffffff', '#ffd23f', club, '#ffffff', club, '#ffd23f', '#ffffff'];
    return BURST.map(function (b, i) {
      return h('span', { class: 'kk-c', 'aria-hidden': 'true', style: 'background:' + colors[i] + ';--dx:' + b[0] + 'px;--dy:' + b[1] + 'px;--r:' + b[2] + 'deg;animation-delay:' + (i * 0.04).toFixed(2) + 's' });
    });
  }

  function exactCard(m, mine, total, items) {
    var r = m.result;
    var tone = winTone();
    var chips = [h('span', { class: 'kk-chipx', text: '+' + total + (mine.doubled ? ' с козырем' : '') })];
    var place = S.bestLeagueChip(items);
    if (place) chips.push(h('span', { class: 'kk-chipx', text: place }));
    return h('section', { class: 'kk-cel', 'aria-label': 'Итог хода', style: 'background:' + tone.bg + ';color:' + tone.ink }, burst(tone).concat([
      h('span', { class: 'kk-cel__d', text: S.dayLabelUp(m.starts_at) + ' · ИТОГ' }),
      h('div', { class: 'kk-cel__s' }, [K.logoDisc(m.home, 60), h('span', { class: 'kk-cel__n', text: r.home_score + ':' + r.away_score }), K.logoDisc(m.away, 60)]),
      h('span', { class: 'kk-pop', text: 'В ТОЧКУ!' }),
      h('span', { class: 'kk-cel__l', text: 'Твой ход ' + mine.home_score + ':' + mine.away_score + ' — так и вышло.' }),
      h('div', { class: 'kk-cel__c' }, chips),
    ]));
  }

  function nextTurnLink(m) {
    var nm = S.nextMatch(state.matches, m);
    if (!nm) return null;
    return h('button', { type: 'button', class: 'kk-nextl', onclick: function () { K.go('match', { id: nm.id }); } }, [h('span', { text: S.nextTurnLabel(nm) }), icon(I.chev, 18)]);
  }

  function finalView(m) {
    var mine = m.my_pick;
    var r = m.result;
    var pts = mine && mine.points != null ? mine.points : null;
    var v = M.verdict(pts == null ? 0 : pts);
    var total = pts == null ? null : M.totalPoints(mine);
    var mv = state.movement[m.id];
    var items = mv && mv.data ? mv.data.items : [];
    var exact = !!mine && pts === M.EXACT;
    var center = h('div', { class: 'kk-hero__mid' }, [
      h('span', { class: 'kk-hero__score', text: r.home_score + ' : ' + r.away_score }),
      h('span', { class: 'kk-hero__day', text: M.decidedLabel(r.decided_in) }),
    ]);
    var main = h('main', { class: 'kk-main' });
    if (!mine) {
      main.appendChild(K.emptyCard('ЭТОТ МАТЧ БЕЗ ТЕБЯ', 'Хода на матч не было, очков нет. Следующий матч — на главной игры.'));
    } else {
      var tone = winTone();
      if (exact) {
        main.appendChild(h('div', { class: 'kk-top' }, [h('button', { type: 'button', class: 'kk-round', 'aria-label': 'Назад', onclick: K.back }, [icon(I.back)]), h('span', { class: 'kk-sub', text: leagueTag(m) })]));
        main.appendChild(exactCard(m, mine, total, items));
      } else {
        var stkStyle = v.tone === 'ok' && tone.club ? 'background:' + tone.bg + ';color:' + tone.ink : null;
        var next = pts === 0 ? S.nextMatch(state.matches, m) : null;
        main.appendChild(h('div', { class: 'kk-resh' }, [
          h('div', { class: 'kk-col' }, [
            h('span', { class: 'kk-lbl', text: 'ТВОЙ ХОД ' + (mine.home_score != null ? mine.home_score + ':' + mine.away_score : 'ЗА ' + name(m[mine.side]).toUpperCase()) }),
            h('h2', { class: 'kk-h2 kk-h2--xl', text: pts == null ? 'Считаем очки' : S.resultHead(pts) }),
            pts === 0 ? h('span', { class: 'kk-tx', text: S.missLine(next, new Date()) }) : null,
            pts && mine.doubled ? h('span', { class: 'kk-sub', text: 'с козырем' }) : null,
          ]),
          h('span', { class: 'kk-stk kk-stk--' + v.tone, style: stkStyle, 'aria-label': pts == null ? 'очки считаются' : M.points(total || 0), text: pts == null ? '…' : total ? '+' + total : '0' }),
        ]));
      }
      if (pts != null) {
        var rows = S.movementRows(items);
        main.appendChild(h('div', { class: 'kk-sec' }, [
          h('span', { class: 'kk-lbl', text: 'КУДА СДВИНУЛОСЬ ТВОЁ МЕСТО' }),
          mv && mv.loading ? h('span', { class: 'kk-skel kk-skel--line' }) : rows.length ? h('div', { class: 'kk-rows' }, rows.map(moveRow)) : h('span', { class: 'kk-sub', text: 'Пока в таблицах меньше трёх игроков с очками — места появятся, когда людей станет больше.' }),
          S.crownLineAfter(items) ? h('span', { class: 'kk-crownline', text: S.crownLineAfter(items) }) : null,
        ]));
        var duel = duelCard(m);
        if (duel) main.appendChild(duel);
      }
      if (exact) {
        main.appendChild(h('button', { type: 'button', class: 'kk-btn kk-btn--gold kk-btn--lg', onclick: function () { brag(m, v); } }, [icon(I.send, 20), 'Похвастаться в чате']));
        var nl = nextTurnLink(m);
        if (nl) main.appendChild(nl);
        main.appendChild(h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.go('table', {}); }, text: 'Таблица' }));
      } else {
        main.appendChild(h('div', { class: 'kk-two' }, [
          pts == null ? null : h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { brag(m, v); }, text: pts >= 20 ? 'Похвастаться' : 'Позвать на реванш' }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.go('table', {}); }, text: 'Таблица' }),
        ]));
      }
    }
    if (!exact || !mine) main.appendChild(nextCard(m));
    return exact ? [main] : [hero(m, center), main];
  }

  function brag(m, v) {
    var league = (state.leagues || [])[0];
    var r = m.result;
    var total = M.totalPoints(m.my_pick);
    var shown = total ? '+' + total + (m.my_pick.doubled ? ' с козырем' : '') : v.sticker;
    var text = S.resultHead(m.my_pick.points) + ' ' + name(m.home) + ' — ' + name(m.away) + ' ' + r.home_score + ':' + r.away_score + ', ' + shown + '. А ты угадаешь?';
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
          h('b', { class: 'kk-hd', text: name(m.home) + ' — ' + name(m.away) + ' отменён' }),
          h('span', { class: 'kk-tx', text: 'Ход без очков, дуэли не считаются. Если на нём стоял козырь, он свободен: назначь его на другой матч недели.' }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.back(); }, text: 'К матчам' }),
        ]),
      ]),
    ];
  }

  function notFound() {
    return [h('main', { class: 'kk-main' }, [K.topbar('Матч', null), K.emptyCard('МАТЧ НЕ НАЙДЕН', 'Такого матча нет или ссылка устарела. Ближайшие матчи — на главной игры.')])];
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
        if (ph === 'open') {
          // Ходы закрываются за минуту до старта: экран, открытый заранее, сам переходит в «матч идёт».
          K.poll('match', 15000, function (args) {
            var cur = K.findMatch(args.id);
            if (!cur || new Date(cur.starts_at).getTime() - Date.now() > 70000) return;
            K.fetchMatch(args.id).then(function (fresh) {
              if (fresh && phase(fresh) !== 'open') K.replace('match', args);
            }, function () {});
          });
        }
      }, function (e) {
        if (e && e.status === 404) missing[id] = true;
        else {
          missing[id] = 'error';
          K.fail(e);
        }
        K.render();
      });
    },
    render: function (a) {
      if (missing[a.id] === 'error' && !K.findMatch(a.id)) return [h('main', { class: 'kk-main' }, [K.topbar('Матч', null), K.retryCard('Матч не загрузился.', function () { K.replace('match', a); })])];
      if (missing[a.id] === true) return notFound();
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
