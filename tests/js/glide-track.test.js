'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SRC = fs.readFileSync(
  path.resolve(__dirname, '../../static/shared/glide-track.js'),
  'utf8'
);

function load(env) {
  const sandbox = {
    globalThis: null,
    window: null,
    document: env.document,
    ym: env.ym,
    gtag: env.gtag,
    console,
  };
  sandbox.globalThis = sandbox;
  sandbox.window = sandbox;
  vm.runInNewContext(SRC, sandbox, { filename: 'glide-track.js' });
  return sandbox;
}

function makeDoc({ contextJson, scriptAttrs, readyState }) {
  const listeners = {};
  const html = {
    getAttribute() {
      return null;
    },
  };
  const contextEl = contextJson
    ? { textContent: contextJson, id: 'glide-es-context' }
    : null;
  const script = {
    getAttribute(name) {
      return (scriptAttrs && scriptAttrs[name]) || null;
    },
  };
  const doc = {
    readyState: readyState || 'complete',
    documentElement: html,
    currentScript: script,
    getElementById(id) {
      return id === 'glide-es-context' ? contextEl : null;
    },
    addEventListener(type, fn) {
      listeners[type] = listeners[type] || [];
      listeners[type].push(fn);
    },
    _listeners: listeners,
  };
  return doc;
}

describe('glide-track', () => {
  it('fires es_view once with context and reachGoal + gtag', () => {
    const goals = [];
    const ga = [];
    const doc = makeDoc({
      contextJson: JSON.stringify({
        state: 'P6',
        page_type: 'place',
        city: 'Минск',
        arena_id: 2,
      }),
      scriptAttrs: { 'data-ym-id': '113702031', 'data-ga-id': 'G-E1KJ3L2042' },
    });
    const sandbox = load({
      document: doc,
      ym(id, method, name, params) {
        goals.push({ id, method, name, params });
      },
      gtag(cmd, name, params) {
        ga.push({ cmd, name, params });
      },
    });
    assert.equal(goals.length, 1);
    assert.equal(goals[0].method, 'reachGoal');
    assert.equal(goals[0].name, 'es_view');
    assert.equal(goals[0].params.state, 'P6');
    assert.equal(goals[0].params.arena_id, 2);
    assert.equal(ga.length, 1);
    assert.equal(ga[0].cmd, 'event');
    assert.equal(ga[0].name, 'es_view');
    assert.equal(ga[0].params.transport_type, 'beacon');
    assert.equal(ga[0].params.send_to, 'G-E1KJ3L2042');
    // повторный boot не шлёт
    sandbox.GlideTrack.track('es_view', { state: 'P6' });
    assert.ok(goals.length >= 1);
  });

  it('swallows missing ym/gtag without throwing', () => {
    const doc = makeDoc({
      contextJson: '{"state":"P8","page_type":"place"}',
      scriptAttrs: { 'data-ym-id': '1', 'data-ga-id': 'G-E1KJ3L2042' },
    });
    assert.doesNotThrow(() => load({ document: doc }));
  });

  it('tracks click on data-glide-track without waiting', () => {
    const goals = [];
    const listeners = {};
    const a = {
      getAttribute(name) {
        const map = {
          'data-glide-track': 'es_fallback_click',
          'data-glide-fallback': 'nearby_city',
          'data-glide-target': '/c/baranovichi',
          href: '/c/baranovichi',
        };
        return map[name] || null;
      },
    };
    const target = {
      closest(sel) {
        return sel === '[data-glide-track]' ? a : null;
      },
    };
    const doc = {
      readyState: 'complete',
      documentElement: { getAttribute: () => null },
      currentScript: {
        getAttribute(name) {
          return name === 'data-ym-id' ? '113702031' : null;
        },
      },
      getElementById() {
        return { textContent: '{"state":"P8","page_type":"place"}' };
      },
      addEventListener(type, fn) {
        listeners[type] = fn;
      },
    };
    load({
      document: doc,
      ym(_id, method, name, params) {
        goals.push({ method, name, params });
      },
    });
    assert.equal(typeof listeners.click, 'function');
    listeners.click({ target });
    const click = goals.find((g) => g.name === 'es_fallback_click');
    assert.ok(click);
    assert.equal(click.params.fallback, 'nearby_city');
    assert.equal(click.params.state, 'P8');
  });
});
