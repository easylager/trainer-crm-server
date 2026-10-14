'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const api = require(path.resolve(
  __dirname,
  '../../static/shared/public-bfcache-session-refresh.js'
));

function htmlFetchResponse(body) {
  return {
    ok: true,
    headers: {
      get(name) {
        return name.toLowerCase() === 'content-type' ? 'text/html; charset=utf-8' : '';
      },
    },
    text: () => Promise.resolve(body),
  };
}

function makeDom(initialHtml) {
  const root = { innerHTML: initialHtml };
  return {
    document: {
      querySelector(sel) {
        if (sel === '[data-glide-session-list-root]') return root;
        return null;
      },
      getElementById() {
        return null;
      },
    },
    listRoot: root,
  };
}

describe('public-bfcache-session-refresh', () => {
  it('findSessionListRoot prefers data-glide-session-list-root', () => {
    const doc = {
      querySelector(sel) {
        return sel === '[data-glide-session-list-root]' ? { id: 'marked' } : null;
      },
      getElementById() {
        return { id: 'schedule' };
      },
    };
    assert.equal(api.findSessionListRoot(doc).id, 'marked');
  });

  it('does not fetch when pageshow is not persisted', () => {
    let fetches = 0;
    const handlers = {};
    const g = {
      document: makeDom('<old/>').document,
      location: { pathname: '/c/minsk', search: '' },
      scrollY: 0,
      scrollTo() {},
      addEventListener(type, fn) {
        handlers[type] = fn;
      },
      fetch() {
        fetches += 1;
        return Promise.resolve(htmlFetchResponse(''));
      },
      DOMParser: class {
        parseFromString() {
          return { querySelector: () => null };
        }
      },
    };
    api.wireBfCacheSessionRefresh(g, { now: () => 0 });
    handlers.pageshow({ persisted: false });
    assert.equal(fetches, 0);
  });

  it('does not fetch when page is younger than STALE_MS', () => {
    let fetches = 0;
    const handlers = {};
    const t0 = 1_000_000;
    let now = t0;
    const g = {
      document: makeDom('<old/>').document,
      location: { pathname: '/p/minsk/x', search: '' },
      scrollY: 0,
      scrollTo() {},
      addEventListener(type, fn) {
        handlers[type] = fn;
      },
      fetch() {
        fetches += 1;
        return Promise.resolve(htmlFetchResponse(''));
      },
      DOMParser: class {
        parseFromString() {
          return { querySelector: () => null };
        }
      },
    };
    api.wireBfCacheSessionRefresh(g, { now: () => now });
    now = t0 + api.STALE_MS - 1;
    handlers.pageshow({ persisted: true });
    assert.equal(fetches, 0);
  });

  it('swaps list HTML and restores scroll when stale persisted', async () => {
    const dom = makeDom('<span id="old">old</span>');
    const scrollCalls = [];
    const handlers = {};
    const t0 = 5_000_000;
    const freshHtml =
      '<div data-glide-session-list-root><span id="new">new</span></div>';
    const g = {
      document: dom.document,
      location: { pathname: '/c/minsk', search: '?t=ice' },
      scrollY: 420,
      scrollTo(x, y) {
        scrollCalls.push(y);
      },
      addEventListener(type, fn) {
        handlers[type] = fn;
      },
      fetch(url) {
        assert.equal(url, '/c/minsk?t=ice');
        return Promise.resolve(
          htmlFetchResponse(`<html><body>${freshHtml}</body></html>`)
        );
      },
      DOMParser: class {
        parseFromString(html) {
          const match = html.match(/data-glide-session-list-root[^>]*>([\s\S]*?)<\/div>/);
          const inner = match ? match[1] : '';
          return {
            querySelector(sel) {
              if (sel !== '[data-glide-session-list-root]') return null;
              return { innerHTML: inner };
            },
          };
        }
      },
    };
    let now = t0;
    api.wireBfCacheSessionRefresh(g, { now: () => now });
    now = t0 + api.STALE_MS + 1;
    handlers.pageshow({ persisted: true });
    await new Promise((r) => setTimeout(r, 0));
    assert.match(dom.listRoot.innerHTML, /id="new"/);
    assert.ok(scrollCalls.includes(420));
  });

  it('leaves DOM unchanged on fetch error', async () => {
    const dom = makeDom('<keep/>');
    const handlers = {};
    const t0 = 9_000_000;
    const g = {
      document: dom.document,
      location: { pathname: '/c/minsk', search: '' },
      scrollY: 0,
      scrollTo() {},
      addEventListener(type, fn) {
        handlers[type] = fn;
      },
      fetch() {
        return Promise.reject(new Error('network'));
      },
      DOMParser: class {
        parseFromString() {
          return { querySelector: () => ({ innerHTML: '<gone/>' }) };
        }
      },
    };
    let now = t0;
    api.wireBfCacheSessionRefresh(g, { now: () => now });
    now = t0 + api.STALE_MS + 1;
    handlers.pageshow({ persisted: true });
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(dom.listRoot.innerHTML, '<keep/>');
  });

  it('ignores non-html content-type', async () => {
    const dom = makeDom('<keep/>');
    const handlers = {};
    const t0 = 10_000_000;
    let fetches = 0;
    let now = t0;
    const g = {
      document: dom.document,
      location: { pathname: '/c/minsk', search: '' },
      scrollY: 0,
      scrollTo() {},
      addEventListener(type, fn) {
        handlers[type] = fn;
      },
      fetch() {
        fetches += 1;
        return Promise.resolve({
          ok: true,
          headers: { get: () => 'application/json' },
          text: () => Promise.resolve('{"x":1}'),
        });
      },
      DOMParser: class {
        parseFromString() {
          return { querySelector: () => ({ innerHTML: '<gone/>' }) };
        }
      },
    };
    api.wireBfCacheSessionRefresh(g, { now: () => now });
    now = t0 + api.STALE_MS + 1;
    handlers.pageshow({ persisted: true });
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(dom.listRoot.innerHTML, '<keep/>');
    assert.equal(fetches, 1);
  });

  it('resets loadedAt after successful refresh', async () => {
    const dom = makeDom('<span>v1</span>');
    const handlers = {};
    const t0 = 20_000_000;
    let fetches = 0;
    let now = t0;
    const g = {
      document: dom.document,
      location: { pathname: '/c/minsk', search: '' },
      scrollY: 0,
      scrollTo() {},
      addEventListener(type, fn) {
        handlers[type] = fn;
      },
      fetch() {
        fetches += 1;
        const body =
          '<div data-glide-session-list-root><span>v' + fetches + '</span></div>';
        return Promise.resolve(htmlFetchResponse(body));
      },
      DOMParser: class {
        parseFromString(html) {
          const match = html.match(/data-glide-session-list-root[^>]*>([\s\S]*?)<\/div>/);
          const inner = match ? match[1] : '';
          return {
            querySelector(sel) {
              if (sel !== '[data-glide-session-list-root]') return null;
              return { innerHTML: inner };
            },
          };
        }
      },
    };
    api.wireBfCacheSessionRefresh(g, { now: () => now });
    now = t0 + api.STALE_MS + 1;
    handlers.pageshow({ persisted: true });
    await new Promise((r) => setTimeout(r, 0));
    assert.match(dom.listRoot.innerHTML, /v1/);
    assert.equal(fetches, 1);

    now = t0 + api.STALE_MS + 2;
    handlers.pageshow({ persisted: true });
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(fetches, 1);
  });
});
