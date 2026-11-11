/**
 * «Как тебя зовут?» (TASK-373).
 * Run: node --test tests/js/client-name-sheet.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const sheetSrc = fs.readFileSync(path.join(webapp, 'client-sheet.js'), 'utf8');
const nameSrc = fs.readFileSync(path.join(webapp, 'client-name-sheet.js'), 'utf8');
const nameSheet = require(path.join(webapp, 'client-name-sheet.js'));

const FAMILY = '👨‍👩‍👧';
const EMPTY = 'Имя не может быть пустым';
const NET = 'Не сохранилось. Попробуй ещё раз';
const SUB = 'Так тебя увидят в\u00a0таблицах «Кто кого» и\u00a0в\u00a0лигах друзей.';

describe('нормализация как на сервере', () => {
  it('схлопывает пробелы, режет Cc/Cf и оставляет эмодзи с ZWJ', () => {
    assert.equal(nameSheet.normalizeDisplayName('  Макс   К. '), 'Макс К.');
    assert.equal(nameSheet.normalizeDisplayName('Максим 🌱'), 'Максим 🌱');
    assert.equal(nameSheet.normalizeDisplayName('Макс ' + FAMILY), 'Макс ' + FAMILY);
    assert.equal(nameSheet.normalizeDisplayName('Макс\u0007им'), 'Максим');
    assert.equal(nameSheet.normalizeDisplayName('Макс\u200bК'), 'МаксК');
    assert.equal(nameSheet.normalizeDisplayName('\u0000\u200b'), '');
    assert.equal(nameSheet.normalizeDisplayName('   '), '');
    assert.equal(nameSheet.normalizeDisplayName('а\u00a0б'), 'а б');
    assert.equal(nameSheet.normalizeDisplayName('а\u2003б'), 'а б');
    assert.equal(nameSheet.normalizeDisplayName('Макс\nК'), 'МаксК');
    assert.equal(nameSheet.normalizeDisplayName('Макс\tК'), 'МаксК');
    assert.equal(nameSheet.normalizeDisplayName('Макс\u200d'), 'Макс\u200d');
    assert.equal(nameSheet.normalizeDisplayName(null), '');
    assert.ok(nameSheet.normalizeDisplayName(FAMILY).includes('\u200d'));
  });

  it('считает кодовые точки, не единицы UTF-16', () => {
    assert.equal(nameSheet.codePointLength('а'.repeat(40)), 40);
    assert.equal(nameSheet.codePointLength('а'.repeat(41)), 41);
    assert.equal(nameSheet.codePointLength(FAMILY), 5);
    assert.equal(FAMILY.length, 8);
    assert.equal(nameSheet.codePointLength('а'.repeat(35) + FAMILY), 40);
    assert.equal(('а'.repeat(35) + FAMILY).length, 43);
    assert.equal(nameSheet.codePointLength(FAMILY.repeat(8)), 40);
    assert.equal(FAMILY.repeat(8).length, 64);
  });

  it('пустое и «не изменилось» смотрит на нормализованную строку', () => {
    assert.deepEqual(nameSheet.draftState('Макс', '  Макс  '), {
      normalized: 'Макс',
      empty: false,
      changed: false,
      canSave: false,
      hint: '',
    });
    assert.equal(nameSheet.draftState('Макс', '   ').canSave, false);
    assert.equal(nameSheet.draftState('Макс', '   ').hint, EMPTY);
    assert.equal(nameSheet.draftState('Макс', '   ').empty, true);
    assert.equal(nameSheet.draftState('', '').hint, EMPTY);
    assert.equal(nameSheet.draftState('Макс\u0007им', 'Максим').changed, false);
    const changed = nameSheet.draftState('Макс', 'Макс К');
    assert.equal(changed.canSave, true);
    assert.equal(changed.hint, '');
    assert.equal(changed.normalized, 'Макс К');
  });
});

describe('поле не режет ZWJ-кластер', () => {
  it('40 букв остаются, 41-я отсекается целиком', () => {
    assert.equal(nameSheet.fitNameField('а'.repeat(40)), 'а'.repeat(40));
    assert.equal(nameSheet.fitNameField('а'.repeat(41)), 'а'.repeat(40));
    assert.equal(nameSheet.codePointLength(nameSheet.fitNameField('а'.repeat(80))), 40);
  });

  it('семейный эмодзи не рвётся на границе 40 знаков', () => {
    const fits = 'а'.repeat(35) + FAMILY;
    assert.equal(nameSheet.fitNameField(fits), fits);
    assert.equal(nameSheet.codePointLength(fits), 40);
    assert.equal(nameSheet.fitNameField('а'.repeat(36) + FAMILY), 'а'.repeat(36));
    assert.equal(nameSheet.fitNameField('а'.repeat(36) + '👨\u200d'), 'а'.repeat(36));
    assert.equal(nameSheet.fitNameField(FAMILY.repeat(8)), FAMILY.repeat(8));
    assert.equal(nameSheet.fitNameField(FAMILY.repeat(9)), FAMILY.repeat(8));
    assert.equal(nameSheet.fitNameField(FAMILY), FAMILY);
    assert.equal(nameSheet.fitNameField('👨\u200d'), '');
  });
});

describe('тексты шторки', () => {
  it('совпадают с макетом и не подмешивают цвет', () => {
    assert.match(nameSrc, /Как тебя зовут\?/);
    assert.match(nameSrc, /Так тебя увидят в\\u00a0таблицах «Кто кого» и\\u00a0в\\u00a0лигах друзей\./);
    assert.match(nameSrc, /Имя не может быть пустым/);
    assert.match(nameSrc, /Не сохранилось\. Попробуй ещё раз/);
    assert.match(nameSrc, /Сохранить/);
    assert.equal(nameSrc.match(/#[0-9a-fA-F]{3,8}/g), null);
  });
});

function matchesOne(el, sel) {
  if (sel === 'a[href]') return el.tagName === 'A' && el.hasAttribute('href');
  const not = sel.match(/^(\w+):not\(\[disabled\]\)$/);
  if (not) return el.tagName === not[1].toUpperCase() && !el.disabled;
  if (sel === '[tabindex]:not([tabindex="-1"])') {
    return el.hasAttribute('tabindex') && el.getAttribute('tabindex') !== '-1';
  }
  const attr = sel.match(/^\[([\w-]+)="([^"]*)"\]$/);
  if (attr) return el.getAttribute(attr[1]) === attr[2];
  if (sel[0] === '.') return el.classList.contains(sel.slice(1));
  if (sel[0] === '#') return el.id === sel.slice(1);
  if (/^[a-z][a-z0-9]*$/i.test(sel)) return el.tagName === sel.toUpperCase();
  return false;
}

function matches(el, selector) {
  return String(selector).split(',').some((part) => matchesOne(el, part.trim()));
}

function walk(el, sel, out) {
  if (!el || !el.tagName) return;
  if (sel === '*' || matches(el, sel)) out.push(el);
  for (const child of el.children) walk(child, sel, out);
}

class El {
  constructor(tag, doc) {
    this.tagName = String(tag).toUpperCase();
    this.doc = doc;
    this.attrs = {};
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this._text = '';
    this._disabled = false;
    this.id = '';
    this.classList = {
      _s: new Set(),
      add(...names) { names.forEach((name) => this._s.add(name)); },
      remove(...names) { names.forEach((name) => this._s.delete(name)); },
      contains: (name) => this.classList._s.has(name),
      toggle(name, force) {
        const on = force === undefined ? !this._s.has(name) : !!force;
        if (on) this._s.add(name);
        else this._s.delete(name);
      },
    };
    this.style = {};
    this.nodeType = 1;
    this.value = '';
    this.selectionStart = 0;
    this.selectionEnd = 0;
    this.maxLength = -1;
  }

  get textContent() {
    if (this.children.length) return this.children.map((child) => child.textContent).join('');
    return this._text;
  }

  set textContent(value) {
    this._text = value == null ? '' : String(value);
    this.children = [];
  }

  get disabled() { return this._disabled; }

  set disabled(value) {
    this._disabled = !!value;
    if (this._disabled) this.attrs.disabled = '';
    else delete this.attrs.disabled;
  }

  get className() { return [...this.classList._s].join(' '); }

  set className(value) {
    this.classList._s = new Set(String(value || '').split(/\s+/).filter(Boolean));
  }

  get firstChild() { return this.children[0] || null; }

  get isConnected() {
    let node = this;
    while (node.parentNode) node = node.parentNode;
    return node === this.doc.documentElement;
  }

  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name === 'id') this.id = String(value);
    if (name === 'class') this.className = String(value);
    if (name === 'maxlength') this.maxLength = Number(value);
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
  }

  hasAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name); }

  removeAttribute(name) { delete this.attrs[name]; }

  appendChild(child) {
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.children.push(child);
    this._text = '';
    return child;
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }

  addEventListener(type, fn) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(fn);
  }

  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((item) => item !== fn);
  }

  dispatch(type, event) {
    const ev = Object.assign({ bubbles: true }, event || {});
    ev.target = ev.target || this;
    ev.preventDefault = () => { ev.defaultPrevented = true; };
    let node = this;
    while (node) {
      const list = (node.listeners && node.listeners[type]) ? node.listeners[type].slice() : [];
      for (const fn of list) fn(ev);
      if (!ev.bubbles || !node.parentNode) break;
      node = node.parentNode;
    }
    return ev;
  }

  focus() { this.doc.activeElement = this; }

  setSelectionRange(start, end) {
    this.selectionStart = start;
    this.selectionEnd = end;
  }

  contains(node) {
    if (node === this) return true;
    return this.children.some((child) => child.contains(node));
  }

  closest(sel) {
    let node = this;
    while (node && node.tagName) {
      if (matches(node, sel)) return node;
      node = node.parentNode;
    }
    return null;
  }

  querySelectorAll(sel) {
    const all = [];
    for (const child of this.children) walk(child, sel, all);
    return all;
  }

  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function flush() {
  for (let i = 0; i < 8; i += 1) await tick();
}

function harness(options) {
  options = options || {};
  const calls = [];
  const haptic = [];
  const rafQueue = [];
  const document = {
    activeElement: null,
    documentElement: null,
    body: null,
    head: null,
    listeners: {},
    createElement(tag) { return new El(tag, document); },
    createElementNS(_ns, tag) { return new El(tag, document); },
    addEventListener(type, fn) {
      if (!this.listeners[type]) this.listeners[type] = [];
      this.listeners[type].push(fn);
    },
    removeEventListener(type, fn) {
      this.listeners[type] = (this.listeners[type] || []).filter((item) => item !== fn);
    },
    getElementById(id) {
      const all = [];
      walk(document.documentElement, '*', all);
      return all.find((node) => node.id === id) || null;
    },
    querySelector(sel) {
      const all = [];
      walk(document.documentElement, sel, all);
      return all[0] || null;
    },
    querySelectorAll(sel) {
      const all = [];
      walk(document.documentElement, sel, all);
      return all;
    },
  };
  const html = new El('html', document);
  const head = new El('head', document);
  const body = new El('body', document);
  html.appendChild(head);
  html.appendChild(body);
  document.documentElement = html;
  document.head = head;
  document.body = body;
  document.activeElement = body;

  let saveGate = null;
  const sandbox = {
    document,
    console,
    URLSearchParams,
    JSON,
    location: { search: options.search || '' },
    matchMedia() { return { matches: true }; },
    requestAnimationFrame(fn) {
      if (options.queueRaf) rafQueue.push(fn);
      else fn();
      return rafQueue.length;
    },
    setTimeout(fn) { fn(); return 0; },
    clearTimeout() {},
    scrollY: 0,
    scrollTo() {},
    fetch(url, opts) {
      const call = { url: String(url), opts };
      calls.push(call);
      if (options.hangSave) {
        return new Promise((resolve, reject) => { saveGate = { resolve, reject }; });
      }
      if (options.saveReject) return Promise.reject(new Error('offline'));
      const saved = options.save || { ok: true, status: 200, body: { name: 'Макс' } };
      return Promise.resolve({
        ok: saved.ok,
        status: saved.status,
        json: () => Promise.resolve(saved.body),
      });
    },
    Telegram: options.telegram === false ? undefined : {
      WebApp: {
        initData: options.initData == null ? 'init-1' : options.initData,
        HapticFeedback: { notificationOccurred(kind) { haptic.push(kind); } },
      },
    },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(sheetSrc, sandbox);
  vm.runInContext(nameSrc, sandbox);
  return {
    sandbox,
    document,
    calls,
    haptic,
    rafQueue,
    saveGate: () => saveGate,
    flushRaf() {
      const batch = rafQueue.splice(0, rafQueue.length);
      batch.forEach((fn) => fn());
    },
  };
}

function inputOf(sheet) {
  return sheet.el.querySelector('.cn-input');
}

function saveOf(sheet) {
  return sheet.el.querySelector('.cn-save');
}

describe('ClientNameSheet', () => {
  it('открывает макет: имя в поле, курсор в конце после фокуса листа', () => {
    const h = harness({ queueRaf: true });
    const sheet = h.sandbox.ClientNameSheet.open({ current: 'Макс' });
    const input = inputOf(sheet);
    assert.equal(input.value, 'Макс');
    assert.notEqual(h.document.activeElement, input);
    h.flushRaf();
    assert.equal(h.document.activeElement, sheet.el);
    assert.notEqual(h.document.activeElement, input);
    h.flushRaf();
    assert.equal(h.document.activeElement, input);
    assert.equal(input.selectionStart, 'Макс'.length);
    assert.equal(input.selectionEnd, 'Макс'.length);
    assert.equal(sheet.el.getAttribute('aria-labelledby'), 'cn-title');
    assert.equal(sheet.el.querySelector('.cn-title').textContent, 'Как тебя зовут?');
    assert.equal(sheet.el.querySelector('.cn-sub').textContent, SUB);
    assert.equal(sheet.el.querySelector('.cs-sr').textContent, 'Имя');
    assert.equal(input.getAttribute('maxlength'), '40');
    assert.equal(input.getAttribute('autocomplete'), 'nickname');
    assert.equal(input.getAttribute('enterkeyhint'), 'done');
    assert.equal(saveOf(sheet).textContent, 'Сохранить');
    assert.equal(saveOf(sheet).disabled, true);
    assert.equal(sheet.el.querySelector('.cn-hint').textContent, '');
    assert.equal(input.classList.contains('is-filled'), true);
  });

  it('пустое имя: подсказка на месте, кнопка неактивна, место подсказки не снимается', () => {
    const h = harness();
    const sheet = h.sandbox.ClientNameSheet.open({ current: '   ' });
    const input = inputOf(sheet);
    assert.equal(h.document.activeElement, input);
    assert.equal(input.selectionStart, input.value.length);
    assert.equal(sheet.el.querySelector('.cn-hint').textContent, EMPTY);
    assert.equal(sheet.el.querySelector('.cn-hint').className, 'cn-hint');
    assert.equal(saveOf(sheet).disabled, true);
    assert.equal(input.classList.contains('is-filled'), false);
    input.value = 'Макс';
    input.dispatch('input', {});
    assert.equal(sheet.el.querySelector('.cn-hint').textContent, '');
    assert.equal(saveOf(sheet).disabled, false);
    assert.equal(input.classList.contains('is-filled'), true);
  });

  it('не шлёт запрос, пока имя то же после схлопывания пробелов', () => {
    const h = harness();
    const sheet = h.sandbox.ClientNameSheet.open({ current: 'Макс К' });
    const input = inputOf(sheet);
    input.value = '  Макс   К ';
    input.dispatch('input', {});
    assert.equal(saveOf(sheet).disabled, true);
    assert.equal(sheet.el.querySelector('.cn-hint').textContent, '');
    input.dispatch('keydown', { key: 'Enter' });
    saveOf(sheet).dispatch('click', {});
    assert.equal(h.calls.length, 0);
  });

  it('ввод режет 41-ю букву и не оставляет оборванный ZWJ', () => {
    const h = harness();
    const sheet = h.sandbox.ClientNameSheet.open({ current: '' });
    const input = inputOf(sheet);
    input.value = 'а'.repeat(41);
    input.selectionStart = 41;
    input.dispatch('input', {});
    assert.equal(input.value, 'а'.repeat(40));
    assert.equal(nameSheet.codePointLength(input.value), 40);
    input.value = 'а'.repeat(36) + FAMILY;
    input.dispatch('input', {});
    assert.equal(input.value, 'а'.repeat(36));
    assert.equal(input.value.includes('\u200d'), false);
    const kept = 'а'.repeat(35) + FAMILY;
    input.value = kept;
    input.dispatch('input', {});
    assert.equal(input.value, kept);
    assert.equal(input.value.length, 43);
    assert.equal(nameSheet.codePointLength(input.value), 40);
  });

  it('вставка через beforeinput оставляет семейный эмодзи, если он умещается в 40 знаков', () => {
    const h = harness();
    const sheet = h.sandbox.ClientNameSheet.open({ current: '' });
    const input = inputOf(sheet);
    input.selectionStart = 0;
    input.selectionEnd = 0;
    const kept = 'а'.repeat(35) + FAMILY;
    const ok = input.dispatch('beforeinput', {
      cancelable: true,
      inputType: 'insertText',
      data: kept,
    });
    assert.equal(ok.defaultPrevented, true);
    assert.equal(input.value, kept);
    assert.equal(nameSheet.codePointLength(input.value), 40);
    assert.equal(input.selectionStart, kept.length);
    input.value = '';
    input.selectionStart = 0;
    input.selectionEnd = 0;
    input.dispatch('beforeinput', {
      cancelable: true,
      inputType: 'insertFromPaste',
      data: 'а'.repeat(36) + FAMILY,
    });
    assert.equal(input.value, 'а'.repeat(36));
    assert.equal(input.value.includes('\u200d'), false);
    input.value = 'а'.repeat(40);
    input.selectionStart = 40;
    input.selectionEnd = 40;
    input.dispatch('beforeinput', { cancelable: true, inputType: 'insertText', data: 'б' });
    assert.equal(input.value, 'а'.repeat(40));
  });

  it('открывает серверное имя из эмодзи длиннее 40 единиц UTF-16', () => {
    const stored = FAMILY.repeat(8);
    const h = harness();
    const sheet = h.sandbox.ClientNameSheet.open({ current: stored });
    const input = inputOf(sheet);
    assert.equal(input.value, stored);
    assert.equal(input.selectionStart, stored.length);
    assert.equal(input.getAttribute('maxlength'), '40');
    assert.equal(saveOf(sheet).disabled, true);
  });

  it('Enter и кнопка сохраняют value, 200 закрывает и отдаёт имя из ответа', async () => {
    const saved = [];
    const h = harness({ save: { ok: true, status: 200, body: { name: 'Макс К' } } });
    const sheet = h.sandbox.ClientNameSheet.open({
      current: 'Макс',
      onSaved(next) { saved.push(next); },
    });
    const input = inputOf(sheet);
    input.value = '  Макс   К ';
    input.dispatch('input', {});
    const enter = input.dispatch('keydown', { key: 'Enter' });
    assert.equal(enter.defaultPrevented, true);
    await flush();
    assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].url, '/api/webapp/client/me/name');
    assert.equal(h.calls[0].opts.method, 'PUT');
    assert.equal(h.calls[0].opts.headers['Content-Type'], 'application/json');
    assert.equal(h.calls[0].opts.headers['X-Telegram-Init-Data'], 'init-1');
    assert.equal(h.calls[0].opts.body, '{"name":"  Макс   К "}');
    assert.deepEqual(h.haptic, ['success']);
    assert.deepEqual(saved, ['Макс К']);
    assert.equal(sheet.el.isConnected, false);
  });

  it('422 «Имя — от 1 до 40 знаков» (пустое по счёту сервера) — клиентская фраза «Имя не может быть пустым»', async () => {
    const h = harness({ save: { ok: false, status: 422, body: { detail: 'Имя — от 1 до 40 знаков' } } });
    const sheet = h.sandbox.ClientNameSheet.open({ current: 'Макс' });
    const input = inputOf(sheet);
    input.value = 'Лена';
    input.dispatch('input', {});
    saveOf(sheet).dispatch('click', {});
    await flush();
    assert.equal(h.calls.length, 1);
    assert.equal(sheet.el.querySelector('.cn-hint').textContent, 'Имя не может быть пустым');
    assert.equal(input.value, 'Лена');
  });

  it('422 оставляет ввод и пишет detail, сеть — свою фразу, без второго запроса', async () => {
    const h = harness({
      hangSave: true,
      save: { ok: false, status: 422, body: { detail: 'Имя занято' } },
    });
    const sheet = h.sandbox.ClientNameSheet.open({ current: 'Макс' });
    const input = inputOf(sheet);
    const save = saveOf(sheet);
    input.value = 'Новое';
    input.dispatch('input', {});
    save.dispatch('click', {});
    save.dispatch('click', {});
    input.dispatch('keydown', { key: 'Enter' });
    assert.equal(h.calls.length, 1);
    assert.equal(save.disabled, true);
    assert.equal(input.value, 'Новое');
    h.saveGate().resolve({
      ok: false,
      status: 422,
      json: () => Promise.resolve({ detail: 'Имя занято' }),
    });
    await flush();
    assert.equal(sheet.el.isConnected, true);
    assert.equal(input.value, 'Новое');
    assert.equal(sheet.el.querySelector('.cn-hint').textContent, 'Имя занято');
    assert.equal(save.disabled, false);
    assert.deepEqual(h.haptic, []);

    const offline = harness({ saveReject: true });
    const again = offline.sandbox.ClientNameSheet.open({ current: 'Макс' });
    inputOf(again).value = 'Лена';
    inputOf(again).dispatch('input', {});
    saveOf(again).dispatch('click', {});
    await flush();
    assert.equal(again.el.isConnected, true);
    assert.equal(inputOf(again).value, 'Лена');
    assert.equal(again.el.querySelector('.cn-hint').textContent, NET);
    assert.equal(saveOf(again).disabled, false);
  });

  it('берёт init_data из адреса, если Telegram его не дал', async () => {
    const h = harness({ telegram: false, search: '?init_data=from-url' });
    const sheet = h.sandbox.ClientNameSheet.open({ current: 'Макс' });
    inputOf(sheet).value = 'Лена';
    inputOf(sheet).dispatch('input', {});
    saveOf(sheet).dispatch('click', {});
    await flush();
    assert.equal(h.calls[0].opts.headers['X-Telegram-Init-Data'], 'from-url');
  });
});
