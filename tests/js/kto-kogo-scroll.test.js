/**
 * Возврат из матча в список оставляет то же место прокрутки, с которого матч открыли.
 * Run: node --test tests/js/kto-kogo-scroll.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');

function load() {
  const scrolled = [];
  const root = {
    querySelector() { return null; },
    replaceChildren() {},
  };
  const ctx = {
    console, setTimeout, clearTimeout, Promise, URL, URLSearchParams, Date, JSON, Math, Number, String, Object, Array, Error,
    scrollY: 0,
    innerHeight: 800,
    scrollTo(_x, y) { scrolled.push(y); ctx.scrollY = y; },
    requestAnimationFrame(fn) { fn(); },
    location: { search: '', href: 'https://x/webapp/kto-kogo' },
    document: {
      getElementById: (id) => (id === 'kk' ? root : null),
      documentElement: { scrollTop: 0, scrollHeight: 4000 },
      activeElement: null,
      body: { classList: { toggle() {}, contains() { return false; } } },
    },
  };
  ctx.window = ctx;
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  for (const file of ['kto-kogo-model.js', 'kto-kogo.js']) {
    vm.runInContext(fs.readFileSync(path.join(webapp, file), 'utf8'), ctx, { filename: file });
  }
  const KK = ctx.KK;
  KK.register('list', { render() { return []; }, enter() {} });
  KK.register('match', { render() { return []; }, enter() {} });
  KK.state.stack = [{ name: 'list', args: {} }];
  return { ctx, KK, scrolled };
}

describe('прокрутка списка «Кто кого»', () => {
  it('из матча назад — на то же место списка, а не в начало', () => {
    const { ctx, KK, scrolled } = load();
    ctx.scrollY = 960;
    KK.go('match', { id: 7 });
    assert.equal(KK.state.stack[0].scroll, 960);
    assert.equal(scrolled[scrolled.length - 1], 0, 'сам матч открывается сверху');
    KK.back();
    assert.equal(KK.state.stack.length, 1);
    assert.equal(KK.state.stack[0].name, 'list');
    assert.equal(scrolled[scrolled.length - 1], 960);
  });
});
