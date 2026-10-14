/**
 * Восстановление скролла списка после возврата с карточки места.
 *
 * Запасной скролл списка, если bfcache недоступен (старый браузер, блокировка).
 * При pageshow.persisted позицию не трогаем — страница уже восстановлена из памяти. Ключ —
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

  function wirePublicListScrollRestore(storage, root) {
    var g = root || (typeof globalThis !== 'undefined' ? globalThis : null);
    if (!storage || !g || typeof g.addEventListener !== 'function' || !g.location) return;
    var pathname = g.location.pathname;
    var search = g.location.search;

    function saveScroll() {
      var y = (g.scrollY != null ? g.scrollY : g.pageYOffset) || 0;
      save(storage, pathname, search, y);
    }

    function restoreScroll() {
      var y = consume(storage, pathname, search);
      if (!y) return;
      var go = function () {
        g.scrollTo(0, y);
      };
      go();
      if (typeof g.requestAnimationFrame === 'function') {
        g.requestAnimationFrame(function () {
          g.requestAnimationFrame(go);
        });
      } else {
        setTimeout(go, 0);
      }
    }

    g.addEventListener('pagehide', saveScroll);
    if (g.document && typeof g.document.addEventListener === 'function') {
      g.document.addEventListener('visibilitychange', function () {
        if (g.document.visibilityState === 'hidden') saveScroll();
      });
    }
    g.addEventListener('pageshow', function (ev) {
      if (ev.persisted) return;
      restoreScroll();
    });
  }

  return {
    KEY_PREFIX: KEY_PREFIX,
    storageKey: storageKey,
    save: save,
    consume: consume,
    wirePublicListScrollRestore: wirePublicListScrollRestore,
  };
});
