/**
 * Шит «Поделиться» отдаёт креденшл Mini App в превью и в запись по каналу.
 * Run: node --test tests/js/mini-app-share-sheet-auth.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { URL } = require('node:url');

const jsPath = path.resolve(__dirname, '../../static/webapp/mini-app-share-sheet.js');
const src = fs.readFileSync(jsPath, 'utf8');

function element() {
  return {
    className: '',
    hidden: true,
    innerHTML: '',
    style: {},
    classList: { add() {}, remove() {} },
    addEventListener() {},
    querySelector: () => element(),
    querySelectorAll: () => [],
    appendChild() {},
    getAttribute: () => null,
    setAttribute() {},
    closest: () => null,
    blur() {},
  };
}

function loadSheet({ initData, runtimeHeaders }) {
  const calls = [];
  const handlers = {};
  const root = element();
  root.addEventListener = (type, fn) => {
    handlers[type] = fn;
  };
  const context = {
    document: {
      createElement: () => root,
      body: { appendChild() {} },
      querySelector: () => element(),
    },
    location: { href: 'https://app.test/webapp/arena' },
    navigator: { clipboard: { writeText: () => Promise.resolve() } },
    Telegram: { WebApp: initData ? { initData } : {} },
    fetch: (url, opts) => {
      calls.push({ url: String(url), opts: opts || {} });
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ share_url: 'https://glide.test/p/x', share_body: 'Лёд' }),
      });
    },
    URL,
    open: () => {},
    requestAnimationFrame: (fn) => fn(),
    setTimeout: (fn) => fn(),
    clearTimeout: () => {},
  };
  if (runtimeHeaders) {
    context.MiniAppRuntime = { authHeaders: () => runtimeHeaders };
  }
  context.window = context;
  vm.runInNewContext(src, context);
  context.GlideShareSheet.open({ ref: 'minsk-arena' });
  return {
    calls,
    press(channel) {
      handlers.click({
        target: {
          closest: (sel) => (sel === '[data-ch]' ? { getAttribute: () => channel } : null),
        },
      });
    },
  };
}

async function settle() {
  for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setImmediate(resolve));
}

function authHeader(call) {
  return call.opts.headers && call.opts.headers['X-Telegram-Init-Data'];
}

describe('GlideShareSheet auth headers', () => {
  it('превью и запись канала шлют initData', async () => {
    const sheet = loadSheet({ initData: 'signed-init-data' });
    await settle();
    const preview = sheet.calls.find((call) => call.url.includes('record=false'));
    assert.ok(preview, 'превью record=false');
    assert.equal(authHeader(preview), 'signed-init-data');
    sheet.press('telegram');
    const tracked = sheet.calls.find((call) => call.url.includes('channel=telegram'));
    assert.ok(tracked, 'запись по каналу');
    assert.equal(tracked.opts.keepalive, true);
    assert.equal(authHeader(tracked), 'signed-init-data');
  });

  it('вне Telegram заголовка нет', async () => {
    const sheet = loadSheet({});
    await settle();
    sheet.press('copy');
    assert.ok(sheet.calls.length >= 2);
    for (const call of sheet.calls) {
      assert.equal(authHeader(call), undefined);
    }
  });

  it('берёт заголовки MiniAppRuntime.authHeaders, если рантайм есть', async () => {
    const sheet = loadSheet({
      runtimeHeaders: { 'X-Telegram-Init-Data': 'from-runtime', 'X-Mini-App-Platform': 'telegram' },
    });
    await settle();
    const preview = sheet.calls.find((call) => call.url.includes('record=false'));
    assert.equal(authHeader(preview), 'from-runtime');
    assert.equal(preview.opts.headers['X-Mini-App-Platform'], 'telegram');
  });
});
