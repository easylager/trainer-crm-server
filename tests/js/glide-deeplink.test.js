/**
 * TASK-223: ранний redirect и парсер start_param (glide-deeplink.js).
 * Run: node --test tests/js/glide-deeplink.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');

function load() {
  const modPath = path.join(webapp, 'glide-deeplink.js');
  delete require.cache[require.resolve(modPath)];
  return require(modPath);
}

describe('GlideDeepLink.deepLinkTarget', () => {
  const G = load();

  it('arena и catalog как в шелле', () => {
    assert.deepEqual(G.deepLinkTarget('arena_42'), { key: 'arena', path: 'arena?ref=42' });
    assert.deepEqual(G.deepLinkTarget('arena_42_s_9001'), { key: 'arena', path: 'arena?ref=42&s=9001' });
    assert.deepEqual(G.deepLinkTarget('catalog_7_skate_weekend'), {
      key: 'ice',
      path: 'ice?city_id=7&intent=skate&when=weekend',
    });
    assert.deepEqual(G.deepLinkTarget('catalog_7_ohm'), {
      key: 'ice',
      path: 'ice?city_id=7&intent=ohm',
    });
    assert.deepEqual(G.deepLinkTarget('catalog_7_ohm_weekend'), {
      key: 'ice',
      path: 'ice?city_id=7&intent=ohm&when=weekend',
    });
    assert.deepEqual(G.deepLinkTarget('catalog_7_service'), {
      key: 'ice',
      path: 'ice?city_id=7&intent=service',
    });
    assert.equal(G.deepLinkTarget('nope'), null);
  });
});

describe('GlideDeepLink.readStartParam', () => {
  const G = load();

  it('читает initDataUnsafe, hash и query', () => {
    assert.equal(
      G.readStartParam({
        Telegram: { WebApp: { initDataUnsafe: { start_param: 'arena_1' } } },
        location: { search: '', hash: '' },
      }),
      'arena_1'
    );
    assert.equal(
      G.readStartParam({
        location: { search: '', hash: '#tgWebAppData=1&tgWebAppStartParam=arena_2' },
      }),
      'arena_2'
    );
    assert.equal(
      G.readStartParam({
        location: { search: '?tgWebAppStartParam=catalog_3', hash: '' },
      }),
      'catalog_3'
    );
    assert.equal(
      G.readStartParam({
        location: { search: '?startapp=catalog', hash: '' },
      }),
      'catalog'
    );
  });
});

describe('GlideDeepLink.maybeEarlyRedirect', () => {
  const G = load();

  function memStorage() {
    const map = new Map();
    return {
      getItem(k) {
        return map.has(k) ? map.get(k) : null;
      },
      setItem(k, v) {
        map.set(k, String(v));
      },
    };
  }

  it('replace на карточку с сохранением hash', () => {
    const storage = memStorage();
    let replaced = '';
    const loc = {
      href: 'https://app.test/webapp/client-home',
      pathname: '/webapp/client-home',
      search: '',
      hash: '#tgWebAppData=abc',
      replace(u) {
        replaced = u;
      },
    };
    const ok = G.maybeEarlyRedirect({
      location: loc,
      sessionStorage: storage,
      Telegram: { WebApp: { initDataUnsafe: { start_param: 'arena_9_s_11' } } },
    });
    assert.equal(ok, true);
    assert.equal(replaced, '/webapp/arena?ref=9&s=11#tgWebAppData=abc');
    assert.equal(storage.getItem(G.DEEP_LINK_FLAG), 'arena_9_s_11');
  });

  it('не редиректит при уже использованном start_param', () => {
    const storage = memStorage();
    storage.setItem(G.DEEP_LINK_FLAG, 'arena_9');
    let replaced = '';
    const loc = {
      href: 'https://app.test/webapp/client-home',
      pathname: '/webapp/client-home',
      search: '',
      hash: '',
      replace(u) {
        replaced = u;
      },
    };
    const ok = G.maybeEarlyRedirect({
      location: loc,
      sessionStorage: storage,
      Telegram: { WebApp: { initDataUnsafe: { start_param: 'arena_9' } } },
    });
    assert.equal(ok, false);
    assert.equal(replaced, '');
  });

  it('не редиректит, если уже на целевой ice-странице', () => {
    const storage = memStorage();
    let replaced = '';
    const loc = {
      href: 'https://app.test/webapp/ice?city_id=7',
      pathname: '/webapp/ice',
      search: '?city_id=7',
      hash: '',
      replace(u) {
        replaced = u;
      },
    };
    const ok = G.maybeEarlyRedirect({
      location: loc,
      sessionStorage: storage,
      Telegram: { WebApp: { initDataUnsafe: { start_param: 'catalog_7' } } },
    });
    assert.equal(ok, false);
    assert.equal(replaced, '');
  });
});
