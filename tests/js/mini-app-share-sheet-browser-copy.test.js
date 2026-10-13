/**
 * TASK-254: подсказка и «Сторис» в браузере vs Telegram.
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const jsPath = path.resolve(__dirname, '../../static/webapp/mini-app-share-sheet.js');
const src = fs.readFileSync(jsPath, 'utf8');

function load(initData) {
  const context = {
    window: {},
    document: {
      createElement: () => ({
        hidden: true,
        className: '',
        innerHTML: '',
        addEventListener: () => {},
        querySelector: () => null,
      }),
      body: { appendChild: () => {} },
    },
    fetch: () => Promise.reject(new Error('no fetch')),
    location: { href: 'https://app.test/p/minsk/x' },
    navigator: {},
    Telegram: { WebApp: { initData: initData || '' } },
    requestAnimationFrame: (fn) => fn(),
    setTimeout: (fn) => fn(),
    clearTimeout: () => {},
  };
  context.window = context;
  vm.runInNewContext(src, context);
  return context.GlideShareSheet;
}

describe('GlideShareSheet browser copy (TASK-254)', () => {
  it('подсказка про стикер только при initData', () => {
    const browser = load('');
    const tg = load('user=1&auth_date=1&hash=x');
    assert.match(browser._shareNoteHtml(), /вертикальную картинку для сторис/);
    assert.doesNotMatch(browser._shareNoteHtml(), /стикер/);
    assert.match(tg._shareNoteHtml(), /Ссылку для стикера скопируйте сами/);
  });

  it('isTelegramMiniApp согласован с catalog-public-url', () => {
    assert.match(src, /function isTelegramMiniApp\(\)/);
    const G = load('x');
    assert.equal(G._isTelegramMiniApp(), true);
    assert.equal(load('')._isTelegramMiniApp(), false);
  });
});
