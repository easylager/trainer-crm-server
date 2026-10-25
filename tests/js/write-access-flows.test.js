/**
 * «Сообщить, когда появятся слоты» и подписка на каток: подписка сохраняется только когда
 * боту разрешено писать. Функции UI лежат внутри больших IIFE, поэтому их исходники
 * вырезаются из файлов и выполняются в vm с моками (Telegram, fetch, toast).
 * Нативный диалог Telegram не воспроизводится.
 *
 * Run: node --test tests/js/write-access-flows.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const read = (f) => fs.readFileSync(path.join(webapp, f), 'utf8');
const waSource = read('write-access.js');

async function flush() {
  for (let i = 0; i < 40; i += 1) await Promise.resolve();
}

function makeTg(o) {
  const tg = {
    initData: o.noInitData ? '' : 'x',
    initDataUnsafe: { user: Object.assign({ id: 5 }, o.user || {}) },
    requests: 0,
    alerts: [],
    popups: [],
    opened: [],
    isVersionAtLeast: () => true,
    showAlert(t, cb) {
      tg.alerts.push(t);
      if (cb) cb();
    },
    showPopup(p, cb) {
      tg.popups.push(p);
      cb(o.tap || null);
    },
    openTelegramLink(u) {
      tg.opened.push(u);
    },
  };
  if (!o.noMethod) {
    tg.requestWriteAccess = (cb) => {
      tg.requests += 1;
      if (o.throws) throw new Error('boom');
      cb(o.answer === undefined ? true : o.answer);
    };
  }
  return tg;
}

function makeFetch(calls) {
  return (url, init) => {
    calls.push({ url, method: init && init.method, body: init && init.body ? JSON.parse(init.body) : null });
    const isOutcome = String(url).includes('/write-access/outcome');
    return Promise.resolve({
      ok: true,
      json: () =>
        Promise.resolve(
          isOutcome
            ? { ok: true, bot_link: 'https://t.me/glide_bot' }
            : { edge: { notify_when_slots: true }, watch: { id: 1 } }
        ),
    });
  };
}

const subscribed = (calls) => calls.filter((c) => /notify-slots|ice-watches/.test(c.url) && c.method === 'POST');

function sliceBetween(src, startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  const b = src.indexOf(endMarker, a);
  assert.ok(a >= 0 && b > a, 'не найден фрагмент ' + startMarker);
  return src.slice(a, b);
}

/* --- catalog-main.js: toggleNotifySlots --------------------------------------------- */

function bootCatalog(tgOpts) {
  const calls = [];
  const toasts = [];
  const tg = makeTg(tgOpts);
  const win = { Telegram: { WebApp: tg } };
  win.window = win;
  const fn = sliceBetween(
    read('catalog-main.js'),
    'function toggleNotifySlots(trainerId) {',
    '/**\n       * Client→friend trainer recommendation'
  );
  const apply = fn.slice(fn.indexOf('function applyNotifySlots'));
  assert.ok(apply.includes("'/api/webapp/client/trainer-edges/notify-slots'"));
  const ctx = vm.createContext({
    window: win,
    tg,
    fetch: makeFetch(calls),
    Promise,
    JSON,
    Object,
    state: { trainerEdges: {} },
    showToast: (t) => toasts.push(t),
    _updateNotifyChipUI() {},
  });
  vm.runInContext(fn + '\nthis.toggle = toggleNotifySlots;', ctx);
  vm.runInContext(waSource, ctx);
  win.fetch = ctx.fetch;
  return { toggle: ctx.toggle, calls, toasts, tg, state: ctx.state };
}

describe('catalog: уведомить о слотах тренера', () => {
  it('разрешение есть -> подписка и прежний тост', async () => {
    const t = bootCatalog({ user: { allows_write_to_pm: true } });
    t.toggle(7);
    await flush();
    assert.equal(subscribed(t.calls).length, 1);
    assert.deepEqual(t.toasts, ['🔔 Уведомим, когда тренер добавит свободные окна']);
    assert.equal(t.tg.requests, 0);
  });

  it('granted -> подписка и тост', async () => {
    const t = bootCatalog({ answer: true });
    t.toggle(7);
    await flush();
    assert.equal(t.tg.requests, 1);
    assert.equal(subscribed(t.calls).length, 1);
    assert.equal(t.toasts.length, 1);
  });

  it('denied -> подписки нет, тоста «Уведомим» нет, нужный текст', async () => {
    const t = bootCatalog({ answer: false });
    t.toggle(7);
    await flush();
    assert.equal(subscribed(t.calls).length, 0);
    assert.deepEqual(t.toasts, []);
    assert.deepEqual(t.tg.alerts, ['Чтобы мы написали, разрешите сообщения от бота.']);
    assert.ok(!t.state.trainerEdges['7'] || !t.state.trainerEdges['7'].notify_when_slots);
  });

  it('unsupported (нет метода) -> подписки нет, успех не заявлен, кнопка в бота', async () => {
    const t = bootCatalog({ noMethod: true, tap: 'open_bot' });
    t.toggle(7);
    await flush();
    assert.equal(subscribed(t.calls).length, 0);
    assert.deepEqual(t.toasts, []);
    assert.equal(t.tg.popups[0].message, 'Откройте бота и нажмите «Старт», чтобы получать уведомления.');
    assert.deepEqual(t.tg.opened, ['https://t.me/glide_bot']);
  });

  it('метод бросает -> то же, что unsupported', async () => {
    const t = bootCatalog({ throws: true });
    t.toggle(7);
    await flush();
    assert.equal(subscribed(t.calls).length, 0);
    assert.deepEqual(t.toasts, []);
    assert.equal(t.tg.popups.length, 1);
  });

  it('не Telegram (нет initData): поведение прежнее, ничего не спрашиваем', async () => {
    const t = bootCatalog({ noInitData: true });
    t.toggle(7);
    await flush();
    assert.equal(t.tg.requests, 0);
    assert.equal(subscribed(t.calls).length, 0, 'без initData подписка не оформляется и раньше');
  });

  it('отключение подписки не спрашивает разрешение', async () => {
    const t = bootCatalog({ answer: false });
    t.state.trainerEdges['7'] = { notify_when_slots: true };
    t.toggle(7);
    await flush();
    assert.equal(t.tg.requests, 0);
    assert.equal(t.calls.filter((c) => c.method === 'DELETE').length, 1);
  });
});

/* --- client-home-main.js: toggleHubNotifySlots -------------------------------------- */

function bootHub(tgOpts) {
  const calls = [];
  const toasts = [];
  const tg = makeTg(tgOpts);
  const win = { Telegram: { WebApp: tg } };
  win.window = win;
  const fn = sliceBetween(read('client-home-main.js'), 'function toggleHubNotifySlots(trainerId) {', 'function paintMeCardForTrainerSync');
  const ctx = vm.createContext({
    window: win,
    fetch: makeFetch(calls),
    Promise,
    JSON,
    String,
    Number,
    encodeURIComponent,
    initData: 'x',
    _meCardTrainerPaintCtx: { trainer: { id: 7 }, slots: [], hubMeta: null, notifyWhenSlots: false },
    paintMeCardForTrainerSync() {},
    patchWarmCacheNotify() {},
    headersJson: () => ({ 'Content-Type': 'application/json' }),
    hubShowToast: (t) => toasts.push(t),
  });
  vm.runInContext(fn + '\nthis.toggle = toggleHubNotifySlots;', ctx);
  vm.runInContext(waSource, ctx);
  win.fetch = ctx.fetch;
  return { toggle: ctx.toggle, calls, toasts, tg };
}

describe('главная: уведомить о слотах тренера', () => {
  it('granted -> подписка и тост', async () => {
    const t = bootHub({ answer: true });
    t.toggle(7);
    await flush();
    assert.equal(subscribed(t.calls).length, 1);
    assert.deepEqual(t.toasts, ['🔔 Уведомим, когда тренер добавит свободные окна']);
  });
  it('denied -> подписки нет', async () => {
    const t = bootHub({ answer: false });
    t.toggle(7);
    await flush();
    assert.equal(subscribed(t.calls).length, 0);
    assert.deepEqual(t.toasts, []);
    assert.deepEqual(t.tg.alerts, ['Чтобы мы написали, разрешите сообщения от бота.']);
  });
  it('unsupported -> подписки нет, кнопка в бота', async () => {
    const t = bootHub({ noMethod: true, tap: 'open_bot' });
    t.toggle(7);
    await flush();
    assert.equal(subscribed(t.calls).length, 0);
    assert.deepEqual(t.toasts, []);
    assert.deepEqual(t.tg.opened, ['https://t.me/glide_bot']);
  });
  it('already -> подписка без диалога', async () => {
    const t = bootHub({ user: { allows_write_to_pm: true } });
    t.toggle(7);
    await flush();
    assert.equal(t.tg.requests, 0);
    assert.equal(subscribed(t.calls).length, 1);
  });
});

/* --- arena-card.js: subscribeIceWatch ------------------------------------------------ */

async function bootArena(tgOpts) {
  const calls = [];
  const tg = makeTg(tgOpts);
  const model = require(path.join(webapp, 'arena-card-model.js'));
  const el = () => ({
    innerHTML: '',
    textContent: '',
    style: {},
    dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => null,
    querySelectorAll: () => [],
    setAttribute() {},
    getAttribute: () => null,
    addEventListener() {},
  });
  const root = el();
  const win = {
    ArenaCardModel: model,
    RuText: {},
    Telegram: { WebApp: tg },
    location: { search: '?arena_id=42', href: 'https://example.test/arena' },
    history: { length: 1, back() {} },
    sessionStorage: { getItem: () => null, setItem() {} },
    localStorage: { getItem: () => null, setItem() {} },
    addEventListener() {},
    setTimeout: (fn) => {
      fn();
      return 0;
    },
    clearTimeout() {},
    navigator: { clipboard: null },
  };
  const fetchImpl = makeFetch(calls);
  const ctx = vm.createContext({
    window: win,
    document: {
      readyState: 'complete',
      getElementById: (id) => (id === 'arenaRoot' ? root : id === 'headerTitle' || id === 'btnHome' || id === 'btnBack' ? el() : null),
      addEventListener() {},
    },
    fetch: (url, init) => {
      if (String(url).includes('/api/public/arenas')) return Promise.reject(new Error('no card in this test'));
      return fetchImpl(url, init);
    },
    Promise,
    console,
  });
  win.document = ctx.document;
  vm.runInContext(waSource, ctx);
  win.fetch = ctx.fetch;
  vm.runInContext(read('arena-card.js'), ctx);
  await flush();
  const page = win.ArenaCardPage;
  page.state.card = { id: 42, city_id: 1, name: 'Каток' };
  return { page, calls, tg };
}

describe('карточка катка: подписка на расписание', () => {
  it('unsupported -> подписка не сохраняется, кнопка ведёт в бота', async () => {
    const t = await bootArena({ noMethod: true, tap: 'open_bot' });
    t.page.subscribeIceWatch('sessions');
    await flush();
    assert.equal(subscribed(t.calls).length, 0);
    assert.equal(t.tg.popups[0].message, 'Откройте бота и нажмите «Старт», чтобы получать уведомления.');
    const outcome = t.calls.find((c) => c.url.includes('/write-access/outcome'));
    assert.deepEqual(outcome.body, { surface: 'arena_watch', outcome: 'unsupported', retry: false, arena_id: 42 });
    assert.deepEqual(t.tg.opened, ['https://t.me/glide_bot']);
  });

  it('метод бросает -> подписка не сохраняется', async () => {
    const t = await bootArena({ throws: true });
    t.page.subscribeIceWatch('sessions');
    await flush();
    assert.equal(subscribed(t.calls).length, 0);
  });

  it('denied -> подписки нет, прежний текст', async () => {
    const t = await bootArena({ answer: false });
    t.page.subscribeIceWatch('sessions');
    await flush();
    assert.equal(subscribed(t.calls).length, 0);
    assert.deepEqual(t.tg.alerts, ['Без разрешения писать бот не сможет прислать напоминание.']);
  });

  it('granted и already сохраняют подписку как раньше', async () => {
    const g = await bootArena({ answer: true });
    g.page.subscribeIceWatch('sessions');
    await flush();
    assert.equal(subscribed(g.calls).length, 1);
    const a = await bootArena({ user: { allows_write_to_pm: true } });
    a.page.subscribeIceWatch('sessions');
    await flush();
    assert.equal(a.tg.requests, 0);
    assert.equal(subscribed(a.calls).length, 1);
  });
});
