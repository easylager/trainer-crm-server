/**
 * TASK-211: кнопка подписки на странице места.
 * Вне Telegram ссылка на бота остаётся как есть. Внутри Mini App GET
 * /api/webapp/client/arena-follows/{id} решает, заменить ли её на «отписаться».
 * Browser: window.PlaceFollow. Node: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.PlaceFollow = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function placeFollowState(input) {
    var initData = input && input.initData ? String(input.initData).trim() : '';
    var status = input && input.status;
    if (!initData || !status || status.following !== true) {
      return { mode: 'link' };
    }
    var id = Number(status.arena_id);
    if (!id || id < 1) {
      return { mode: 'link' };
    }
    return {
      mode: 'unfollow',
      method: 'DELETE',
      url: '/api/webapp/client/arena-follows/' + id,
      label: String((input && input.label) || ''),
    };
  }

  function runUnfollow(button, fetchFn, alertFn) {
    if (!button || button.pending) return Promise.resolve({ skipped: true });
    button.pending = true;
    button.disabled = true;
    var url = button.url;
    return Promise.resolve()
      .then(function () { return fetchFn(url); })
      .then(function (response) {
        if (!response || response.ok === false) throw new Error('unfollow');
        button.pending = false;
        button.disabled = false;
        button.following = false;
        button.label = button.offLabel || '';
        return { ok: true };
      })
      .catch(function () {
        button.pending = false;
        button.disabled = false;
        button.following = true;
        var message = String(button.error || '');
        if (message && typeof alertFn === 'function') alertFn(message);
        return { ok: false, message: message };
      });
  }

  return { placeFollowState: placeFollowState, runUnfollow: runUnfollow };
});
