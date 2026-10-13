/**
 * TASK-256: Telegram shell на серверной /p/…
 * Run: node --test tests/js/place-tg-shell.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const repo = path.resolve(__dirname, '..', '..');
const webapp = path.join(repo, 'static', 'webapp');

function read(rel) {
  return fs.readFileSync(path.join(repo, rel), 'utf8');
}

function runShellOnPlace(initData) {
  const dom = new vm.createContext({
    window: {
      location: { pathname: '/p/minsk/zamok', search: '', href: 'http://test/p/minsk/zamok' },
      history: { length: 2 },
      document: {
        readyState: 'complete',
        body: { classList: { add() {}, toggle() {} }, getAttribute() { return null; }, setAttribute() {} },
        documentElement: { style: { setProperty() {} } },
        getElementById() { return null; },
        createElement() { return { appendChild() {}, setAttribute() {}, addEventListener() {} }; },
        head: { appendChild() {} },
        addEventListener() {},
        querySelector() { return null; },
        querySelectorAll() { return []; },
      },
      addEventListener() {},
      sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
      Telegram: { WebApp: { initData: initData || '' } },
      navigation: null,
      ClientShell: undefined,
    },
  });
  dom.window = dom.window;
  dom.document = dom.window.document;
  dom.location = dom.window.location;
  dom.history = dom.window.history;
  dom.Telegram = dom.window.Telegram;
  dom.sessionStorage = dom.window.sessionStorage;
  dom.addEventListener = dom.window.addEventListener;
  vm.runInContext(fs.readFileSync(path.join(webapp, 'mini-app-client-shell.js'), 'utf8'), dom);
  return dom;
}

describe('TASK-256 place-tg-shell wiring', () => {
  it('b.html подключает bootstrap; в SSR нет clientTabBar', () => {
    const html = read('static/share/b.html');
    assert.match(html, /place-tg-shell\.js/);
    const boot = read('static/share/place-tg-shell.js');
    assert.match(boot, /mini-app-client-shell\.js/);
    assert.ok(!html.includes('clientTabBar'));
    assert.ok(!html.includes('client-tab-bar'));
  });

  it('place-tg-shell выходит без initData', () => {
    const src = read('static/share/place-tg-shell.js');
    assert.match(src, /if \(!initData\(\)\) return/);
    assert.match(src, /if \(!isPlacePage\(\)\) return/);
    assert.match(src, /tg-dark/);
    assert.match(src, /if \(!getTg\(\)\)/);
    assert.match(src, /telegram-web-app\.js/);
  });

  it('mini-app-client-shell на /p/ без initData не монтирует вкладки', () => {
    const ctx = runShellOnPlace('');
    assert.equal(ctx.window.document.getElementById('clientTabBar'), null);
  });
});
