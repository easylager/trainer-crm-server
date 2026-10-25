/**
 * Разрешение боту писать первым (Telegram.WebApp.requestWriteAccess, Bot API 6.9): общий код.
 *
 * Бот может написать клиенту, только если тот нажал /start или разрешил сообщения. Mini App,
 * открытая по прямой ссылке, этого не гарантирует, поэтому подписки и запись сначала смотрят
 * сюда. Успех = колбэк requestWriteAccess вернул ровно true; сам вызов метода успехом не считается.
 *
 * Сервер: POST /api/webapp/client/write-access/outcome (surface: booking | slot_wait | arena_watch)
 * пишет исход в platform_audit_events и отдаёт bot_link на чат бота.
 * Нативный диалог Telegram в headless-тестах не воспроизвести: там window.Telegram.WebApp — мок.
 */
(function (global, factory) {
  'use strict';
  var api = factory(global);
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (global) {
    global.GlideWriteAccess = api;
  }
})(typeof window !== 'undefined' ? window : typeof global !== 'undefined' ? global : this, function (root) {
  'use strict';

  var OUTCOME_PATH = '/api/webapp/client/write-access/outcome';
  var LINK_WAIT_MS = 2500;

  var COPY_ALLOW = 'Разрешить';
  var COPY_OPEN_BOT = 'Откройте бота и нажмите «Старт», чтобы получать уведомления.';
  var COPY_OPEN_BOT_BUTTON = 'Открыть бота';
  var COPY_SLOT_DENIED = 'Чтобы мы написали, разрешите сообщения от бота.';

  function getTg() {
    return root && root.Telegram && root.Telegram.WebApp ? root.Telegram.WebApp : null;
  }

  /** Только Telegram: подписанная initData и положительный id (у MAX/VK ключ отрицательный). */
  function isTelegramPrincipal(tg) {
    if (!tg || !tg.initData) return false;
    var user = tg.initDataUnsafe && tg.initDataUnsafe.user;
    if (user && user.id != null && Number(user.id) <= 0) return false;
    return true;
  }

  /** Метод есть и версия SDK его знает. */
  function canRequestWriteAccess(tg) {
    if (!tg || typeof tg.requestWriteAccess !== 'function') return false;
    if (typeof tg.isVersionAtLeast === 'function') {
      try {
        if (!tg.isVersionAtLeast('6.9')) return false;
      } catch (e) {
        return false;
      }
    }
    return true;
  }

  /** ``already`` / ``askable`` / ``unsupported`` — без проверки платформы. */
  function rawState(tg) {
    var user = tg && tg.initDataUnsafe && tg.initDataUnsafe.user;
    if (user && user.allows_write_to_pm === true) return 'already';
    return canRequestWriteAccess(tg) ? 'askable' : 'unsupported';
  }

  /** ``already`` | ``askable`` | ``unsupported`` | ``not_telegram``. */
  function writeAccessState(tg) {
    if (!isTelegramPrincipal(tg)) return 'not_telegram';
    return rawState(tg);
  }

  /** Показывает диалог; ``granted`` только если колбэк вернул ``true``. Промис не отклоняется. */
  function requestWriteAccess(tg) {
    return new Promise(function (resolve) {
      if (!canRequestWriteAccess(tg)) {
        resolve('unsupported');
        return;
      }
      try {
        tg.requestWriteAccess(function (granted) {
          resolve(granted === true ? 'granted' : 'denied');
        });
      } catch (e) {
        resolve('unsupported');
      }
    });
  }

  /** Открывает чат бота внутри Telegram; ``false`` — открыть нечем. */
  function openBotChat(tg, url) {
    if (!tg || !url || String(url).indexOf('https://t.me/') !== 0) return false;
    try {
      if (typeof tg.openTelegramLink === 'function') {
        tg.openTelegramLink(url);
        return true;
      }
      if (typeof tg.openLink === 'function') {
        tg.openLink(url);
        return true;
      }
    } catch (e) {
      /* SDK не смог открыть — страница не должна ломаться */
    }
    return false;
  }

  /**
   * Исход -> сервер (метрика). Резолвится ``{bot_link}`` или ``null``; никогда не отклоняется.
   * ids: { arenaId, trainerId, retry }. opts.fetch подменяет глобальный fetch (тесты).
   */
  function reportOutcome(tg, surface, outcome, ids, opts) {
    ids = ids || {};
    opts = opts || {};
    return new Promise(function (resolve) {
      try {
        var fetchFn = opts.fetch || (root && root.fetch && root.fetch.bind(root));
        if (!fetchFn || !tg || !tg.initData) {
          resolve(null);
          return;
        }
        var body = { surface: surface, outcome: outcome, retry: !!ids.retry };
        if (ids.arenaId != null) body.arena_id = Number(ids.arenaId);
        if (ids.trainerId != null) body.trainer_id = Number(ids.trainerId);
        Promise.resolve(
          fetchFn(OUTCOME_PATH, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': tg.initData },
            body: JSON.stringify(body),
          })
        )
          .then(function (r) {
            if (!r || !r.ok) return null;
            return r.json().catch(function () {
              return null;
            });
          })
          .then(function (json) {
            resolve(json && typeof json === 'object' ? json : null);
          })
          .catch(function () {
            resolve(null);
          });
      } catch (e) {
        resolve(null);
      }
    });
  }

  /** Ждёт ответ не дольше ``ms``: кнопка «Открыть бота» не должна зависеть от медленной сети. */
  function withTimeout(promise, ms) {
    return new Promise(function (resolve) {
      var t = null;
      try {
        t = setTimeout(function () {
          resolve(null);
        }, ms);
      } catch (e) {
        /* без таймера просто ждём ответ */
      }
      promise.then(function (v) {
        try {
          if (t !== null) clearTimeout(t);
        } catch (e) {
          /* noop */
        }
        resolve(v);
      });
    });
  }

  /** Нативный попап «Откройте бота…» с кнопкой «Открыть бота» (если есть ссылка). */
  function showOpenBotPopup(tg, link) {
    return new Promise(function (resolve) {
      if (!tg) {
        resolve(null);
        return;
      }
      try {
        if (typeof tg.showPopup === 'function') {
          var buttons = link
            ? [{ id: 'open_bot', type: 'default', text: COPY_OPEN_BOT_BUTTON }, { type: 'close' }]
            : [{ type: 'close' }];
          tg.showPopup({ message: COPY_OPEN_BOT, buttons: buttons }, function (id) {
            if (id === 'open_bot') openBotChat(tg, link);
            resolve(id == null ? null : String(id));
          });
          return;
        }
        if (typeof tg.showAlert === 'function') {
          tg.showAlert(COPY_OPEN_BOT, function () {
            resolve(null);
          });
          return;
        }
      } catch (e) {
        /* попап уже открыт или SDK не умеет */
      }
      resolve(null);
    });
  }

  function showAlert(tg, text) {
    try {
      if (tg && typeof tg.showAlert === 'function') tg.showAlert(text);
    } catch (e) {
      /* без алерта */
    }
  }

  /**
   * Ворота перед подпиской. Резолвится ``proceed`` (можно сохранять) | ``denied`` | ``unsupported``.
   * Не Telegram (MAX/VK) -> ``proceed`` без изменений. На denied/unsupported показывает текст сам.
   * opts: { surface, arenaId, trainerId, deniedText, fetch }.
   */
  function gate(tg, opts) {
    opts = opts || {};
    var ids = { arenaId: opts.arenaId, trainerId: opts.trainerId };
    var state = writeAccessState(tg);
    if (state === 'not_telegram') return Promise.resolve('proceed');
    if (state === 'already') {
      reportOutcome(tg, opts.surface, 'already', ids, opts);
      return Promise.resolve('proceed');
    }

    function unsupported() {
      return withTimeout(reportOutcome(tg, opts.surface, 'unsupported', ids, opts), LINK_WAIT_MS).then(function (res) {
        return showOpenBotPopup(tg, res && res.bot_link ? res.bot_link : null).then(function () {
          return 'unsupported';
        });
      });
    }

    if (state === 'unsupported') return unsupported();
    return requestWriteAccess(tg).then(function (outcome) {
      if (outcome === 'unsupported') return unsupported();
      reportOutcome(tg, opts.surface, outcome, ids, opts);
      if (outcome === 'granted') return 'proceed';
      showAlert(tg, opts.deniedText || COPY_SLOT_DENIED);
      return 'denied';
    });
  }

  return {
    OUTCOME_PATH: OUTCOME_PATH,
    COPY_ALLOW: COPY_ALLOW,
    COPY_OPEN_BOT: COPY_OPEN_BOT,
    COPY_OPEN_BOT_BUTTON: COPY_OPEN_BOT_BUTTON,
    COPY_SLOT_DENIED: COPY_SLOT_DENIED,
    getTg: getTg,
    isTelegramPrincipal: isTelegramPrincipal,
    canRequestWriteAccess: canRequestWriteAccess,
    rawState: rawState,
    writeAccessState: writeAccessState,
    requestWriteAccess: requestWriteAccess,
    openBotChat: openBotChat,
    reportOutcome: reportOutcome,
    showOpenBotPopup: showOpenBotPopup,
    gate: gate,
  };
});
