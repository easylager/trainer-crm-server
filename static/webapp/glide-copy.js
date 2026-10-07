/**
 * TASK-209: словарь подписей каталога — JS-зеркало ``src/shared/copy_ru.json``.
 * Один источник для сайта (static/share/*) и Mini App (static/webapp/*): раньше
 * меню времени говорило «В выходные» в одном месте и «Выходные» в другом.
 * COPY ниже — валидный JSON, тест сверяет его с ``src/shared/copy_ru.json`` построчно.
 * Browser: window.GlideCopy. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GlideCopy = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var COPY = {
    "when.today": "Сегодня",
    "when.tomorrow": "Завтра",
    "when.weekend": "В выходные",
    "when.day": "День…",
    "when.evening": "Сегодня вечером",
    "basis.live": "с сайта катка",
    "basis.projected": "обычно",
    "basis.projected_long": "по обычной сетке катка — лучше уточнить",
    "basis.photo": "по фото афиши",
    "mode.phone": "Расписание — только по телефону",
    "mode.season_closed": "Сейчас закрыто",
    "mode.reopen": "Откроется {date}",
    "kind.public_skate": "Массовое катание",
    "kind.hockey_practice": "Хоккей для любителей (ОХМ)",
    "cta.follow": "Следить за катком в Telegram",
    "cta.follow_closed": "Сообщить об открытии",
    "cta.following": "Вы следите за катком",
    "cta.metoo": "Я тоже иду",
    "cta.call": "Позвонить",
    "cta.route": "Маршрут",
    "cta.share": "Поделиться",
    "cta.report": "Нашли ошибку? Напишите нам",
    "price.with_rental": "с прокатом {total} {currency}",
    "footer.made_by": "Сделано теми, кто сам катается."
  };

  function t(key, kw) {
    var template = COPY[key];
    if (template === undefined) return key;
    if (!kw) return template;
    return template.replace(/\{(\w+)\}/g, function (match, name) {
      return Object.prototype.hasOwnProperty.call(kw, name) ? String(kw[name]) : match;
    });
  }

  return { COPY: COPY, t: t };
});
