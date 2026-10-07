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

  return { placeFollowState: placeFollowState };
});
