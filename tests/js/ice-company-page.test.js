/**
 * Страница «Собрать компанию» (ice-company.html):
 *  - двойной тап = одна компания;
 *  - без сети — понятная ошибка, а не тишина;
 *  - компания создана, чат не открылся — повтор шлёт ту же компанию и есть ссылка;
 *  - ссылка без номера сеанса — объяснение, а не техническая ошибка.
 * Run: node --test tests/js/ice-company-page.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/ice-company.html'), 'utf8');
const script = html.split('<script>').pop().split('</script>')[0];

function el(id) {
  const listeners = {};
  return {
    id, hidden: false, disabled: false, textContent: '', value: '', children: [],
    appendChild(c) { this.children.push(c); },
    addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
    click() { (listeners.click || []).forEach((fn) => fn()); },
  };
}

const json = (body, ok = true, status = 200) => Promise.resolve({ ok, status, json: () => Promise.resolve(body) });
const tick = async (n = 40) => { for (let i = 0; i < n; i += 1) await Promise.resolve(); };

function boot({ search = '?s=7', fetch, tg }) {
  const els = { go: el('go'), err: el('err'), title: el('title'), you: el('you'), hint: el('hint') };
  const calls = [];
  const win = {
    Telegram: tg === null ? undefined : { WebApp: Object.assign({ initData: 'init', ready() {} }, tg || {}) },
  };
  const ctx = vm.createContext({
    window: win,
    location: { search, href: '' },
    URLSearchParams,
    document: { getElementById: (id) => els[id], createElement: () => ({ set href(v) { this._h = v; }, set textContent(v) { this._t = v; } }) },
    fetch: (url, init) => { calls.push({ url: String(url), method: (init && init.method) || 'GET' }); return fetch(String(url), init); },
    Promise, Number, Array, encodeURIComponent, String, console,
  });
  vm.runInContext(script, ctx);
  return { els, calls, ctx };
}

const createdOk = () => json({ public_code: 'abc', page_url: '/k/abc' }, true, 201);
const creates = (calls) => calls.filter((c) => c.url.endsWith('/api/public/ice-companies'));

describe('ice-company.html', () => {
  it('двойной тап «Собрать» — один POST', async () => {
    let release;
    const gate = new Promise((r) => { release = r; });
    const t = boot({
      fetch: (u) => (u.endsWith('/ice-companies') ? gate.then(createdOk) : json({ prepared_message_id: 'm1' })),
      tg: { shareMessage() {} },
    });
    t.els.go.click();
    t.els.go.click();
    release();
    await tick();
    assert.equal(creates(t.calls).length, 1);
  });

  it('без сети: понятная ошибка, кнопка снова живая', async () => {
    const t = boot({ fetch: () => Promise.reject(new TypeError('Failed to fetch')) });
    t.els.go.click();
    await tick();
    assert.match(t.els.err.textContent, /Нет связи/);
    assert.equal(t.els.go.disabled, false);
  });

  it('компания создана, подготовка чата упала: повтор не создаёт вторую, есть ссылка', async () => {
    let prepareFails = true;
    const t = boot({
      fetch: (u) => {
        if (u.endsWith('/ice-companies')) return createdOk();
        return prepareFails ? json({}, false, 500) : json({ prepared_message_id: 'm1' });
      },
      tg: { shareMessage() {} },
    });
    t.els.go.click();
    await tick();
    assert.match(t.els.err.textContent, /Компания создана/);
    assert.equal(t.els.err.children.length, 1, 'ссылка на страницу компании');
    prepareFails = false;
    t.els.go.click();
    await tick();
    assert.equal(creates(t.calls).length, 1, 'вторая компания не создаётся');
    assert.equal(t.calls.filter((c) => c.url.endsWith('/telegram-prepare')).length, 2);
  });

  it('создана, но нет сети на подготовке: сообщение, не тишина', async () => {
    const t = boot({
      fetch: (u) => (u.endsWith('/ice-companies') ? createdOk() : Promise.reject(new TypeError('offline'))),
      tg: { shareMessage() {} },
    });
    t.els.go.click();
    await tick();
    assert.match(t.els.err.textContent, /Компания создана, но нет связи/);
  });

  it('ссылка без номера сеанса: объяснение, запросов нет', async () => {
    for (const search of ['', '?s=', '?s=abc', '?s=0']) {
      const t = boot({ search, fetch: () => json({}) });
      assert.equal(t.els.go.disabled, true, search);
      assert.match(t.els.err.textContent, /без сеанса собирать нечего/, search);
      t.els.go.click();
      await tick();
      assert.equal(t.calls.length, 0, search);
    }
  });

  it('ошибка сервера списком (422) не превращается в [object Object]', async () => {
    const t = boot({ fetch: () => json({ detail: [{ msg: 'Сеанс не найден' }] }, false, 422) });
    t.els.go.click();
    await tick();
    assert.equal(t.els.err.textContent, 'Сеанс не найден');
  });
});
