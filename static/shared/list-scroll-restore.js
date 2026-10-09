/**
 * Восстановление скролла списка после возврата с карточки места.
 *
 * Публичные /c/ и /ice/…/today отдают Cache-Control: no-store (учёт просмотров),
 * поэтому bfcache и штатный history.scrollRestoration не работают. Ключ —
 * pathname+search текущей страницы: скролл списка не попадёт на /p/.
 *
 * Используется из тестов; в шаблонах share — тот же алгоритм инлайном
 * (страницы намеренно без лишнего asset round-trip).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.GlideListScrollRestore = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var KEY_PREFIX = 'glidePublicListScroll:';

  function storageKey(pathname, search) {
    return KEY_PREFIX + String(pathname || '') + String(search || '');
  }

  function save(storage, pathname, search, scrollY) {
    if (!storage || typeof storage.setItem !== 'function') return false;
    var y = Number(scrollY);
    if (!(y > 0) || !isFinite(y)) return false;
    try {
      storage.setItem(storageKey(pathname, search), String(Math.round(y)));
      return true;
    } catch (e) {
      return false;
    }
  }

  function consume(storage, pathname, search) {
    if (!storage || typeof storage.getItem !== 'function') return 0;
    try {
      var key = storageKey(pathname, search);
      var raw = storage.getItem(key);
      if (!raw) return 0;
      storage.removeItem(key);
      var y = parseInt(raw, 10);
      return y > 0 && isFinite(y) ? y : 0;
    } catch (e) {
      return 0;
    }
  }

  return {
    KEY_PREFIX: KEY_PREFIX,
    storageKey: storageKey,
    save: save,
    consume: consume,
  };
});
