/**
 * «Кто кого» — карточки хаба v2: «Твоя команда» (счёт и козырь прямо в хабе), матчи дня и таблица очков.
 * Холст: claude.ai/artifact/SpMeyNMs2GoG29akhF2o6a (Main, Points). Логика выбора матча и счёта — в kto-kogo-screens-model.js
 * (heroMatch, dayMatches, stepScore, effectivePick); здесь только вёрстка и отправка ходов теми же вызовами,
 * что у карточки матча: K.pickSide, K.saveScore, K.toggleTrump.
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
  var timers = {};
  /** Счёт уходит на сервер, когда игрок перестал тапать: серия тапов — один запрос, а не десять. */
  var SEND_AFTER_MS = 350;

  function nm(team) {
    return S.clubName(team.name);
  }

  function openMatch(m) {
    K.go('match', { id: m.id });
  }

  // ---------- ход: сторона, счёт, козырь ----------

  function tapSide(m, side) {
    if (!m.open) return openMatch(m);
    var draft = state.drafts[m.id] || null;
    if (!S.sideTapSends(m.my_pick, draft, side)) return;
    clearTimeout(timers[m.id]);
    delete state.drafts[m.id];
    K.pickSide(m, side);
  }

  function flushScore(m) {
    var d = state.drafts[m.id];
    if (!d || d[0] === d[1]) return;
    delete state.drafts[m.id];
    K.saveScore(m, d[0], d[1]);
  }

  function step(m, idx, delta) {
    if (!m.open) return;
    var draft = S.stepScore(m.my_pick, state.drafts[m.id] || null, idx, delta);
    state.drafts[m.id] = draft;
    clearTimeout(timers[m.id]);
    // Ничья не отправляется: в хоккее её нет, игрок видит объяснение и двигает счёт дальше.
    if (draft[0] !== draft[1]) timers[m.id] = setTimeout(function () { flushScore(m); }, SEND_AFTER_MS);
    K.haptic();
    K.render();
  }

  function effective(m) {
    return S.effectivePick(m.my_pick, state.drafts[m.id] || null);
  }

  function stepBtn(m, idx, delta, size) {
    var team = nm(m[idx === 0 ? 'home' : 'away']);
    return h('button', {
      type: 'button',
      class: 'kk-hs kk-hs--' + size,
      id: 'kk-s-' + m.id + '-' + idx + (delta > 0 ? 'p' : 'm'),
      'data-keep': '',
      'aria-label': (delta > 0 ? 'Больше шайб: ' : 'Меньше шайб: ') + team,
      onclick: function () { step(m, idx, delta); },
      text: delta > 0 ? '+' : '−',
    });
  }

  function goalVal(eff, idx, cls) {
    return h('span', { class: cls, 'aria-hidden': 'true', text: eff.score ? String(eff.score[idx]) : '–' });
  }

  function scoreRow(m, eff, size) {
    return h('div', { class: 'kk-hsr kk-hsr--' + size }, [
      stepBtn(m, 0, -1, size), goalVal(eff, 0, 'kk-hsr__v'), stepBtn(m, 0, 1, size),
      h('span', { class: 'kk-hsr__c', 'aria-hidden': 'true', text: ':' }),
      stepBtn(m, 1, -1, size), goalVal(eff, 1, 'kk-hsr__v'), stepBtn(m, 1, 1, size),
    ]);
  }

  // ---------- «Твоя команда» / «Матч дня» ----------

  function current() {
    var club = state.profile && state.profile.club ? state.profile.club.name : null;
    return S.heroMatch(state.matches, club, new Date());
  }

  function teamBtn(m, side, eff) {
    var on = eff.side === side;
    return h('button', {
      type: 'button',
      class: 'kk-ht' + (on ? ' is-on' : ''),
      'aria-pressed': on ? 'true' : 'false',
      'aria-label': 'Победит ' + nm(m[side]),
      onclick: function () { tapSide(m, side); },
    }, [K.logoDisc(m[side], 52), h('span', { class: 'kk-ht__n', text: nm(m[side]) })]);
  }

  function trumpButton(m) {
    var t = S.trumpState(m, state.doubles, new Date().toISOString());
    var on = !!(m.my_pick && m.my_pick.doubled);
    return [
      h('button', {
        type: 'button',
        class: 'kk-htr' + (on ? ' is-on' : '') + (t.usable ? '' : ' is-off'),
        id: 'kk-trump-' + m.id,
        'data-keep': '',
        'aria-pressed': on ? 'true' : 'false',
        'aria-disabled': t.usable ? null : 'true',
        onclick: function () { K.toggleTrump(m); },
      }, [icon(I.bolt, 16), S.trumpLabel(on)]),
      h('span', { class: 'kk-htr__note', text: S.trumpHint(m, state.doubles, state.matches, new Date().toISOString()) }),
    ];
  }

  function heroCard() {
    if (!state.hubReady) return h('div', { class: 'kk-skel kk-skel--hero' });
    var hero = current();
    if (!hero) return null;
    var m = hero.match;
    var club = state.profile && state.profile.club;
    var eff = effective(m);
    var doubled = !!(m.my_pick && m.my_pick.doubled);
    var bg = (club ? club.color : (m.away_team === M.DINAMO ? m.away : m.home).color) || M.NEUTRAL;
    var sum = eff.side ? S.moveSummary(eff, doubled, nm(m[eff.side])) : null;
    var kids = [
      K.sticker(hero.tag),
      h('button', { type: 'button', class: 'kk-hm', 'aria-label': 'Открыть матч ' + nm(m.home) + ' — ' + nm(m.away), onclick: function () { openMatch(m); }, text: S.heroMeta(m) }),
      h('div', { class: 'kk-two kk-two--hero' }, [teamBtn(m, 'home', eff), teamBtn(m, 'away', eff)]),
    ];
    if (!eff.side) kids.push(h('span', { class: 'kk-hh', text: 'Тапни, кто победит.' }));
    else {
      kids.push(h('div', { class: 'kk-hbox' }, [
        h('div', { class: 'kk-hbox__head' }, [
          h('span', { class: 'kk-hbox__t', text: 'Точный счёт' }),
          h('span', { class: 'kk-hbox__s', text: 'необязательно' }),
        ]),
        scoreRow(m, eff, 'lg'),
      ].concat(trumpButton(m))));
      kids.push(h('div', { class: 'kk-hsum' }, [
        h('span', { class: 'kk-hsum__t', 'aria-live': 'polite', text: sum.text }),
        sum.sticker ? h('span', { class: 'kk-tag kk-tag--inline', text: sum.sticker }) : null,
      ]));
      kids.push(h('span', { class: 'kk-hnote', text: S.changeUntil(m.starts_at, new Date()) }));
    }
    return h('section', { class: 'kk-card kk-yc', 'aria-label': hero.tag === 'ТВОЯ КОМАНДА' ? 'Матч твоей команды' : 'Матч дня', style: 'background:' + bg }, kids);
  }

  // ---------- матчи дня ----------

  function dayTeam(m, side, eff, colors) {
    var on = eff.side === side;
    return h('button', {
      type: 'button',
      class: 'kk-dt' + (on ? ' is-on' : '') + (m.open ? '' : ' is-off'),
      'aria-pressed': on ? 'true' : 'false',
      'aria-label': 'Победит ' + nm(m[side]),
      'aria-disabled': m.open ? null : 'true',
      style: on ? 'background:' + colors[side] : '',
      onclick: function () { tapSide(m, side); },
    }, [K.logoDisc(m[side], 32), h('span', { class: 'kk-dt__n', text: S.clubShort(m[side].name) })]);
  }

  function dayRow(m, mixed) {
    var colors = M.pairColors(m.home, m.away);
    var eff = effective(m);
    var time = m.open || m.status === 'scheduled' || m.status === 'review' ? S.timeOnly(m.starts_at) : m.result ? m.result.home_score + ':' + m.result.away_score : '';
    var where = [mixed && m.league !== 'extraliga' ? 'КХЛ' : null, m.city || m.arena].filter(Boolean).join(' · ');
    var kids = [
      h('button', { type: 'button', class: 'kk-dh', 'aria-label': 'Открыть матч ' + nm(m.home) + ' — ' + nm(m.away), onclick: function () { openMatch(m); } }, [
        h('b', { class: 'kk-dh__t', text: time }),
        h('span', { class: 'kk-dh__w', text: where }),
      ]),
      h('div', { class: 'kk-two kk-two--day' }, [dayTeam(m, 'home', eff, colors), dayTeam(m, 'away', eff, colors)]),
    ];
    var moved = M.movedLine(m);
    if (moved) kids.push(h('span', { class: 'kk-moved', text: moved }));
    if (m.open && eff.side) {
      if (!state.scoreOpen[m.id] && !eff.score) {
        kids.push(h('button', { type: 'button', class: 'kk-dofr', onclick: function () { state.scoreOpen[m.id] = true; K.render(); } }, [
          h('span', { text: 'Угадать точный счёт' }),
          h('span', { class: 'kk-dofr__m', text: '«в точку»' }),
        ]));
      } else {
        kids.push(h('div', { class: 'kk-dsc' }, [h('span', { class: 'kk-dsc__l', text: 'Счёт' }), scoreRow(m, eff, 'sm')]));
        if (eff.tie) kids.push(h('span', { class: 'kk-sub', text: S.TIE_LINE }));
      }
    }
    return h('div', { class: 'kk-dr' }, kids);
  }

  function daySection() {
    if (!state.hubReady) return h('div', { class: 'kk-skel kk-skel--card' });
    var hero = current();
    var d = S.dayMatches(state.matches, new Date(), hero ? hero.match.id : null);
    if (!d && !hero && !state.matches.length && state.matchesFailed) return K.retryCard('Матчи не загрузились.', function () { K.reset('hub', {}); });
    if (!d) return hero ? null : K.emptyCard('МАТЧИ ДНЯ', 'Ближайших матчей пока нет — календарь обновится, как только клубы их назначат.');
    return h('div', { class: 'kk-sec' }, [
      h('div', { class: 'kk-sec__head' }, [
        h('h2', { class: 'kk-lbl kk-lbl--h', text: d.heading }),
        h('span', { class: 'kk-cnt' + (d.total && d.made === d.total ? ' is-done' : ''), text: S.dayCount(d.made, d.total) }),
      ]),
      h('div', { class: 'kk-day' }, d.items.map(function (m) { return dayRow(m, d.mixed); })),
      h('span', { class: 'kk-sub', text: 'Ход можно изменить до минуты перед стартом матча.' }),
    ]);
  }

  // ---------- очки: ссылка и шторка ----------

  var POINTS_LINK_ID = 'kk-points-link';

  function pointsLink() {
    return h('button', {
      type: 'button', class: 'kk-ptsl', id: POINTS_LINK_ID, 'aria-haspopup': 'dialog',
      onclick: function () { state.sheet = { kind: 'points', returnId: POINTS_LINK_ID }; K.render(); },
    }, [
      h('span', { class: 'kk-ptsl__t' }, [h('span', { class: 'kk-ptsl__q', 'aria-hidden': 'true', text: '?' }), 'Как считаются очки?']),
      icon(I.chev, 18),
    ]);
  }

  function pointsSheet() {
    var r = S.pointsRules();
    return K.sheet('Как считаются очки', null, [
      h('div', { class: 'kk-rl' }, r.rows.map(function (x) {
        return h('div', { class: 'kk-rl__r' }, [h('span', { class: 'kk-rl__v' + (x.gold ? ' is-gold' : ''), text: x.value }), h('span', { class: 'kk-rl__t', text: x.text })]);
      })),
      h('div', { class: 'kk-rl__trump' }, [h('b', { text: r.trumpTitle }), h('span', { text: r.trumpText })]),
      h('span', { class: 'kk-sub', text: r.foot }),
    ], 'kk-sheet--pts');
  }

  K.hubCards = { hero: heroCard, day: daySection, pointsLink: pointsLink, pointsSheet: pointsSheet };
})();
