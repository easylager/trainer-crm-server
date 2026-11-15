/**
 * write-access.js: разрешение боту писать первым. Нативный диалог Telegram здесь не
 * воспроизводится: window.Telegram.WebApp — мок, а requestWriteAccess зовёт колбэк так же,
 * как Telegram после закрытия диалога.
 *
 * Run: node --test tests/js/write-access.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const WA = require('../../static/webapp/write-access.js');

function makeTg(opts) {
  opts = opts || {};
  const tg = {
    initData: opts.noInitData ? '' : 'x',
    initDataUnsafe: { user: Object.assign({ id: 111 }, opts.user || {}) },
    requests: 0,
    popups: [],
    alerts: [],
    opened: [],
    isVersionAtLeast: opts.version === undefined ? () => true : (v) => opts.version >= parseFloat(v),
    showPopup(params, cb) {
      tg.popups.push(params);
      cb(opts.tap || null);
    },
    showAlert(text, cb) {
      tg.alerts.push(text);
      if (cb) cb();
    },
    openTelegramLink(url) {
      tg.opened.push(url);
    },
  };
  if (!opts.noMethod) {
    tg.requestWriteAccess = (cb) => {
      tg.requests += 1;
      if (opts.throws) throw new Error('boom');
      cb(opts.answer === undefined ? true : opts.answer);
    };
  }
  return tg;
}

function makeFetch(botLink) {
  const calls = [];
  const fn = (url, init) => {
    calls.push({ url, body: JSON.parse(init.body), headers: init.headers });
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, bot_link: botLink || null }) });
  };
  fn.calls = calls;
  return fn;
}

describe('writeAccessState', () => {
  it('already / askable / unsupported / not_telegram', () => {
    assert.equal(WA.writeAccessState(makeTg({ user: { allows_write_to_pm: true } })), 'already');
    assert.equal(WA.writeAccessState(makeTg()), 'askable');
    assert.equal(WA.writeAccessState(makeTg({ user: { allows_write_to_pm: false } })), 'askable');
    assert.equal(WA.writeAccessState(makeTg({ noMethod: true })), 'unsupported');
    assert.equal(WA.writeAccessState(makeTg({ version: 6.7 })), 'unsupported');
    assert.equal(WA.writeAccessState(makeTg({ noInitData: true })), 'not_telegram');
    assert.equal(WA.writeAccessState(makeTg({ user: { id: -5 } })), 'not_telegram');
    assert.equal(WA.writeAccessState(null), 'not_telegram');
  });
});

describe('requestWriteAccess', () => {
  it('granted только при true', async () => {
    assert.equal(await WA.requestWriteAccess(makeTg({ answer: true })), 'granted');
    assert.equal(await WA.requestWriteAccess(makeTg({ answer: false })), 'denied');
    assert.equal(await WA.requestWriteAccess(makeTg({ answer: 'yes' })), 'denied');
  });
  it('нет метода или он бросает -> unsupported, без исключения', async () => {
    assert.equal(await WA.requestWriteAccess(makeTg({ noMethod: true })), 'unsupported');
    assert.equal(await WA.requestWriteAccess(makeTg({ throws: true })), 'unsupported');
    assert.equal(await WA.requestWriteAccess(null), 'unsupported');
  });
});

describe('openBotChat', () => {
  it('открывает только https://t.me/ через openTelegramLink', () => {
    const tg = makeTg();
    assert.equal(WA.openBotChat(tg, 'https://t.me/bot?start=watch_3'), true);
    assert.deepEqual(tg.opened, ['https://t.me/bot?start=watch_3']);
    assert.equal(WA.openBotChat(tg, 'https://evil.example/x'), false);
    assert.equal(WA.openBotChat(tg, null), false);
  });
});

describe('reportOutcome', () => {
  it('шлёт surface, исход и id, без telegram id', async () => {
    const f = makeFetch('https://t.me/bot');
    const res = await WA.reportOutcome(makeTg(), 'slot_wait', 'denied', { trainerId: 7, retry: true }, { fetch: f });
    assert.equal(res.bot_link, 'https://t.me/bot');
    assert.equal(f.calls[0].url, '/api/webapp/client/write-access/outcome');
    assert.deepEqual(f.calls[0].body, { surface: 'slot_wait', outcome: 'denied', retry: true, trainer_id: 7 });
    assert.ok(!JSON.stringify(f.calls[0].body).includes('111'));
  });
  it('сбой сети -> null, не исключение', async () => {
    const f = () => Promise.reject(new Error('net'));
    assert.equal(await WA.reportOutcome(makeTg(), 'booking', 'granted', {}, { fetch: f }), null);
  });
});

describe('gate', () => {
  it('already: proceed, диалога нет, исход already записан', async () => {
    const tg = makeTg({ user: { allows_write_to_pm: true } });
    const f = makeFetch();
    assert.equal(await WA.gate(tg, { surface: 'slot_wait', trainerId: 1, fetch: f }), 'proceed');
    assert.equal(tg.requests, 0);
    assert.equal(f.calls[0].body.outcome, 'already');
  });
  it('granted: proceed', async () => {
    const tg = makeTg({ answer: true });
    const f = makeFetch();
    assert.equal(await WA.gate(tg, { surface: 'slot_wait', trainerId: 1, fetch: f }), 'proceed');
    assert.equal(tg.requests, 1);
    assert.equal(f.calls[0].body.outcome, 'granted');
  });
  it('denied: не proceed, точный текст алерта', async () => {
    const tg = makeTg({ answer: false });
    const f = makeFetch();
    assert.equal(await WA.gate(tg, { surface: 'slot_wait', trainerId: 1, fetch: f }), 'denied');
    assert.deepEqual(tg.alerts, ['Чтобы мы написали, разрешите сообщения от бота.']);
    assert.equal(f.calls[0].body.outcome, 'denied');
  });
  it('denied: подменяемый текст', async () => {
    const tg = makeTg({ answer: false });
    await WA.gate(tg, { surface: 'arena_watch', arenaId: 3, deniedText: 'свой', fetch: makeFetch() });
    assert.deepEqual(tg.alerts, ['свой']);
  });
  it('unsupported (нет метода): не proceed, попап с честной строкой и кнопкой в бота', async () => {
    const tg = makeTg({ noMethod: true, tap: 'open_bot' });
    const f = makeFetch('https://t.me/bot?start=watch_3');
    assert.equal(await WA.gate(tg, { surface: 'arena_watch', arenaId: 3, fetch: f }), 'unsupported');
    assert.equal(tg.popups[0].message, 'Откройте бота и нажмите «Старт», чтобы получать уведомления.');
    assert.equal(tg.popups[0].buttons[0].text, 'Открыть бота');
    assert.deepEqual(tg.opened, ['https://t.me/bot?start=watch_3']);
    assert.deepEqual(f.calls[0].body, { surface: 'arena_watch', outcome: 'unsupported', retry: false, arena_id: 3 });
  });
  it('unsupported (метод бросает): то же самое', async () => {
    const tg = makeTg({ throws: true });
    const f = makeFetch('https://t.me/bot');
    assert.equal(await WA.gate(tg, { surface: 'slot_wait', trainerId: 1, fetch: f }), 'unsupported');
    assert.equal(tg.popups.length, 1);
  });
  it('unsupported без ссылки: только «закрыть», подписка не оформляется', async () => {
    const tg = makeTg({ noMethod: true });
    assert.equal(await WA.gate(tg, { surface: 'slot_wait', trainerId: 1, fetch: makeFetch(null) }), 'unsupported');
    assert.deepEqual(tg.popups[0].buttons, [{ type: 'close' }]);
  });
  it('не Telegram: proceed без диалога и без запроса', async () => {
    const tg = makeTg({ noInitData: true });
    const f = makeFetch();
    assert.equal(await WA.gate(tg, { surface: 'slot_wait', trainerId: 1, fetch: f }), 'proceed');
    assert.equal(tg.requests, 0);
    assert.equal(f.calls.length, 0);
    assert.equal(await WA.gate(null, { surface: 'slot_wait', fetch: f }), 'proceed');
  });
});

describe('entryGate', () => {
  function installDoc() {
    const store = new Map();
    const mem = {};
    global.sessionStorage = {
      getItem(k) {
        return Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null;
      },
      setItem(k, v) {
        mem[k] = String(v);
      },
      removeItem(k) {
        delete mem[k];
      },
      _mem: mem,
    };
    const body = {
      classList: {
        _c: new Set(),
        add(c) {
          this._c.add(c);
        },
        remove(c) {
          this._c.delete(c);
        },
      },
      appendChild(el) {
        store.set(el.id, el);
      },
    };
    function el(tag) {
      const node = {
        tagName: tag,
        id: '',
        className: '',
        hidden: false,
        disabled: false,
        textContent: '',
        innerHTML: '',
        _kids: {},
        _on: {},
        setAttribute() {},
        querySelector(sel) {
          if (sel.startsWith('.')) return this._kids[sel.slice(1)] || null;
          if (sel.startsWith('[data-act=')) {
            const act = sel.match(/data-act="([^"]+)"/)[1];
            return this._kids['act:' + act] || null;
          }
          return null;
        },
        addEventListener(type, fn) {
          this._on[type] = this._on[type] || [];
          this._on[type].push(fn);
        },
        click() {
          (this._on.click || []).forEach((fn) => fn());
        },
        parentNode: {
          removeChild(child) {
            store.delete(child.id);
          },
        },
      };
      Object.defineProperty(node, 'innerHTML', {
        get() {
          return this._html || '';
        },
        set(html) {
          this._html = html;
          this._kids = {};
          ['glide-entry-gate__title', 'glide-entry-gate__text'].forEach((cls) => {
            this._kids[cls] = el('div');
          });
          this._kids['act:allow'] = el('button');
          this._kids['act:bot'] = el('button');
          this._kids['act:bot'].hidden = true;
        },
      });
      return node;
    }
    global.document = {
      body,
      getElementById(id) {
        return store.get(id) || null;
      },
      createElement: el,
    };
    return { body, store, mem };
  }

  it('already: proceed без оверлея, пишет session', async () => {
    const { store, mem } = installDoc();
    const f = makeFetch();
    const tg = makeTg({ user: { allows_write_to_pm: true } });
    assert.equal(await WA.entryGate(tg, { fetch: f }), 'proceed');
    assert.equal(store.size, 0);
    assert.equal(mem.glide_entry_write_ok, '1');
    assert.equal(f.calls[0].body.surface, 'shell_entry');
    assert.equal(f.calls[0].body.outcome, 'already');
  });

  it('granted: системный запрос без оверлея, потом proceed', async () => {
    const { store, body, mem } = installDoc();
    const f = makeFetch('https://t.me/bot?start=x');
    const tg = makeTg({ answer: true });
    assert.equal(await WA.entryGate(tg, { fetch: f }), 'proceed');
    assert.equal(tg.requests, 1);
    assert.equal(store.size, 0);
    assert.equal(body.classList._c.has('glide-entry-gate-on'), false);
    assert.equal(mem.glide_entry_write_ok, '1');
    assert.equal(tg.initDataUnsafe.user.allows_write_to_pm, true);
    assert.equal(f.calls[0].body.outcome, 'granted');
  });

  it('повторный вход после granted: без запроса и без оверлея', async () => {
    const { store, mem } = installDoc();
    mem.glide_entry_write_ok = '1';
    const f = makeFetch();
    const tg = makeTg({ answer: false });
    assert.equal(await WA.entryGate(tg, { fetch: f }), 'proceed');
    assert.equal(tg.requests, 0);
    assert.equal(store.size, 0);
    assert.equal(f.calls.length, 0);
  });

  it('denied: оверлей после отказа, кнопка бота', async () => {
    installDoc();
    const f = makeFetch('https://t.me/bot?start=x');
    const tg = makeTg({ answer: false });
    let done = false;
    const p = WA.entryGate(tg, { fetch: f }).then(() => {
      done = true;
    });
    await Promise.resolve();
    await Promise.resolve();
    await new Promise((r) => setTimeout(r, 20));
    assert.equal(done, false);
    const overlay = global.document.getElementById('glide-entry-gate');
    assert.ok(overlay);
    const bot = overlay.querySelector('[data-act="bot"]');
    assert.equal(bot.hidden, false);
    tg.requestWriteAccess = (cb) => cb(true);
    overlay.querySelector('[data-act="allow"]').click();
    await p;
    assert.equal(done, true);
  });

  it('не Telegram: proceed', async () => {
    installDoc();
    assert.equal(await WA.entryGate(makeTg({ noInitData: true })), 'proceed');
  });
});
