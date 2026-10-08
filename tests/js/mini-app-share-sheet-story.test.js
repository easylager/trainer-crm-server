/**
 * TASK-168: сторис из GlideShareSheet — shareToStory, Web Share, telemetry channels.
 * Run: node --test tests/js/mini-app-share-sheet-story.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const jsPath = path.resolve(__dirname, '../../static/webapp/mini-app-share-sheet.js');
const src = fs.readFileSync(jsPath, 'utf8');

describe('mini-app-share-sheet story channel (TASK-168)', () => {
  it('предпочитает shareToStory перед downloadFile', () => {
    const shareIdx = src.indexOf('shareToStory');
    const dlIdx = src.indexOf('downloadFile');
    assert.ok(shareIdx > -1, 'shareToStory');
    assert.ok(dlIdx > -1, 'downloadFile fallback');
    assert.ok(shareIdx < dlIdx, 'shareToStory должен идти раньше downloadFile в файле');
  });

  it('пишет отдельные каналы telemetry для сторис', () => {
    assert.match(src, /story_tg/);
    assert.match(src, /story_os/);
    assert.match(src, /story_fallback/);
    assert.match(src, />Сторис</);
    assert.match(src, />В галерею</);
    assert.match(src, /openImageSave/);
    assert.match(src, /image_tg/);
  });

  it('подборка города показывает превью чат + сторис', () => {
    assert.match(src, /gss-preview-duo/);
    assert.match(src, /gss-preview__img--story/);
  });

  it('openStoryShare вызывает shareToStory при наличии API', async () => {
    const calls = [];
    const context = {
      window: {},
      document: {
        createElement: () => ({
          hidden: true,
          className: '',
          innerHTML: '',
          addEventListener: () => {},
        }),
        body: { appendChild: () => {} },
      },
      fetch: () => Promise.reject(new Error('no fetch')),
      location: { href: 'https://app.test/webapp/catalog' },
      navigator: {},
      Telegram: {
        WebApp: {
          isVersionAtLeast: () => true,
          shareToStory: (url, params) => {
            calls.push({ url, params });
          },
        },
      },
      requestAnimationFrame: (fn) => fn(),
      setTimeout: (fn) => fn(),
      clearTimeout: () => {},
    };
    context.window = context;
    vm.runInNewContext(src, context);
    const channel = await context.GlideShareSheet._openStoryShare({
      story_image_url: 'https://cdn.test/p/minsk/x/story.png',
      share_url: 'https://cdn.test/p/minsk/x',
      share_body: 'Пт 20:30',
    });
    assert.equal(channel, 'story_tg');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, 'https://cdn.test/p/minsk/x/story.png');
    assert.equal(calls[0].params.widget_link.url, 'https://cdn.test/p/minsk/x');
    assert.equal(calls[0].params.widget_link.name, 'Карта льда');
    // TASK-222: сторис — без подписи. Свой текст уже нарисован в кадре.
    assert.equal(Object.prototype.hasOwnProperty.call(calls[0].params, 'text'), false);
  });

  it('openImageSave вызывает downloadFile в Telegram', async () => {
    const downloads = [];
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
      location: { href: 'https://app.test/webapp/catalog' },
      navigator: {},
      Telegram: {
        WebApp: {
          isVersionAtLeast: () => true,
          downloadFile: (opts) => {
            downloads.push(opts);
          },
        },
      },
      requestAnimationFrame: (fn) => fn(),
      setTimeout: (fn) => fn(),
      clearTimeout: () => {},
    };
    context.window = context;
    vm.runInNewContext(src, context);
    const channel = await context.GlideShareSheet._openImageSave({
      story_image_url: 'https://cdn.test/p/minsk/x/story.png',
      og_image_url: 'https://cdn.test/p/minsk/x/og.png',
      share_url: 'https://cdn.test/p/minsk/x',
    });
    assert.equal(channel, 'image_tg');
    assert.equal(downloads.length, 1);
    assert.equal(downloads[0].file_name, 'glide-story.png');
    assert.equal(downloads[0].url, 'https://cdn.test/p/minsk/x/story.png');
  });
});

describe('mini-app-share-sheet telegram (TASK-217)', () => {
  it('подборка уходит в Telegram только ссылкой, место — со текстом', () => {
    const context = { window: {}, document: {}, navigator: {} };
    context.window = context;
    vm.runInNewContext(src, context);
    const href = context.GlideShareSheet._telegramShareHref;
    const selection = href('https://glide.test/c/minsk', 'Минск · все места\n12 катков\n• CCMshop', true);
    assert.equal(selection, 'https://t.me/share/url?url=' + encodeURIComponent('https://glide.test/c/minsk'));
    assert.equal(selection.includes('text='), false);
    const place = href('https://glide.test/p/minsk/ledovy', 'Пт 20:30', false);
    assert.match(place, /[?&]text=/);
    assert.match(place, /20%3A30|20:30/);
  });
});

/**
 * TASK-222: реальный путь канала — открыть шит, дождаться payload, нажать «Telegram».
 * Не тестовый хелпер, а тот же CHANNELS.telegram, что работает в бою.
 */
function openSheet({ endpoint, ref, payload, miniAppHandles }) {
  const calls = { miniApp: [], opened: [], fetches: [] };
  const handlers = {};
  const element = () => ({
    className: '',
    hidden: true,
    innerHTML: '',
    style: {},
    classList: { add: () => {}, remove: () => {} },
    addEventListener: (type, fn) => {
      handlers[type] = fn;
    },
    querySelector: () => element(),
    appendChild: () => {},
    getAttribute: () => null,
    setAttribute: () => {},
    blur: () => {},
  });
  const context = {
    document: {
      createElement: () => element(),
      body: { appendChild: () => {} },
      querySelector: () => element(),
    },
    location: { href: 'https://app.test/webapp/ice' },
    navigator: {},
    fetch: (url) => {
      calls.fetches.push(String(url));
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) });
    },
    open: (url) => {
      calls.opened.push(url);
    },
    openTelegramShareUrlFromMiniApp: (opts) => {
      calls.miniApp.push(opts);
      return !!miniAppHandles;
    },
    requestAnimationFrame: (fn) => fn(),
    setTimeout: (fn) => fn(),
    clearTimeout: () => {},
  };
  context.window = context;
  vm.runInNewContext(src, context);
  context.GlideShareSheet.open(endpoint ? { endpoint, context: 'ice_list' } : { ref });
  return {
    calls,
    press: (channel) =>
      handlers.click({
        target: {
          closest: (sel) => (sel === '[data-ch]' ? { getAttribute: () => channel } : null),
        },
      }),
  };
}

async function settle() {
  for (let i = 0; i < 4; i += 1) await new Promise((resolve) => setImmediate(resolve));
}

describe('mini-app-share-sheet telegram selection (TASK-222)', () => {
  const selectionPayload = {
    share_url: 'https://glide.test/c/minsk',
    share_body: 'Минск · все места\n15 катков · 10 сеансов',
  };

  it('подборка: Mini App-путь уходит без текста', async () => {
    const sheet = openSheet({
      endpoint: '/api/public/ice/selection/share',
      payload: selectionPayload,
      miniAppHandles: true,
    });
    await settle();
    sheet.press('telegram');
    assert.equal(sheet.calls.miniApp.length, 1);
    assert.equal(sheet.calls.miniApp[0].shareUrl, 'https://glide.test/c/minsk');
    assert.equal(sheet.calls.miniApp[0].shareBody, '');
    assert.equal(sheet.calls.opened.length, 0, 'Mini App-путь открылся — фоллбэк не нужен');
  });

  it('подборка: t.me/share/url тоже без text=', async () => {
    const sheet = openSheet({
      endpoint: '/api/public/ice/selection/share',
      payload: selectionPayload,
      miniAppHandles: false,
    });
    await settle();
    sheet.press('telegram');
    assert.equal(sheet.calls.miniApp[0].shareBody, '');
    assert.equal(sheet.calls.opened.length, 1);
    assert.match(sheet.calls.opened[0], /url=/);
    assert.equal(sheet.calls.opened[0].includes('text='), false);
  });

  it('место: Telegram текст сохраняет', async () => {
    const placePayload = { share_url: 'https://glide.test/p/minsk/ledovy', share_body: 'Пт 20:30' };
    const sheet = openSheet({ ref: 7, payload: placePayload, miniAppHandles: false });
    await settle();
    sheet.press('telegram');
    assert.equal(sheet.calls.miniApp[0].shareBody, 'Пт 20:30');
    assert.match(sheet.calls.opened[0], /[?&]text=/);
  });

  it('у подборки нет figcaption, у места он остаётся', () => {
    const context = {
      window: {},
      document: {},
      location: { href: 'https://app.test/webapp/ice' },
    };
    context.window = context;
    vm.runInNewContext(src, context);
    const selection = context.GlideShareSheet._previewFigureHtml(
      {
        share_body: 'простыня текста',
        og_image_url: 'https://cdn.test/c/minsk/og.png',
        story_image_url: 'https://cdn.test/c/minsk/story.png',
      },
      true,
    );
    assert.equal(selection.includes('figcaption'), false);
    assert.match(selection, /gss-preview-duo/);
    assert.match(selection, /c\/minsk\/og\.png/);
    assert.match(selection, /c\/minsk\/story\.png/);
    const place = context.GlideShareSheet._previewFigureHtml(
      {
        share_body: 'Пт 20:30',
        og_image_url: 'https://cdn.test/p/minsk/x/og.png',
      },
      false,
    );
    assert.match(place, /<figcaption>Пт 20:30<\/figcaption>/);
  });
});

describe('mini-app-share-sheet story without caption (TASK-222)', () => {
  it('подборка: сторис уходит отрендеренным story.png без text', async () => {
    const calls = [];
    const context = {
      window: {},
      document: {},
      location: { href: 'https://app.test/webapp/ice' },
      fetch: () => Promise.reject(new Error('no fetch')),
      Telegram: {
        WebApp: {
          isVersionAtLeast: () => true,
          shareToStory: (url, params) => {
            calls.push({ url, params });
          },
        },
      },
      navigator: {},
      setTimeout: (fn) => fn(),
      clearTimeout: () => {},
    };
    context.window = context;
    vm.runInNewContext(src, context);
    const channel = await context.GlideShareSheet._openStoryShare({
      story_image_url: 'https://cdn.test/c/minsk/story.png?v=abc',
      og_image_url: 'https://cdn.test/c/minsk/og.png?v=abc',
      share_url: 'https://glide.test/c/minsk',
      share_body: 'простыня',
    });
    assert.equal(channel, 'story_tg');
    assert.equal(calls[0].url, 'https://cdn.test/c/minsk/story.png?v=abc');
    assert.equal(Object.prototype.hasOwnProperty.call(calls[0].params, 'text'), false);
    assert.equal(calls[0].params.widget_link.url, 'https://glide.test/c/minsk');
  });

  it('фоллбэк Web Share отдаёт только файл', async () => {
    const shares = [];
    const context = {
      window: {},
      document: {},
      location: { href: 'https://app.test/webapp/ice' },
      fetch: () =>
        Promise.resolve({
          ok: true,
          blob: () => Promise.resolve(new Uint8Array([1, 2, 3])),
        }),
      File: function File(_bits, name, opts) {
        this.name = name;
        this.type = opts && opts.type;
      },
      navigator: {
        share: (payload) => {
          shares.push(payload);
          return Promise.resolve();
        },
        canShare: () => true,
      },
      setTimeout: (fn) => fn(),
      clearTimeout: () => {},
    };
    context.window = context;
    vm.runInNewContext(src, context);
    const channel = await context.GlideShareSheet._openStoryShare({
      story_image_url: 'https://cdn.test/c/minsk/story.png',
      share_url: 'https://cdn.test/c/minsk',
      share_body: 'Минск · все места',
    });
    assert.equal(channel, 'story_os');
    assert.equal(shares.length, 1);
    assert.deepEqual(Object.keys(shares[0]), ['files']);
    assert.equal(shares[0].text, undefined);
  });
});
