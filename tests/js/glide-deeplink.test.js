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
    assert.deepEqual(G.deepLinkTarget('trainer_15'), {
      key: 'catalog',
      path: 'catalog?trainer_id=15',
    });
    assert.equal(G.deepLinkTarget('nope'), null);
  });
});

describe('GlideDeepLink.readStartParam', () => {
  const G = load();

  it('trainer_ открывает карточку тренера; с катка — с возвратом на каток (TASK-265)', () => {
    assert.deepEqual(G.deepLinkTarget('trainer_7'), { key: 'catalog', path: 'catalog?trainer_id=7' });
    assert.deepEqual(G.deepLinkTarget('trainer_7_a_3'), {
      key: 'catalog',
      path: 'catalog?from=arena&trainer_id=7&arena_id=3',
    });
    assert.equal(G.deepLinkTarget('trainer_0'), null);
    assert.equal(G.deepLinkTarget('trainer_7_a_'), null);
  });

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

describe('GlideDeepLink.resolveArenaDeepLinkTarget (TASK-257)', () => {
  const G = load();

  it('без флага — arena?ref=42&s=9', async () => {
    const target = await G.resolveArenaDeepLinkTarget('arena_42_s_9', { serverPlaceCard: false });
    assert.deepEqual(target, { key: 'arena', path: 'arena?ref=42&s=9' });
  });

  it('с флагом — public_path?s=9', async () => {
    const target = await G.resolveArenaDeepLinkTarget('arena_42_s_9', {
      serverPlaceCard: true,
      fetchPublicArenaCard: async () => ({ public_path: '/p/minsk/chizhovka-arena' }),
    });
    assert.deepEqual(target, { key: 'place', path: '/p/minsk/chizhovka-arena?s=9' });
  });

  it('с флагом без public_path — fallback arena?ref=', async () => {
    const target = await G.resolveArenaDeepLinkTarget('arena_42_s_9', {
      serverPlaceCard: true,
      fetchPublicArenaCard: async () => ({}),
    });
    assert.deepEqual(target, { key: 'arena', path: 'arena?ref=42&s=9' });
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

  it('arena startapp не редиректит из head — ждёт session в shell (TASK-257)', () => {
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
    assert.equal(ok, false);
    assert.equal(replaced, '');
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
