/**
 * Этап 1 входов в витрину тренеров на главной: строка «Учиться с тренером» в «Чем займёмся?» для всех,
 * блок для нового клиента без дубля, «Другие тренеры» под «Моим тренером». Денежные пути «Мой тренер» /
 * «Записаться снова» остаются на старом каталоге.
 * Run: node --test tests/js/client-home-trainer-entries.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const homeHtml = fs.readFileSync(path.join(webapp, 'client-home.html'), 'utf8');
const homeMain = fs.readFileSync(path.join(webapp, 'client-home-main.js'), 'utf8');

function fnBody(name) {
  const start = homeMain.indexOf('function ' + name + '(');
  assert.ok(start >= 0, 'нет функции ' + name);
  let depth = 0;
  for (let i = homeMain.indexOf('{', start); i < homeMain.length; i++) {
    if (homeMain[i] === '{') depth++;
    else if (homeMain[i] === '}' && --depth === 0) return homeMain.slice(start, i + 1);
  }
  throw new Error('не закрыта ' + name);
}

/** Узел-заглушка: дети, атрибуты, hidden. */
function node(tag) {
  const n = {
    tag, children: [], attrs: {}, hidden: false, className: '', textContent: '', style: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    setAttribute(k, v) { n.attrs[k] = String(v); },
    getAttribute: (k) => (k in n.attrs ? n.attrs[k] : null),
    removeAttribute(k) { delete n.attrs[k]; },
    appendChild(c) { n.children.push(c); return c; },
    replaceChildren(...c) { n.children = c; },
    addEventListener() {},
    querySelector: () => null,
  };
  return n;
}

function loadHubHome() {
  const els = { hubNeeds: node('section'), hubNeedsList: node('div') };
  const doc = {
    documentElement: node('html'),
    body: node('body'),
    getElementById: (id) => els[id] || null,
    createElement: (t) => node(t),
    createElementNS: (_ns, t) => node(t),
    createTextNode: (t) => ({ t }),
  };
  const ctx = { document: doc, localStorage: { getItem: () => null, setItem() {} }, setTimeout, Promise, Date, Intl, console };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(webapp, 'hub-home.js'), 'utf8'), ctx, { filename: 'hub-home.js' });
  return { HH: ctx.HubHome, els };
}

const keys = (els) => els.hubNeedsList.children.map((r) => r.getAttribute('data-need'));
const city = (rows) => ({ id: 1, needs: rows.map((k) => ({ key: k, title: k === 'coach' ? 'Учиться с тренером' : k, line: '', href: k === 'coach' ? 'trainers?city_id=1' : 'ice?city_id=1', windows: [] })) });

describe('«Чем займёмся?»: строку можно спрятать и вернуть', () => {
  it('hideNeed прячет «Учиться с тренером» и перерисовывает список', () => {
    const { HH, els } = loadHubHome();
    HH._needs(city(['skate', 'coach']));
    assert.deepEqual(keys(els), ['skate', 'coach']);
    HH.hideNeed('coach', true);
    assert.deepEqual(keys(els), ['skate']);
    assert.equal(els.hubNeeds.hidden, false);
    HH.hideNeed('coach', false);
    assert.deepEqual(keys(els), ['skate', 'coach']);
  });

  it('спрятанная строка не возвращается при новом bootstrap; единственная — секция скрыта', () => {
    const { HH, els } = loadHubHome();
    HH.hideNeed('coach', true);
    HH._needs(city(['coach']));
    assert.deepEqual(keys(els), []);
    assert.equal(els.hubNeeds.hidden, true);
  });
});

describe('главная: блок или строка — что-то одно', () => {
  function runSetHubLearn({ blockShown, mountFails = false }) {
    const learn = node('section');
    learn.hidden = true;
    const hidden = [];
    const LB = {
      mount: () => (mountFails ? Promise.reject(new Error('x')) : Promise.resolve().then(() => { learn.hidden = !blockShown; })),
      hide: () => { learn.hidden = true; },
    };
    const win = { LearnBlock: LB, HubHome: { hideNeed: (k, h) => hidden.push([k, h]) } };
    const doc = { getElementById: (id) => (id === 'hubLearn' ? learn : null) };
    const setHubLearn = new Function('window', 'document', 'var hubLearnGen = 0;\n' + fnBody('setHubLearn') + '\nreturn setHubLearn;')(win, doc);
    return { setHubLearn, hidden };
  }

  it('новый клиент: блок показан — строка спрятана', async () => {
    const t = runSetHubLearn({ blockShown: true });
    t.setHubLearn(true, 1);
    await new Promise((r) => setTimeout(r, 5));
    assert.deepEqual(t.hidden, [['coach', true], ['coach', true]]);
  });

  it('новый клиент, но показать нечего (блок пуст или не загрузился) — строка возвращается', async () => {
    const t = runSetHubLearn({ blockShown: false });
    t.setHubLearn(true, 1);
    await new Promise((r) => setTimeout(r, 5));
    assert.deepEqual(t.hidden[t.hidden.length - 1], ['coach', false]);
    const f = runSetHubLearn({ blockShown: true, mountFails: true });
    f.setHubLearn(true, 1);
    await new Promise((r) => setTimeout(r, 5));
    assert.deepEqual(f.hidden[f.hidden.length - 1], ['coach', false]);
  });

  it('клиент с записями (блок выключен) — строка есть', () => {
    const t = runSetHubLearn({ blockShown: true });
    t.setHubLearn(false);
    assert.deepEqual(t.hidden, [['coach', false]]);
  });

  it('поздний ответ блока не прячет строку после смены состояния', async () => {
    const t = runSetHubLearn({ blockShown: true });
    t.setHubLearn(true, 1);
    t.setHubLearn(false);
    await new Promise((r) => setTimeout(r, 5));
    assert.deepEqual(t.hidden[t.hidden.length - 1], ['coach', false]);
  });
});

describe('«Другие тренеры» под «Моим тренером»', () => {
  function runLink() {
    const btn = node('button');
    btn.hidden = true;
    const nav = [];
    const doc = { getElementById: (id) => (id === 'hubOtherTrainers' ? btn : null) };
    const fn = new Function('document', 'navigateTo', fnBody('setOtherTrainersLink') + '\nreturn setOtherTrainersLink;')(doc, (p) => nav.push(p));
    return { fn, btn, nav };
  }

  it('кнопка внутри «Моих занятий», под «Записаться снова»', () => {
    const mine = homeHtml.slice(homeHtml.indexOf('id="hubMine"'), homeHtml.indexOf('id="hubNearest"'));
    assert.ok(mine.indexOf('id="hubOtherTrainers"') > mine.indexOf('id="hubRebook"'));
    assert.match(homeHtml, /<button type="button" class="hh-others" id="hubOtherTrainers" hidden>Другие тренеры<\/button>/);
  });

  it('ведёт на витрину города; без города — витрина по городу сессии', () => {
    const t = runLink();
    t.fn(true, 4);
    assert.equal(t.btn.hidden, false);
    t.btn.onclick();
    assert.deepEqual(t.nav, ['trainers?city_id=4']);
    const u = runLink();
    u.fn(true, null);
    u.btn.onclick();
    assert.deepEqual(u.nav, ['trainers']);
    u.fn(false);
    assert.equal(u.btn.hidden, true);
  });

  it('показывается только в ветке «Мой тренер» и снимается в начале каждого состояния', () => {
    assert.equal((homeMain.match(/setOtherTrainersLink\(true,/g) || []).length, 1);
    const p2 = homeMain.slice(homeMain.indexOf('/* ── Priority 2: Has primary trainer ── */'), homeMain.indexOf('/* ── Priority 3'));
    assert.match(p2, /setOtherTrainersLink\(true,/);
    assert.match(homeMain, /setHubLearn\(false\);\s*setOtherTrainersLink\(false\);/);
  });
});

describe('денежные пути главной не переключены (этап 1)', () => {
  it('«Мой тренер» и «Записаться снова» по-прежнему ведут в catalog?trainer_id=…&from=hub', () => {
    assert.ok(homeMain.includes("navigateTo('catalog?trainer_id=' + encodeURIComponent(tid) + catalogPrimaryServiceQuery() + '&from=hub');"));
    const fn = fnBody('buildBookPathFromHubContext');
    assert.match(fn, /'catalog\?trainer_id=' \+ encodeURIComponent\(String\(trainerId\)\)/);
    assert.match(fn, /'from=hub'/);
    assert.ok(homeMain.includes("navigateTo('catalog?trainer_id=' + encodeURIComponent(btn.getAttribute('data-tid')));"));
  });
});
