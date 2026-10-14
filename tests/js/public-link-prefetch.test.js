'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SRC = fs.readFileSync(
  path.resolve(__dirname, '../../static/shared/public-link-prefetch.js'),
  'utf8'
);

function runPrefetch(dom) {
  const sandbox = {
    document: dom.document,
    location: dom.location,
    navigator: dom.navigator || {},
    URL,
    Set,
    setTimeout,
    clearTimeout,
  };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(SRC, sandbox);
  return sandbox;
}

function baseDom() {
  const links = [];
  return {
    links,
    location: { href: 'http://test/c/minsk', origin: 'http://test' },
    navigator: { connection: {} },
    document: {
      head: { appendChild(el) { links.push(el); } },
      createElement() {
        return { rel: '', href: '' };
      },
      _handlers: {},
      addEventListener(type, fn) {
        this._handlers[type] = fn;
      },
    },
  };
}

describe('public-link-prefetch', () => {
  it('touch pointerdown prefetches same-origin /p/ HTML', () => {
    const dom = baseDom();
    const sandbox = runPrefetch(dom);
    const anchor = {
      href: 'http://test/p/minsk/chizhovka-arena',
      hasAttribute() {
        return false;
      },
      closest(sel) {
        return sel === 'a[href]' ? this : null;
      },
    };
    sandbox.document._handlers.pointerdown({ pointerType: 'touch', target: anchor });
    assert.equal(dom.links.length, 1);
    assert.equal(dom.links[0].rel, 'prefetch');
    assert.equal(dom.links[0].href, '/p/minsk/chizhovka-arena');
  });

  it('mouse hover after 65ms prefetches /c/ list', async () => {
    const dom = baseDom();
    runPrefetch(dom);
    const anchor = {
      href: 'http://test/c/minsk?t=ice',
      hasAttribute() {
        return false;
      },
      closest(sel) {
        return sel === 'a[href]' ? this : null;
      },
    };
    dom.document._handlers.pointerenter({ pointerType: 'mouse', target: anchor });
    assert.equal(dom.links.length, 0);
    await new Promise((r) => setTimeout(r, 70));
    assert.equal(dom.links.length, 1);
    assert.equal(dom.links[0].href, '/c/minsk?t=ice');
  });

  it('skips og.png, download, and Save-Data', () => {
    const dom = baseDom();
    dom.navigator.connection = { saveData: true };
    const sandbox = runPrefetch(dom);
    const og = {
      href: 'http://test/p/minsk/x/og.png',
      hasAttribute() {
        return false;
      },
      closest(sel) {
        return sel === 'a[href]' ? this : null;
      },
    };
    sandbox.document._handlers.pointerdown({ pointerType: 'touch', target: og });
    assert.equal(dom.links.length, 0);

    dom.navigator.connection = { effectiveType: '2g' };
    const sandbox2 = runPrefetch(dom);
    sandbox2.document._handlers.pointerdown({ pointerType: 'touch', target: og });
    assert.equal(dom.links.length, 0);

    dom.navigator.connection = {};
    const dom2 = baseDom();
    runPrefetch(dom2);
    const dl = {
      href: 'http://test/p/minsk/x',
      hasAttribute(n) {
        return n === 'download';
      },
      closest(sel) {
        return sel === 'a[href]' ? this : null;
      },
    };
    dom2.document._handlers.pointerdown({ pointerType: 'touch', target: dl });
    assert.equal(dom2.links.length, 0);
  });
});
