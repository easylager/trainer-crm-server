/**
 * Колокольчик сайта: startapp=follow_arena_<id> (src/application/place_links.py: follow_start_param).
 *
 * Сначала разрешение боту писать (``GlideWriteAccess.gate``), и только потом подписка.
 * Без права писать подписку не сохраняем — иначе пуш уходит в никуда.
 *
 * Сервер: POST /api/webapp/client/bell-follow (подписка, идемпотентно).
 * Исход разрешения пишет ``write-access.js`` (surface ``arena_watch``).
 * Нативный диалог Telegram в headless-тестах не воспроизвести: здесь он подменён моком.
 */
(function (global, factory) {
  'use strict';
  var api = factory(global);
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (global) {
    global.GlideBellFollow = api;
  }
})(typeof window !== 'undefined' ? window : typeof global !== 'undefined' ? global : this, function (global) {
  'use strict';

  var FLAG = 'glide_bell_follow_v1';
  var FOLLOW_RE = /^follow_arena_([1-9][0-9]{0,8})$/;

  var COPY_DENIED = 'Без разрешения писать бот не\u00a0сможет прислать напоминание.';
  var COPY_FAILED = 'Не удалось сохранить подписку.';

  function copyDone(arenaName) {
    return 'Готово. Напишем, когда у «' + arenaName + '» появится расписание.';
  }

  /** ``follow_arena_42`` → ``42``; ``arena_42`` и мусор → ``null``. */
  function parseFollowStartParam(sp) {
    var m = FOLLOW_RE.exec(String(sp || '').trim());
    return m ? m[1] : null;
  }

  /** Для остального диплинк-кода колокольчик — обычный ``arena_<id>``. */
  function arenaStartParam(sp) {
    var id = parseFollowStartParam(sp);
    return id ? 'arena_' + id : sp;
  }

  var WA = typeof module !== 'undefined' && module.exports && typeof require === 'function'
    ? require('./write-access.js')
    : global.GlideWriteAccess;

  var isTelegramPrincipal = WA.isTelegramPrincipal;
  var canRequestWriteAccess = WA.canRequestWriteAccess;
  var writeAccessState = WA.rawState;
  var requestWriteAccess = WA.requestWriteAccess;

  function showPopup(tg, message, buttons) {
    return new Promise(function (resolve) {
      if (!tg) {
        resolve(null);
        return;
      }
      try {
        if (typeof tg.showPopup === 'function') {
          tg.showPopup({ message: message, buttons: buttons }, function (id) {
            resolve(id == null ? null : String(id));
          });
          return;
        }
        if (typeof tg.showAlert === 'function') {
          tg.showAlert(message, function () {
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

  function makePost(initData, fetchFn) {
    return function (path, body) {
      return fetchFn(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData },
        body: JSON.stringify(body),
      }).then(function (r) {
        return r
          .json()
          .catch(function () {
            return null;
          })
          .then(function (json) {
            return { ok: !!r.ok, status: r.status, json: json };
          });
      });
    };
  }

  /**
   * opts: { tg, startParam, storage, post(path, body) → Promise<{ok,status,json}>, fetch }.
   * Резолвится, когда человек закрыл последний попап: после этого шелл может уводить на карточку.
   */
  function run(opts) {
    var tg = opts.tg;
    var sp = String(opts.startParam || '').trim();
    var arenaId = parseFollowStartParam(sp);
    if (!arenaId) return Promise.resolve({ status: 'not_follow' });
    if (!isTelegramPrincipal(tg)) return Promise.resolve({ status: 'skipped' });
    try {
      if (opts.storage) {
        if (opts.storage.getItem(FLAG) === sp) return Promise.resolve({ status: 'already_handled' });
        opts.storage.setItem(FLAG, sp);
      }
    } catch (e) {
      /* без storage — один раз за загрузку страницы */
    }
    var id = Number(arenaId);
    var post = opts.post;

    function done(name) {
      return showPopup(tg, copyDone(name), [{ type: 'close' }]).then(function () {
        return { status: 'done' };
      });
    }

    function subscribeThenDone() {
      return post('/api/webapp/client/bell-follow', { arena_id: id }).then(function (res) {
        if (res && res.status === 409) return { status: 'skipped' };
        if (!res || !res.ok || !res.json) {
          return showPopup(tg, COPY_FAILED, [{ type: 'close' }]).then(function () {
            return { status: 'error' };
          });
        }
        return done(String(res.json.arena_name || ''));
      });
    }

    var gateOpts = { surface: 'arena_watch', arenaId: id, deniedText: COPY_DENIED };
    if (opts.fetch) gateOpts.fetch = opts.fetch;

    return WA.gate(tg, gateOpts)
      .then(function (res) {
        if (res !== 'proceed') return { status: 'declined' };
        return subscribeThenDone();
      })
      .catch(function () {
        return { status: 'error' };
      });
  }

  return {
    FLAG: FLAG,
    COPY_DENIED: COPY_DENIED,
    COPY_FAILED: COPY_FAILED,
    copyDone: copyDone,
    parseFollowStartParam: parseFollowStartParam,
    arenaStartParam: arenaStartParam,
    isTelegramPrincipal: isTelegramPrincipal,
    canRequestWriteAccess: canRequestWriteAccess,
    writeAccessState: writeAccessState,
    requestWriteAccess: requestWriteAccess,
    makePost: makePost,
    run: run,
  };
});
