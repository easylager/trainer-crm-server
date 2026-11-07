/**
 * TASK-357: глобальный патч fetch не перетирает явный X-Profile-Id (выбор профиля в форме записи).
 * Run: node --test tests/js/client-profile-switcher-explicit.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const src = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/client-profile-switcher.js'), 'utf8');

async function boot({ stored = null } = {}) {
  const calls = [];
  const storage = new Map(stored != null ? [['cw_active_profile_id_v1', String(stored)]] : []);
  const nativeFetch = (input, init) => {
    calls.push({ input, headers: (init && init.headers) || {} });
    if (String(input).indexOf('/api/webapp/client/profiles') !== -1) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          items: [
            { client_id: 1, role: 'self', first_name: 'Мама', is_default: true },
            { client_id: 2, role: 'guardian', first_name: 'Соня', is_default: false },
          ],
          default_profile_id: 1,
        }),
      });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  };
  const window = {
    fetch: nativeFetch,
    Telegram: { WebApp: { initData: 'user=%7B%22id%22%3A5%7D' } },
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
      removeItem: (k) => storage.delete(k),
    },
  };
  const document = { readyState: 'complete', getElementById: () => null, addEventListener() {}, head: { appendChild() {} }, createElement: () => ({}) };
  const ctx = { window, document, URLSearchParams, JSON, Object, String, Number, parseInt, console };
  vm.runInNewContext(src, ctx);
  await window.ClientProfileSwitcher.init();
  return { window, calls, storage };
}

describe('ClientProfileSwitcher fetch patch', () => {
  it('без явного заголовка — активный профиль (выбранный в хабе)', async () => {
    const { window, calls } = await boot({ stored: 2 });
    await window.fetch('/api/webapp/client/passes', {});
    assert.equal(calls.at(-1).headers['X-Profile-Id'], '2');
  });

  it('явный X-Profile-Id формы главнее активного и дефолтного профиля', async () => {
    const { window, calls } = await boot({ stored: 2 });
    await window.fetch('/api/webapp/client/booking', { method: 'POST', headers: { 'X-Profile-Id': '1' } });
    assert.equal(calls.at(-1).headers['X-Profile-Id'], '1');
    await window.fetch('/api/webapp/client/passes', { headers: { 'x-profile-id': '2' } });
    assert.equal(calls.at(-1).headers['x-profile-id'], '2');
    assert.equal(calls.at(-1).headers['X-Profile-Id'], undefined);
  });

  it('setActiveProfileId: профиль записи становится активным без перезагрузки и переживает переход', async () => {
    const { window, calls, storage } = await boot();
    window.ClientProfileSwitcher.setActiveProfileId(2);
    assert.equal(window.ClientProfileSwitcher.getActiveProfileId(), 2);
    assert.equal(storage.get('cw_active_profile_id_v1'), '2');
    await window.fetch('/api/webapp/client/bookings', {});
    assert.equal(calls.at(-1).headers['X-Profile-Id'], '2');
    // Явный заголовок по-прежнему главнее.
    await window.fetch('/api/webapp/client/booking', { headers: { 'X-Profile-Id': '1' } });
    assert.equal(calls.at(-1).headers['X-Profile-Id'], '1');
    // Профиль по умолчанию — «нет выбора», как в шторке.
    window.ClientProfileSwitcher.setActiveProfileId(1);
    assert.equal(window.ClientProfileSwitcher.getStoredActiveProfileId(), null);
    assert.equal(storage.has('cw_active_profile_id_v1'), false);
    assert.equal(window.ClientProfileSwitcher.getActiveProfileId(), 1);
  });
});
