/**
 * MiniAppBack — единственная «назад»: нативная стрелка Telegram (mini-app-telegram-chrome.js).
 * Run: node --test tests/js/mini-app-back.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const src = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/mini-app-telegram-chrome.js'), 'utf8');
const block = src.slice(src.indexOf('window.MiniAppBack = (function'), src.indexOf('(function () {\n  if (window.MiniAppRuntime)'));

function load(tg) {
  const win = { Telegram: tg ? { WebApp: tg } : undefined };
  vm.runInNewContext(block, { window: win });
  return win.MiniAppBack;
}

function fakeTg(extra = {}) {
  const calls = [];
  let handler = null;
  return {
    calls,
    click: () => handler && handler(),
    tg: {
      initData: 'query_id=1',
      isVersionAtLeast: () => true,
      BackButton: {
        show: () => calls.push('show'),
        hide: () => calls.push('hide'),
        onClick: (fn) => { calls.push('onClick'); handler = fn; },
      },
      ...extra,
    },
  };
}

describe('MiniAppBack', () => {
  it('shows the native arrow and routes the click to the current screen', () => {
    const f = fakeTg();
    const Back = load(f.tg);
    let hits = 0;
    assert.equal(Back.set(() => { hits += 1; }), true);
    f.click();
    assert.equal(hits, 1);
  });

  it('wires Telegram once and swaps the handler when the screen changes', () => {
    const f = fakeTg();
    const Back = load(f.tg);
    const seen = [];
    Back.set(() => seen.push('a'));
    Back.set(() => seen.push('b'));
    f.click();
    assert.deepEqual(seen, ['b']);
    assert.equal(f.calls.filter((c) => c === 'onClick').length, 1);
  });

  it('clear() hides the arrow and drops the handler', () => {
    const f = fakeTg();
    const Back = load(f.tg);
    let hits = 0;
    Back.set(() => { hits += 1; });
    Back.clear();
    f.click();
    assert.equal(hits, 0);
    assert.equal(f.calls[f.calls.length - 1], 'hide');
  });

  it('is not native outside Telegram or in a client without BackButton', () => {
    for (const tg of [null, { initData: '' , BackButton: {} }, { initData: 'x', isVersionAtLeast: () => false, BackButton: {} }]) {
      const Back = load(tg);
      assert.equal(Back.isNative(), false);
      assert.equal(Back.set(() => {}), false);
    }
  });
});

describe('мост старого #btnBack', () => {
  const bridge = src.slice(src.indexOf('function bridgeLegacyBackButton'), src.indexOf('(function () {\n  if (window.MiniAppRuntime)'));

  function page({ hidden, inNav = true }) {
    const f = fakeTg();
    const clicks = [];
    const observers = [];
    const btn = {
      hidden,
      classList: { contains: () => false },
      closest: (sel) => (inNav && sel === '.client-mini-nav' ? {} : null),
      click: () => clicks.push(1),
    };
    const listeners = {};
    const win = { Telegram: { WebApp: f.tg }, addEventListener: (type, fn) => { listeners[type] = fn; } };
    const ctx = {
      window: win,
      document: { getElementById: () => btn, createElement: () => ({}), head: { appendChild() {} } },
      MutationObserver: function (cb) { observers.push(cb); this.observe = () => {}; },
    };
    vm.runInNewContext(block + bridge + '\nbridgeLegacyBackButton();', ctx);
    return { f, btn, clicks, observers, listeners };
  }

  it('кнопка видна — стрелка включена и нажимает #btnBack', () => {
    const p = page({ hidden: false });
    assert.ok(p.f.calls.includes('show'));
    p.f.click();
    assert.equal(p.clicks.length, 1);
  });

  it('кнопка спрятана — стрелки нет, а когда страница её покажет — появляется', () => {
    const p = page({ hidden: true });
    assert.ok(!p.f.calls.includes('show'));
    p.btn.hidden = false;
    p.observers[0]();
    assert.ok(p.f.calls.includes('show'));
  });

  it('возврат из bfcache: стрелка от прежнего экрана снимается, если у страницы своей «назад» нет', () => {
    const p = page({ hidden: true });
    p.f.calls.length = 0;
    p.listeners.pageshow({ persisted: true });
    assert.deepEqual(p.f.calls, ['hide']);
  });

  it('возврат из bfcache: если #btnBack виден, стрелка остаётся', () => {
    const p = page({ hidden: false });
    p.f.calls.length = 0;
    p.listeners.pageshow({ persisted: true });
    assert.ok(p.f.calls.includes('show'));
  });

  it('не трогает страницы без клиентской шапки', () => {
    const p = page({ hidden: false, inNav: false });
    assert.ok(!p.f.calls.includes('show'));
  });
});
