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
    id, innerHTML: '', hidden: true, handlers: {}, attrs: {},
    addEventListener(t, fn) { this.handlers[t] = fn; },
    querySelector() { return null; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    removeAttribute(k) { delete this.attrs[k]; },
  };
}

/**
 * Шторка с «живым» фокусом: из innerHTML вытаскиваем кнопки и поля как фокусируемые узлы, а .sheet — как окно.
 * Настоящего DOM нет — этого хватает, чтобы проверять порядок фокуса, ловушку Tab и возврат фокуса.
 */
function makeSheet(doc) {
  const el = makeEl('sheet');
  let html = '';
  let nodes = [];
  let dlg = null;
  const mk = (tag, attrStr) => {
    const attrs = {};
    String(attrStr).replace(/([\w-]+)="([^"]*)"/g, (_, k, v) => { attrs[k] = v; return ''; });
    const n = {
      tag, attrs, isConnected: true, selectionStart: 0, selectionEnd: 0,
      getAttribute: (k) => (k in attrs ? attrs[k] : null),
      focus() { doc.activeElement = n; },
      setSelectionRange(a, b) { n.selectionStart = a; n.selectionEnd = b; },
    };
    return n;
  };
  Object.defineProperty(el, 'innerHTML', {
    get: () => html,
    set(v) {
      html = v;
      nodes = [];
      dlg = null;
      if (!v) return;
      const dm = /<div class="sheet"([^>]*)>/.exec(v);
      if (dm) dlg = mk('div', dm[1]);
      const re = /<(button|input|textarea)\b([^>]*)>/g;
      let m;
      while ((m = re.exec(v))) {
        if (/\bdisabled\b/.test(m[2])) continue;
        nodes.push(mk(m[1], m[2]));
      }
    },
  });
  el.querySelectorAll = () => nodes.slice();
  el.querySelector = (sel) => (sel === '.sheet' ? dlg : null);
  el.contains = (n) => !!n && (n === dlg || nodes.includes(n));
  return el;
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
/**
 * historyLength — history.length при открытии витрины: >1 — пришли с другого экрана (есть куда «‹ Назад»).
 * unified — включён флаг единой карточки тренера (window.__UNIFIED_TRAINER_CARD__).
 */
function boot({ search = '', routes = [], profiles = { items: [], default_profile_id: null }, session = {}, showcase = { items: [] }, switcher = null, tg = null, historyLength = 1, initData = 'x', miniAppBack = null, unified = false } = {}) {
  const calls = [];
  const app = makeEl('app');
  const doc = { activeElement: null, body: { tag: 'body' }, keyHandlers: [], addEventListener(t, fn) { if (t === 'keydown') doc.keyHandlers.push(fn); }, getElementById: null, querySelector: () => null };
  doc.activeElement = doc.body;
  const sheet = makeSheet(doc);
  const store = {};
  const ctx = {
    console, setTimeout, clearTimeout, Promise, URL, URLSearchParams, Intl, Date, JSON, Math, Number, String, Object, Array, Error, TypeError, isFinite,
    location: { search, href: 'https://x/static/webapp/trainers' + search, pathname: '/static/webapp/trainers' },
    // Записи витрины (pushState) — стек; back() снимает свою запись и шлёт popstate, а из корня — уход со
    // страницы (left: сколько раз ушли туда, откуда пришли).
    history: {
      state: null, length: historyLength, backs: 0, left: 0, entries: [],
      pushState(st) { this.entries.push(st); this.state = st; this.length += 1; },
      replaceState(st) { this.state = st; if (this.entries.length) this.entries[this.entries.length - 1] = st; },
      back() {
        this.backs += 1;
        if (!this.entries.length) { this.left += 1; return; }
        this.entries.pop();
        this.state = this.entries.length ? this.entries[this.entries.length - 1] : null;
        (ctx.winHandlers.popstate || []).forEach((fn) => fn({ state: this.state }));
      },
    },
    localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } },
    document: doc,
    scrollTo() {}, scrollY: 0,
    winHandlers: {},
    addEventListener(t, fn) { (ctx.winHandlers[t] = ctx.winHandlers[t] || []).push(fn); },
    navigated: [],
  };
  doc.getElementById = (id) => (id === 'app' ? app : id === 'sheet' ? sheet : null);
  ctx.window = ctx;
  ctx.globalThis = ctx;
  ctx.tabBar = [];
  ctx.ClientShell = { navigate: (p) => ctx.navigated.push(p), setTabBarVisible: (v) => ctx.tabBar.push(!!v) };
  if (switcher) ctx.ClientProfileSwitcher = switcher;
  if (miniAppBack) ctx.MiniAppBack = miniAppBack;
  // Единая карточка (TASK-400): как строка, которую /webapp/trainers дописывает в <head> при включённом флаге.
  if (unified) ctx.__UNIFIED_TRAINER_CARD__ = true;
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
    getInitData: () => initData,
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
  if (tg) {
    // Настоящий write-access.js на подменённом Telegram: ворота и состояние — как в продакшене.
    ctx.Telegram = { WebApp: tg };
    vm.runInContext(fs.readFileSync(path.join(webapp, 'write-access.js'), 'utf8'), ctx, { filename: 'write-access.js' });
    ctx.BookingClient.unreachableState = () => {
      const st = ctx.GlideWriteAccess.writeAccessState(tg);
      return st === 'askable' || st === 'unsupported' ? st : '';
    };
    ctx.BookingClient.writeAccessBlockHtml = (st) => (st ? '<div data-wa-block="' + st + '">Разрешите сообщения</div>' : '');
  }
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
    key(k, shiftKey = false) {
      const ev = { key: k, shiftKey, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
      doc.keyHandlers.forEach((fn) => fn(ev));
      return ev;
    },
    doc,
    posts: (prefix) => calls.filter((c) => c.method === 'POST' && c.url.split('?')[0] === prefix),
  };
}

module.exports = { boot, resp, tick };
