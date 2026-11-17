/**
 * TASK-428 (слой A): предложение подписки на каток после содержательного просмотра.
 *
 * «Сообщить, когда на этом катке появятся новые сеансы?» — один раз на человека и каток:
 *   - localStorage (glide_watch_offer_v1_<arena>) — в этом браузере больше не показываем;
 *   - сервер (событие watch_offer_shown по actor_hash) — GET …/watch-offer говорит show=false, если уже показывали
 *     или человек подписан. Ошибка сети или ответа — не показываем (закрыто по умолчанию).
 * «Содержательный просмотр» — карточка открыта и видна не меньше DWELL_MS.
 *
 * Mini App: arena-card.js зовёт start() с подпиской напрямую (POST /client/ice-watches, origin=offer).
 * Сайт: скрипт с data-атрибутами сам монтируется на /p/…; кнопка ведёт в бота (/start watch_<id>_o).
 *
 * Browser: window.GlideWatchOffer. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.GlideWatchOffer = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  var KEY_PREFIX = 'glide_watch_offer_v1_';
  var DWELL_MS = 12000;
  var DONE_HIDE_MS = 3500;
  var HIDDEN_LIMIT_MS = 10 * 60 * 1000;
  var FALLBACK = {
    'watch_offer.title': 'Сообщить, когда на этом катке появятся новые сеансы?',
    'watch_offer.note': 'Напишем в\u00a0Telegram, если добавят сеанс или снимут объявленный.',
    'watch_offer.cta': 'Сообщать о сеансах',
    'watch_offer.cta_site': 'Сообщать в Telegram',
    'watch_offer.close': 'Закрыть',
    'watch_offer.done': 'Готово. Напишем, когда появятся новые сеансы.',
  };

  function copy(key) {
    var C = root && root.GlideCopy;
    var v = C && typeof C.t === 'function' ? C.t(key) : null;
    return v && v !== key ? v : FALLBACK[key];
  }

  function validArena(id) {
    var n = Number(id);
    return n > 0 && n < 2147483648 && Math.floor(n) === n;
  }

  function storageKey(arenaId) {
    return KEY_PREFIX + String(Number(arenaId));
  }

  function isSeen(storage, arenaId) {
    try {
      return !!(storage && storage.getItem(storageKey(arenaId)));
    } catch (e) {
      return false;
    }
  }

  function markSeen(storage, arenaId) {
    try {
      if (storage) storage.setItem(storageKey(arenaId), '1');
    } catch (e) {
      /* приватный режим: защита остаётся на сервере */
    }
  }

  /** Кандидат ли до запроса к серверу: есть каток с катанием, не подписан, в этом браузере не показывали. */
  function isCandidate(o) {
    return !!(o && validArena(o.arenaId) && o.hasSkating && !o.subscribed && !o.seenLocal);
  }

  /** Показать ли прямо сейчас: кандидат, сервер явно разрешил, просмотр был содержательным. */
  function shouldShow(o) {
    return isCandidate(o) && o.serverShow === true && Number(o.dwellMs) >= DWELL_MS;
  }

  /**
   * Сценарий без DOM. deps:
   *   arenaId, hasSkating, subscribed() -> bool, storage,
   *   fetchState() -> Promise<{show}>, record(action), render({onCta, onClose}) -> {done(), remove()},
   *   subscribe() -> Promise<bool> (Mini App) или null (сайт: кнопка — ссылка, уход со страницы),
   *   wait(ms) -> Promise, visible() -> bool.
   * Возвращает Promise<'skip'|'server_no'|'shown'>.
   */
  function start(deps) {
    var base = {
      arenaId: deps.arenaId,
      hasSkating: deps.hasSkating,
      subscribed: !!deps.subscribed(),
      seenLocal: isSeen(deps.storage, deps.arenaId),
    };
    if (!isCandidate(base)) return Promise.resolve('skip');
    return Promise.resolve()
      .then(deps.fetchState)
      .then(
        function (state) {
          return !!(state && state.show === true);
        },
        function () {
          return false;
        }
      )
      .then(function (serverShow) {
        if (!serverShow) {
          markSeen(deps.storage, deps.arenaId);
          return 'server_no';
        }
        return waitVisible(deps).then(function (dwell) {
          var now = {
            arenaId: deps.arenaId,
            hasSkating: deps.hasSkating,
            subscribed: !!deps.subscribed(),
            seenLocal: isSeen(deps.storage, deps.arenaId),
            serverShow: true,
            dwellMs: dwell,
          };
          if (!shouldShow(now)) return 'skip';
          markSeen(deps.storage, deps.arenaId);
          deps.record('shown');
          var view = deps.render({
            onCta: function () {
              deps.record('click');
              if (!deps.subscribe) return;
              deps.subscribe().then(function (ok) {
                if (ok) {
                  view.done();
                  deps.wait(DONE_HIDE_MS).then(view.remove);
                } else {
                  view.remove();
                }
              });
            },
            onClose: function () {
              deps.record('closed');
              view.remove();
            },
          });
          return 'shown';
        });
      });
  }

  /** Ждём DWELL_MS; если страница в этот момент скрыта — ждём её показа шагами по секунде, не дольше
      HIDDEN_LIMIT_MS (дальше человек ушёл: dwell 0, не показываем). */
  function waitVisible(deps) {
    var waited = 0;
    function step() {
      if (deps.visible()) return DWELL_MS;
      if (waited >= HIDDEN_LIMIT_MS) return 0;
      waited += 1000;
      return deps.wait(1000).then(step);
    }
    return deps.wait(DWELL_MS).then(step);
  }

  // ---------- DOM ----------

  function el(doc, tag, cls, text) {
    var node = doc.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  /** Спокойная плашка снизу экрана: заголовок, пояснение, одно действие и «Закрыть». Не модальная. */
  function renderPanel(doc, opts) {
    // Сайт: свой отступ над плавающими «Открыть в Telegram» и «Приложение» (style-b.css, z-index 9).
    var box = el(doc, 'aside', opts.href ? 'watch-offer watch-offer--site' : 'watch-offer');
    box.setAttribute('role', 'region');
    box.setAttribute('aria-label', copy('watch_offer.title'));
    // Плашка появляется сама, без действия человека: читалка экрана объявит её, не перебивая.
    box.setAttribute('aria-live', 'polite');
    var title = el(doc, 'p', 'watch-offer__title', copy('watch_offer.title'));
    var note = el(doc, 'p', 'watch-offer__note', copy('watch_offer.note'));
    var row = el(doc, 'div', 'watch-offer__row');
    var cta;
    if (opts.href) {
      cta = el(doc, 'a', 'watch-offer__cta', copy('watch_offer.cta_site'));
      cta.href = opts.href;
      cta.rel = 'noopener';
    } else {
      cta = el(doc, 'button', 'watch-offer__cta', copy('watch_offer.cta'));
      cta.type = 'button';
    }
    var close = el(doc, 'button', 'watch-offer__close', copy('watch_offer.close'));
    close.type = 'button';
    row.appendChild(cta);
    row.appendChild(close);
    box.appendChild(title);
    box.appendChild(note);
    box.appendChild(row);
    doc.body.appendChild(box);
    cta.addEventListener('click', function () {
      if (!opts.href) cta.disabled = true;
      opts.onCta();
    });
    close.addEventListener('click', opts.onClose);
    return {
      done: function () {
        title.textContent = copy('watch_offer.done');
        if (note.parentNode) note.parentNode.removeChild(note);
        if (row.parentNode) row.parentNode.removeChild(row);
      },
      remove: function () {
        if (box.parentNode) box.parentNode.removeChild(box);
      },
    };
  }

  function realDeps(doc) {
    return {
      storage: (function () {
        try {
          return root.localStorage;
        } catch (e) {
          return null;
        }
      })(),
      wait: function (ms) {
        return new Promise(function (resolve) {
          root.setTimeout(resolve, ms);
        });
      },
      visible: function () {
        return !doc.visibilityState || doc.visibilityState === 'visible';
      },
    };
  }

  function json(r) {
    return r && r.ok ? r.json() : null;
  }

  /** Сайт: <script src="watch-offer.js" data-arena-id data-href data-skating="1">. Подписку оформит бот. */
  function mountSite(script) {
    var doc = root.document;
    var arenaId = Number(script.getAttribute('data-arena-id'));
    var href = script.getAttribute('data-href') || '';
    if (!href || !root.fetch) return Promise.resolve('skip');
    var api = '/api/public/catalog/watch-offer?arena_id=' + encodeURIComponent(String(arenaId));
    var d = realDeps(doc);
    d.arenaId = arenaId;
    d.hasSkating = script.getAttribute('data-skating') === '1';
    d.subscribed = function () {
      return false;
    };
    d.fetchState = function () {
      return root.fetch(api, { cache: 'no-store', credentials: 'same-origin' }).then(json);
    };
    d.record = function (action) {
      var url = api + '&action=' + encodeURIComponent(action);
      if (root.navigator && typeof root.navigator.sendBeacon === 'function') root.navigator.sendBeacon(url);
      else root.fetch(url, { method: 'POST', keepalive: true }).catch(function () {});
    };
    d.render = function (handlers) {
      return renderPanel(doc, { href: href, onCta: handlers.onCta, onClose: handlers.onClose });
    };
    d.subscribe = null;
    return start(d);
  }

  /**
   * Mini App: opts = {arenaId, hasSkating, subscribed(), initData, subscribe() -> Promise<bool>}.
   * Подписку (с разрешением писать) делает arena-card.js — тот же путь, что у колокольчика.
   */
  function mountMiniApp(opts) {
    var doc = root.document;
    if (!opts || !opts.initData || !root.fetch) return Promise.resolve('skip');
    var headers = { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': opts.initData };
    var d = realDeps(doc);
    d.arenaId = Number(opts.arenaId);
    d.hasSkating = !!opts.hasSkating;
    d.subscribed = opts.subscribed;
    d.fetchState = function () {
      var url = '/api/webapp/client/watch-offer?arena_id=' + encodeURIComponent(String(d.arenaId));
      return root.fetch(url, { headers: headers, cache: 'no-store' }).then(json);
    };
    d.record = function (action) {
      root
        .fetch('/api/webapp/client/watch-offer', {
          method: 'POST',
          headers: headers,
          body: JSON.stringify({ arena_id: d.arenaId, action: action }),
        })
        .catch(function () {});
    };
    d.render = function (handlers) {
      return renderPanel(doc, { href: null, onCta: handlers.onCta, onClose: handlers.onClose });
    };
    d.subscribe = opts.subscribe;
    return start(d);
  }

  var script = root && root.document && root.document.currentScript;
  if (script && script.getAttribute('data-surface') === 'site') {
    var go = function () {
      mountSite(script);
    };
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', go);
    else go();
  }

  return {
    DWELL_MS: DWELL_MS,
    FALLBACK: FALLBACK,
    KEY_PREFIX: KEY_PREFIX,
    isCandidate: isCandidate,
    isSeen: isSeen,
    markSeen: markSeen,
    mountMiniApp: mountMiniApp,
    mountSite: mountSite,
    renderPanel: renderPanel,
    shouldShow: shouldShow,
    start: start,
    storageKey: storageKey,
  };
});
