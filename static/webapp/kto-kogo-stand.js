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

  function model() {
    return S.standModel((state.profile && state.profile.crowns) || [], state.clubs || []);
  }

  /** Наклейка: корона и число, чуть повёрнута — «приклеена» к логотипу. */
  function sticker(n, small) {
    return h('span', { class: 'kk-stk' + (small ? ' kk-stk--s' : ''), role: 'img', 'aria-label': S.crownCount(n) }, [K.crownIcon(small ? 11 : 14), String(n)]);
  }

  /** Логотип клуба с наклейкой; у клуба без корон логотип бледный и без наклейки. */
  function clubDisc(entry, size, small) {
    var wrap = h('span', { class: 'kk-stkw' + (entry.count ? '' : ' is-dim') }, [K.logoDisc(entry.club, size)]);
    if (entry.count) wrap.appendChild(sticker(entry.count, small));
    return wrap;
  }

  /** Строка «Мой стенд» для вкладки «Я», профиля и таблицы: шесть логотипов и вход на полный стенд. */
  function strip(label) {
    var m = model();
    var mini = S.standMini(m, MINI_LOGOS);
    var body = m.total
      ? h('span', { class: 'kk-strip__logos' }, mini.shown.map(function (e) { return clubDisc(e, 40, true); }).concat(mini.more ? [h('span', { class: 'kk-sub', text: '+' + mini.more })] : []))
      : h('span', { class: 'kk-sub', text: 'Корона — за первое место месяца в клубе. Загляни на стенд, там видно все клубы' });
    return h('button', { type: 'button', class: 'kk-strip', onclick: function () { K.go('stand', {}); } }, [
      h('span', { class: 'kk-strip__top' }, [
        h('span', { class: 'kk-strip__t', text: label || 'Мой стенд' }),
        h('span', { class: 'kk-strip__n' }, [S.standCountLabel(m.total), icon(I.chev, 14)]),
      ]),
      body,
    ]);
  }

  function plaque(title, n, sub) {
    return h('span', { class: 'kk-plq' + (n ? '' : ' is-dim') }, [
      K.crownIcon(40),
      h('span', { class: 'kk-plq__t', text: title }),
      h('span', { class: 'kk-sub', text: n ? '' : sub }),
      n ? sticker(n, false) : null,
    ]);
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
        h('div', { class: 'kk-shelf' }, m.clubs.map(function (e) {
          return h('button', { type: 'button', class: 'kk-tile', onclick: function () { K.go('club', { club: e.club.name }); } }, [
            clubDisc(e, 64, false),
            h('span', { class: 'kk-tile__n', text: S.clubName(e.club.name) }),
            ledge(),
          ]);
        })),
      ]));
      main.appendChild(h('span', { class: 'kk-sub', text: 'Цифра на наклейке: сколько раз ты был первым в этом клубе. Бледные клубы ждут твоей короны. Тап по клубу откроет его карточку.' }));
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
          ? h('div', { class: 'kk-chips' }, months.map(function (t) { return h('span', { class: 'kk-crch' }, [K.crownIcon(14), t]); }))
          : h('span', { class: 'kk-sub', text: 'Корона — за первое место месяца: очки хотя бы у троих и не меньше трёх ходов у тебя в этом клубе.' }),
      ]));
      main.appendChild(h('div', { class: 'kk-two' }, [
        h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { K.go('table', { club: entry.club.name, period: 'season' }); }, text: 'Таблица клуба' }),
        h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.go('matches', {}); }, text: 'Матчи' }),
      ]));
      return [main];
    },
  });

  K.standStrip = strip;
  K.stand = { model: model, sticker: sticker, clubDisc: clubDisc };
})();
