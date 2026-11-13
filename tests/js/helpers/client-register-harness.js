'use strict';
/**
 * Стенд для static/webapp/client-register-main.js (форма регистрации по ссылке тренера, экран K).
 * Фейковый DOM повторяет дерево client-register.html (шапка, поля телефона/имени/фамилии, ошибки, кнопка,
 * экран успеха), fetch подменён маршрутами теста и пишет полный URL, sessionStorage и таймеры — в памяти.
 * `tree()` сериализует дерево: им сверяется порядок полей и снимок «флаг выключен».
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../../static/webapp');

function makeDom() {
  const byId = {};
  function node(tag, id, text) {
    const n = {
      tag, id: id || '', hidden: false, textContent: text || '', innerHTML: '', value: '', disabled: false,
      className: '', style: {}, attrs: {}, children: [], parentNode: null, handlers: {},
      classList: {
        set: new Set(),
        add(c) { this.set.add(c); },
        remove(c) { this.set.delete(c); },
        toggle(c, on) { if (on === undefined ? !this.set.has(c) : on) this.set.add(c); else this.set.delete(c); },
        contains(c) { return this.set.has(c); },
      },
      setAttribute(k, v) { this.attrs[k] = String(v); },
      getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
      removeAttribute(k) { delete this.attrs[k]; },
      addEventListener(t, fn) { this.handlers[t] = fn; },
      focus() {},
      scrollIntoView() {},
      appendChild(c) { return this.insertBefore(c, null); },
      insertBefore(c, ref) {
        if (c.parentNode) c.parentNode.children.splice(c.parentNode.children.indexOf(c), 1);
        const i = ref ? this.children.indexOf(ref) : -1;
        if (i < 0) this.children.push(c); else this.children.splice(i, 0, c);
        c.parentNode = this;
        if (c.id) byId[c.id] = c;
        return c;
      },
      get firstChild() { return this.children[0] || null; },
    };
    // Как в DOM: запись textContent убирает детей, чтение собирает текст потомков.
    let ownText = n.textContent;
    delete n.textContent;
    Object.defineProperty(n, 'textContent', {
      enumerable: true,
      get() { return n.children.length ? n.children.map((c) => c.textContent).join('') : ownText; },
      set(v) { n.children.forEach((c) => { c.parentNode = null; }); n.children = []; ownText = String(v); },
    });
    if (id) byId[id] = n;
    return n;
  }
  const add = (parent, ...kids) => { kids.forEach((k) => parent.appendChild(k)); return parent; };

  const body = node('body', '');
  const shell = node('div', 'crShell');
  const hero = add(node('div', 'crHero'), node('h1', 'crHeroTitle', 'Короткий профиль'),
    node('p', 'crHeroSub', 'Несколько полей — и вы можете продолжить в приложении со всеми функциями.'));
  const phoneLabel = node('label', '', 'Телефон');
  phoneLabel.attrs.for = 'crPhone';
  const phoneField = add(node('div', ''), node('input', 'crPhone'));
  const phoneStack = add(node('div', ''), phoneLabel, phoneField, node('span', 'crPhoneError'));
  const nameLabel = node('label', '', 'Имя');
  nameLabel.attrs.for = 'crFirstName';
  const nameStack = add(node('div', ''), nameLabel, node('input', 'crFirstName'), node('span', 'crFirstNameError'));
  const lastLabel = node('label', '', 'Фамилия (необязательно)');
  lastLabel.attrs.for = 'crLastName';
  const lastStack = add(node('div', 'crLastNameBlock'), lastLabel, node('input', 'crLastName'));
  const card = add(node('div', 'crFormCard'), phoneStack, nameStack, lastStack);
  const actions = add(node('div', 'crActions'), add(node('button', 'crBtnSubmit'), node('span', '', 'Продолжить')));
  const success = add(node('div', 'crSuccessScreen'), node('p', 'crSuccessSub', 'Профиль сохранён.'), node('button', 'crBtnOpenHome', 'Открыть «Главная»'));
  add(shell, hero, card, node('div', 'crGlobalError'), actions, success);
  add(body, shell);
  const labels = { crPhone: phoneLabel, crFirstName: nameLabel, crLastName: lastLabel };

  const doc = {
    body,
    getElementById: (id) => byId[id] || null,
    querySelector(sel) {
      const m = /^label\[for="([^"]+)"\]$/.exec(sel);
      return m ? labels[m[1]] || null : null;
    },
    createElement: (tag) => node(tag, ''),
    head: { appendChild() {} },
  };
  return { doc, byId };
}

/** Дерево как текст: tag#id[атрибуты]{текст}, скрытые помечены «hidden». */
function serialize(n, depth = 0) {
  const attrs = Object.keys(n.attrs).filter((k) => k !== 'for').sort().map((k) => k + '=' + n.attrs[k]).join(',');
  const cls = [...n.classList.set].sort().join('.');
  const line = '  '.repeat(depth) + n.tag + (n.id ? '#' + n.id : '') + (cls ? '.' + cls : '') +
    (attrs ? '[' + attrs + ']' : '') + (n.hidden ? ' hidden' : '') +
    (n.style && n.style.display != null && n.style.display !== '' ? ' display=' + n.style.display : '') +
    (!n.children.length && n.textContent ? ' {' + n.textContent + '}' : '') + (n.innerHTML ? ' <' + n.innerHTML + '>' : '');
  return [line].concat(n.children.map((c) => serialize(c, depth + 1))).join('\n');
}

function jsonResponse(status, data) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  });
}

/**
 * opts: unified, search, session, trainerInfo, slot, routes [{ match(url, init) → bool, reply(url, init) → Promise }],
 * initData (Telegram), withRuName (подключить ru-person-name.js, как строкой в client-register.html), file (другой JS).
 */
function bootRegister(opts = {}) {
  const { doc, byId } = makeDom();
  const timeouts = [];
  const replaced = [];
  const hrefs = [];
  const fetches = [];
  const store = {};
  const ctx = {
    console, URL, URLSearchParams, Date, JSON, Math, Number, String, Object, Array, Promise, Error, encodeURIComponent,
    setTimeout(fn, ms) { timeouts.push({ fn, ms }); return timeouts.length; },
    clearTimeout() {},
    location: {
      search: opts.search || '?trainer_id=7',
      pathname: '/webapp/client-register',
      replace(url) { replaced.push(url); },
    },
    sessionStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    },
    document: doc,
    navigator: {},
    CrmPhoneField: {
      initAll() {},
      validate: (input) => (String(input.value || '').trim() ? { ok: true } : { ok: false, error: 'Укажите номер телефона.' }),
      getE164: (input) => '+375' + String(input.value || '').replace(/\D/g, ''),
    },
    fetch(url, init = {}) {
      const u = String(url);
      fetches.push({ url: u, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : null });
      for (const r of opts.routes || []) if (r.match(u, init)) return r.reply(u, init);
      if (u.includes('/client/session')) return jsonResponse(200, opts.session || {});
      if (u.includes('/trainer-info/')) return jsonResponse(200, opts.trainerInfo || { id: 7, name: 'Анна Соколова' });
      if (u.includes('/client/self-register')) return jsonResponse(200, { status: 'linked', client_id: 1 });
      if (u.includes('/client/slot/')) return jsonResponse(200, opts.slot || { available: false, slot: null });
      if (u.includes('/register-event')) return jsonResponse(200, { ok: true });
      return jsonResponse(404, { detail: 'not mocked' });
    },
  };
  Object.defineProperty(ctx.location, 'href', { set(v) { hrefs.push(v); }, get() { return hrefs[hrefs.length - 1] || ''; } });
  ctx.window = ctx;
  ctx.globalThis = ctx;
  ctx.Telegram = { WebApp: { initData: opts.initData === undefined ? 'user=1' : opts.initData, ready() {}, expand() {}, colorScheme: 'light', close() {} } };
  if (opts.unified) ctx.__UNIFIED_TRAINER_CARD__ = true;
  vm.createContext(ctx);
  if (opts.withRuName !== false) {
    vm.runInContext(fs.readFileSync(path.join(webapp, 'ru-person-name.js'), 'utf8'), ctx, { filename: 'ru-person-name.js' });
  }
  const file = opts.file || path.join(webapp, 'client-register-main.js');
  vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, { filename: 'client-register-main.js' });
  return {
    ctx, ids: byId, timeouts, replaced, hrefs, fetches, store,
    tree: () => serialize(doc.body),
    submit() { byId.crBtnSubmit.handlers.click({ preventDefault() {}, stopPropagation() {} }); },
  };
}

const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));

module.exports = { bootRegister, jsonResponse, tick };
