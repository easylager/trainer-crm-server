'use strict';
/**
 * Запуск inline-скрипта HTML-страницы Mini App в vm с «всеядным» fake-DOM:
 * любой getElementById отдаёт элемент-заглушку (запоминается по id).
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../../static/webapp');

function makeEl(id) {
  const listeners = {};
  const el = {
    id, value: '', innerHTML: '', textContent: '', hidden: false, disabled: false,
    style: {}, dataset: {}, children: [], onclick: null,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    setAttribute() {}, getAttribute: () => null, removeAttribute() {},
    appendChild(c) { this.children.push(c); }, remove() {}, focus() {}, blur() {},
    insertAdjacentHTML(pos, html) { this.innerHTML = pos === 'afterbegin' ? html + this.innerHTML : this.innerHTML + html; },
    querySelector: () => null, querySelectorAll: () => [], closest: () => null,
    addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
    fire(t, ev) { (listeners[t] || []).forEach((fn) => fn(ev || { target: el, preventDefault() {} })); },
    click() { if (el.onclick) el.onclick({ preventDefault() {}, stopPropagation() {} }); el.fire('click'); },
  };
  return el;
}

function inlineScripts(file) {
  const html = fs.readFileSync(path.join(webapp, file), 'utf8');
  const out = [];
  const re = /<script>([\s\S]*?)<\/script>/g;
  let m;
  while ((m = re.exec(html))) out.push(m[1]);
  return out.sort((a, b) => b.length - a.length)[0];
}

function runInlinePage(file, opts) {
  opts = opts || {};
  const els = {};
  const getEl = (id) => (els[id] = els[id] || makeEl(id));
  const alerts = [];
  const win = Object.assign({
    Telegram: opts.telegram === null ? undefined : { WebApp: Object.assign({ initData: 'init', ready() {}, expand() {}, showAlert: (t) => alerts.push(String(t)) }, opts.telegram || {}) },
    location: { search: opts.search || '', origin: 'https://t.example', href: '', pathname: '/' },
    history: { length: 1, back() {} }, addEventListener() {}, setTimeout, clearTimeout,
    alert: (t) => alerts.push(String(t)),
    confirm: opts.confirm || (() => true),
  }, opts.window || {});
  const sandbox = {
    window: win,
    document: {
      getElementById: getEl, querySelector: () => null, querySelectorAll: () => [],
      createElement: () => makeEl('new'), addEventListener() {},
      body: makeEl('body'), documentElement: makeEl('html'), readyState: 'complete',
    },
    location: win.location,
    fetch: opts.fetch,
    alert: win.alert,
    URL, URLSearchParams, Promise, Intl, console, setTimeout, clearTimeout,
    localStorage: { getItem: () => null, setItem() {} },
    sessionStorage: { getItem: () => null, setItem() {} },
  };
  if (opts.sandbox) Object.assign(sandbox, opts.sandbox);
  const ctx = vm.createContext(sandbox);
  (opts.pre || []).forEach((f) => vm.runInContext(fs.readFileSync(path.join(webapp, f), 'utf8'), ctx));
  if (ctx.MinskTime) win.MinskTime = ctx.MinskTime;
  vm.runInContext(opts.source || inlineScripts(file), ctx);
  return { els, getEl, alerts, ctx, win };
}

const json = (body, ok = true, status = 200) => Promise.resolve({
  ok, status, statusText: '',
  json: () => Promise.resolve(body),
  text: () => Promise.resolve(JSON.stringify(body)),
});
const tick = async (n = 60) => { for (let i = 0; i < n; i += 1) await Promise.resolve(); };

module.exports = { runInlinePage, json, tick, inlineScripts, webapp };
