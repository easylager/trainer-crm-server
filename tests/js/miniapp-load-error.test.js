/**
 * TASK-437: один компонент ошибки загрузки на всё клиентское приложение и честный общий экран.
 *  - «Нет связи» при запросе без ответа или офлайн, иначе «Не загрузилось»; кнопка «Повторить» зовёт тот же запрос;
 *  - «Ведутся технические работы» — только по настоящему ответу о работах (502/504, 503 с меткой), без эмодзи;
 *  - обрыв сети не выдаётся за работы, а если экран уже показал свою ошибку — общий экран поверх не встаёт;
 *  - главная, поиск, арена, записи, «Кто кого» и «Я» рисуют ошибку этим компонентом, старых текстов нет.
 * Run: node --test tests/js/miniapp-load-error.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { loadErrorUi } = require('./helpers/load-error-component.js');

const WEBAPP = path.resolve(__dirname, '../../static/webapp');
const read = (f) => fs.readFileSync(path.join(WEBAPP, f), 'utf8');
const CHROME = read('mini-app-telegram-chrome.js');
const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;

function fakeDoc() {
  const styles = [];
  return {
    styles,
    getElementById: (id) => styles.find((s) => s.id === id) || null,
    createElement() {
      const el = {
        id: '', textContent: '', _html: '',
        set innerHTML(v) {
          this._html = v;
          const listeners = [];
          const btn = { listeners, addEventListener: (t, fn) => listeners.push(fn) };
          this.firstChild = { html: v, btn, querySelector: (sel) => (sel === '[data-miniapp-retry]' && /data-miniapp-retry/.test(v) ? btn : null) };
        },
        get innerHTML() { return this._html; },
      };
      return el;
    },
    head: { appendChild: (s) => styles.push(s) },
  };
}

describe('компонент «Не загрузилось · Повторить»', () => {
  const ui = loadErrorUi(fakeDoc());

  it('запрос без ответа (TypeError) и офлайн → «Нет связи»; ответ с ошибкой → «Не загрузилось»', () => {
    assert.equal(ui.loadErrorTitle(new TypeError('Failed to fetch')), 'Нет связи');
    assert.equal(ui.loadErrorTitle(new Error('me 500')), 'Не загрузилось');
    assert.equal(ui.loadErrorTitle(undefined), 'Не загрузилось');
    assert.equal(loadErrorUi(fakeDoc(), { onLine: false }).loadErrorTitle(new Error('x')), 'Нет связи');
  });

  it('разметка: role=alert, метка компонента, кнопка «Повторить», без эмодзи и советов «обновить страницу»', () => {
    const html = ui.loadErrorHtml({ error: new Error('500') });
    assert.match(html, /^<div class="miniapp-load-error" role="alert" data-miniapp-load-error>/);
    assert.match(html, /<p class="miniapp-load-error__title">Не загрузилось<\/p>/);
    assert.match(html, /<button type="button" class="miniapp-load-error__btn ga-press" data-miniapp-retry>Повторить<\/button>/);
    assert.doesNotMatch(html, EMOJI);
    assert.doesNotMatch(html, /обновит|из бота|техническ/i);
  });

  it('data-атрибуты для делегированных обработчиков экрана экранируются; уточнение — отдельной строкой', () => {
    const html = ui.loadErrorHtml({ data: { action: 'retry-load', act: 'a"b', 'Bad Key': 'x' }, hint: '<b>' });
    assert.match(html, / data-action="retry-load"/);
    assert.match(html, / data-act="a&quot;b"/);
    assert.doesNotMatch(html, /Bad Key/);
    assert.match(html, /<p class="miniapp-load-error__hint">&lt;b&gt;<\/p>/);
  });

  it('renderLoadError и loadErrorNode вешают «Повторить» на тот же запрос', () => {
    const doc = fakeDoc();
    const u = loadErrorUi(doc);
    let hits = 0;
    const box = doc.createElement('div');
    u.renderLoadError(box, { onRetry: () => { hits += 1; } });
    assert.match(box.innerHTML, /data-miniapp-load-error/);
    box.firstChild.btn.listeners.forEach((fn) => fn({ stopPropagation() {} }));
    const node = u.loadErrorNode({ onRetry: () => { hits += 1; } });
    node.btn.listeners.forEach((fn) => fn({ stopPropagation() {} }));
    assert.equal(hits, 2);
  });

  it('стили один раз; кнопка не ниже 44 px; цвета — из --miniapp-state-* с запасом на --g-*', () => {
    const doc = fakeDoc();
    const u = loadErrorUi(doc);
    u.loadErrorHtml({});
    u.loadErrorHtml({});
    assert.equal(doc.styles.length, 1);
    const css = doc.styles[0].textContent;
    assert.match(css, /\.miniapp-load-error__btn\{[^}]*min-height:44px/);
    assert.match(css, /var\(--miniapp-state-ink,var\(--g-ink/);
    assert.match(css, /var\(--miniapp-state-btn-bg,var\(--g-accent/);
  });
});

/* ── Общий экран из fetch-guard ─────────────────────────────────────────────────────────── */

const GUARD = CHROME.slice(CHROME.indexOf('  var OUTAGE_OVERLAY_ID'), CHROME.indexOf('  global.MiniAppErrorUi = {'));

function element(tag) {
  const attrs = {};
  const el = {
    tag, id: '', style: {}, children: [], _html: '',
    classList: { remove() {}, add() {} },
    setAttribute: (k, v) => { attrs[k] = String(v); },
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    set innerHTML(v) { this._html = v; },
    get innerHTML() { return this._html; },
    querySelector(sel) {
      if (sel === '[data-miniapp-retry]' && /data-miniapp-retry/.test(this._html)) {
        return (this._btn = this._btn || { disabled: false, onclick: null });
      }
      return null;
    },
  };
  return el;
}

function bootGuard({ fetchImpl, screenError = false, onLine = true } = {}) {
  const body = element('body');
  const nodes = [];
  const timers = [];
  const document = {
    body,
    head: element('head'),
    documentElement: element('html'),
    visibilityState: 'visible',
    createElement: (t) => { const e = element(t); nodes.push(e); return e; },
    getElementById: (id) => nodes.find((n) => n.id === id && (n.parentNode || n.tag === 'style')) || (id === 'skeleton' ? null : null),
    querySelector: (sel) => (sel === '[data-miniapp-load-error]' && screenError ? {} : null),
  };
  const head = document.head;
  head.appendChild = (s) => { s.parentNode = head; nodes.push(s); return s; };
  const global = {
    fetch: fetchImpl,
    navigator: { onLine },
    location: { reload() {}, href: 'https://t/webapp/x' },
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    clearTimeout() {},
    addEventListener() {},
  };
  const ctx = { global, document, Object, String };
  vm.runInNewContext(
    'var fetchGuardInstalled = false; var overlayShown = false; function inspectUnauthorized() {}\n' + GUARD + '\ninstallFetchGuard();',
    ctx
  );
  return {
    fetch: (u, i) => global.fetch(u, i),
    overlay: () => body.children.find((c) => c.id === 'miniAppOutageOverlay') || null,
    runTimers: () => { while (timers.length) timers.shift()(); },
  };
}

const settle = () => new Promise((r) => setImmediate(r));
const res = (status, headers = {}, body = null) => ({
  status, ok: status < 400,
  headers: { get: (k) => headers[k] || headers[k.toLowerCase()] || null },
  clone() { return this; },
  json: () => Promise.resolve(body),
});

describe('общий экран: обрыв связи ≠ технические работы', () => {
  it('запрос без ответа → «Нет связи · Повторить», не «технические работы»', async () => {
    const g = bootGuard({ fetchImpl: () => Promise.reject(new TypeError('Failed to fetch')) });
    await g.fetch('/api/webapp/client/me').catch(() => {});
    await settle();
    g.runTimers();
    const o = g.overlay();
    assert.ok(o, 'экран показан');
    assert.equal(o.getAttribute('data-kind'), 'offline');
    assert.match(o.innerHTML, /miniapp-load-error__title">Нет связи</);
    assert.match(o.innerHTML, />Повторить</);
    assert.doesNotMatch(o.innerHTML, /техническ/i);
    assert.doesNotMatch(o.innerHTML, EMOJI);
  });

  it('экран уже показал свою ошибку компонентом — общий экран поверх не встаёт', async () => {
    const g = bootGuard({ fetchImpl: () => Promise.reject(new TypeError('Load failed')), screenError: true });
    await g.fetch('/api/public/arenas/1').catch(() => {});
    await settle();
    g.runTimers();
    assert.equal(g.overlay(), null);
  });

  it('«Повторить» без связи: сначала проверка /health/live, страница остаётся', async () => {
    const calls = [];
    const g = bootGuard({
      fetchImpl: (u) => { calls.push(u); return Promise.reject(new TypeError('Failed to fetch')); },
    });
    await g.fetch('/api/webapp/client/me').catch(() => {});
    await settle();
    g.runTimers();
    const btn = g.overlay()._btn;
    btn.onclick();
    assert.equal(btn.disabled, true);
    await settle();
    await settle();
    assert.equal(calls[calls.length - 1], '/health/live');
    assert.equal(btn.disabled, false, 'сети нет — кнопка снова доступна');
  });

  for (const [name, r] of [
    ['502', res(502)],
    ['504', res(504)],
    ['503 с X-Ice-Studio-Outage', res(503, { 'X-Ice-Studio-Outage': 'service_unavailable', 'content-type': 'application/json' })],
    ['503 с code=service_unavailable', res(503, { 'content-type': 'application/json' }, { code: 'service_unavailable' })],
  ]) {
    it(`${name} → «Ведутся технические работы», без эмодзи`, async () => {
      const g = bootGuard({ fetchImpl: () => Promise.resolve(r) });
      await g.fetch('/api/webapp/client/me');
      await settle();
      const o = g.overlay();
      assert.ok(o);
      assert.equal(o.getAttribute('data-kind'), 'maintenance');
      assert.match(o.innerHTML, /Ведутся технические работы/);
      assert.match(o.innerHTML, /<svg/);
      assert.doesNotMatch(o.innerHTML, EMOJI);
    });
  }

  it('500 и 503 без метки работ — общего экрана нет (экран сам скажет «Не загрузилось»)', async () => {
    for (const r of [res(500), res(503, { 'content-type': 'application/json' }, { detail: 'x' })]) {
      const g = bootGuard({ fetchImpl: () => Promise.resolve(r) });
      await g.fetch('/api/webapp/client/me');
      await settle();
      g.runTimers();
      assert.equal(g.overlay(), null);
    }
  });
});

describe('экраны приложения рисуют ошибку загрузки одним компонентом', () => {
  const screens = {
    'главная (client-home-main.js)': read('client-home-main.js'),
    'поиск (ice-tab.js)': read('ice-tab.js'),
    'арена (arena-card.js)': read('arena-card.js'),
    'записи (client-bookings.html)': read('client-bookings.html'),
    '«Кто кого» (kto-kogo.js)': read('kto-kogo.js'),
    '«Я» (client-me.js)': read('client-me.js'),
  };
  for (const [name, src] of Object.entries(screens)) {
    it(`${name}: зовёт MiniAppErrorUi, своих текстов ошибки загрузки нет`, () => {
      assert.match(src, /MiniAppErrorUi/);
      assert.doesNotMatch(src, /Похоже, пропала связь|Попробуйте обновить страницу|Не удалось загрузить данные\. Откройте страницу из клиентского бота|НЕ ЗАГРУЗИЛОСЬ|Не удалось загрузить карточку/);
    });
  }

  it('«Кто кого»: все вызовы retryCard — только с обработчиком повтора', () => {
    const files = fs.readdirSync(WEBAPP).filter((f) => /^kto-kogo.*\.js$/.test(f));
    for (const f of files) {
      const calls = read(f).match(/K\.retryCard\([^)]{0,3}/g) || [];
      calls.forEach((c) => assert.doesNotMatch(c, /K\.retryCard\('/, f));
    }
  });

  it('chrome: эмодзи в общем экране нет, «технические работы» только в ветке maintenance', () => {
    assert.doesNotMatch(GUARD, EMOJI);
    assert.equal((CHROME.match(/>Ведутся технические работы</g) || []).length, 1);
  });

  it('«Кто кого»: токены и шрифт игры на body — общие слои не набираются Times', () => {
    const css = read('kto-kogo.css');
    assert.match(css, /^body, \.kk \{\n  --kk-bg/m);
    assert.match(css, /^body\.kk-dark, body\.kk-dark \.kk \{/m);
    assert.match(css, /^body \{[^}]*font-family: var\(--kk-text\)/m);
    assert.match(css, /--miniapp-state-bg: var\(--kk-bg\)/);
  });
});
