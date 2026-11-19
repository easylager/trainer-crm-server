/**
 * «За кого болеешь?» (TASK-371 S2).
 * Run: node --test tests/js/client-club-sheet.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const sheetSrc = fs.readFileSync(path.join(webapp, 'client-sheet.js'), 'utf8');
const clubSrc = fs.readFileSync(path.join(webapp, 'client-club-sheet.js'), 'utf8');
const club = require(path.join(webapp, 'client-club-sheet.js'));

const ITEMS = [
  { name: 'Юность', short: 'ЮН', color: '#004593', logo: null, league: 'extraliga' },
  { name: 'Динамо-Минск', short: 'ДМ', color: '#003DA5', logo: '/static/webapp/hockey-logos/dinamo-minsk.png', league: 'khl' },
  { name: 'Шахтёр', short: 'Ш', color: '#E07000', logo: '', league: 'extraliga' },
  { name: 'СКА', short: 'СК', color: '#C8102E', logo: null, league: 'vhl' },
];

describe('модель клубов', () => {
  it('группирует КХЛ, затем Экстралигу, и сохраняет порядок внутри', () => {
    const groups = club.groupClubs(ITEMS);
    assert.deepEqual(groups.map((group) => group.title), ['КХЛ', 'Экстралига']);
    assert.deepEqual(groups[0].items.map((item) => item.name), ['Динамо-Минск']);
    assert.deepEqual(groups[1].items.map((item) => item.name), ['Юность', 'Шахтёр']);
    assert.equal(club.groupClubs([{ name: 'СКА', league: 'vhl' }]).length, 0);
    assert.deepEqual(club.groupClubs(null), []);
  });

  it('ищет по имени без регистра, «ё» совпадает с «е»', () => {
    assert.deepEqual(club.filterClubs(ITEMS, 'шахтер').map((item) => item.name), ['Шахтёр']);
    assert.deepEqual(club.filterClubs([{ name: 'Шахтер', league: 'extraliga' }], 'ШАХТЁР').map((item) => item.name), ['Шахтер']);
    assert.deepEqual(club.filterClubs(ITEMS, 'ДИНАМО').map((item) => item.name), ['Динамо-Минск']);
    assert.equal(club.filterClubs(ITEMS, 'дм').length, 0);
    assert.equal(club.filterClubs(ITEMS, '   ').length, ITEMS.length);
    assert.deepEqual(club.filterClubs(null, 'а'), []);
  });

  it('подписывает кнопку и гасит её, пока запрос идёт', () => {
    assert.deepEqual(club.buttonState(null, false), { label: 'Выбери команду', disabled: true });
    assert.deepEqual(club.buttonState('  ', false), { label: 'Выбери команду', disabled: true });
    assert.deepEqual(club.buttonState('Динамо-Минск', false), { label: 'Болею за\u00a0Динамо-Минск', disabled: false });
    assert.deepEqual(club.buttonState('Динамо-Минск', true), { label: 'Болею за\u00a0Динамо-Минск', disabled: true });
  });

  it('не звучит как букмекерка', () => {
    assert.doesNotMatch(clubSrc, /×|процент|коэфф/i);
    assert.equal(clubSrc.match(/#[0-9a-fA-F]{3,8}/g), null);
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

  get disabled() { return this._disabled; }

  set disabled(value) {
    this._disabled = !!value;
    if (this._disabled) this.attrs.disabled = '';
    else delete this.attrs.disabled;
  }

  get hidden() { return this.hasAttribute('hidden'); }

  set hidden(value) {
    if (value) this.setAttribute('hidden', '');
    else this.removeAttribute('hidden');
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
  const body = new El('body', document);
  html.appendChild(body);
  document.documentElement = html;
  document.body = body;
  document.activeElement = body;

  const prefs = options.prefs || { ok: true, body: {} };
  let prefsGate = null;
  const sandbox = {
    document,
    console,
    URLSearchParams,
    JSON,
    location: { search: options.search || '' },
    matchMedia() { return { matches: true }; },
    requestAnimationFrame(fn) { fn(); },
    setTimeout(fn) { fn(); return 0; },
    clearTimeout() {},
    scrollY: 0,
    scrollTo() {},
    fetch(url, opts) {
      const call = { url: String(url), opts };
      calls.push(call);
      if (String(url).includes('bot-prefs')) {
        if (options.hangSave) {
          return new Promise((resolve, reject) => { prefsGate = { resolve, reject }; });
        }
        if (options.saveReject) return Promise.reject(new Error('offline'));
        return Promise.resolve({
          ok: prefs.ok,
          json: () => Promise.resolve(prefs.body),
        });
      }
      if (options.clubsReject) return Promise.reject(new Error('offline'));
      return Promise.resolve({
        ok: options.clubsOk !== false,
        json: () => options.clubsBadJson ? Promise.reject(new SyntaxError('bad')) : Promise.resolve(options.clubsBody || { items: ITEMS }),
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
  vm.runInContext(clubSrc, sandbox);
  return { sandbox, document, calls, haptic, prefsGate: () => prefsGate };
}

function radios(sheet) {
  return sheet.el.querySelectorAll('input').filter((node) => node.type === 'radio');
}

function saveButton(sheet) {
  return sheet.el.querySelector('.cc-save');
}

describe('listState', () => {
  const items = [{ name: 'Шахтёр', league: 'khl' }];
  it('разводит загрузку, список, ошибку и поиск без результата', () => {
    assert.equal(club.listState('loading', [], '').kind, 'loading');
    assert.equal(club.listState('loaded', items, '').kind, 'list');
    assert.equal(club.listState('loaded', [], '').kind, 'list');
    assert.equal(club.listState('loaded', items, 'шахтер').kind, 'list');
    const none = club.listState('loaded', items, 'нет такой');
    assert.equal(none.kind, 'no-match');
    assert.equal(none.text, 'Такой команды нет');
    const err = club.listState('error', [], '');
    assert.equal(err.kind, 'error');
    assert.equal(err.text, 'Не загрузилось. Попробуй ещё раз');
    assert.equal(club.listState('error', [], 'шахтер').kind, 'error');
  });
});

describe('ClientClubSheet', () => {
  for (const [name, opt] of [
    ['сеть', { clubsReject: true }],
    ['не-ok', { clubsOk: false }],
    ['битый JSON', { clubsBadJson: true }],
  ]) {
    it('ошибка загрузки (' + name + '): сообщение, кнопка неактивна, поиск не врёт', async () => {
      const h = harness(opt);
      const sheet = h.sandbox.ClientClubSheet.open({ current: 'Юность' });
      await flush();
      assert.equal(sheet.el.querySelector('.cc-empty').textContent, 'Не загрузилось. Попробуй ещё раз');
      assert.equal(radios(sheet).length, 0);
      assert.equal(saveButton(sheet).textContent, 'Выбери команду');
      assert.equal(saveButton(sheet).disabled, true);
      const input = sheet.el.querySelector('input');
      input.value = 'шахтер';
      input.dispatch('input', {});
      assert.equal(sheet.el.querySelector('.cc-empty').textContent, 'Не загрузилось. Попробуй ещё раз');
      assert.equal(sheet.el.querySelector('.cc-clear').disabled, false);
    });
  }

  it('при ошибке загрузки «Пока ни за кого» работает', async () => {
    const saved = [];
    const h = harness({ clubsReject: true });
    const sheet = h.sandbox.ClientClubSheet.open({ current: 'Юность', onSaved(c) { saved.push(c); } });
    await flush();
    sheet.el.querySelector('.cc-clear').dispatch('click', {});
    await flush();
    assert.deepEqual(saved, [null]);
  });

  it('отмечает текущий клуб и рисует группы, логотип и букву', async () => {
    const h = harness();
    const sheet = h.sandbox.ClientClubSheet.open({ current: 'Динамо-Минск' });
    await flush();
    assert.equal(sheet.el.getAttribute('aria-labelledby'), 'cc-title');
    assert.equal(sheet.el.querySelector('.cc-title').textContent, 'За\u00a0кого болеешь?');
    assert.equal(sheet.el.querySelector('.cc-sub').textContent, 'Её матчи будут первыми в\u00a0«КТО КОГО».');
    assert.equal(sheet.el.querySelector('input').getAttribute('placeholder'), 'Название команды');
    assert.equal(sheet.el.querySelector('.cs-sr').textContent, 'Найти команду');
    assert.deepEqual(
      sheet.el.querySelectorAll('h3').map((node) => node.textContent),
      ['КХЛ', 'Экстралига'],
    );
    const boxes = radios(sheet);
    assert.deepEqual(boxes.map((node) => node.value), ['Динамо-Минск', 'Юность', 'Шахтёр']);
    assert.equal(boxes.find((node) => node.value === 'Динамо-Минск').checked, true);
    const logo = sheet.el.querySelectorAll('.cc-mark').map((node) => node.querySelector('img')).find(Boolean);
    assert.equal(logo.getAttribute('src'), '/static/webapp/hockey-logos/dinamo-minsk.png');
    const letter = sheet.el.querySelector('.cc-mark--letter');
    assert.equal(letter.textContent, 'ЮН');
    assert.equal(letter.style.backgroundColor, '#004593');
    assert.equal(saveButton(sheet).textContent, 'Болею за\u00a0Динамо-Минск');
    assert.equal(saveButton(sheet).disabled, false);
    assert.equal(saveButton(sheet).classList.contains('is-ready'), true);
    assert.equal(h.calls[0].url, '/api/webapp/client/hockey/clubs');
    assert.equal(h.calls[0].opts.method, 'GET');
    assert.equal(h.calls[0].opts.headers['X-Telegram-Init-Data'], 'init-1');
  });

  it('принимает клуб объектом и без выбора гасит кнопку', async () => {
    const byObject = harness();
    const sheet = byObject.sandbox.ClientClubSheet.open({ current: { name: 'Шахтёр', color: '#E07000' } });
    await flush();
    assert.equal(radios(sheet).find((node) => node.value === 'Шахтёр').checked, true);

    const empty = harness();
    const blank = empty.sandbox.ClientClubSheet.open({ current: null });
    await flush();
    assert.equal(radios(blank).some((node) => node.checked), false);
    assert.equal(saveButton(blank).textContent, 'Выбери команду');
    assert.equal(saveButton(blank).disabled, true);
    assert.equal(saveButton(blank).classList.contains('is-ready'), false);
    assert.equal(blank.el.querySelector('.cc-clear').textContent, 'Пока ни за\u00a0кого');
  });

  it('фильтрует список и пишет «Такой команды нет»', async () => {
    const h = harness();
    const sheet = h.sandbox.ClientClubSheet.open({ current: null });
    await flush();
    const input = sheet.el.querySelector('input');
    input.value = 'шахтер';
    input.dispatch('input', {});
    assert.deepEqual(radios(sheet).map((node) => node.value), ['Шахтёр']);
    assert.equal(sheet.el.querySelector('.cc-empty'), null);
    input.value = 'нет такой';
    input.dispatch('input', {});
    assert.equal(radios(sheet).length, 0);
    assert.equal(sheet.el.querySelector('.cc-empty').textContent, 'Такой команды нет');
  });

  it('сохраняет fav_club и снимает клуб тем же вызовом, что игра', async () => {
    const saved = [];
    const h = harness();
    const sheet = h.sandbox.ClientClubSheet.open({
      current: 'Динамо-Минск',
      onSaved(club) { saved.push(club); },
    });
    await flush();
    saveButton(sheet).dispatch('click', {});
    await flush();
    const put = h.calls.find((call) => call.url.includes('bot-prefs'));
    assert.equal(put.opts.method, 'PUT');
    assert.equal(put.opts.headers['Content-Type'], 'application/json');
    assert.equal(put.opts.headers['X-Telegram-Init-Data'], 'init-1');
    assert.equal(put.opts.body, '{"fav_club":"Динамо-Минск"}');
    assert.deepEqual(h.haptic, ['success']);
    assert.equal(saved.length, 1);
    assert.equal(saved[0].name, 'Динамо-Минск');
    assert.equal(saved[0].logo, '/static/webapp/hockey-logos/dinamo-minsk.png');
    assert.equal(sheet.el.isConnected, false);

    const cleared = [];
    const second = harness();
    const again = second.sandbox.ClientClubSheet.open({
      current: 'Юность',
      onSaved(club) { cleared.push(club); },
    });
    await flush();
    again.el.querySelector('.cc-clear').dispatch('click', {});
    await flush();
    const clear = second.calls.find((call) => call.url.includes('bot-prefs'));
    assert.equal(clear.opts.body, '{"clear_fav_club":true}');
    assert.deepEqual(cleared, [null]);
    assert.deepEqual(second.haptic, ['success']);
  });

  it('при ошибке не сбрасывает выбор и не шлёт запрос дважды, пока первый идёт', async () => {
    const h = harness({ hangSave: true });
    const sheet = h.sandbox.ClientClubSheet.open({ current: 'Динамо-Минск' });
    await flush();
    const save = saveButton(sheet);
    save.dispatch('click', {});
    save.dispatch('click', {});
    assert.equal(h.calls.filter((call) => call.url.includes('bot-prefs')).length, 1);
    assert.equal(save.disabled, true);
    assert.equal(save.textContent, 'Болею за\u00a0Динамо-Минск');
    h.prefsGate().resolve({ ok: false, json: () => Promise.resolve({}) });
    await flush();
    assert.equal(sheet.el.isConnected, true);
    assert.equal(radios(sheet).find((node) => node.value === 'Динамо-Минск').checked, true);
    assert.equal(save.disabled, false);
    assert.equal(sheet.el.querySelector('.cc-toast').hidden, false);
    assert.equal(sheet.el.querySelector('.cc-toast').textContent, 'Не сохранилось. Попробуй ещё раз');
    save.dispatch('click', {});
    assert.equal(h.calls.filter((call) => call.url.includes('bot-prefs')).length, 2);
  });

  it('обрыв сети — тот же тост, выбор на месте', async () => {
    const h = harness({ saveReject: true });
    const sheet = h.sandbox.ClientClubSheet.open({ current: { name: 'Юность' } });
    await flush();
    saveButton(sheet).dispatch('click', {});
    await flush();
    assert.equal(sheet.el.isConnected, true);
    assert.equal(radios(sheet).find((node) => node.value === 'Юность').checked, true);
    assert.equal(sheet.el.querySelector('.cc-toast').textContent, 'Не сохранилось. Попробуй ещё раз');
    assert.equal(saveButton(sheet).disabled, false);
  });

  it('берёт init_data из адреса, если Telegram его не дал', async () => {
    const h = harness({ telegram: false, search: '?init_data=from-url' });
    h.sandbox.ClientClubSheet.open({ current: null });
    await flush();
    assert.equal(h.calls[0].opts.headers['X-Telegram-Init-Data'], 'from-url');
  });
});
