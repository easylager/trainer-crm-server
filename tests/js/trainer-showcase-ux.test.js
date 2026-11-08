/**
 * PR #236 (M2): витрина тренеров — подписка через ворота записи, тумблер «Сохранить», окна-шторки с клавиатуры, тексты.
 * Run: node --test tests/js/trainer-showcase-ux.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { boot, resp, tick } = require('./helpers/trainer-showcase-harness');

const trainer = (id, extra = {}) => ({
  id, name: 'Анна ' + id, first_name: 'Анна', can_book: true,
  services: [{ service_id: 1, service_name: 'С нуля', is_public: true, is_online: false, currency_code: 'BYN', price_cents: 5000,
    price_tiers: [{ id: 1, tier_kind: 'child', price_cents: 5000, currency_code: 'BYN' }, { id: 2, tier_kind: 'adult', price_cents: 5500, currency_code: 'BYN' }] }],
  arenas: [{ id: 3, name: 'Каток' }], windows: [], ...extra,
});
const slot = (id, extra = {}) => ({
  id, slot_date: '2026-11-20', start_time: '10:00', end_time: '10:45', capacity: 1, spots_left: 1, arena_id: 3, is_online: false, ...extra,
});
const isPath = (c, p) => c.url.split('?')[0] === p;
const PHONE = { client_phone: '+375291234567' };
const EDGES = '/api/webapp/client/trainer-edges';

function makeTg(o = {}) {
  const tg = {
    initData: 'x', initDataUnsafe: { user: { id: 5, allows_write_to_pm: !!o.allowed } }, requests: 0, alerts: [],
    isVersionAtLeast: () => true,
    showAlert(t, cb) { tg.alerts.push(t); if (cb) cb(); },
    showPopup(p, cb) { cb(null); },
    requestWriteAccess(cb) { tg.requests += 1; cb(o.answer !== false); },
  };
  return tg;
}

const noSlots = { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [] }) };

async function openEmptyTrainer(opts = {}) {
  const h = boot({ showcase: { items: [trainer(1)] }, session: PHONE, tg: opts.tg, routes: [noSlots, ...(opts.routes || [])] });
  await tick();
  h.click({ 'data-act': 'trainer', 'data-tid': 1 });
  await tick();
  return h;
}

describe('подписка «Сообщить, когда появится время»', () => {
  it('бот не может писать и человек отказал: подписки нет, показан блок «Разрешите сообщения»', async () => {
    const tg = makeTg({ answer: false });
    const h = await openEmptyTrainer({ tg });
    h.click({ 'data-act': 'notify' });
    await tick();
    assert.equal(tg.requests, 1);
    assert.equal(h.posts(EDGES + '/notify-slots').length, 0);
    assert.equal(h.S.notify, false);
    assert.ok(h.app.innerHTML.includes('data-wa-block="askable"'));
    assert.ok(h.app.innerHTML.includes('Разрешите сообщения'));
    assert.ok(!h.app.innerHTML.includes('Сообщим, когда'));
  });

  it('разрешение выдано в окне Telegram: одна подписка, кнопка показывает итог', async () => {
    const tg = makeTg({ answer: true });
    const h = await openEmptyTrainer({ tg, routes: [{ match: (c) => isPath(c, EDGES + '/notify-slots'), reply: () => resp(200, { edge: { notify_when_slots: true } }) }] });
    h.click({ 'data-act': 'notify' });
    await tick();
    assert.equal(h.posts(EDGES + '/notify-slots').length, 1);
    assert.equal(h.S.notify, true);
    assert.ok(h.app.innerHTML.includes('Сообщим, когда появится время'));
    assert.ok(!h.app.innerHTML.includes('data-wa-block'));
  });

  it('бот уже может писать: окно не спрашивает, подписка уходит', async () => {
    const tg = makeTg({ allowed: true });
    const h = await openEmptyTrainer({ tg, routes: [{ match: (c) => isPath(c, EDGES + '/notify-slots'), reply: () => resp(200, {}) }] });
    h.click({ 'data-act': 'notify' });
    await tick();
    assert.equal(tg.requests, 0);
    assert.equal(h.posts(EDGES + '/notify-slots').length, 1);
  });

  it('уже подписан (по данным сервера): кнопка неактивна и без повторной подписки', async () => {
    const h = await openEmptyTrainer({ routes: [{ match: (c) => isPath(c, EDGES) && c.method === 'GET', reply: () => resp(200, { all: [{ trainer_id: 1, notify_when_slots: true }] }) }] });
    assert.equal(h.S.notify, true);
    assert.match(h.app.innerHTML, /data-act="notify" disabled>Сообщим, когда появится время/);
  });

  it('текст кнопки: «Сообщить», не «Напомнить»', async () => {
    const h = await openEmptyTrainer();
    assert.ok(h.app.innerHTML.includes('Сообщить, когда появится время'));
    assert.ok(!h.app.innerHTML.includes('Напомнить'));
  });
});

describe('«Сохранить тренера»', () => {
  const edgesRoute = (all) => ({ match: (c) => isPath(c, EDGES) && c.method === 'GET', reply: () => resp(200, { all }) });

  it('сохранён на сервере → экран открывается с «Тренер сохранён»; повтор снимает через DELETE', async () => {
    const h = await openEmptyTrainer({ routes: [
      edgesRoute([{ trainer_id: 1, is_saved: true }]),
      { match: (c) => isPath(c, EDGES + '/save/1') && c.method === 'DELETE', reply: () => resp(200, { edge: { is_saved: false } }) },
    ] });
    assert.equal(h.S.saved, true);
    assert.ok(h.app.innerHTML.includes('♥ Тренер сохранён'));
    assert.ok(h.app.innerHTML.includes('aria-pressed="true"'));
    h.click({ 'data-act': 'save' });
    await tick();
    assert.equal(h.calls.filter((c) => c.method === 'DELETE').length, 1);
    assert.equal(h.S.saved, false);
    assert.ok(h.app.innerHTML.includes('♡ Сохранить тренера'));
  });

  it('не сохранён: POST, потом можно снять обратно', async () => {
    const h = await openEmptyTrainer({ routes: [
      edgesRoute([{ trainer_id: 2, is_saved: true }]),
      { match: (c) => isPath(c, EDGES + '/save') && c.method === 'POST', reply: () => resp(200, {}) },
      { match: (c) => isPath(c, EDGES + '/save/1') && c.method === 'DELETE', reply: () => resp(200, {}) },
    ] });
    assert.equal(h.S.saved, false, 'запись про другого тренера не считается');
    h.click({ 'data-act': 'save' });
    await tick();
    assert.equal(h.posts(EDGES + '/save').length, 1);
    assert.equal(h.S.saved, true);
    h.click({ 'data-act': 'save' });
    await tick();
    assert.equal(h.S.saved, false);
    assert.equal(h.calls.filter((c) => c.method === 'DELETE').length, 1);
  });

  it('ошибка: состояние не меняется, человек видит сообщение', async () => {
    const h = await openEmptyTrainer({ routes: [
      edgesRoute([]),
      { match: (c) => isPath(c, EDGES + '/save') && c.method === 'POST', reply: () => resp(500, { detail: 'x' }) },
    ] });
    h.click({ 'data-act': 'save' });
    await tick();
    assert.equal(h.S.saved, false);
    assert.ok(h.app.innerHTML.includes('Не получилось — попробуйте ещё раз.'));
    assert.ok(h.app.innerHTML.includes('♡ Сохранить тренера'));
  });

  it('GET состояния упал: экран работает как с несохранённым', async () => {
    const h = await openEmptyTrainer({ routes: [{ match: (c) => isPath(c, EDGES) && c.method === 'GET', reply: () => resp(500, {}) }] });
    assert.equal(h.S.saved, false);
    assert.ok(h.app.innerHTML.includes('♡ Сохранить тренера'));
  });
});

describe('шторки: клавиатура и фокус', () => {
  async function openRequest() {
    const card = trainer(1, { can_book: false });
    const h = boot({ showcase: { items: [card] }, session: PHONE, routes: [noSlots] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    const opener = { isConnected: true, getAttribute: (k) => (k === 'data-act' ? 'request' : null), focus() { h.doc.activeElement = opener; } };
    h.doc.activeElement = opener;
    h.click({ 'data-act': 'request' });
    return { h, opener };
  }

  it('окно имеет имя, фокус внутри, фон недоступен', async () => {
    const { h } = await openRequest();
    assert.ok(!h.sheet.hidden);
    assert.match(h.sheet.innerHTML, /role="dialog" aria-modal="true" aria-labelledby="sheetTitle"/);
    assert.match(h.sheet.innerHTML, /<h4 id="sheetTitle">Оставить заявку/);
    assert.match(h.sheet.innerHTML, /aria-label="Закрыть"/);
    assert.equal(h.doc.activeElement.tag, 'div');
    assert.ok(h.sheet.contains(h.doc.activeElement));
    assert.equal(h.app.attrs.inert, '');
    assert.equal(h.app.attrs['aria-hidden'], 'true');
  });

  it('Esc закрывает, фокус возвращается на кнопку-открывашку, фон снова доступен', async () => {
    const { h, opener } = await openRequest();
    const ev = h.key('Escape');
    assert.ok(ev.defaultPrevented);
    assert.ok(h.sheet.hidden);
    assert.equal(h.doc.activeElement, opener);
    assert.ok(!('inert' in h.app.attrs));
    assert.ok(!('aria-hidden' in h.app.attrs));
  });

  it('Tab и Shift+Tab ходят по кругу внутри окна', async () => {
    const { h } = await openRequest();
    const items = h.sheet.querySelectorAll();
    assert.ok(items.length >= 3);
    const first = items[0];
    const last = items[items.length - 1];
    last.focus();
    assert.ok(h.key('Tab').defaultPrevented);
    assert.equal(h.doc.activeElement, first);
    assert.ok(h.key('Tab', true).defaultPrevented);
    assert.equal(h.doc.activeElement, last);
    // Из окна-контейнера Shift+Tab тоже уходит на последний, а не за окно.
    h.sheet.querySelector('.sheet').focus();
    assert.ok(h.key('Tab', true).defaultPrevented);
    assert.equal(h.doc.activeElement, last);
    // Посередине браузер ходит сам.
    items[1].focus();
    assert.ok(!h.key('Tab').defaultPrevented);
  });

  it('перерисовка заявки (ошибка поля) не теряет фокус и не затирает открывашку', async () => {
    const { h, opener } = await openRequest();
    const field = h.sheet.querySelectorAll().find((n) => n.attrs['data-field'] === 'rq-name');
    field.focus();
    h.sheetClick({ 'data-act': 'rq-send' });
    await tick();
    const now = h.doc.activeElement;
    assert.equal(now.attrs['data-field'], 'rq-name', 'фокус остался на том же поле');
    assert.ok(h.sheet.contains(now));
    h.sheetClick({ 'data-act': 'sheet-close' });
    assert.equal(h.doc.activeElement, opener);
  });

  it('Esc без открытого окна ничего не делает', async () => {
    const h = boot({ showcase: { items: [trainer(1)] }, session: PHONE, routes: [noSlots] });
    await tick();
    assert.ok(!h.key('Escape').defaultPrevented);
  });
});

describe('тексты окна «время недоступно»', () => {
  const profileRoute = { match: (c) => isPath(c, '/api/webapp/client/profiles') && c.method === 'POST', reply: () => resp(200, { client_id: 501 }) };
  it('после неудачной записи: «10:00 уже недоступно», «Данные запомнили…», родительный падеж имени', async () => {
    const h = boot({ showcase: { items: [trainer(1)] }, session: PHONE, routes: [
      profileRoute,
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(101), slot(102, { start_time: '11:00' })] }) },
      { match: (c) => isPath(c, '/api/webapp/client/booking'), reply: () => resp(400, { detail: 'Slot not available' }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 101 });
    h.click({ 'data-act': 'pick', 'data-k': 'child' });
    h.input('name', 'Соня', 'child');
    h.click({ 'data-act': 'submit' });
    await tick();
    assert.ok(h.sheet.innerHTML.includes('10:00 уже недоступно'));
    assert.ok(h.sheet.innerHTML.includes('Данные запомнили. Свободное время у Анны:'));
    assert.ok(!h.sheet.innerHTML.includes('заняли'));
    assert.ok(!h.sheet.innerHTML.includes('телефон сохранены'));
  });

  it('имя латиницей не склоняется: «у тренера»', async () => {
    const h = boot({ showcase: { items: [trainer(1, { first_name: 'Katusha' })] }, session: PHONE, routes: [
      profileRoute,
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(101), slot(102, { start_time: '11:00' })] }) },
      { match: (c) => isPath(c, '/api/webapp/client/booking'), reply: () => resp(400, { detail: 'Slot not available' }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 101 });
    h.click({ 'data-act': 'pick', 'data-k': 'child' });
    h.input('name', 'Соня', 'child');
    h.click({ 'data-act': 'submit' });
    await tick();
    assert.ok(h.sheet.innerHTML.includes('Данные запомнили. Свободное время у тренера:'));
  });

  it('ссылка на время, которого нет: «Это время уже недоступно», без «Данные запомнили»', async () => {
    const h = boot({ search: '?trainer_id=1&slot_id=999', showcase: { items: [trainer(1)] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(101)] }) },
      { match: (c) => c.url.startsWith('/api/webapp/client/slot/'), reply: () => resp(200, { available: false }) },
    ] });
    await tick(80);
    assert.ok(h.sheet.innerHTML.includes('Это время уже недоступно'));
    assert.ok(!h.sheet.innerHTML.includes('Данные запомнили'));
  });
});
