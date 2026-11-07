/**
 * TASK-350: окно «Показывать вас родителям на страницах катков?» — кому показываем и что пишем.
 * Run: node --test tests/js/trainer-catalog-offer.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const O = require(path.resolve(__dirname, '../../static/webapp/trainer-catalog-offer.js'));

describe('TrainerCatalogOffer', () => {
  it('offers only a ready draft the trainer can publish himself', () => {
    const ready = { state: 'draft', can_act: true, readiness: { submit_ready: true } };
    assert.equal(O.eligible(ready), true);
    assert.equal(O.eligible({ ...ready, state: 'hidden' }), false, 'снял сам — не спорим с решением');
    assert.equal(O.eligible({ ...ready, state: 'published' }), false);
    assert.equal(O.eligible({ ...ready, can_act: false }), false, 'карточкой управляет студия');
    assert.equal(O.eligible({ ...ready, readiness: { submit_ready: false } }), false, 'POST вернул бы 422');
    assert.equal(O.eligible(null), false);
  });

  it('says "on rink pages" for rink trainers and "in Glide" for online ones', () => {
    assert.equal(O.onRinks({ arena_names: ['ТЦ Замок'] }), true);
    assert.equal(O.onRinks({ arena_names: ['ТЦ Замок', 'Чижовка'] }), true);
    assert.equal(O.onRinks({ arena_names: ['А'], arena_work_format: 'online' }), false);
    assert.equal(O.onRinks({}), false);
    const rink = openWith({ preview: { arena_names: ['Чижовка'] } });
    assert.match(rink.box.innerHTML, /Показывать вас родителям на страницах катков\?/);
    const online = openWith({ preview: { arena_work_format: 'online', arena_names: [] } });
    assert.match(online.box.innerHTML, /Показывать вас родителям в Glide\?/);
  });

  it('network failure on publish shows an error in the note and re-enables the button', async () => {
    const ui = openWith({ preview: { arena_names: ['Чижовка'] } }, () => Promise.reject(new TypeError('Failed to fetch')));
    const yes = ui.el('[data-tco-yes]');
    yes.onclick();
    assert.equal(yes.disabled, true);
    assert.equal(yes.textContent, 'Публикуем…');
    await new Promise((r) => setImmediate(r));
    assert.equal(yes.disabled, false);
    assert.equal(yes.textContent, 'Показать меня');
    const note = ui.el('.tco-note');
    assert.equal(note.textContent, 'Нет связи — попробуйте ещё раз.');
    assert.equal(note.attrs.role, 'alert');
  });
});

/** Минимальный DOM: ровно то, что трогает окно (data-tco-* и .tco-note из innerHTML). */
function openWith(profile, fetchImpl) {
  const found = {};
  const mk = () => ({
    attrs: {}, textContent: '', disabled: false, children: [],
    setAttribute(k, v) { this.attrs[k] = v; },
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    removeChild() {},
    querySelector(sel) { return found[sel] || null; },
  });
  const box = mk();
  let html = '';
  Object.defineProperty(box, 'innerHTML', {
    get: () => html,
    set(v) {
      html = v;
      Object.keys(found).forEach((k) => delete found[k]);
      for (const m of v.matchAll(/<(?:button|p|span)\b[^>]*?\b(data-tco-[a-z]+)[^>]*>/g)) found['[' + m[1] + ']'] = mk();
      if (/class="tco-note"/.test(v)) found['.tco-note'] = mk();
    },
  });
  const doc = { getElementById: () => ({}), head: mk(), body: mk() };
  // Первый div — подложка, второй — окно; подложка получает окно через appendChild.
  const back = mk();
  doc.createElement = (tag) => (tag === 'div' ? (doc.__n = (doc.__n || 0) + 1) === 1 ? back : box : mk());
  const prev = { document: globalThis.document, localStorage: globalThis.localStorage };
  globalThis.document = doc;
  const win = { document: doc, fetch: fetchImpl || (() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })) };
  // Окно берёт document/fetch из `global` модуля — подменяем на время вызова.
  const g = globalThis;
  const old = { fetch: g.fetch, localStorage: g.localStorage };
  g.fetch = win.fetch;
  g.localStorage = { getItem: () => null, setItem() {} };
  try {
    O.render(Object.assign({ preview: {} }, profile), { apiUrl: (p) => p, headers: () => ({}) });
  } finally {
    g.fetch = old.fetch;
    if (old.localStorage === undefined) delete g.localStorage; else g.localStorage = old.localStorage;
    g.document = prev.document;
  }
  g.fetch = win.fetch; // клик по кнопке происходит позже
  return { box, el: (sel) => found[sel], restore: () => { g.fetch = old.fetch; } };
}
