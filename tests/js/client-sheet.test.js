/**
 * Базовая шторка «Я» (TASK-371 S1).
 * Run: node --test tests/js/client-sheet.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const sheetSrc = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/client-sheet.js'), 'utf8');
const sheetCss = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/client-sheet.css'), 'utf8');

function matchesOne(el, sel) {
  if (sel === 'a[href]') return el.tagName === 'A' && el.hasAttribute('href');
  let m = sel.match(/^(\w+):not\(\[disabled\]\)$/);
  if (m) return el.tagName === m[1].toUpperCase() && !el.disabled;
  if (sel === '[tabindex]:not([tabindex="-1"])') {
    return el.hasAttribute('tabindex') && el.getAttribute('tabindex') !== '-1';
  }
  m = sel.match(/^\[([\w-]+)="([^"]*)"\]$/);
  if (m) return el.getAttribute(m[1]) === m[2];
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
  if (matches(el, sel)) out.push(el);
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
    this.classList = createClassList(this);
    this.style = new Proxy({}, {
      get(target, key) {
        if (typeof key !== 'string') return target[key];
        return Object.prototype.hasOwnProperty.call(target, key) ? target[key] : '';
      },
      set(target, key, value) {
        target[key] = value == null ? '' : String(value);
        return true;
      },
    });
    this.nodeType = 1;
    this.checked = false;
    this.value = '';
  }

  get textContent() {
    if (this.children.length) return this.children.map((child) => child.textContent).join('');
    return this._text;
  }

  set textContent(value) {
    this._text = value == null ? '' : String(value);
    this.children = [];
  }

  get disabled() {
    return this._disabled;
  }

  set disabled(value) {
    this._disabled = !!value;
    if (this._disabled) this.attrs.disabled = '';
    else delete this.attrs.disabled;
  }

  get className() {
    return [...this.classList._s].join(' ');
  }

  set className(value) {
    this.classList._s = new Set(String(value || '').split(/\s+/).filter(Boolean));
  }

  get isConnected() {
    let node = this;
    while (node.parentNode) node = node.parentNode;
    return node === this.doc.documentElement;
  }

  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name === 'id') this.id = String(value);
    if (name === 'class') this.className = String(value);
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
  }

  hasAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name);
  }

  removeAttribute(name) {
    delete this.attrs[name];
  }

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
    const ev = event || {};
    ev.target = ev.target || this;
    ev.currentTarget = this;
    ev.bubbles = ev.bubbles !== false;
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

  focus() {
    this.doc.activeElement = this;
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

  querySelector(sel) {
    const all = [];
    for (const child of this.children) walk(child, sel, all);
    return all[0] || null;
  }

  querySelectorAll(sel) {
    const all = [];
    for (const child of this.children) walk(child, sel, all);
    return all;
  }
}

function createClassList(el) {
  const list = {
    _s: new Set(),
    add(...names) { names.forEach((name) => this._s.add(name)); },
    remove(...names) { names.forEach((name) => this._s.delete(name)); },
    contains(name) { return this._s.has(name); },
    toggle(name, force) {
      const on = force === undefined ? !this._s.has(name) : !!force;
      if (on) this._s.add(name);
      else this._s.delete(name);
      return on;
    },
  };
  return list;
}

function makeHarness(options) {
  options = options || {};
  const timeouts = [];
  let timerId = 0;
  const vvListeners = { resize: [], scroll: [] };
  const backClicks = [];
  let backHandler = null;
  const back = {
    isVisible: !!options.backVisible,
    show() { this.isVisible = true; backClicks.push('show'); },
    hide() { this.isVisible = false; backClicks.push('hide'); },
    onClick(fn) { backHandler = fn; backClicks.push('on'); },
    offClick(fn) {
      if (backHandler === fn) backHandler = null;
      backClicks.push('off');
    },
  };
  const document = {
    activeElement: null,
    documentElement: null,
    body: null,
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
    dispatch(type, event) {
      const ev = event || {};
      ev.target = ev.target || document.body;
      ev.preventDefault = () => { ev.defaultPrevented = true; };
      const list = (this.listeners[type] || []).slice();
      for (const fn of list) fn(ev);
      return ev;
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
    contains(node) {
      return !!(node && (node === document.documentElement || document.documentElement.contains(node)));
    },
  };
  const html = new El('html', document);
  const body = new El('body', document);
  html.appendChild(body);
  html.parentNode = null;
  document.documentElement = html;
  document.body = body;
  document.activeElement = body;

  const sandbox = {
    document,
    console,
    Math,
    setTimeout(fn, ms) {
      timerId += 1;
      const id = timerId;
      timeouts.push({ id, fn, ms });
      return id;
    },
    clearTimeout(id) {
      const index = timeouts.findIndex((item) => item.id === id);
      if (index >= 0) timeouts.splice(index, 1);
    },
    requestAnimationFrame(fn) { fn(); },
    matchMedia(query) {
      return {
        matches: !!options.reduced && String(query).includes('prefers-reduced-motion'),
      };
    },
    visualViewport: {
      height: options.vvHeight == null ? 700 : options.vvHeight,
      offsetTop: options.vvTop == null ? 0 : options.vvTop,
      addEventListener(type, fn) { vvListeners[type].push(fn); },
      removeEventListener(type, fn) {
        vvListeners[type] = vvListeners[type].filter((item) => item !== fn);
      },
    },
    scrollY: options.scrollY || 0,
    pageYOffset: options.scrollY || 0,
    scrollTo(_x, y) { sandbox.scrollY = y; },
    Telegram: options.telegram === false ? undefined : { WebApp: { BackButton: back } },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(sheetSrc, sandbox);
  return {
    sandbox,
    document,
    body,
    timeouts,
    back,
    backClicks,
    pressBack() { if (backHandler) backHandler(); },
    fireViewport(type) { vvListeners[type].slice().forEach((fn) => fn()); },
    flush() {
      const queued = timeouts.splice(0, timeouts.length);
      queued.forEach((item) => item.fn());
    },
  };
}

function opener(h) {
  const button = h.document.createElement('button');
  button.textContent = 'Клуб';
  h.body.appendChild(button);
  button.focus();
  return button;
}

function contentOf(h, id) {
  const wrap = h.document.createElement('div');
  const title = h.document.createElement('h2');
  title.id = id || 'sheetTitle';
  title.setAttribute('id', title.id);
  title.textContent = 'Заголовок';
  const list = h.document.createElement('div');
  list.className = 'cs-scroll';
  const input = h.document.createElement('input');
  list.appendChild(input);
  const action = h.document.createElement('button');
  action.textContent = 'Готово';
  wrap.appendChild(title);
  wrap.appendChild(list);
  wrap.appendChild(action);
  return wrap;
}

describe('client-sheet.css', () => {
  it('берёт вид из спеки и не подставляет свои цвета', () => {
    assert.match(sheetCss, /rgba\(13,27,38,\.48\)/);
    assert.match(sheetCss, /220ms cubic-bezier\(\.2,\.8,\.2,1\)/);
    assert.match(sheetCss, /border-radius:\s*24px 24px 0 0/);
    assert.match(sheetCss, /width:\s*40px/);
    assert.match(sheetCss, /height:\s*4px/);
    assert.match(sheetCss, /border-radius:\s*2px/);
    assert.match(sheetCss, /calc\(100dvh - 100px\)/);
    assert.match(sheetCss, /padding:\s*10px 16px calc\(20px \+ env\(safe-area-inset-bottom/);
    assert.match(sheetCss, /var\(--g-surface\)/);
    assert.match(sheetCss, /var\(--g-line-strong\)/);
    assert.match(sheetCss, /prefers-reduced-motion:\s*reduce/);
    assert.equal(sheetCss.match(/#[0-9a-fA-F]{3,8}/g), null);
  });
});

describe('ClientSheet', () => {
  it('открывает одну модалку, переносит фокус и блокирует прокрутку страницы', () => {
    const h = makeHarness({ scrollY: 40, vvHeight: 700, vvTop: 12 });
    const button = opener(h);
    const sheet = h.sandbox.ClientSheet.open({
      labelledBy: 'sheetTitle',
      content: contentOf(h),
    });
    assert.equal(sheet.el.getAttribute('role'), 'dialog');
    assert.equal(sheet.el.getAttribute('aria-modal'), 'true');
    assert.equal(sheet.el.getAttribute('aria-labelledby'), 'sheetTitle');
    assert.equal(h.document.activeElement, sheet.el);
    assert.equal(h.body.style.overflow, 'hidden');
    assert.equal(h.document.documentElement.style.overflow, 'hidden');
    assert.equal(h.body.style.position, 'fixed');
    assert.equal(h.body.style.top, '-40px');
    assert.equal(h.sandbox.document.querySelector('.cs-root').style.top, '12px');
    assert.equal(h.sandbox.document.querySelector('.cs-root').style.height, '700px');
    assert.equal(sheet.el.style.maxHeight, '600px');
    assert.equal(h.backClicks[0], 'on');
    assert.equal(h.backClicks[1], 'show');
    assert.equal(h.back.isVisible, true);
    assert.notEqual(h.document.activeElement, button);
  });

  it('закрывается по подложке, Esc, close() и свайпу длиннее 80 px и возвращает фокус', () => {
    const h = makeHarness({ scrollY: 80 });
    const button = opener(h);
    const sheet = h.sandbox.ClientSheet.open({ labelledBy: 'sheetTitle', content: contentOf(h) });
    h.document.dispatch('keydown', { key: 'Escape' });
    assert.equal(h.timeouts.length, 1);
    assert.equal(h.timeouts[0].ms, 220);
    assert.equal(sheet.el.isConnected, true);
    h.flush();
    assert.equal(sheet.el.isConnected, false);
    assert.equal(h.document.activeElement, button);
    assert.equal(h.body.style.overflow, '');
    assert.equal(h.body.style.position, '');
    assert.equal(h.sandbox.scrollY, 80);

    const button2 = opener(h);
    const again = h.sandbox.ClientSheet.open({ labelledBy: 'sheetTitle', content: contentOf(h, 't2') });
    h.document.querySelector('.cs-backdrop').dispatch('click', {});
    h.flush();
    assert.equal(again.el.isConnected, false);
    assert.equal(h.document.activeElement, button2);

    const button3 = opener(h);
    const third = h.sandbox.ClientSheet.open({ labelledBy: 'sheetTitle', content: contentOf(h, 't3') });
    third.close();
    h.flush();
    assert.equal(third.el.isConnected, false);
    assert.equal(h.document.activeElement, button3);

    opener(h);
    const fourth = h.sandbox.ClientSheet.open({ labelledBy: 'sheetTitle', content: contentOf(h, 't4') });
    const handle = fourth.el.querySelector('.cs-handle');
    handle.dispatch('pointerdown', { clientY: 10, target: handle });
    h.document.dispatch('pointermove', { clientY: 90 });
    h.document.dispatch('pointerup', { clientY: 90 });
    assert.equal(h.timeouts.length, 0);
    assert.equal(fourth.el.className.includes('cs-sheet'), true);
    handle.dispatch('pointerdown', { clientY: 10, target: handle });
    h.document.dispatch('pointermove', { clientY: 91 });
    h.document.dispatch('pointerup', { clientY: 91 });
    assert.equal(h.timeouts.length, 1);
    h.flush();
    assert.equal(fourth.el.isConnected, false);
  });

  it('свайп с кнопки и из прокрученного списка шторку не закрывает', () => {
    const h = makeHarness();
    opener(h);
    const sheet = h.sandbox.ClientSheet.open({ labelledBy: 'sheetTitle', content: contentOf(h) });
    const action = sheet.el.querySelector('button');
    action.dispatch('pointerdown', { clientY: 0, target: action });
    h.document.dispatch('pointerup', { clientY: 200 });
    assert.equal(h.timeouts.length, 0);
    const list = sheet.el.querySelector('.cs-scroll');
    list.scrollTop = 40;
    list.dispatch('pointerdown', { clientY: 0, target: list });
    h.document.dispatch('pointerup', { clientY: 200 });
    assert.equal(h.timeouts.length, 0);
    assert.equal(sheet.el.isConnected, true);
  });

  it('свайп по строке списка в начале закрывает шторку и не выбирает строку', () => {
    const h = makeHarness();
    opener(h);
    const sheet = h.sandbox.ClientSheet.open({ labelledBy: 'sheetTitle', content: contentOf(h) });
    const list = sheet.el.querySelector('.cs-scroll');
    const row = h.document.createElement('label');
    list.appendChild(row);
    list.scrollTop = 0;
    /* touch-action: none на списке в начале блокирует и нативную прокрутку: scrollTop не растёт, и список не листается. */
    assert.notEqual(list.style.touchAction, 'none');
    row.dispatch('pointerdown', { clientY: 10, target: row });
    h.document.dispatch('pointermove', { clientY: 40 });
    h.document.dispatch('pointerup', { clientY: 140 });
    const click = row.dispatch('click', { target: row });
    assert.equal(click.defaultPrevented, true);
    assert.equal(h.timeouts.length, 1);
    h.flush();
    assert.equal(sheet.el.isConnected, false);
  });

  it('pointercancel без координат закрывает по последней точке движения', () => {
    const h = makeHarness();
    opener(h);
    const sheet = h.sandbox.ClientSheet.open({ labelledBy: 'sheetTitle', content: contentOf(h) });
    const handle = sheet.el.querySelector('.cs-handle');
    handle.dispatch('pointerdown', { clientY: 10, target: handle });
    h.document.dispatch('pointermove', { clientY: 140 });
    h.document.dispatch('pointercancel', {});
    assert.equal(h.timeouts.length, 1);
    h.flush();
    assert.equal(sheet.el.isConnected, false);
  });

  it('CSS: шапка и тело шторки не отдают вертикальный жест браузеру, список — pan-y', () => {
    assert.match(sheetCss, /\.cs-body,\s*\.cs-body > \*\s*\{[^}]*touch-action:\s*none/);
    assert.match(sheetCss, /\.cs-scroll\s*\{[^}]*touch-action:\s*pan-y/);
    assert.match(sheetCss, /\.cs-handle::before/);
  });

  it('список, прокрученный к началу: жест вниз через touch тянет и закрывает шторку', () => {
    const h = makeHarness();
    opener(h);
    const sheet = h.sandbox.ClientSheet.open({ labelledBy: 'sheetTitle', content: contentOf(h) });
    const list = sheet.el.querySelector('.cs-scroll');
    list.scrollTop = 0;
    list.dispatch('touchstart', { touches: [{ clientY: 0 }], target: list });
    const first = h.document.dispatch('touchmove', { touches: [{ clientY: 40 }], cancelable: true });
    assert.equal(sheet.el.style.transform, 'translateY(40px)');
    assert.equal(first.defaultPrevented, true);
    h.document.dispatch('touchmove', { touches: [{ clientY: 120 }], cancelable: true });
    h.document.dispatch('touchend', {});
    assert.equal(h.timeouts.length, 1);
    h.flush();
    assert.equal(sheet.el.isConnected, false);
  });

  it('список, прокрученный вниз или жест вверх: шторка не тянется, скролл не перехватывается', () => {
    const h = makeHarness();
    opener(h);
    const sheet = h.sandbox.ClientSheet.open({ labelledBy: 'sheetTitle', content: contentOf(h) });
    const list = sheet.el.querySelector('.cs-scroll');
    const moves = [];
    list.scrollTop = 50;
    list.dispatch('touchstart', { touches: [{ clientY: 0 }], target: list });
    moves.push(h.document.dispatch('touchmove', { touches: [{ clientY: 150 }], cancelable: true }));
    h.document.dispatch('touchend', {});
    list.scrollTop = 0;
    list.dispatch('touchstart', { touches: [{ clientY: 200 }], target: list });
    moves.push(h.document.dispatch('touchmove', { touches: [{ clientY: 100 }], cancelable: true }));
    moves.push(h.document.dispatch('touchmove', { touches: [{ clientY: 400 }], cancelable: true }));
    h.document.dispatch('touchend', {});
    assert.equal(moves.some((m) => m.defaultPrevented), false);
    assert.equal(h.timeouts.length, 0);
    assert.equal(sheet.el.isConnected, true);
  });

  it('короткий рывок пальца вверх в начале жеста не срывает закрытие', () => {
    const h = makeHarness();
    opener(h);
    const sheet = h.sandbox.ClientSheet.open({ labelledBy: 'sheetTitle', content: contentOf(h) });
    const list = sheet.el.querySelector('.cs-scroll');
    list.scrollTop = 0;
    list.dispatch('touchstart', { touches: [{ clientY: 100 }], target: list });
    h.document.dispatch('touchmove', { touches: [{ clientY: 97 }], cancelable: true });
    h.document.dispatch('touchmove', { touches: [{ clientY: 200 }], cancelable: true });
    h.document.dispatch('touchend', {});
    assert.equal(h.timeouts.length, 1);
    h.flush();
    assert.equal(sheet.el.isConnected, false);
  });

  it('открытая шторка отключает вертикальный свайп Telegram и возвращает его после закрытия', () => {
    const h = makeHarness();
    const calls = [];
    h.sandbox.Telegram.WebApp.disableVerticalSwipes = () => calls.push('off');
    h.sandbox.Telegram.WebApp.enableVerticalSwipes = () => calls.push('on');
    opener(h);
    const sheet = h.sandbox.ClientSheet.open({ content: contentOf(h) });
    assert.deepEqual(calls, ['off']);
    h.document.body.classList.add('client-shell-more-open');
    sheet.close();
    h.flush();
    assert.deepEqual(calls, ['off']);
    h.document.body.classList.remove('client-shell-more-open');
    const again = h.sandbox.ClientSheet.open({ content: contentOf(h) });
    again.close();
    h.flush();
    assert.deepEqual(calls, ['off', 'off', 'on']);
  });

  it('после закрытия возвращает кнопку «назад» Telegram в прежнее состояние', () => {
    const hidden = makeHarness({ backVisible: false });
    opener(hidden);
    const sheet = hidden.sandbox.ClientSheet.open({ content: contentOf(hidden) });
    hidden.pressBack();
    hidden.flush();
    assert.equal(sheet.el.isConnected, false);
    assert.equal(hidden.backClicks.includes('off'), true);
    assert.equal(hidden.back.isVisible, false);
    hidden.pressBack();
    assert.equal(hidden.document.querySelector('[role="dialog"]'), null);

    const shown = makeHarness({ backVisible: true });
    opener(shown);
    const kept = shown.sandbox.ClientSheet.open({ content: contentOf(shown) });
    kept.close();
    shown.flush();
    assert.equal(shown.back.isVisible, true);
    assert.equal(shown.backClicks.includes('hide'), false);
  });

  it('держит одну шторку: новая сразу закрывает старую', () => {
    const h = makeHarness();
    opener(h);
    let firstClosed = 0;
    const first = h.sandbox.ClientSheet.open({
      content: contentOf(h, 'a'),
      onClose() { firstClosed += 1; },
    });
    const second = h.sandbox.ClientSheet.open({ content: contentOf(h, 'b') });
    assert.equal(firstClosed, 1);
    assert.equal(first.el.isConnected, false);
    assert.equal(second.el.isConnected, true);
    assert.equal(h.document.querySelectorAll('[role="dialog"]').length, 1);
  });

  it('поднимает лист по visualViewport и без движения закрывается сразу', () => {
    const h = makeHarness({ vvHeight: 640, vvTop: 0, reduced: true });
    const button = opener(h);
    const sheet = h.sandbox.ClientSheet.open({ content: contentOf(h) });
    h.sandbox.visualViewport.height = 420;
    h.sandbox.visualViewport.offsetTop = 30;
    h.fireViewport('resize');
    const layer = h.document.querySelector('.cs-root');
    assert.equal(layer.style.top, '30px');
    assert.equal(layer.style.height, '420px');
    assert.equal(sheet.el.style.maxHeight, '320px');
    h.document.dispatch('keydown', { key: 'Escape' });
    assert.equal(h.timeouts.length, 0);
    assert.equal(sheet.el.isConnected, false);
    assert.equal(h.document.activeElement, button);
  });

  it('Tab не уводит фокус из шторки', () => {
    const h = makeHarness();
    opener(h);
    const sheet = h.sandbox.ClientSheet.open({ content: contentOf(h) });
    const input = sheet.el.querySelector('input');
    const action = sheet.el.querySelector('button');
    action.focus();
    const forward = h.document.dispatch('keydown', { key: 'Tab', shiftKey: false });
    assert.equal(forward.defaultPrevented, true);
    assert.equal(h.document.activeElement, input);
    const backward = h.document.dispatch('keydown', { key: 'Tab', shiftKey: true });
    assert.equal(backward.defaultPrevented, true);
    assert.equal(h.document.activeElement, action);
  });
});
