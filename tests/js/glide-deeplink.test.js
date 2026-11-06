/**
 * TASK-223: ранний redirect и парсер start_param (glide-deeplink.js).
 * Run: node --test tests/js/glide-deeplink.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
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

  it('catalog_* с главной сразу уходит на ice, не дожидаясь body', () => {
    const storage = memStorage();
    let replaced = '';
    const loc = {
      href: 'https://app.test/webapp/client-home#tgWebAppStartParam=catalog_7',
      pathname: '/webapp/client-home',
      search: '',
      hash: '#tgWebAppStartParam=catalog_7',
      replace(u) {
        replaced = u;
      },
    };
    const ok = G.maybeEarlyRedirect({
      location: loc,
      sessionStorage: storage,
      Telegram: { WebApp: { initDataUnsafe: { start_param: 'catalog_7' } } },
    });
    assert.equal(ok, true);
    assert.equal(replaced, '/webapp/ice?city_id=7#tgWebAppStartParam=catalog_7');
    assert.equal(storage.getItem(G.DEEP_LINK_FLAG), 'catalog_7');
  });
});

describe('client-home подключает early redirect до body', () => {
  const html = fs.readFileSync(path.join(webapp, 'client-home.html'), 'utf8');
  const head = html.slice(0, html.indexOf('</head>'));

  it('glide-deeplink.js синхронно после Telegram SDK, без defer', () => {
    assert.match(head, /<script src="glide-deeplink\.js\?v=[^"]+"><\/script>/);
    assert.doesNotMatch(head, /<script defer[^>]*glide-deeplink/);
    const tg = head.indexOf('telegram-web-app.js');
    const dl = head.indexOf('glide-deeplink.js');
    const bodyTag = html.indexOf('<body');
    assert.ok(tg >= 0 && dl > tg, 'redirect читает start_param из уже загруженного SDK');
    assert.ok(dl < bodyTag, 'уходим до разбора главной');
  });
});

describe('«Кто кого» из сообщений бота (TASK-335)', () => {
  const G = require('../../static/webapp/glide-deeplink.js');
  it('ход за сторону, матчи, итоги месяца, выключить напоминания', () => {
    assert.deepEqual(G.deepLinkTarget('kkn_42_h'), { key: 'kto-kogo', path: 'kto-kogo?pick=42&side=home' });
    assert.deepEqual(G.deepLinkTarget('kkn_42_a'), { key: 'kto-kogo', path: 'kto-kogo?pick=42&side=away' });
    assert.deepEqual(G.deepLinkTarget('kkn_42'), { key: 'kto-kogo', path: 'kto-kogo' });
    assert.deepEqual(G.deepLinkTarget('kkmo_7'), { key: 'kto-kogo', path: 'kto-kogo?month=7' });
    assert.deepEqual(G.deepLinkTarget('kkoff'), { key: 'kto-kogo', path: 'kto-kogo?remind=off' });
    assert.deepEqual(G.deepLinkTarget('kkm_5'), { key: 'client-match', path: 'client-match?id=5' });
  });
});

describe('Mini App public URL recovery', () => {
  const G = load();

  function browser(url, { initData = 'signed', startParam = '', arenaId = '31', cityId = '18', storage = new Map() } = {}) {
    let current = new URL(url);
    const entries = [current.href];
    let index = 0;
    const loc = {
      get href() { return current.href; },
      set href(value) {
        current = new URL(value, current);
        entries.splice(++index, entries.length, current.href);
      },
      get pathname() { return current.pathname; },
      get search() { return current.search; },
      get hash() { return current.hash; },
      replace(value) {
        current = new URL(value, current);
        entries[index] = current.href;
      },
    };
    const history = {
      get length() { return entries.length; },
      back() { if (index > 0) current = new URL(entries[--index]); },
    };
    return {
      location: loc, history, entries,
      sessionStorage: { getItem: (key) => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) },
      Telegram: { WebApp: { initData, initDataUnsafe: { start_param: startParam } } },
      document: {
        querySelector(selector) {
          const id = selector.includes('arena') ? arenaId : cityId;
          return id ? { getAttribute() { return id; } } : null;
        },
      },
    };
  }

  it('resolves webapp paths under /webapp even when launched on / or /p/', () => {
    for (const url of ['https://app.test/', 'https://app.test/p/orsha/orsha-arena']) {
      assert.equal(G.resolveWebappPath('client-match?id=5', { href: url }), '/webapp/client-match?id=5');
    }
  });

  it('launch on / replaces / and arena Back returns to the Mini App home', () => {
    const ctx = browser('https://app.test/#tgWebAppData=signed');
    assert.equal(G.maybePublicRedirect(ctx), true);
    assert.equal(ctx.location.pathname, '/webapp/client-home');
    assert.equal(ctx.history.length, 1);
    ctx.location.href = '/webapp/arena?ref=31';
    ctx.history.back();
    assert.equal(ctx.location.pathname, '/webapp/client-home');
    assert.ok(ctx.entries.every((url) => new URL(url).pathname !== '/'));
  });

  it('public entry preserves kkm_, arena_ session and catalog_ startapp targets', () => {
    for (const [sp, target] of [
      ['kkm_5_ABCD', '/webapp/client-match?id=5&c=ABCD'],
      ['arena_31_s_99', '/webapp/arena?ref=31&s=99'],
      ['catalog_18_skate_tomorrow', '/webapp/ice?city_id=18&intent=skate&when=tomorrow'],
    ]) {
      const ctx = browser('https://app.test/#tgWebAppData=signed', { startParam: sp });
      assert.equal(G.maybePublicRedirect(ctx), true);
      assert.equal(ctx.location.pathname + ctx.location.search, target);
      assert.equal(ctx.location.hash, '#tgWebAppData=signed');
      assert.equal(ctx.history.length, 1);
      assert.equal(ctx.sessionStorage.getItem(G.DEEP_LINK_FLAG), sp);
    }
  });

  it('recovers /p/, /c/ and /m/ to the corresponding screen and keeps context', () => {
    for (const [url, target] of [
      ['/p/orsha/orsha-arena?s=99&init_data=signed', '/webapp/arena?ref=31&s=99&init_data=signed'],
      ['/c/orsha?when=tomorrow&init_data=signed', '/webapp/ice?city_id=18&when=tomorrow&init_data=signed'],
      ['/m/5-dinamo?c=ABCD&init_data=signed', '/webapp/client-match?id=5&c=ABCD&init_data=signed'],
    ]) {
      const ctx = browser('https://app.test' + url, { initData: '' });
      assert.equal(G.maybePublicRedirect(ctx), true);
      assert.equal(ctx.location.pathname + ctx.location.search, target);
      assert.equal(ctx.history.length, 1);
    }
  });

  it('used startapp cannot hijack recovery after Back to public /', () => {
    const storage = new Map([[G.DEEP_LINK_FLAG, 'arena_31'], ['glide_mini_app_active_v1', '1']]);
    const ctx = browser('https://app.test/', { storage, initData: '', startParam: 'arena_31' });
    assert.equal(G.maybePublicRedirect(ctx), true);
    assert.equal(ctx.location.pathname, '/webapp/client-home');
  });

  it('ordinary browser including empty Telegram SDK and startapp query stays public', () => {
    for (const url of ['/', '/?startapp=kkm_5', '/p/orsha/orsha-arena', '/c/orsha', '/m/5-dinamo']) {
      const ctx = browser('https://app.test' + url, { initData: '' });
      assert.equal(G.maybePublicRedirect(ctx), false);
      assert.equal(ctx.location.href, 'https://app.test' + url);
    }
  });

  it('does not redirect /webapp or guess arena/city IDs when SSR metadata is missing', () => {
    for (const url of ['/webapp/client-home', '/webapp/arena?ref=31', '/p/orsha/unknown', '/c/unknown']) {
      const ctx = browser('https://app.test' + url, { arenaId: '', cityId: '' });
      assert.equal(G.maybePublicRedirect(ctx), false);
    }
  });

  it('recovers /hockey to the Mini App matches catalog without the site city slug', () => {
    for (const [url, target] of [
      ['/hockey', '/webapp/client-matches'],
      ['/hockey?city=orsha', '/webapp/client-matches'],
      ['/hockey?club=lokomotiv-orsha&init_data=signed', '/webapp/client-matches?team=lokomotiv-orsha&init_data=signed'],
    ]) {
      const ctx = browser('https://app.test' + url, { initData: url.includes('init_data') ? '' : 'signed' });
      assert.equal(G.maybePublicRedirect(ctx), true);
      assert.equal(ctx.location.pathname + ctx.location.search, url.includes('init_data') ? target : target + (target.includes('?') ? '&' : '?') + 'init_data=signed');
      assert.equal(ctx.history.length, 1);
    }
  });

  it('ordinary browser keeps /hockey public', () => {
    const ctx = browser('https://app.test/hockey?city=orsha', { initData: '' });
    assert.equal(G.maybePublicRedirect(ctx), false);
    assert.equal(ctx.location.pathname, '/hockey');
  });

  it('public home and shared place/city/match template wire recovery', () => {
    for (const file of ['catalog-home.html', 'b.html']) {
      const html = fs.readFileSync(path.join(webapp, '../share', file), 'utf8');
      assert.match(html.slice(0, html.indexOf('</head>')), /src="\/static\/webapp\/glide-deeplink\.js\?v=/);
    }
  });
});
