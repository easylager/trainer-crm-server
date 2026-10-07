import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const api = require(path.resolve(import.meta.dirname, '../../static/webapp/catalog-public-url.js'));

describe('catalog-public-url', () => {
  it('uses server public_path for Minsk', () => {
    const href = api.arenaHref(
      { id: 1, slug: 'minsk-arena', public_path: '/p/minsk/minsk-arena' },
      'arena?ref=1',
    );
    assert.equal(href, '/p/minsk/minsk-arena');
  });

  it('appends session id to public_path', () => {
    const href = api.arenaHref(
      {
        public_path: '/p/minsk/led',
        live: { kind: 'session', session_id: 42 },
      },
      'arena?ref=1',
    );
    assert.equal(href, '/p/minsk/led?s=42');
  });

  it('keeps mini-app href when initData is non-empty', () => {
    const g = globalThis;
    const prev = g.Telegram;
    g.Telegram = { WebApp: { initData: 'signed-payload', platform: 'tdesktop' } };
    const href = api.arenaHref({ public_path: '/p/minsk/x' }, 'arena?ref=1');
    assert.equal(href, 'arena?ref=1');
    g.Telegram = prev;
  });

  it('treats platform-only WebApp as anonymous web', () => {
    const g = globalThis;
    const prev = g.Telegram;
    g.Telegram = { WebApp: { initData: '', platform: 'unknown' } };
    const href = api.arenaHref({ public_path: '/p/minsk/x' }, 'arena?ref=1');
    assert.equal(href, '/p/minsk/x');
    g.Telegram = prev;
  });

  it('isTelegramMiniApp requires non-empty initData', () => {
    const g = globalThis;
    const prev = g.Telegram;
    g.Telegram = { WebApp: { initData: 'x', platform: 'ios' } };
    assert.equal(api.isTelegramMiniApp(), true);
    g.Telegram = { WebApp: { initData: '', platform: 'unknown' } };
    assert.equal(api.isTelegramMiniApp(), false);
    g.Telegram = undefined;
    assert.equal(api.isTelegramMiniApp(), false);
    g.Telegram = prev;
  });
});
