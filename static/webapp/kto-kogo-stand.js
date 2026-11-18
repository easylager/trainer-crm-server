/**
 * «Кто кого» — стенд наград (TASK-430): полка клубов с наклейками-коронами, карточка клуба и строка «Мой стенд».
 * Данные — ``profile.crowns`` и каталог клубов; считает ``S.standModel``. Цифра на наклейке — сколько раз игрок был
 * первым в клубе. Общая таблица и лиги стоят отдельной полкой над клубами.
 */
(function () {
  'use strict';

  var K = window.KK;
  var h = K.h;
  var S = K.S;
  var I = K.I;
  var state = K.state;
  var icon = K.icon;
  var NBSP = ' ';
  var MINI_LOGOS = 6;
  // «Сравнить с моим стендом» собрано, но в релиз пока не идёт (решение владельца 2026-11-18): включить = true.
  var COMPARE_ENABLED = false;

  function model() {
    return S.standModel((state.profile && state.profile.crowns) || [], state.clubs || []);
  }

  /** Наклейка: корона и число, чуть повёрнута — «приклеена» к логотипу. */
  function sticker(n, small) {
    return h('span', { class: 'kk-crst' + (small ? ' kk-crst--s' : ''), role: 'img', 'aria-label': S.crownCount(n) }, [K.crownIcon(small ? 11 : 14), String(n)]);
  }

  /** Логотип клуба с наклейкой; у клуба без корон логотип бледный и без наклейки. */
  function clubDisc(entry, size, small) {
    var wrap = h('span', { class: 'kk-crstw' + (entry.count ? '' : ' is-dim') }, [K.logoDisc(entry.club, size)]);
    if (entry.count) wrap.appendChild(sticker(entry.count, small));
    return wrap;
  }

  /** Строка «Мой стенд» для вкладки «Я», профиля и таблицы: шесть логотипов и вход на полный стенд. */
  function strip(label) {
    var m = model();
    var mini = S.standMini(m, MINI_LOGOS);
    // Без корон строка не пустая: бледные логотипы клубов и подсказка, как получить первую корону.
    var empty = m.clubs.slice(0, MINI_LOGOS - 1);
    var body = m.total
      ? h('span', { class: 'kk-strip__logos' }, mini.shown.map(function (e) { return clubDisc(e, 40, true); }).concat(mini.more ? [h('span', { class: 'kk-sub', text: '+' + mini.more })] : []))
      : h('span', { class: 'kk-col' }, [
          h('span', { class: 'kk-strip__logos' }, empty.map(function (e) { return clubDisc(e, 40, true); })),
          h('span', { class: 'kk-sub', text: 'Первая корона — за 1-е место месяца в клубе: очки хотя бы у троих игроков и не меньше трёх ходов у тебя.' }),
        ]);
    return h('button', { type: 'button', class: 'kk-strip', onclick: function () { K.go('stand', {}); } }, [
      h('span', { class: 'kk-strip__top' }, [
        h('span', { class: 'kk-strip__t', text: label || 'Мой стенд' }),
        h('span', { class: 'kk-strip__n' }, [S.standCountLabel(m.total), icon(I.chev, 14)]),
      ]),
      body,
    ]);
  }

  function shortName(n) {
    return n && n.length > 12 ? n.slice(0, 11) + '…' : n || '';
  }

  /** «Андрей 2 · ты 4»: у кого корон больше, того число жирное. Без сравнения — ничего. */
  function cmpLine(cmp, theirs) {
    if (!cmp || (!theirs && !cmp.mine)) return null;
    return h('span', { class: 'kk-cmpl' }, [
      h('span', { class: theirs > cmp.mine ? 'is-lead' : '', text: shortName(cmp.who) + ' ' + theirs }),
      ' · ',
      h('span', { class: cmp.mine > theirs ? 'is-lead' : '', text: 'ты ' + cmp.mine }),
    ]);
  }

  function plaque(title, n, sub, cmp) {
    return h('span', { class: 'kk-plq' + (n ? '' : ' is-dim') }, [
      K.crownIcon(40),
      h('span', { class: 'kk-plq__t', text: title }),
      n || cmp ? null : h('span', { class: 'kk-sub', text: sub }),
      cmpLine(cmp, n),
      n ? sticker(n, false) : null,
    ]);
  }

  /** Полка клубов. ``onTile`` — тап по клубу (у чужого стенда его нет); ``mine`` и ``who`` — сравнение с моим стендом. */
  function shelf(m, onTile, mine, who) {
    return h('div', { class: 'kk-shelf' }, m.clubs.map(function (e, i) {
      var inner = [
        clubDisc(e, 64, false),
        h('span', { class: 'kk-tile__n', text: S.clubName(e.club.name) }),
        mine ? cmpLine({ who: who, mine: mine.clubs[i].count }, e.count) : null,
        ledge(),
      ];
      return onTile
        ? h('button', { type: 'button', class: 'kk-tile', onclick: function () { onTile(e); } }, inner)
        : h('div', { class: 'kk-tile' }, inner);
    }));
  }

  function ledge() {
    return h('span', { class: 'kk-ledge', 'aria-hidden': 'true' });
  }

  // ---------- Полный стенд ----------

  K.register('stand', {
    enter: function () {
      Promise.all([K.loadProfile(), K.loadClubs().catch(function () {})]).then(K.render, function (e) { K.render(); K.fail(e); });
    },
    render: function () {
      if (!state.profile) return [h('main', { class: 'kk-main' }, [K.topbar('Мой стенд', null), K.loading()])];
      var m = model();
      var main = h('main', { class: 'kk-main' }, [K.topbar('Мой стенд', S.standCountLabel(m.total))]);
      main.appendChild(h('div', { class: 'kk-plqs' }, [
        plaque('Общая таблица', m.overall, 'ещё без короны'),
        plaque('Лиги', m.leagues, 'ещё без короны'),
      ]));
      main.appendChild(ledge());
      main.appendChild(h('div', { class: 'kk-sec' }, [
        h('span', { class: 'kk-lbl', text: 'КЛУБЫ' }),
        shelf(m, function (e) { K.go('club', { club: e.club.name }); }),
      ]));
      main.appendChild(h('span', { class: 'kk-sub', text: 'Цифра на наклейке: сколько раз ты был первым в этом клубе. Бледные клубы ждут твоей короны. Тап по клубу откроет его карточку.' }));
      return [main];
    },
  });

  // ---------- Стенд другого игрока ----------

  K.register('player', {
    enter: function (a) {
      a.failed = false;
      var load = K.api('GET', '/client/hockey/players/' + encodeURIComponent(a.pid) + '/stand').then(function (d) { a.data = d; });
      Promise.all([load, K.loadProfile(), K.loadClubs().catch(function () {})]).then(K.render, function (e) { a.failed = true; K.render(); K.fail(e); });
    },
    render: function (a) {
      if (!a.data) {
        return [h('main', { class: 'kk-main' }, [K.topbar('Стенд', null), a.failed ? K.emptyCard('Стенд', 'Игрок не найден или стенд сейчас не открывается.') : K.loading()])];
      }
      var m = S.standModel(a.data.crowns, state.clubs || []);
      var mine = COMPARE_ENABLED && a.compare && state.profile ? model() : null;
      var who = a.data.display_name || 'Игрок';
      var main = h('main', { class: 'kk-main' }, [K.topbar(a.data.display_name || 'Игрок', S.standCountLabel(m.total))]);
      if (COMPARE_ENABLED && !a.data.is_me) {
        main.appendChild(h('button', { type: 'button', class: 'kk-btn kk-btn--alt', 'aria-pressed': a.compare ? 'true' : 'false', onclick: function () { a.compare = !a.compare; K.render(); }, text: a.compare ? 'Скрыть сравнение' : 'Сравнить с моим стендом' }));
      }
      if (mine) {
        var vs = S.standCompare(m, mine);
        main.appendChild(h('section', { class: 'kk-card kk-cmp' }, [
          h('span', { class: 'kk-lbl', text: 'КТО КОГО ЧАЩЕ ПЕРВЫЙ' }),
          h('span', { class: 'kk-cmp__row' }, [
            h('span', { class: 'kk-col' }, [h('b', { text: shortName(who) }), h('span', { class: 'kk-sub', text: S.standCountLabel(m.total) })]),
            h('span', { class: 'kk-cmp__vs', text: 'против' }),
            h('span', { class: 'kk-col' }, [h('b', { text: 'Ты' }), h('span', { class: 'kk-sub', text: S.standCountLabel(mine.total) })]),
          ]),
          h('span', { class: 'kk-sub', text: 'По клубам. Больше у тебя: ' + vs.mine + ' · больше у него: ' + vs.theirs + ' · поровну: ' + vs.same + '. Под каждым клубом сначала его короны, потом твои.' }),
        ]));
      }
      main.appendChild(h('div', { class: 'kk-plqs' }, [
        plaque('Общая таблица', m.overall, 'ещё без короны', mine ? { who: who, mine: mine.overall } : null),
        plaque('Лиги', m.leagues, 'ещё без короны', mine ? { who: who, mine: mine.leagues } : null),
      ]));
      main.appendChild(ledge());
      main.appendChild(h('div', { class: 'kk-sec' }, [h('span', { class: 'kk-lbl', text: 'КЛУБЫ' }), shelf(m, null, mine, who)]));
      main.appendChild(h('span', { class: 'kk-sub', text: 'Видны только награды: прогнозы игрока остаются у него.' }));
      return [main];
    },
  });

  // ---------- Карточка клуба ----------

  K.register('club', {
    enter: function () {
      Promise.all([K.loadProfile(), K.loadClubs().catch(function () {})]).then(K.render, function (e) { K.render(); K.fail(e); });
    },
    render: function (a) {
      if (!state.profile) return [h('main', { class: 'kk-main' }, [K.topbar('Клуб', null), K.loading()])];
      var entry = model().clubs.filter(function (c) { return c.club.name === a.club; })[0];
      if (!entry) return [h('main', { class: 'kk-main' }, [K.topbar('Клуб', null), K.emptyCard('Клуб', 'Такого клуба на стенде нет.')])];
      var months = S.clubCrownMonths(entry);
      var main = h('main', { class: 'kk-main' }, [K.topbar(S.clubName(entry.club.name), S.standCountLabel(entry.count))]);
      main.appendChild(h('div', { class: 'kk-clubhead' }, [clubDisc(entry, 96, false)]));
      main.appendChild(h('div', { class: 'kk-sec' }, [
        h('span', { class: 'kk-lbl', text: 'ТВОИ КОРОНЫ В КЛУБЕ' }),
        months.length
          ? h('div', { class: 'kk-crchs' }, months.map(function (t) { return h('span', { class: 'kk-crch' }, [K.crownIcon(14), t]); }))
          : h('span', { class: 'kk-sub', text: 'Корона — за первое место месяца: очки хотя бы у троих и не меньше трёх ходов у тебя в этом клубе.' }),
      ]));
      main.appendChild(h('div', { class: 'kk-two' }, [
        h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { K.go('table', { club: entry.club.name, period: 'season' }); }, text: 'Таблица клуба' }),
        h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.go('matches', {}); }, text: 'Матчи' }),
      ]));
      return [main];
    },
  });

  /** Момент «корона получена»: золотая плашка с короной «прилипает» с отскоком, по ней проходит блик, вокруг свечение. */
  function moment() {
    return h('span', { class: 'kk-mom' }, [
      h('span', { class: 'kk-mom__halo', 'aria-hidden': 'true' }),
      h('span', { class: 'kk-mom__stk' }, [K.crownIcon(48, 'Корона'), h('span', { class: 'kk-mom__shine', 'aria-hidden': 'true' })]),
    ]);
  }

  K.standStrip = strip;
  K.stand = { model: model, sticker: sticker, clubDisc: clubDisc, moment: moment };
})();
