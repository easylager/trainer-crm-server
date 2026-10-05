/**
 * Каталог → «Написать тренеру»: короткая подсказка про Glide (без автотекста в чате).
 * Сервер: src/shared/catalog_contact_attribution.py
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

  var HINT = 'Если не сложно, упомяните, пожалуйста, что вы из Glide.';

  return {
    hintText: function () {
      return HINT;
    },
  };
});
