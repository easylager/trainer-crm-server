/**
 * TASK-354: блок «Учиться с тренером» в точках входа Mini App — тексты по местам, правило «нет тренеров —
 * нет блока», время только если есть, один запрос на город с кешем сеанса, ошибка — блока нет.
 * Run: node --test tests/js/learn-block.test.js
 */
'use strict';

const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const WEBAPP = path.resolve(__dirname, '../../static/webapp');
const M = require(path.join(WEBAPP, 'trainer-showcase-model.js'));
const L = require(path.join(WEBAPP, 'learn-block-model.js'));

const tiers = (pairs) => pairs.map(([kind, cents], i) => ({ id: 100 + i, tier_kind: kind, price_cents: cents, currency_code: 'BYN' }));
const svc = (id, t, extra = {}) => ({ service_id: id, is_public: true, currency_code: 'BYN', price_cents: null, price_tiers: t, ...extra });
const win = (slot, arena, startsAt, day, time) => ({ slot_id: slot, arena_id: arena, starts_at: startsAt, day, time });

/** Что отдал бы сервер в `min_price_by_direction` для фикстуры без групповых и абонементов: тарифы/цена услуг вкладки. */
function serverMins(services) {
  const out = {};
  M.DIRECTIONS.forEach((d) => {
    let best = null;
    M.servicesInDirection({ services }, d.key).forEach((s) => {
      const ps = (s.price_tiers || []).map((t) => t.price_cents).filter((c) => c > 0);
      const c = ps.length ? Math.min(...ps) : (s.price_cents > 0 ? s.price_cents : null);
      if (c && (!best || c < best.cents)) best = { cents: c, currency: 'BYN' };
    });
    if (best) out[d.key] = best;
  });
  return out;
}

function trainer(id, over = {}) {
  const t = {
    id, name: 'Тренер ' + id, initial: 'Т', photo_url: null, can_book: true,
    min_session_price_cents: 5000, min_session_price_currency: 'BYN',
    services: [svc(1, tiers([['adult', 5000]]))],
    arenas: [{ id: 3, name: 'ТЦ «Замок»' }],
    windows: [],
    ...over,
  };
  if (!('min_price_by_direction' in over)) t.min_price_by_direction = serverMins(t.services);
  return t;
}

const gaevsky = trainer(9, {
  name: 'Александр Гаевский', initial: 'А', photo_url: '/p/9.jpg', min_session_price_cents: 5000,
  windows: [win(1, 3, '2026-11-07T17:15:00+03:00', 'сегодня', '17:15')],
});
const vlad = trainer(11, {
  initial: 'В', min_session_price_cents: 4500, services: [svc(1, tiers([['child', 4500], ['adult', 5000]]))],
  windows: [win(2, 3, '2026-11-08T10:00:00+03:00', 'завтра', '10:00')],
});
const klimas = trainer(77, { initial: 'К', min_session_price_cents: 3000, services: [svc(1, tiers([['adult', 5000]])), svc(6, tiers([['adult', 5000]])), svc(7, tiers([['adult', 3000]]))], arenas: [{ id: 5, name: 'Чижовка' }], windows: [win(3, 5, '2026-11-08T18:00:00+03:00', 'завтра', '18:00')] });
const hockey = trainer(20, { initial: 'Х', min_session_price_cents: 6000, services: [svc(6, tiers([['adult', 6000]]))] });
const hockey2 = trainer(21, { initial: 'Я', min_session_price_cents: 5500, services: [svc(4, tiers([['adult', 5500]]))] });
const noWrite = trainer(74, { can_book: false, windows: [win(9, 3, '2026-11-07T09:00:00+03:00', 'сегодня', '09:00')] });
const hidden = trainer(80, { services: [svc(99, tiers([['adult', 4000]]), { is_public: false })] });

describe('склонения и число тренеров', () => {
  it('N тренеров со склонением', () => {
    assert.equal(L.count(1), '1 тренер');
    assert.equal(L.count(2), '2 тренера');
    assert.equal(L.count(4), '4 тренера');
    assert.equal(L.count(5), '5 тренеров');
    assert.equal(L.count(11), '11 тренеров');
    assert.equal(L.count(21), '21 тренер');
  });
});

describe('главная и «Мои записи» (city)', () => {
  const items = [gaevsky, vlad, klimas, hockey];

  it('строка: «от», ближайшее время; заголовок и кнопка единые', () => {
    const b = L.build(items, 'city', { cityId: 1 });
    assert.equal(b.title, 'Учиться с тренером');
    assert.equal(b.button, 'Выбрать тренера');
    assert.equal(b.countText, '4 тренера');
    assert.equal(b.line, 'От 45 BYN за занятие. Ближайшее свободное время — сегодня, 17:15.');
    assert.equal(b.href, 'trainers?city_id=1');
  });

  it('до 4 лиц: фото или буква', () => {
    const b = L.build([gaevsky, vlad, klimas, hockey, hockey2], 'city', { cityId: 1 });
    assert.equal(b.faces.length, 4);
    assert.equal(b.count, 5);
    const withPhoto = b.faces.find((f) => f.photo);
    assert.equal(withPhoto.photo, '/p/9.jpg');
    assert.ok(b.faces.some((f) => f.photo === null && f.initial));
  });

  it('чипы — вкладки витрины с тренерами, ведут на свою вкладку и город', () => {
    const b = L.build(items, 'city', { cityId: 1 });
    assert.deepEqual(b.chips.map((c) => c.label), ['С нуля', 'С клюшкой']);
    assert.equal(b.chips[1].href, 'trainers?tab=s-klyushkoy&city_id=1');
  });

  it('одно направление — чипов нет (повторяли бы кнопку)', () => {
    assert.deepEqual(L.build([gaevsky, vlad], 'city', { cityId: 1 }).chips, []);
  });

  it('время только если есть: нет окон — нет фразы; тренер без онлайн-записи окон не даёт', () => {
    const b = L.build([trainer(1), noWrite], 'city', { cityId: 1 });
    assert.equal(b.line, 'От 50 BYN за занятие.');
    assert.ok(!/время/.test(b.line));
  });

  it('нет цены и нет окон — строки нет, блок остаётся', () => {
    const b = L.build([trainer(1, { services: [svc(1, [])] })], 'city', { cityId: 1 });
    assert.equal(b.line, '');
  });

  it('слова «окно» в тексте нет', () => {
    assert.ok(!/окн/i.test(L.build(items, 'city', { cityId: 1 }).line));
  });

  it('нет тренеров, которым есть что показать, — нет блока', () => {
    assert.equal(L.build([], 'city', { cityId: 1 }), null);
    assert.equal(L.build([hidden, trainer(5, { services: [], arenas: [] })], 'city', { cityId: 1 }), null);
  });
});

describe('Поиск → массовое катание (skate)', () => {
  it('«С нуля»: дословно из прототипа, ведёт на вкладку', () => {
    const b = L.build([gaevsky, vlad, klimas, hockey], 'skate', { cityId: 1 });
    assert.equal(b.line, 'Учат с нуля и тех, кто уже катается. 3 тренера, от 45 BYN.');
    assert.equal(b.href, 'trainers?tab=s-nulya&city_id=1');
    assert.deepEqual(b.chips, []);
  });

  it('нет тренеров «С нуля» — нет блока', () => {
    assert.equal(L.build([hockey], 'skate', { cityId: 1 }), null);
  });
});

describe('Поиск → ОХМ (hockey)', () => {
  it('только тренеры «С клюшкой»', () => {
    const b = L.build([gaevsky, hockey, hockey2], 'hockey', { cityId: 1 });
    assert.equal(b.line, 'Катание для хоккеистов: скорость, перекрёстный шаг, торможение. 2 тренера, от 55 BYN.');
    assert.equal(b.count, 2);
    assert.equal(b.href, 'trainers?tab=s-klyushkoy&city_id=1');
  });

  it('нет хоккейных тренеров — нет блока', () => {
    assert.equal(L.build([gaevsky, vlad], 'hockey', { cityId: 1 }), null);
  });
});

describe('карточка катка (arena)', () => {
  const items = [gaevsky, vlad, klimas];

  it('тренеры на катке есть: строка про каток, время с этого катка, ведёт на каток', () => {
    const b = L.build(items, 'arena', { cityId: 1, arenaId: 3 });
    assert.equal(b.line, 'На этом катке учат 2 тренера. Ближайшее свободное время — сегодня, 17:15.');
    assert.equal(b.href, 'trainers?arena_id=3&city_id=1');
    assert.equal(b.count, 2);
  });

  it('время берётся только с этого катка', () => {
    const b = L.build(items, 'arena', { cityId: 1, arenaId: 5 });
    assert.equal(b.line, 'На этом катке учит 1 тренер. Ближайшее свободное время — завтра, 18:00.');
  });

  it('на катке нет — тренеры города', () => {
    const b = L.build(items, 'arena', { cityId: 1, arenaId: 42 });
    assert.equal(b.line, 'На этом катке тренеров пока нет. В городе — 3, от 45 BYN за занятие.');
    assert.equal(b.href, 'trainers?city_id=1');
    assert.equal(b.count, 3);
  });

  it('в городе нет — нет блока', () => {
    assert.equal(L.build([], 'arena', { cityId: 1, arenaId: 3 }), null);
  });

  it('неизвестное место — нет блока', () => {
    assert.equal(L.build(items, 'nowhere', {}), null);
  });
});

describe('«от» — по услугам направления, а не по всем услугам тренера', () => {
  const k = trainer(77, { min_session_price_cents: 3000, services: [svc(1, tiers([['adult', 5000]])), svc(6, tiers([['adult', 5000]])), svc(7, tiers([['adult', 3000]]))] });
  const v = trainer(11, { services: [svc(1, tiers([['child', 4500], ['adult', 5000]]))] });

  it('ОФП (30) в «от» не входит: «С нуля» 45, «Все» 45, «С клюшкой» 50', () => {
    const items = [k, v];
    const show = (key) => M.minPriceOf(M.visibleTrainers(items, key, null), key).cents;
    assert.equal(show('s-nulya'), 4500);
    assert.equal(show('all'), 4500);
    assert.equal(show('s-klyushkoy'), 5000);
  });

  it('у вкладки нет цены — null', () => {
    assert.equal(M.minPriceOf([trainer(2, { services: [svc(1, [])] })], 'all'), null);
    assert.equal(M.minPriceOf([trainer(3, { min_price_by_direction: undefined })], 'all'), null);
  });

  it('блок входов считает так же: главная, «С нуля», «С клюшкой»', () => {
    const items = [k, v];
    assert.match(L.build(items, 'city', { cityId: 1 }).line, /^От 45 BYN за занятие/);
    assert.match(L.build(items, 'skate', { cityId: 1 }).line, /2 тренера, от 45 BYN\.$/);
    assert.match(L.build(items, 'hockey', { cityId: 1 }).line, /1 тренер, от 50 BYN\.$/);
  });
});

describe('«от» с групповой и абонементом (решение владельца 2026-11-07)', () => {
  // Сервер посчитал: Влад — групповая 25 на «С нуля»; Гаевский — абонемент 670/16 = 41,87 только на «Хоккейное».
  const vlad25 = trainer(11, {
    services: [svc(1, tiers([['child', 4500], ['adult', 5000]]), { group_price_cents: 2500 })],
    min_price_by_direction: { all: { cents: 2500, currency: 'BYN' }, 's-nulya': { cents: 2500, currency: 'BYN' } },
  });
  const gaev = trainer(9, {
    services: [svc(1, tiers([['child', 5000], ['adult', 5500]])), svc(4, tiers([['adult', 5500]]))],
    min_price_by_direction: {
      all: { cents: 4187, currency: 'BYN' },
      's-nulya': { cents: 5000, currency: 'BYN' },
      's-klyushkoy': { cents: 4187, currency: 'BYN' },
    },
  });

  it('групповая 25 → «С нуля» и главная «от 25»', () => {
    assert.match(L.build([vlad25, gaev], 'city', { cityId: 1 }).line, /^От 25 BYN за занятие/);
    assert.match(L.build([vlad25, gaev], 'skate', { cityId: 1 }).line, /2 тренера, от 25 BYN\.$/);
  });

  it('абонемент на «Хоккейное» — «С клюшкой» «от 41,87», «С нуля» не трогает', () => {
    assert.match(L.build([gaev], 'hockey', { cityId: 1 }).line, /1 тренер, от 41,87 BYN\.$/);
    assert.match(L.build([gaev], 'skate', { cityId: 1 }).line, /1 тренер, от 50 BYN\.$/);
    assert.match(L.build([gaev], 'city', { cityId: 1 }).line, /^От 41,87 BYN за занятие/);
  });
});

describe('одна модель с витриной', () => {
  it('число и «от» совпадают с тем, что считает витрина для вкладки', () => {
    const items = [gaevsky, vlad, klimas, hockey];
    const list = M.visibleTrainers(items, 's-nulya', null);
    const b = L.build(items, 'skate', { cityId: 1 });
    assert.equal(b.count, list.length);
    const p = M.minPriceOf(list);
    assert.ok(b.line.includes(M.formatMoney(p.cents, p.currency)));
  });
});

/* ── Компонент: запрос, кеш, ошибка ─────────────────────────────────────── */

function fakeHost() {
  const attrs = {};
  return {
    hidden: true, innerHTML: '', __listeners: {}, style: {},
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    setAttribute: (k, v) => { attrs[k] = String(v); },
    removeAttribute: (k) => { delete attrs[k]; },
    hasAttribute: (k) => k in attrs,
    addEventListener() {},
  };
}

describe('компонент LearnBlock', () => {
  let calls;
  let hosts;
  let respond;

  function load() {
    delete require.cache[require.resolve(path.join(WEBAPP, 'learn-block-core.js'))];
    globalThis.TrainerShowcaseModel = M;
    globalThis.LearnBlockModel = L;
    const store = {};
    globalThis.sessionStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } };
    globalThis.document = { querySelector: (sel) => hosts[sel] || null };
    require(path.join(WEBAPP, 'learn-block-core.js'));
    return globalThis.LearnBlock;
  }

  beforeEach(() => {
    calls = [];
    hosts = { '#a': fakeHost(), '#b': fakeHost() };
    respond = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ items: [gaevsky, vlad] }) });
    globalThis.fetch = (url) => { calls.push(url); return respond(url); };
  });

  it('рисует блок и делает один запрос на город для двух экранов', async () => {
    const LB = load();
    await Promise.all([LB.mount('#a', { place: 'city', cityId: 1 }), LB.mount('#b', { place: 'skate', cityId: 1 })]);
    assert.deepEqual(calls, ['/api/public/trainer-showcase?city_id=1']);
    assert.equal(hosts['#a'].hidden, false);
    assert.match(hosts['#a'].innerHTML, /Учиться с тренером/);
    assert.match(hosts['#a'].innerHTML, /Выбрать тренера/);
    assert.match(hosts['#b'].innerHTML, /Учат с нуля/);
  });

  it('повторный показ — из кеша сеанса, без запроса', async () => {
    const LB = load();
    await LB.mount('#a', { place: 'city', cityId: 1 });
    await LB.mount('#b', { place: 'city', cityId: 1 });
    assert.equal(calls.length, 1);
    assert.equal(hosts['#b'].hidden, false);
  });

  it('ошибка загрузки — блока нет, исключения нет', async () => {
    respond = () => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
    const LB = load();
    await LB.mount('#a', { place: 'city', cityId: 1 });
    assert.equal(hosts['#a'].hidden, true);
    assert.equal(hosts['#a'].innerHTML, '');
    respond = () => Promise.reject(new Error('offline'));
    await LB.mount('#b', { place: 'city', cityId: 2 });
    assert.equal(hosts['#b'].hidden, true);
  });

  it('пока грузятся данные, держит место (CLS); готово — снимает, ошибка/пусто — прячет без дыры', async () => {
    let done;
    respond = () => new Promise((r) => { done = () => r({ ok: true, json: () => Promise.resolve({ items: [gaevsky, vlad] }) }); });
    const LB = load();
    const pending = LB.mount('#a', { place: 'city', cityId: 1 });
    assert.equal(hosts['#a'].hidden, false);
    assert.equal(hosts['#a'].style.minHeight, '266px');
    assert.equal(hosts['#a'].getAttribute('data-lb-wait'), '');
    done();
    await pending;
    assert.equal(hosts['#a'].style.minHeight, '');
    assert.equal(hosts['#a'].hasAttribute('data-lb-wait'), false);
    assert.match(hosts['#a'].innerHTML, /lb-learn/);

    respond = () => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) });
    const failed = LB.mount('#b', { place: 'arena', cityId: 2 });
    assert.equal(hosts['#b'].style.minHeight, '212px');
    await failed;
    assert.equal(hosts['#b'].hidden, true);
    assert.equal(hosts['#b'].style.minHeight, '');
    assert.equal(hosts['#b'].hasAttribute('data-lb-wait'), false);
  });

  it('нет тренеров для места — блок скрыт', async () => {
    const LB = load();
    await LB.mount('#a', { place: 'hockey', cityId: 1 });
    assert.equal(hosts['#a'].hidden, true);
    assert.equal(hosts['#a'].innerHTML, '');
  });
});

describe('загрузчик learn-block.js', () => {
  it('держит место до загрузки файлов; не загрузились — прячет без дыры', async () => {
    const host = fakeHost();
    const doc = {
      currentScript: { getAttribute: () => 'learn-block.js?v=1' },
      head: { appendChild(node) { setImmediate(() => (node.onerror ? node.onerror() : null)); } },
      createElement: () => ({}),
      querySelector: () => host,
    };
    const prev = { LearnBlock: globalThis.LearnBlock, window: globalThis.window };
    delete globalThis.LearnBlock;
    globalThis.document = doc;
    delete require.cache[require.resolve(path.join(WEBAPP, 'learn-block.js'))];
    const code = fs.readFileSync(path.join(WEBAPP, 'learn-block.js'), 'utf8');
    new Function('window', code)(Object.assign(globalThis, {}));
    const pending = globalThis.LearnBlock.mount('#hubLearn', { place: 'city', cityId: 1 });
    assert.equal(host.hidden, false);
    assert.equal(host.style.minHeight, '266px');
    await pending;
    assert.equal(host.hidden, true);
    assert.equal(host.style.minHeight, '');
    assert.equal(host.hasAttribute('data-lb-wait'), false);
    if (prev.LearnBlock) globalThis.LearnBlock = prev.LearnBlock; else delete globalThis.LearnBlock;
  });
});

/* ── Подключение на экранах ────────────────────────────────────────────── */

const read = (f) => fs.readFileSync(path.join(WEBAPP, f), 'utf8');
const appPy = fs.readFileSync(path.resolve(__dirname, '../../src/api/app.py'), 'utf8');

describe('подключение на экранах', () => {
  for (const page of ['client-home.html', 'arena.html', 'client-bookings.html']) {
    it(page + ': статически только маленький загрузчик; тяжёлое грузится по требованию', () => {
      const html = read(page);
      assert.match(html, /src="learn-block\.js\?v=\d+"/);
      for (const a of ['learn-block.css', 'trainer-showcase-model.js', 'learn-block-model.js', 'learn-block-core.js']) {
        assert.ok(!html.includes(a), a + ' не должен подключаться статически');
      }
    });
  }

  it('Поиск: загрузчик подключает сам ice-tab.js, когда блок есть что показывать (вес ice.html)', () => {
    const html = read('ice.html');
    for (const a of ['learn-block', 'trainer-showcase-model', 'learn-block-core']) assert.ok(!html.includes(a + '.'), a);
    assert.match(read('ice-tab.js'), /replace\('ice-tab\.js', 'learn-block\.js'\)/);
  });

  it('загрузчик тянет стили, модели и компонент и не грузит ничего на hide()', () => {
    const js = read('learn-block.js');
    for (const a of ['learn-block.css', 'trainer-showcase-model.js', 'learn-block-model.js', 'learn-block-core.js']) {
      assert.ok(js.includes(a), a);
    }
  });

  it('сервер отдаёт файлы блока', () => {
    for (const a of ['learn-block-model.js', 'learn-block.js', 'learn-block-core.js', 'learn-block.css']) {
      assert.ok(appPy.includes('@app.get("/webapp/' + a + '")'), a);
    }
  });

  it('главная: блок только в чистом состоянии (приоритет 5), в остальных ветках скрыт', () => {
    const js = read('client-home-main.js');
    assert.match(js, /setHubLearn\(false\)/);
    assert.match(js, /setHubLearn\(true,/);
    assert.equal((js.match(/setHubLearn\(true,/g) || []).length, 1);
  });

  it('«Мои записи»: блок только после проверки, что записей не было никогда', () => {
    const html = read('client-bookings.html');
    assert.match(html, /bookings\/history\?offset=0&limit=1/);
    assert.match(html, /showBookingsLearnIfNever\(\);\s*paintBookingsEmpty/);
  });

  it('карточка катка: блок сразу после расписания', () => {
    const js = read('arena-card.js');
    assert.match(js, /renderIceTabs\(\) \+\s*renderLearnSlot\(\)/);
  });

  it('Поиск: массовое катание без фильтров и ОХМ-сеансы, не центры', () => {
    const js = read('ice-tab.js');
    assert.match(js, /state\.intent === 'skate' \? 'skate'/);
    assert.match(js, /state\.hockeySeg !== 'centers' \? 'hockey'/);
  });
});
