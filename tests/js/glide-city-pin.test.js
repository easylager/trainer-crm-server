'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const api = require(path.resolve(__dirname, '../../static/shared/glide-city-pin.js'));

function host() {
  const listeners = {};
  return {
    listeners,
    addEventListener(name, fn) {
      listeners[name] = fn;
    },
  };
}

describe('glide-city-pin', () => {
  it('posts the open city on every pageshow, including a bfcache return', async () => {
    const calls = [];
    const g = host();
    api.wireGlideCityPin(g, {
      slug: 'gomel',
      fetch(url, opts) {
        calls.push({ url, opts });
        return Promise.resolve({ ok: true });
      },
    });

    g.listeners.pageshow({ persisted: false });
    g.listeners.pageshow({ persisted: true });

    assert.equal(calls.length, 2);
    assert.equal(calls[0].url, '/api/public/glide-city');
    assert.equal(calls[0].opts.method, 'POST');
    assert.equal(calls[0].opts.credentials, 'same-origin');
    assert.deepEqual(JSON.parse(calls[0].opts.body), { slug: 'gomel' });
    assert.deepEqual(JSON.parse(calls[1].opts.body), { slug: 'gomel' });
  });

  it('does not listen when the page has no city slug', () => {
    const g = host();
    api.wireGlideCityPin(g, { slug: '', fetch() {} });
    assert.equal(g.listeners.pageshow, undefined);
  });
});
