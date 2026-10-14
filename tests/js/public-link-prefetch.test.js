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
  const sandbox = { document: dom.document, location: dom.location, URL, Set };
  sandbox.globalThis = sandbox;
  vm.runInNewContext(SRC, sandbox);
}

describe('public-link-prefetch', () => {
  it('adds one prefetch link on pointerdown for same-origin /p/', () => {
    const links = [];
    const dom = {
      location: { href: 'http://test/c/minsk', origin: 'http://test' },
      document: {
        head: { appendChild(el) { links.push(el); } },
        createElement() {
          return { rel: '', href: '' };
        },
        addEventListener(type, fn) {
          if (type === 'pointerdown') this._pd = fn;
        },
      },
    };
    runPrefetch(dom);
    const anchor = { href: 'http://test/p/minsk/chizhovka', closest(sel) {
      return sel === 'a[href]' ? this : null;
    } };
    dom.document._pd({ target: anchor });
    assert.equal(links.length, 1);
    assert.equal(links[0].rel, 'prefetch');
    assert.equal(links[0].href, '/p/minsk/chizhovka');
    dom.document._pd({ target: anchor });
    assert.equal(links.length, 1);
  });

  it('ignores external links', () => {
    const links = [];
    const dom = {
      location: { href: 'http://test/', origin: 'http://test' },
      document: {
        head: { appendChild(el) { links.push(el); } },
        addEventListener(type, fn) {
          if (type === 'pointerdown') this._pd = fn;
        },
      },
    };
    runPrefetch(dom);
    const anchor = { href: 'https://example.com/p/x', closest(sel) {
      return sel === 'a[href]' ? this : null;
    } };
    dom.document._pd({ target: anchor });
    assert.equal(links.length, 0);
  });
});
