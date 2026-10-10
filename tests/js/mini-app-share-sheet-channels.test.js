/**
 * TASK-223: withSrc, Viber/WhatsApp из GlideShareSheet.
 * Run: node --test tests/js/mini-app-share-sheet-channels.test.js
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

function loadShareSheet() {
  const context = {
    URL,
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
    location: { href: 'https://app.test/webapp/arena' },
    navigator: { clipboard: { writeText: () => Promise.resolve() } },
    Telegram: { WebApp: { openLink: () => {} } },
    requestAnimationFrame: (fn) => fn(),
    setTimeout: (fn) => fn(),
    clearTimeout: () => {},
  };
  context.window = context;
  vm.runInNewContext(src, context);
  return context.GlideShareSheet;
}

describe('GlideShareSheet resolveInitialSessionId (gone invite)', () => {
  const G = loadShareSheet();

  it('не подставляет slots[0], если сеанс из ссылки пропал', () => {
    const slots = [{ id: 100, label: 'Пт 18:00' }, { id: 200, label: 'Пт 20:00' }];
    assert.equal(G._resolveInitialSessionId({ slots: slots, sessionMissing: true }), null);
    assert.equal(G._resolveInitialSessionId({ slots: slots, sessionMissing: false }), '100');
    assert.equal(G._resolveInitialSessionId({ slots: slots }), '100');
  });

  it('явный sessionId важнее sessionMissing', () => {
    assert.equal(
      G._resolveInitialSessionId({ sessionId: '42', sessionMissing: true, slots: [{ id: 1, label: 'x' }] }),
      '42'
    );
  });
});

describe('GlideShareSheet withSrc (TASK-223)', () => {
  const G = loadShareSheet();

  it('добавляет src, не трогая hash и существующий query', () => {
    assert.equal(
      G._withSrc('https://cdn.test/p/minsk/x?s=9001', 'tg'),
      'https://cdn.test/p/minsk/x?s=9001&src=tg'
    );
    assert.equal(G._withSrc('https://cdn.test/p/minsk/x', 'vb'), 'https://cdn.test/p/minsk/x?src=vb');
    assert.equal(G._withSrc('https://cdn.test/p/minsk/x?src=copy', 'wa'), 'https://cdn.test/p/minsk/x?src=copy');
  });

  it('fullMessage = body + url как на веб-странице места', () => {
    const p = { share_body: 'Пт 20:30', share_url: 'https://cdn.test/p/x?src=wa' };
    assert.equal(G._shareFullMessage(p), 'Пт 20:30\nhttps://cdn.test/p/x?src=wa');
    assert.equal(G._shareFullMessage({ share_url: 'https://cdn.test/p/x' }), 'https://cdn.test/p/x');
  });
});

describe('GlideShareSheet Viber / WhatsApp href', () => {
  it('строит viber:// и wa.me с полным текстом', () => {
    assert.match(src, /viber:\/\/forward\?text=/);
    assert.match(src, /https:\/\/wa\.me\/\?text=/);
    assert.match(src, /data-ch="viber"/);
    assert.match(src, /data-ch="whatsapp"/);
    assert.match(src, /shareFullMessage/);
    assert.match(src, /function openDeepLink/);
    assert.match(src, /openLink\(u, \{ try_instant_view: false \}\)/);
    assert.doesNotMatch(src, /if \(\/^viber:\/i\.test\(u\)\)[\s\S]*?location\.href = u/);
  });

  it('копирование ссылки добавляет src=copy, без share_body', () => {
    const copyIdx = src.indexOf('copy: function (p)');
    assert.ok(copyIdx > -1);
    const nextChannel = src.indexOf('story: function (p)', copyIdx);
    const block = src.slice(copyIdx, nextChannel > -1 ? nextChannel : copyIdx + 600);
    assert.match(block, /withSrc\(p\.share_url, 'copy'\)/);
    assert.doesNotMatch(block, /share_body/);
  });
});
