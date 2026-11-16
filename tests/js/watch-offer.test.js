/**
 * TASK-428 (слой A): предложение подписки на каток — один раз на человека и каток, не подписанным,
 * только после содержательного просмотра и только с явного «да» сервера.
 *
 * Run: TZ=UTC node --test tests/js/watch-offer.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const W = require('../../static/webapp/watch-offer.js');
const COPY = require('../../src/shared/copy_ru.json');

function memStorage(init) {
  const data = Object.assign({}, init || {});
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => {
      data[k] = String(v);
    },
  };
}

/** Сценарий без DOM и таймеров: wait резолвится сразу, видимость и ответы сервера — из opts. */
function deps(opts) {
  opts = opts || {};
  const log = { records: [], rendered: 0, removed: 0, done: 0, waits: [], fetched: 0 };
  let handlers = null;
  const d = {
    arenaId: opts.arenaId === undefined ? 42 : opts.arenaId,
    hasSkating: opts.hasSkating === undefined ? true : opts.hasSkating,
    subscribed: () => (typeof opts.subscribed === 'function' ? opts.subscribed() : !!opts.subscribed),
    storage: opts.storage || memStorage(),
    fetchState: () => {
      log.fetched += 1;
      if (opts.fetchFails) return Promise.reject(new Error('net'));
      return Promise.resolve(opts.server === undefined ? { show: true } : opts.server);
    },
    record: (a) => log.records.push(a),
    render: (h) => {
      log.rendered += 1;
      handlers = h;
      return {
        done: () => {
          log.done += 1;
        },
        remove: () => {
          log.removed += 1;
        },
      };
    },
    subscribe: opts.subscribe === undefined ? () => Promise.resolve(true) : opts.subscribe,
    wait: (ms) => {
      log.waits.push(ms);
      return Promise.resolve();
    },
    visible: opts.visible || (() => true),
  };
  return { d, log, handlers: () => handlers };
}

describe('watch offer: when to show', () => {
  it('shows once after dwell, marks seen and records shown', async () => {
    const storage = memStorage();
    const { d, log } = deps({ storage });
    assert.equal(await W.start(d), 'shown');
    assert.deepEqual(log.records, ['shown']);
    assert.equal(log.waits[0], W.DWELL_MS);
    assert.equal(storage.getItem(W.storageKey(42)), '1');
    // второй раз в этом браузере — даже не спрашиваем сервер
    const again = deps({ storage });
    assert.equal(await W.start(again.d), 'skip');
    assert.equal(again.log.fetched, 0);
  });

  it('never shows to a subscriber, before or after dwell', async () => {
    const a = deps({ subscribed: true });
    assert.equal(await W.start(a.d), 'skip');
    assert.equal(a.log.fetched, 0);
    let sub = false;
    const b = deps({
      subscribed: () => sub,
      server: { show: true },
    });
    b.d.wait = () => {
      sub = true; // подписался колокольчиком, пока шёл таймер
      return Promise.resolve();
    };
    assert.equal(await W.start(b.d), 'skip');
    assert.equal(b.log.rendered, 0);
  });

  it('server says no (already shown elsewhere) — remembered locally, nothing shown', async () => {
    const storage = memStorage();
    const { d, log } = deps({ storage, server: { show: false } });
    assert.equal(await W.start(d), 'server_no');
    assert.equal(log.rendered, 0);
    assert.equal(storage.getItem(W.storageKey(42)), '1');
  });

  it('fails closed on network error or odd answer', async () => {
    for (const opts of [{ fetchFails: true }, { server: null }, { server: { show: 'yes' } }, { server: {} }]) {
      const { d, log } = deps(opts);
      assert.equal(await W.start(d), 'server_no');
      assert.equal(log.rendered, 0);
    }
  });

  it('no skating or bad arena — skip', async () => {
    for (const opts of [{ hasSkating: false }, { arenaId: 0 }, { arenaId: -1 }, { arenaId: 'x' }, { arenaId: 1.5 }]) {
      const { d, log } = deps(opts);
      assert.equal(await W.start(d), 'skip');
      assert.equal(log.fetched, 0);
    }
  });

  it('hidden page does not count; gives up after the limit', async () => {
    let checks = 0;
    const visibleLater = deps({ visible: () => ++checks > 3 });
    assert.equal(await W.start(visibleLater.d), 'shown');
    const neverVisible = deps({ visible: () => false });
    assert.equal(await W.start(neverVisible.d), 'skip');
    assert.equal(neverVisible.log.rendered, 0);
  });

  it('storage that throws (private mode) does not break, server still guards', async () => {
    const broken = {
      getItem() {
        throw new Error('denied');
      },
      setItem() {
        throw new Error('denied');
      },
    };
    const { d } = deps({ storage: broken });
    assert.equal(await W.start(d), 'shown');
  });

  it('pure model', () => {
    const base = { arenaId: 7, hasSkating: true, subscribed: false, seenLocal: false, serverShow: true };
    assert.equal(W.shouldShow(Object.assign({ dwellMs: W.DWELL_MS }, base)), true);
    assert.equal(W.shouldShow(Object.assign({ dwellMs: W.DWELL_MS - 1 }, base)), false);
    assert.equal(W.shouldShow(Object.assign({}, base, { dwellMs: W.DWELL_MS, seenLocal: true })), false);
    assert.equal(W.shouldShow(Object.assign({}, base, { dwellMs: W.DWELL_MS, serverShow: undefined })), false);
  });
});

describe('watch offer: actions', () => {
  it('Mini App: click subscribes, shows done, then hides; funnel shown → click', async () => {
    const { d, log, handlers } = deps();
    await W.start(d);
    handlers().onCta();
    await new Promise((r) => setImmediate(r));
    assert.deepEqual(log.records, ['shown', 'click']);
    assert.equal(log.done, 1);
    assert.equal(log.removed, 1);
  });

  it('Mini App: refused write access — panel just goes away', async () => {
    const { d, log, handlers } = deps({ subscribe: () => Promise.resolve(false) });
    await W.start(d);
    handlers().onCta();
    await new Promise((r) => setImmediate(r));
    assert.equal(log.done, 0);
    assert.equal(log.removed, 1);
  });

  it('close records closed and removes; site click only records (link leaves the page)', async () => {
    const a = deps();
    await W.start(a.d);
    a.handlers().onClose();
    assert.deepEqual(a.log.records, ['shown', 'closed']);
    assert.equal(a.log.removed, 1);
    const site = deps({ subscribe: null });
    await W.start(site.d);
    site.handlers().onCta();
    assert.deepEqual(site.log.records, ['shown', 'click']);
    assert.equal(site.log.removed, 0);
  });
});

describe('watch offer: texts', () => {
  it('fallback copy equals copy_ru.json (site loads no glide-copy.js)', () => {
    const keys = Object.keys(COPY).filter((k) => k.startsWith('watch_offer.'));
    assert.ok(keys.length >= 6);
    assert.deepEqual(Object.keys(W.FALLBACK).sort(), keys.sort());
    for (const key of keys) assert.equal(W.FALLBACK[key], COPY[key], key);
  });
});
