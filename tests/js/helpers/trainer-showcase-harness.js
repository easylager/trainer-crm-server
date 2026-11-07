'use strict';
/**
 * Стенд для static/webapp/trainer-showcase-main.js: настоящие model/ru-person-name/main в vm,
 * фейковый DOM (#app, #sheet) и подменённый fetch с маршрутами теста. Клики идут через реальный onClick.
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../../static/webapp');

function makeEl(id) {
  return {
    id, innerHTML: '', hidden: true, handlers: {},
    addEventListener(t, fn) { this.handlers[t] = fn; },
    querySelector() { return null; },
  };
}

function resp(status, data, delay = 0) {
  const r = {
    ok: status >= 200 && status < 300, status,
    text: () => Promise.resolve(JSON.stringify(data)),
    json: () => Promise.resolve(data),
  };
  return delay ? new Promise((res) => setTimeout(() => res(r), delay)) : Promise.resolve(r);
}

const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));

/**
 * routes: [{ match(call) → bool, reply(call) → Promise<Response> }]; первые совпавшие выигрывают.
 * profiles: ответ GET /client/profiles (можно функцией — на каждый вызов).
 */
function boot({ search = '', routes = [], profiles = { items: [], default_profile_id: null }, session = {}, showcase = { items: [] }, switcher = null } = {}) {
  const calls = [];
  const app = makeEl('app');
  const sheet = makeEl('sheet');
  const store = {};
  const ctx = {
    console, setTimeout, clearTimeout, Promise, URL, URLSearchParams, Intl, Date, JSON, Math, Number, String, Object, Array, Error, TypeError, isFinite,
    location: { search, href: 'https://x/static/webapp/trainers' + search, pathname: '/static/webapp/trainers' },
    history: { state: null, pushState() {}, replaceState() {}, back() {} },
    localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } },
    document: { getElementById: (id) => (id === 'app' ? app : id === 'sheet' ? sheet : null), querySelector: () => null },
    scrollTo() {}, scrollY: 0,
    addEventListener() {},
    navigated: [],
  };
  ctx.window = ctx;
  ctx.globalThis = ctx;
  ctx.ClientShell = { navigate: (p) => ctx.navigated.push(p) };
  if (switcher) ctx.ClientProfileSwitcher = switcher;
  ctx.fetch = (url, init = {}) => {
    const u = String(url).replace(/[?&]init_data=[^&]*/, '');
    const c = { url: u, method: init.method || 'GET', headers: init.headers || {}, body: init.body ? JSON.parse(init.body) : null };
    calls.push(c);
    const pathOnly = u.split('?')[0];
    for (const r of routes) {
      if (r.match(c)) return r.reply(c);
    }
    if (pathOnly === '/api/webapp/client/profiles' && c.method === 'GET') return resp(200, typeof profiles === 'function' ? profiles() : profiles);
    if (pathOnly === '/api/webapp/client/session') return resp(200, session);
    if (pathOnly === '/api/public/trainer-showcase') return resp(200, showcase);
    if (pathOnly === '/api/webapp/client/passes') return resp(200, { items: [] });
    return resp(404, { detail: 'not mocked ' + u });
  };
  ctx.BookingClient = {
    getInitData: () => 'x',
    fetchClientSession: (tid) => ctx.fetch('/api/webapp/client/session' + (tid ? '?for_trainer_id=' + tid : '')).then((r) => r.json()),
    fetchClientSlots: (o) => ctx.fetch('/api/webapp/client/slots?trainer_id=' + o.trainerId + (o.serviceId ? '&service_id=' + o.serviceId : ''))
      .then((r) => { if (!r.ok) throw new Error('x'); return r.json(); }),
    newIdempotencyKey: () => 'idem-' + Math.random(),
    emitBookingAnalytics() {},
    buildBookingPayload: (o) => ({
      slot_id: o.slotId, phone: o.phone, comment: o.comment || null, service_id: o.serviceId,
      service_price_variant_id: o.priceVariantId ?? undefined, first_name: o.needsProfileName ? o.firstName : undefined,
    }),
    submitBooking: (o) => {
      const h = { 'Content-Type': 'application/json' };
      if (o.profileId != null) h['X-Profile-Id'] = String(o.profileId);
      return ctx.fetch('/api/webapp/client/booking', { method: 'POST', headers: h, body: JSON.stringify(o.body) })
        .then((res) => res.text().then((t) => ({ res, data: t ? JSON.parse(t) : null })));
    },
    hapticSuccess() {}, unreachableState: () => null, writeAccessBlockHtml: () => '', bindWriteAccessBlock() {},
  };
  vm.createContext(ctx);
  for (const f of ['trainer-showcase-model.js', 'ru-person-name.js', 'trainer-showcase-main.js']) {
    vm.runInContext(fs.readFileSync(path.join(webapp, f), 'utf8'), ctx, { filename: f });
  }
  const S = ctx.__trainerShowcase.state;
  function clickOn(root, attrs) {
    const el = { disabled: false, getAttribute: (k) => (k in attrs ? String(attrs[k]) : null), textContent: '' };
    root.handlers.click({ target: { closest: () => el }, stopPropagation() {} });
  }
  return {
    ctx, S, app, sheet, calls, store,
    click: (attrs) => clickOn(app, attrs),
    sheetClick: (attrs) => clickOn(sheet, attrs),
    input(field, value, key) {
      app.handlers.input({ target: { value, getAttribute: (k) => (k === 'data-field' ? field : k === 'data-key' ? key : null) } });
    },
    sheetInput(field, value) {
      sheet.handlers.input({ target: { value, getAttribute: (k) => (k === 'data-field' ? field : null) } });
    },
    posts: (prefix) => calls.filter((c) => c.method === 'POST' && c.url.split('?')[0] === prefix),
  };
}

module.exports = { boot, resp, tick };
