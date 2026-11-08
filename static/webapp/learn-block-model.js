/**
 * Блок «Учиться с тренером» в точках входа Mini App (TASK-354, PDEC-033) — чистая логика без DOM.
 *
 * Тот же по смыслу блок, что на сайте (`site_learn_block.py`). Цифры не считаем заново: число
 * тренеров, «от» и ближайшее время берутся из выдачи `/api/public/trainer-showcase` через
 * TrainerShowcaseModel — те же вкладки и то же правило показа, что на витрине.
 *
 * Места (place): city — главная и пустые «Мои записи»; skate — Поиск → массовое катание;
 * hockey — Поиск → ОХМ; arena — карточка катка. Нет тренеров, которым есть что показать, — null.
 * Браузер: window.LearnBlockModel. Node-тесты: module.exports.
 */
(function (root, factory) {
  'use strict';
  var showcase = typeof module === 'object' && module.exports ? require('./trainer-showcase-model.js') : root && root.TrainerShowcaseModel;
  var api = factory(showcase);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.LearnBlockModel = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (M) {
  'use strict';

  var TITLE = 'Учиться с тренером';
  var BUTTON = 'Выбрать тренера';
  var FACES_SHOWN = 4;
  var PLACES = ['city', 'skate', 'hockey', 'arena'];

  function count(n) {
    return M.word(n, 'тренер', 'тренера', 'тренеров');
  }

  function isOne(n) {
    return n % 10 === 1 && n % 100 !== 11;
  }

  function priceText(list, key) {
    var p = M.minPriceOf(list, key);
    return p ? M.formatMoney(p.cents, p.currency) : '';
  }

  /** «сегодня, 17:15» — самое раннее окно среди показанных тренеров с онлайн-записью (как время на карточке витрины). */
  function nearest(list, arenaId) {
    var best = null;
    (list || []).forEach(function (t) {
      if (!t.can_book) return;
      (t.windows || []).forEach(function (w) {
        if (arenaId != null && Number(w.arena_id) !== Number(arenaId)) return;
        if (!w.time || !w.day || !w.starts_at) return;
        if (!best || String(w.starts_at) < String(best.starts_at)) best = w;
      });
    });
    return best ? best.day + ', ' + best.time : '';
  }

  function faces(list) {
    return list.slice(0, FACES_SHOWN).map(function (t) {
      return { photo: t.photo_url || null, initial: (t.initial || String(t.name || 'Т').charAt(0) || 'Т').toUpperCase() };
    });
  }

  function href(q, cityId) {
    var parts = [];
    Object.keys(q).forEach(function (k) {
      if (q[k] != null && q[k] !== '') parts.push(k + '=' + encodeURIComponent(q[k]));
    });
    if (cityId) parts.push('city_id=' + encodeURIComponent(cityId));
    return 'trainers' + (parts.length ? '?' + parts.join('&') : '');
  }

  function block(list, line, to, chips) {
    return { title: TITLE, button: BUTTON, faces: faces(list), count: list.length, countText: count(list.length), line: line, href: to, chips: chips || [] };
  }

  /**
   * @param {Array} items  выдача `/api/public/trainer-showcase`
   * @param {string} place city | skate | hockey | arena
   * @param {{cityId?:number|null, arenaId?:number|null}} opts
   * @returns {object|null}  null — показывать нечего
   */
  function build(items, place, opts) {
    opts = opts || {};
    var cityId = opts.cityId || null;
    if (PLACES.indexOf(place) < 0) return null;
    var everyone = M.visibleTrainers(items, 'all', null);
    if (!everyone.length) return null;

    if (place === 'city') {
      var bits = [];
      var price = priceText(everyone, 'all');
      if (price) bits.push('От ' + price + ' за занятие.');
      var soon = nearest(everyone, null);
      if (soon) bits.push('Ближайшее свободное время — ' + soon + '.');
      var counts = M.tabCounts(items, null);
      var chips = M.DIRECTIONS.filter(function (d) { return d.key !== 'all' && counts[d.key] > 0; })
        .map(function (d) { return { label: d.title, href: href({ tab: d.key }, cityId) }; });
      // Одно направление повторяло бы кнопку — как на сайте и в самой витрине (вкладок при одном тренере/направлении нет).
      return block(everyone, bits.join(' '), href({}, cityId), chips.length > 1 ? chips : []);
    }

    if (place === 'skate') {
      var zero = M.visibleTrainers(items, 's-nulya', null);
      if (!zero.length) return null;
      var p1 = priceText(zero, 's-nulya');
      return block(zero, 'Учат с нуля — детей и взрослых. ' + count(zero.length) + (p1 ? ', от ' + p1 : '') + '.',
        href({ tab: 's-nulya' }, cityId));
    }

    if (place === 'hockey') {
      var stick = M.visibleTrainers(items, 's-klyushkoy', null);
      if (!stick.length) return null;
      var p2 = priceText(stick, 's-klyushkoy');
      return block(stick, 'Катание для хоккеистов: скорость, перекрёстный шаг, торможение. ' + count(stick.length) + (p2 ? ', от ' + p2 : '') + '.',
        href({ tab: 's-klyushkoy' }, cityId));
    }

    // Каток. Название в падеж не ставим (названия катков не склоняются) — экран и так про этот каток.
    var arenaId = opts.arenaId != null ? opts.arenaId : null;
    var here = arenaId != null ? M.visibleTrainers(items, 'all', arenaId) : [];
    if (here.length) {
      var line = 'На этом катке ' + (isOne(here.length) ? 'учит ' : 'учат ') + count(here.length) + '.';
      var t = nearest(here, arenaId);
      if (t) line += ' Ближайшее свободное время — ' + t + '.';
      return block(here, line, href({ arena_id: arenaId }, cityId));
    }
    var p3 = priceText(everyone, 'all');
    return block(everyone, 'На этом катке тренеров пока нет. В городе — ' + everyone.length + (p3 ? ', от ' + p3 + ' за занятие' : '') + '.',
      href({}, cityId));
  }

  return { TITLE: TITLE, BUTTON: BUTTON, FACES_SHOWN: FACES_SHOWN, build: build, nearest: nearest, count: count };
});
