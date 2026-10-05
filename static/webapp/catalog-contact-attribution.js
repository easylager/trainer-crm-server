/**
 * Каталог → «Написать тренеру»: подсказка и текст для автоподстановки в Telegram.
 * Сервер: src/shared/catalog_contact_attribution.py (редирект /r/tg/).
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.CatalogContactAttribution = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var PREFILL =
    'Здравствуйте! Пишу из каталога Glide. ' +
    'Хочу заниматься — подскажите, как удобнее записаться?';

  var HINT =
    'Откроется чат в Telegram — в поле сообщения подставим короткий текст про Glide, ' +
    'его можно отредактировать перед отправкой.';

  return {
    prefillText: function () {
      return PREFILL;
    },
    hintText: function () {
      return HINT;
    },
  };
});
