import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const api = require(path.resolve(import.meta.dirname, '../../static/webapp/catalog-public-url.js'));

describe('catalog-public-url', () => {
  it('builds public place path from slug and city', () => {
    const p = api.publicPlacePath({ slug: 'minsk-arena' }, 'Минск');
    assert.match(p, /^\/p\/.+\/minsk-arena$/);
  });

  it('keeps mini-app href inside telegram', () => {
    const g = globalThis;
    const prev = g.Telegram;
    g.Telegram = { WebApp: { initData: 'x', platform: 'tdesktop' } };
    const href = api.arenaHref({ id: 1, slug: 'x' }, 'Минск', 'arena?ref=1');
    assert.equal(href, 'arena?ref=1');
    g.Telegram = prev;
  });

  it('uses public path on anonymous web', () => {
    const g = globalThis;
    const prev = g.Telegram;
    g.Telegram = undefined;
    const href = api.arenaHref({ id: 1, slug: 'led' }, 'Минск', 'arena?ref=1');
    assert.match(href, /^\/p\//);
    g.Telegram = prev;
  });
});
