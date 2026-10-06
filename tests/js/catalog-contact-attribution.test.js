/**
 * TASK-202: подпись «упомяните Glide» под «Написать тренеру» в каталоге.
 * Run: node --test tests/js/catalog-contact-attribution.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../..');
const modelPath = path.join(ROOT, 'static/webapp/catalog-contact-attribution.js');
const mainSrc = fs.readFileSync(path.join(ROOT, 'static/webapp/catalog-main.js'), 'utf8');
const catalogHtml = fs.readFileSync(path.join(ROOT, 'static/webapp/catalog.html'), 'utf8');

const EXACT = 'Если не сложно, упомяните, пожалуйста, что вы из Glide';

function loadModel() {
  delete require.cache[require.resolve(modelPath)];
  return require(modelPath);
}

/** Минимальный DOM: плоский список детей, innerHTML-пересборка = новые узлы без подписи. */
function makeContainer() {
  const doc = {
    createElement(tag) {
      return makeNode(tag, doc);
    },
  };
  const container = makeNode('div', doc);
  return { container, doc };
}

function makeNode(tag, doc) {
  const node = {
    tagName: tag.toUpperCase(),
    ownerDocument: doc,
    className: '',
    attrs: {},
    children: [],
    parentNode: null,
    textContent: '',
    _html: null,
    getAttribute(k) {
      return this.attrs[k] == null ? null : this.attrs[k];
    },
    setAttribute(k, v) {
      this.attrs[k] = String(v);
    },
    get nextSibling() {
      if (!this.parentNode) return null;
      const sibs = this.parentNode.children;
      return sibs[sibs.indexOf(this) + 1] || null;
    },
    appendChild(child) {
      child.parentNode = this;
      this.children.push(child);
      return child;
    },
    removeChild(child) {
      this.children.splice(this.children.indexOf(child), 1);
      child.parentNode = null;
      return child;
    },
    insertAdjacentElement(where, el) {
      assert.equal(where, 'afterend');
      if (el.parentNode) el.parentNode.removeChild(el);
      const sibs = this.parentNode.children;
      sibs.splice(sibs.indexOf(this) + 1, 0, el);
      el.parentNode = this.parentNode;
      return el;
    },
    querySelector(sel) {
      const match = (n) => {
        if (sel === '[data-action="contact-trainer"]') return n.attrs['data-action'] === 'contact-trainer';
        if (sel.startsWith('.')) return n.className.split(/\s+/).includes(sel.slice(1));
        throw new Error('unsupported selector ' + sel);
      };
      return this.children.find(match) || null;
    },
    /** Имитирует `innerHTML +=`: все дети пересоздаются, подпись (не кнопка) теряется. */
    rebuildLikeInnerHtml(extraButton) {
      const kept = this.children.filter((c) => c.attrs['data-action']);
      this.children = [];
      kept.forEach((c) => this.appendChild(makeButton(doc, c.attrs['data-action'])));
      if (extraButton) this.appendChild(makeButton(doc, extraButton));
    },
  };
  return node;
}

function makeButton(doc, action) {
  const b = doc.createElement('button');
  b.setAttribute('data-action', action);
  return b;
}

describe('catalog contact attribution (TASK-202)', () => {
  it('текст подписи ровно как решил владелец', () => {
    const m = loadModel();
    assert.equal(m.HINT, EXACT);
    assert.equal(m.hintText(), EXACT);
  });

  it('подпись встаёт сразу под кнопкой «Написать тренеру», через textContent', () => {
    const { ensureHint } = loadModel();
    const { container, doc } = makeContainer();
    container.appendChild(makeButton(doc, 'book'));
    const btn = container.appendChild(makeButton(doc, 'contact-trainer'));
    container.appendChild(makeButton(doc, 'leave-request'));
    const hint = ensureHint(container);
    assert.ok(hint);
    assert.equal(btn.nextSibling, hint);
    assert.equal(hint.textContent, EXACT);
    assert.match(hint.className, /trainer-contact-hint/);
    assert.equal(hint._html, null, 'innerHTML не используется');
  });

  it('AC-2: переживает innerHTML-пересборку и не дублируется', () => {
    const { ensureHint } = loadModel();
    const { container, doc } = makeContainer();
    container.appendChild(makeButton(doc, 'contact-trainer'));
    ensureHint(container);
    container.rebuildLikeInnerHtml('leave-request');
    assert.equal(container.querySelector('.trainer-contact-hint'), null, 'пересборка стёрла подпись');
    ensureHint(container);
    ensureHint(container);
    const hints = container.children.filter((c) => /trainer-contact-hint/.test(c.className));
    assert.equal(hints.length, 1);
    assert.equal(container.querySelector('[data-action="contact-trainer"]').nextSibling, hints[0]);
  });

  it('нет кнопки связи — нет подписи', () => {
    const { ensureHint } = loadModel();
    const { container, doc } = makeContainer();
    container.appendChild(makeButton(doc, 'leave-request'));
    assert.equal(ensureHint(container), null);
    assert.equal(container.children.length, 1);
  });

  it('catalog-main ставит подпись после каждой пересборки блока с кнопкой связи', () => {
    const calls = mainSrc.match(/[^\w ] *appendContactTrainerButton\((\w+),/g) || [];
    assert.equal(calls.length, 4);
    calls.forEach((c) => {
      const el = c.match(/\((\w+),/)[1];
      const re = new RegExp(
        el + '\\.innerHTML \\+= [^\\n]+\\n(?:[^\\n]*\\n){0,3}?\\s*ensureCatalogContactHint\\(' + el + '\\);'
      );
      assert.match(mainSrc, re, 'нет ensureCatalogContactHint(' + el + ') после innerHTML +=');
    });
  });

  it('без автотекста в Telegram: ссылки связи не получают text=/start=', () => {
    const fn = mainSrc.match(/function trainerContactTelegramUrl[\s\S]*?\n {6}\}/)[0];
    assert.doesNotMatch(fn, /text=|start=|src=/);
  });

  it('catalog.html грузит модуль до catalog-main.js', () => {
    const iMod = catalogHtml.indexOf('<script src="catalog-contact-attribution.js?v=');
    const iMain = catalogHtml.indexOf('<script defer src="catalog-main.js?v=');
    assert.ok(iMod > 0 && iMain > iMod);
  });
});
