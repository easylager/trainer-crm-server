/**
 * Колокольчик сайта: startapp=follow_arena_<id> (src/application/place_links.py: follow_start_param).
 *
 * Мини-апп открывается уже подписанной на каток и один раз просит разрешение, чтобы бот мог
 * написать первым (Telegram.WebApp.requestWriteAccess, Bot API 6.9). Успех показываем только
 * когда разрешение реально есть: исход берём из колбэка requestWriteAccess, а не из его вызова.
 *
 * Сервер: POST /api/webapp/client/bell-follow (подписка, идемпотентно) и
 * POST /api/webapp/client/bell-follow/outcome (granted | denied | already | unsupported).
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

  var COPY_DECLINED = 'Подписка сохранена, но уведомления выключены.';
  var COPY_ENABLE = 'Включить уведомления';
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

  /* Проверки и запрос разрешения живут в write-access.js (общие с записью, ожиданием слотов и каткой). */
  var WA = typeof module !== 'undefined' && module.exports && typeof require === 'function'
    ? require('./write-access.js')
    : global.GlideWriteAccess;

  var isTelegramPrincipal = WA.isTelegramPrincipal;
  var canRequestWriteAccess = WA.canRequestWriteAccess;
  /** ``already`` — бот уже может писать; ``askable`` — спросим; ``unsupported`` — спросить нечем. */
  var writeAccessState = WA.rawState;
  var requestWriteAccess = WA.requestWriteAccess;

  /** Нативный попап Telegram; промис резолвится id нажатой кнопки (или ``null``). */
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
        /* попап уже открыт или SDK не умеет — страница не должна от этого ломаться */
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
   * opts: { tg, startParam, storage, post(path, body) → Promise<{ok,status,json}> }.
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

    function report(outcome, retry) {
      try {
        Promise.resolve(opts.post('/api/webapp/client/bell-follow/outcome', { arena_id: id, outcome: outcome, retry: !!retry })).catch(
          function () {}
        );
      } catch (e) {
        /* метрика не должна ломать сценарий */
      }
    }

    function done(name) {
      return showPopup(tg, copyDone(name), [{ type: 'close' }]).then(function () {
        return { status: 'done' };
      });
    }

    function declined(name, retry) {
      var buttons = canRequestWriteAccess(tg)
        ? [{ id: 'enable', type: 'default', text: COPY_ENABLE }, { type: 'close' }]
        : [{ type: 'close' }];
      return showPopup(tg, COPY_DECLINED, buttons).then(function (btn) {
        if (btn !== 'enable') return { status: 'declined' };
        return requestWriteAccess(tg).then(function (res) {
          report(res, true);
          return res === 'granted' ? done(name) : declined(name, true);
        });
      });
    }

    return Promise.resolve()
      .then(function () {
        return opts.post('/api/webapp/client/bell-follow', { arena_id: id });
      })
      .then(function (res) {
        if (res && res.status === 409) return { status: 'skipped' };
        if (!res || !res.ok || !res.json) {
          return showPopup(tg, COPY_FAILED, [{ type: 'close' }]).then(function () {
            return { status: 'error' };
          });
        }
        var name = String(res.json.arena_name || '');
        var state = writeAccessState(tg);
        if (state === 'already') {
          report('already');
          return done(name);
        }
        if (state === 'unsupported') {
          report('unsupported');
          return declined(name, false);
        }
        return requestWriteAccess(tg).then(function (outcome) {
          report(outcome);
          return outcome === 'granted' ? done(name) : declined(name, false);
        });
      })
      .catch(function () {
        return { status: 'error' };
      });
  }

  return {
    FLAG: FLAG,
    COPY_DECLINED: COPY_DECLINED,
    COPY_ENABLE: COPY_ENABLE,
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
