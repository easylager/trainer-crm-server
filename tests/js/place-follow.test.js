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

  it('ошибка DELETE возвращает кнопку и показывает сообщение', async () => {
    const { runUnfollow } = load();
    const alerts = [];
    const button = {
      pending: false,
      disabled: false,
      following: true,
      url: '/api/webapp/client/arena-follows/4',
      label: LABEL,
      offLabel: 'Следить за катком в Telegram',
      error: 'Не удалось отписаться. Попробуйте ещё раз.',
    };
    const result = await runUnfollow(
      button,
      async () => ({ ok: false }),
      (message) => alerts.push(message),
    );
    assert.deepEqual(result, { ok: false, message: button.error });
    assert.equal(button.pending, false);
    assert.equal(button.disabled, false);
    assert.equal(button.following, true);
    assert.equal(button.label, LABEL);
    assert.deepEqual(alerts, [button.error]);
  });

  it('повторный клик во время DELETE не шлёт второй запрос', async () => {
    const { runUnfollow } = load();
    let calls = 0;
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    const button = {
      pending: false,
      disabled: false,
      following: true,
      url: '/api/webapp/client/arena-follows/4',
      label: LABEL,
      offLabel: 'Следить за катком в Telegram',
      error: 'Не удалось отписаться. Попробуйте ещё раз.',
    };
    const fetchFn = () => {
      calls += 1;
      return gate.then(() => ({ ok: true, json: async () => ({}) }));
    };
    const first = runUnfollow(button, fetchFn, () => {});
    const second = await runUnfollow(button, fetchFn, () => {});
    assert.equal(calls, 1);
    assert.equal(button.disabled, true);
    assert.deepEqual(second, { skipped: true });
    release();
    assert.deepEqual(await first, { ok: true });
    assert.equal(button.pending, false);
    assert.equal(button.disabled, false);
    assert.equal(button.following, false);
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
