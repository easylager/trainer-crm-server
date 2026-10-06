/**
 * Каталог → «Написать тренеру»: мягкая просьба упомянуть Glide (TASK-202).
 * Только подпись под кнопкой — текст сообщения в Telegram не подставляется.
 *
 * Блок #trainerDetailActions пересобирается через innerHTML +=, поэтому подпись
 * ставится заново после каждой пересборки: ensureHint идемпотентна.
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

  var HINT = 'Если не сложно, упомяните, пожалуйста, что вы из Glide';
  var HINT_CLASS = 'trainer-contact-hint';

  /**
   * Ставит подпись сразу под кнопкой [data-action="contact-trainer"] внутри container.
   * Нет кнопки — подписи тоже нет (старая убирается). Текст только через textContent.
   */
  function ensureHint(container) {
    if (!container || typeof container.querySelector !== 'function') return null;
    var btn = container.querySelector('[data-action="contact-trainer"]');
    var hint = container.querySelector('.' + HINT_CLASS);
    if (!btn) {
      if (hint && hint.parentNode) hint.parentNode.removeChild(hint);
      return null;
    }
    if (!hint) {
      var doc = container.ownerDocument || (typeof document !== 'undefined' ? document : null);
      if (!doc) return null;
      hint = doc.createElement('p');
      hint.className = 'chips-hint ' + HINT_CLASS;
    }
    if (btn.nextSibling !== hint) btn.insertAdjacentElement('afterend', hint);
    hint.textContent = HINT;
    return hint;
  }

  return {
    HINT: HINT,
    hintText: function () {
      return HINT;
    },
    ensureHint: ensureHint,
  };
});
