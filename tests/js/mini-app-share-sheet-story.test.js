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
