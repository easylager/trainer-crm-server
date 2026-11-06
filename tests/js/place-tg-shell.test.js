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

function runShellOnPlace(initData, opts = {}) {
  const dom = new vm.createContext({
    URL, URLSearchParams,
    window: {
      location: opts.location || { pathname: '/p/minsk/zamok', search: '', href: 'http://test/p/minsk/zamok' },
      history: { length: 2 },
      document: {
        readyState: opts.delayBoot ? 'loading' : 'complete',
        body: { classList: { add() {}, toggle() {} }, getAttribute() { return null; }, setAttribute() {} },
        documentElement: { style: { setProperty() {} } },
        getElementById() { return null; },
        createElement() { return { appendChild() {}, setAttribute() {}, addEventListener() {} }; },
        head: { appendChild() {} },
        addEventListener: opts.addEventListener || function () {},
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

describe('Mini App shell navigation boundaries', () => {
  it('a shell accidentally on /p/ still resolves internal navigation under /webapp/', () => {
    const ctx = runShellOnPlace('signed', { delayBoot: true });
    ctx.window.ClientShell.navigate('ice');
    assert.equal(ctx.window.location.href, '/webapp/ice?init_data=signed');
  });

  it('startup navigation replaces the entry rather than assigning href', () => {
    let replaced;
    const loc = { pathname: '/webapp/client-home', search: '', href: 'https://test/webapp/client-home', replace(value) { replaced = value; } };
    const ctx = runShellOnPlace('signed', { delayBoot: true, location: loc });
    ctx.window.ClientShell.navigate('arena?ref=31', { replace: true });
    assert.equal(replaced, '/webapp/arena?ref=31&init_data=signed');
    assert.equal(loc.href, 'https://test/webapp/client-home');
    assert.match(read('static/webapp/mini-app-client-shell.js'), /navigate\(target\.path, \{ replace: true \}\)/);
  });

  it('unhandled external HTTP anchors use tg.openLink and tel/internal anchors stay native', () => {
    const handlers = {};
    const ctx = runShellOnPlace('signed', { delayBoot: true, addEventListener: (type, fn) => { handlers[type] = fn; } });
    const links = [];
    ctx.window.Telegram.WebApp.openLink = (url) => links.push(url);
    assert.equal(typeof handlers.click, 'function');
    function click(href, attrs = {}, prevented = false) {
      const a = { href, getAttribute: (key) => attrs[key] || null };
      const event = { defaultPrevented: prevented, target: { closest: () => a }, preventDefault() { this.defaultPrevented = true; } };
      handlers.click(event);
      return event;
    }
    assert.equal(click('https://lokomotiv-orsha.by/расписание/').defaultPrevented, true);
    assert.equal(links.length, 1);
    assert.equal(click('tel:+375216550832').defaultPrevented, false);
    assert.equal(click('http://test/webapp/ice').defaultPrevented, false);
    click('https://t.me/ice_studio_bot?startapp=arena_31', {}, true);
    assert.equal(links.length, 1);
  });

  it('ordinary browser unhandled external links are not intercepted', () => {
    const handlers = {};
    runShellOnPlace('', { delayBoot: true, addEventListener: (type, fn) => { handlers[type] = fn; } });
    if (handlers.click) {
      const event = { target: { closest: () => ({ href: 'https://lokomotiv-orsha.by/' }) }, preventDefault() { this.defaultPrevented = true; } };
      handlers.click(event);
      assert.ok(!event.defaultPrevented);
    }
  });
});
