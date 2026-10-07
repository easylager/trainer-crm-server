/**
 * TASK-211: оба состояния кнопки «Следить» на странице места.
 * Run: node --test tests/js/place-follow.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/place-follow.js');

function load() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

const LABEL = 'Вы следите за катком · отписаться';

describe('подписка на странице места', () => {
  it('вне Telegram ссылка на бота остаётся, даже если статус «уже следите»', () => {
    const { placeFollowState } = load();
    assert.deepEqual(
      placeFollowState({
        initData: '',
        status: { arena_id: 4, following: true, muted: false },
        label: LABEL,
      }),
      { mode: 'link' },
    );
  });

  it('в Mini App без подписки кнопка остаётся «Следить»', () => {
    const { placeFollowState } = load();
    assert.deepEqual(
      placeFollowState({
        initData: 'telegram-init',
        status: { arena_id: 4, following: false, muted: false },
        label: LABEL,
      }),
      { mode: 'link' },
    );
  });

  it('в Mini App при following кнопка отписывается DELETE того же пути', () => {
    const { placeFollowState } = load();
    assert.deepEqual(
      placeFollowState({
        initData: 'telegram-init',
        status: { arena_id: 4, following: true, muted: false },
        label: LABEL,
      }),
      {
        mode: 'unfollow',
        method: 'DELETE',
        url: '/api/webapp/client/arena-follows/4',
        label: LABEL,
      },
    );
  });
});
