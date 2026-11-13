/**
 * TASK-401: форма K. Флаг выключен — таймер и хаб. Флаг включён — replace на карточку, без таймера.
 * Run: node --test tests/js/client-register-unified.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function el(id) {
  return {
    id,
    hidden: false,
    textContent: '',
    innerHTML: '',
    value: '',
    style: {},
    classList: { toggle() {}, add() {} },
    addEventListener() {},
    focus() {},
    parentNode: null,
  };
}

function boot(opts = {}) {
  const ids = {};
  ['crHeroSub', 'crPhone', 'crPhoneError', 'crFirstName', 'crFirstNameError', 'crLastName', 'crGlobalError',
    'crBtnSubmit', 'crFormCard', 'crActions', 'crSuccessScreen', 'crSuccessSub', 'crBtnOpenHome', 'crHeroTitle',
    'crLastNameBlock', 'crShell'].forEach((id) => { ids[id] = el(id); });
  ids.crPhoneError.parentNode = { appendChild(node) { ids.crPhoneNote = node; } };
  ids.crShell.firstChild = null;
  ids.crShell.insertBefore = (node) => { ids.crSlotBar = node; };
  const timeouts = [];
  const replaced = [];
  const hrefs = [];
  const fetches = [];
  const ctx = {
    console, URL, URLSearchParams, Date, JSON, Math, Number, String, Object, Array, encodeURIComponent,
    setTimeout(fn, ms) { timeouts.push({ fn, ms }); return timeouts.length; },
    clearTimeout() {},
    location: {
      search: opts.search || '?trainer_id=7',
      pathname: '/webapp/client-register',
      href: '',
      replace(url) { replaced.push(url); },
    },
    document: {
      body: { classList: { add(c) { this.cls = c; } } },
      getElementById: (id) => ids[id] || null,
      querySelector: () => null,
      createElement: (tag) => ({ tag, id: '', className: '', textContent: '', hidden: false }),
      head: { appendChild() {} },
    },
    fetch(url) {
      const u = String(url);
      fetches.push(u);
      let data = {};
      if (u.includes('/client/session')) data = opts.session || {};
      else if (u.includes('/trainer-info/')) data = { name: 'Анна Соколова' };
      else if (u.includes('/client/self-register')) data = { status: 'linked' };
      else if (u.includes('/client/slot/')) data = opts.slot || { available: false, slot: null };
      else if (u.includes('/register-event')) data = { ok: true };
      return Promise.resolve({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve(data),
        text: () => Promise.resolve(JSON.stringify(data)),
      });
    },
    navigator: {},
  };
  Object.defineProperty(ctx.location, 'href', { set(v) { hrefs.push(v); }, get() { return hrefs[0] || ''; } });
  ctx.window = ctx;
  ctx.Telegram = { WebApp: { initData: 'user=1', ready() {}, expand() {}, colorScheme: 'light' } };
  if (opts.unified) ctx.__UNIFIED_TRAINER_CARD__ = true;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../static/webapp/client-register-main.js'), 'utf8'), ctx);
  return { ctx, ids, timeouts, replaced, hrefs, fetches };
}

const tick = () => new Promise((r) => setTimeout(r, 30));

describe('форма регистрации', () => {
  it('флаг выключен: хаб и таймер, без пояснения K', async () => {
    const h = boot({ session: { client_phone: '+375291112233', client_first_name: 'Анна' } });
    await tick();
    const redirect = h.timeouts.find((t) => t.ms >= 2000 && t.ms < 10000);
    assert.ok(redirect, 'автопереход');
    redirect.fn();
    assert.ok(h.hrefs.some((u) => u.includes('client-home')));
    assert.equal(h.replaced.length, 0);
    assert.equal(h.ids.crPhoneNote, undefined);
    assert.equal(h.ids.crHeroTitle.textContent, '');
  });

  it('флаг включён: пояснение, слот сверху, replace на карточку без таймера', async () => {
    const h = boot({
      unified: true,
      search: '?trainer_id=7&slot_id=55',
      session: { client_phone: '+375291112233', client_first_name: 'Анна' },
      slot: { available: true, slot: { slot_date: '2026-11-21', start_time: '10:00', arena_name: 'Замок' } },
    });
    await tick();
    assert.equal(h.ids.crHeroTitle.textContent, 'Как вас зовут?');
    assert.equal(h.ids.crLastNameBlock.hidden, true);
    assert.match(h.ids.crPhoneNote.textContent, /Тот же номер, что у вас записан у Анна Соколова/);
    assert.match(h.ids.crSlotBar.textContent, /Сб, 10:00 · Замок/);
    assert.ok(h.replaced.some((u) => u.includes('trainers?trainer_id=7') && u.includes('listed=1') && u.includes('slot_id=55')));
    assert.ok(!h.timeouts.some((t) => t.ms >= 2000 && t.ms < 10000));
    assert.equal(h.hrefs.length, 0);
    assert.ok(!h.replaced.some((u) => u.includes('client-home')));
  });
});
