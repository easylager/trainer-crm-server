/**
 * PR #236: запись из витрины тренеров — сценарии на стенде (настоящий trainer-showcase-main.js, fetch подменён).
 * Run: node --test tests/js/trainer-showcase-booking.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { boot, resp, tick } = require('./helpers/trainer-showcase-harness');

const tiers = (pairs) => pairs.map(([k, c], i) => ({ id: 100 + i, tier_kind: k, price_cents: c, currency_code: 'BYN' }));
const svc = (id, t, extra = {}) => ({
  service_id: id, service_name: 'Услуга ' + id, is_public: true, is_online: false, currency_code: 'BYN', price_cents: 5000, price_tiers: t, ...extra,
});
const trainer = (id, extra = {}) => ({
  id, name: 'Тренер ' + id, first_name: 'Тренер' + id, can_book: true,
  services: [svc(1, tiers([['child', 5000], ['adult', 5500]]))], arenas: [{ id: 3, name: 'Каток' }], windows: [], ...extra,
});
const slot = (id, extra = {}) => ({
  id, slot_date: '2026-11-20', start_time: '10:00', end_time: '10:45', capacity: 1, spots_left: 1, arena_id: 3, is_online: false, ...extra,
});
const isPath = (c, p) => c.url.split('?')[0] === p;
const PHONE = { client_phone: '+375291234567' };

describe('гонка ответов при переключении тренеров', () => {
  it('поздний ответ слотов тренера A не попадает в карточку B', async () => {
    const h = boot({ showcase: { items: [trainer(1), trainer(2)] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots') && c.url.includes('trainer_id=1'), reply: () => resp(200, { slots: [slot(101)] }, 120) },
      { match: (c) => isPath(c, '/api/webapp/client/slots') && c.url.includes('trainer_id=2'), reply: () => resp(200, { slots: [slot(201)] }, 10) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    h.click({ 'data-act': 'back' });
    h.click({ 'data-act': 'trainer', 'data-tid': 2 });
    await tick(200);
    assert.equal(h.S.trainer.id, 2);
    assert.deepEqual(h.S.slots.map((s) => s.id), [201]);
    assert.ok(!h.app.innerHTML.includes('data-slot="101"'));
    assert.ok(h.app.innerHTML.includes('data-slot="201"'));
  });

  it('слот чужого тренера не открывает форму записи', async () => {
    const h = boot({ showcase: { items: [trainer(1), trainer(2)] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: (c) => resp(200, { slots: [slot(c.url.includes('trainer_id=1') ? 101 : 201)] }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 2 });
    await tick();
    h.S.slots.push(Object.assign(slot(101), { trainer_id: 1 }));
    h.click({ 'data-act': 'slot', 'data-slot': 101 });
    assert.equal(h.S.view, 'trainer');
    assert.equal(h.S.book, null);
  });

  it('время с витрины: поздний ответ тренера A не открывает запись к A поверх тренера B', async () => {
    const h = boot({ showcase: { items: [trainer(1), trainer(2)] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots') && c.url.includes('trainer_id=1'), reply: () => resp(200, { slots: [slot(101)] }, 120) },
      { match: (c) => isPath(c, '/api/webapp/client/slots') && c.url.includes('trainer_id=2'), reply: () => resp(200, { slots: [slot(201)] }, 10) },
    ] });
    await tick();
    h.click({ 'data-act': 'win', 'data-tid': 1, 'data-slot': 101 });
    h.click({ 'data-act': 'back' });
    h.click({ 'data-act': 'trainer', 'data-tid': 2 });
    await tick(200);
    assert.equal(h.S.trainer.id, 2);
    assert.equal(h.S.view, 'trainer');
    assert.equal(h.S.book, null);
    assert.deepEqual(h.S.slots.map((s) => s.id), [201]);
  });

  it('быстрое переключение услуги: применяется ответ последнего запроса', async () => {
    const T = trainer(1, { services: [svc(1, tiers([['adult', 5000]])), svc(2, tiers([['adult', 5000]]))] });
    const h = boot({ showcase: { items: [T] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots') && c.url.includes('service_id=1'), reply: () => resp(200, { slots: [slot(111)] }, 100) },
      { match: (c) => isPath(c, '/api/webapp/client/slots') && c.url.includes('service_id=2'), reply: () => resp(200, { slots: [slot(222)] }, 10) },
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [] }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'svc', 'data-sid': 1 });
    h.click({ 'data-act': 'svc', 'data-sid': 2 });
    await tick(160);
    assert.deepEqual(h.S.slots.map((s) => s.id), [222]);
  });
});

describe('групповой слот: одно место — один участник', () => {
  const family = { items: [
    { client_id: 10, role: 'self', first_name: 'Мама' },
    { client_id: 11, role: 'guardian', first_name: 'Соня' },
    { client_id: 12, role: 'guardian', first_name: 'Маша' },
  ], default_profile_id: 10 };
  const groupTrainer = () => trainer(1, { services: [svc(1, tiers([['child', 5000], ['adult', 5500], ['two_children', 8000]]), { group_price_cents: 2500 })] });

  it('постоянный: второго ребёнка не отметить, «Можно двоих» не показываем, запись — на одного', async () => {
    const h = boot({ showcase: { items: [groupTrainer()] }, profiles: family, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(301, { capacity: 6, spots_left: 1, service_id: 1 })] }) },
      { match: (c) => isPath(c, '/api/webapp/client/booking'), reply: () => resp(200, { success: true }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 301 });
    await tick();
    h.click({ 'data-act': 'pick', 'data-k': 10 }); // снять маму
    h.click({ 'data-act': 'pick', 'data-k': 11 });
    assert.ok(!h.app.innerHTML.includes('Можно двоих'));
    assert.match(h.app.innerHTML, /data-k="12" aria-checked="false" disabled/);
    assert.match(h.app.innerHTML, /<b>25 BYN<\/b>/);
    h.click({ 'data-act': 'submit' });
    await tick();
    const b = h.posts('/api/webapp/client/booking');
    assert.equal(b.length, 1);
    assert.equal(b[0].headers['X-Profile-Id'], '11');
    assert.equal(b[0].body.comment, null);
  });

  it('двое, отмеченные на индивидуальном слоте, в группе не уходят одной записью', async () => {
    const T = groupTrainer();
    const h = boot({ showcase: { items: [T] }, profiles: family, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(201), slot(301, { capacity: 6, spots_left: 2, service_id: 1 })] }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 201 });
    h.click({ 'data-act': 'pick', 'data-k': 10 });
    h.click({ 'data-act': 'pick', 'data-k': 11 });
    h.click({ 'data-act': 'pick', 'data-k': 12 });
    assert.equal(h.S.book.selected.length, 2);
    h.click({ 'data-act': 'slot', 'data-slot': 301 }); // из формы — на групповой слот
    assert.equal(h.S.book.selected.length, 1);
  });

  it('новый ученик: в группе нет «Двое на одном занятии»', async () => {
    const h = boot({ showcase: { items: [groupTrainer()] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(301, { capacity: 6, spots_left: 3, service_id: 1 })] }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 301 });
    assert.ok(!h.app.innerHTML.includes('data-act="duo"'));
    assert.ok(!h.app.innerHTML.includes('data-k="two_children"'));
  });
});
