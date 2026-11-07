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

describe('профиль ребёнка не дублируется', () => {
  function profilesServer() {
    // Сервер: профили аккаунта = созданные через POST /client/profiles (как list_accessible_profiles).
    const items = [];
    let pid = 500;
    return {
      items,
      routes: [
        { match: (c) => isPath(c, '/api/webapp/client/profiles') && c.method === 'POST', reply: (c) => {
          const id = ++pid;
          items.push({ client_id: id, role: 'guardian', first_name: c.body.first_name });
          return resp(200, { client_id: id });
        } },
        { match: (c) => isPath(c, '/api/webapp/client/profiles') && c.method === 'GET', reply: () => resp(200, { items: items.slice(), default_profile_id: null }) },
      ],
    };
  }

  it('две записи Сони подряд — один профиль, вторая запись идёт формой постоянного', async () => {
    const srv = profilesServer();
    const h = boot({ showcase: { items: [trainer(1)] }, session: PHONE, routes: [
      ...srv.routes,
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(101), slot(102, { start_time: '11:00' })] }) },
      { match: (c) => isPath(c, '/api/webapp/client/booking'), reply: () => resp(200, { success: true, booking_id: 1 }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 101 });
    h.click({ 'data-act': 'pick', 'data-k': 'child' });
    h.input('name', 'Соня', 'child');
    h.click({ 'data-act': 'submit' });
    await tick();
    assert.equal(h.S.view, 'sent');
    h.click({ 'data-act': 'back' });
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 102 });
    assert.equal(h.S.book.regular, true);
    assert.deepEqual([...h.S.book.selected.map((p) => p.client_id)], [501]);
    h.click({ 'data-act': 'submit' });
    await tick();
    assert.equal(h.posts('/api/webapp/client/profiles').length, 1);
    assert.deepEqual(h.posts('/api/webapp/client/booking').map((c) => c.headers['X-Profile-Id']), ['501', '501']);
  });

  it('«время заняли» → время из шторки: форма нового ученика, профиль тот же', async () => {
    const srv = profilesServer();
    let n = 0;
    const h = boot({ showcase: { items: [trainer(1)] }, session: PHONE, routes: [
      ...srv.routes,
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(101), slot(102, { start_time: '11:00' })] }) },
      { match: (c) => isPath(c, '/api/webapp/client/booking'), reply: () => (++n === 1 ? resp(400, { detail: 'Slot not available' }) : resp(200, { success: true })) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 101 });
    h.click({ 'data-act': 'pick', 'data-k': 'child' });
    h.input('name', 'Соня', 'child');
    h.click({ 'data-act': 'submit' });
    await tick();
    h.sheetClick({ 'data-act': 'slot', 'data-slot': 102 });
    assert.equal(h.S.book.regular, false, 'форма нового ученика остаётся ею');
    assert.equal(h.S.book.kind, 'child');
    h.click({ 'data-act': 'submit' });
    await tick();
    assert.equal(h.S.view, 'sent');
    assert.equal(h.posts('/api/webapp/client/profiles').length, 1);
    assert.deepEqual(h.posts('/api/webapp/client/booking').map((c) => c.headers['X-Profile-Id']), ['501', '501']);
  });

  it('«время заняли» → другое время: профиль ребёнка тот же', async () => {
    const srv = profilesServer();
    let n = 0;
    const h = boot({ showcase: { items: [trainer(1)] }, session: PHONE, routes: [
      ...srv.routes,
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(101), slot(102, { start_time: '11:00' })] }) },
      { match: (c) => isPath(c, '/api/webapp/client/booking'), reply: () => (++n === 1 ? resp(400, { detail: 'Slot not available' }) : resp(200, { success: true })) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 101 });
    h.click({ 'data-act': 'pick', 'data-k': 'child' });
    h.input('name', 'Соня', 'child');
    h.click({ 'data-act': 'submit' });
    await tick();
    h.sheetClick({ 'data-act': 'week' });
    h.click({ 'data-act': 'slot', 'data-slot': 102 });
    // Соня уже есть в профилях — форма постоянного с ней отмеченной; имя заново не вводится.
    assert.deepEqual([...h.S.book.selected.map((p) => p.first_name)], ['Соня']);
    h.click({ 'data-act': 'submit' });
    await tick();
    assert.equal(h.S.view, 'sent');
    assert.equal(h.posts('/api/webapp/client/profiles').length, 1);
    assert.deepEqual(h.posts('/api/webapp/client/booking').map((c) => c.headers['X-Profile-Id']), ['501', '501']);
  });
});

describe('услуга и формат слота (онлайн/очно)', () => {
  const mixed = () => trainer(1, { services: [
    svc(1, tiers([['adult', 5000]])),
    { ...svc(99, tiers([['adult', 3000]])), is_public: false, direction_service_id: 1, is_online: true, service_name: 'Онлайн-разбор' },
    svc(2, tiers([['adult', 4000]])),
  ] });

  it('очный слот: онлайн-услуга не предлагается, на сервер не уходит', async () => {
    const h = boot({ showcase: { items: [mixed()] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(401)] }) },
      { match: (c) => isPath(c, '/api/webapp/client/booking'), reply: (c) => (c.body.service_id === 99 ? resp(422, { detail: 'Эта услуга только онлайн — выберите онлайн-слот.' }) : resp(200, { success: true })) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'dir', 'data-key': 's-nulya' }); // направление с очной 1 и онлайн 99
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 401 });
    // Подходит одна (очная 1) — выбрана сразу, «Какое занятие?» не спрашиваем.
    assert.ok(!h.app.innerHTML.includes('data-sid="99"'));
    h.click({ 'data-act': 'pick', 'data-k': 'adult' });
    h.input('name', 'Иван', 'self');
    h.click({ 'data-act': 'submit' });
    await tick();
    const b = h.posts('/api/webapp/client/booking');
    assert.equal(b.length, 1);
    assert.equal(b[0].body.service_id, 1);
    assert.equal(h.S.view, 'sent');
  });

  it('«Все»: в форме только очные услуги; выбранная раньше онлайн-услуга сброшена', async () => {
    const h = boot({ search: '?trainer_id=1&slot_id=401&service_id=99', showcase: { items: [mixed()] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [] }) },
      { match: (c) => c.url.startsWith('/api/webapp/client/slot/401'), reply: () => resp(200, { available: true, slot: slot(401) }) },
    ] });
    await tick(80);
    assert.equal(h.S.view, 'book');
    assert.equal(h.S.serviceId, null);
    const offered = (h.app.innerHTML.match(/data-act="svc" data-sid="(\d+)"/g) || []).map((x) => x.match(/\d+/)[0]);
    assert.deepEqual(offered, ['1', '2']);
    assert.match(h.app.innerHTML, /cta off/);
  });

  it('онлайн-слот: подходит только онлайн-услуга — выбрана сама', async () => {
    const h = boot({ showcase: { items: [mixed()] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(402, { is_online: true, arena_id: null })] }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 402 });
    assert.ok(h.app.innerHTML.includes('Онлайн-разбор'));
    assert.ok(!h.app.innerHTML.includes('Какое занятие?'));
  });
});

describe('групповая цена в форме = цена, которую запишет сервер', () => {
  // Сервер: COALESCE(group_price_cents, price_cents) — тарифы в группе не применяются.
  const serverGroupPrice = (s) => (s.group_price_cents != null ? s.group_price_cents : s.price_cents);
  const groupSlot = slot(701, { capacity: 6, spots_left: 3, service_id: 1 });
  const payLine = (html) => (html.match(/<p class="payl">(.*?)<\/p>/) || [])[1] || '';

  it('из выдачи', async () => {
    const T = trainer(7, { services: [svc(1, [], { price_cents: 5000, group_price_cents: 2500 })] });
    const h = boot({ showcase: { items: [T] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [groupSlot] }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 7 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 701 });
    h.click({ 'data-act': 'pick', 'data-k': 'child' });
    assert.match(payLine(h.app.innerHTML), new RegExp('<b>' + serverGroupPrice(T.services[0]) / 100 + ' BYN</b>'));
  });

  it('по личной ссылке (тренер не в выдаче — карточка каталога)', async () => {
    const card = { id: 7, can_book: true, profile: { first_name: 'Ольга', last_name: 'К' }, photos: [], arena_ids: [3], arena_names: ['Каток'],
      services: [{ service_id: 1, service_name: 'С нуля', is_online: false, price_cents: 5000, group_price_cents: 2500, currency_code: 'BYN', price_tiers: [] }] };
    const h = boot({ search: '?trainer_id=7&slot_id=701', session: PHONE, routes: [
      { match: (c) => c.url.startsWith('/api/webapp/client/catalog-trainer/7'), reply: () => resp(200, card) },
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [] }) },
      { match: (c) => c.url.startsWith('/api/webapp/client/slot/701'), reply: () => resp(200, { available: true, slot: groupSlot }) },
    ] });
    await tick(80);
    assert.equal(h.S.view, 'book');
    assert.equal(h.S.trainer.services[0].group_price_cents, 2500);
    h.click({ 'data-act': 'pick', 'data-k': 'child' });
    assert.match(payLine(h.app.innerHTML), new RegExp('<b>' + serverGroupPrice(card.services[0]) / 100 + ' BYN</b>'));
  });
});

describe('обрыв связи при записи', () => {
  it('запись проверяется у профиля, на который уходила (ребёнок), а не у родителя', async () => {
    const h = boot({ showcase: { items: [trainer(1)] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(101)] }) },
      { match: (c) => isPath(c, '/api/webapp/client/profiles') && c.method === 'POST', reply: () => resp(200, { client_id: 900 }) },
      { match: (c) => isPath(c, '/api/webapp/client/booking'), reply: () => Promise.reject(new TypeError('Failed to fetch')) },
      // Сервер: запись создана на профиль 900; у родителя (без заголовка) — пусто.
      { match: (c) => isPath(c, '/api/webapp/client/bookings'), reply: (c) => resp(200, { days: c.headers['X-Profile-Id'] === '900' ? [{ bookings: [{ slot_id: 101 }] }] : [] }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 101 });
    h.click({ 'data-act': 'pick', 'data-k': 'child' });
    h.input('name', 'Соня', 'child');
    h.click({ 'data-act': 'submit' });
    await tick();
    const check = h.calls.filter((c) => isPath(c, '/api/webapp/client/bookings'));
    assert.equal(check.length, 1);
    assert.equal(check[0].headers['X-Profile-Id'], '900');
    assert.equal(h.S.view, 'sent');
  });
});

describe('«Мои записи» после записи', () => {
  function switcherStub(active = null) {
    const st = { active, sets: [] };
    st.api = {
      getActiveProfileId: () => st.active,
      setActiveProfileId: (id) => { st.sets.push(id); st.active = id; },
    };
    return st;
  }

  it('записали ребёнка — «Мои записи» открываются на его профиле', async () => {
    const sw = switcherStub(null);
    const h = boot({ switcher: sw.api, showcase: { items: [trainer(1)] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(101)] }) },
      { match: (c) => isPath(c, '/api/webapp/client/profiles') && c.method === 'POST', reply: () => resp(200, { client_id: 900 }) },
      { match: (c) => isPath(c, '/api/webapp/client/booking'), reply: () => resp(200, { success: true }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 101 });
    h.click({ 'data-act': 'pick', 'data-k': 'child' });
    h.input('name', 'Соня', 'child');
    h.click({ 'data-act': 'submit' });
    await tick();
    h.click({ 'data-act': 'my-bookings' });
    assert.deepEqual([...sw.sets], [900]);
    assert.deepEqual([...h.ctx.navigated], ['client-bookings']);
  });

  it('записали активный профиль — переключать нечего', async () => {
    const sw = switcherStub(10);
    const profiles = { items: [{ client_id: 10, role: 'self', first_name: 'Мама' }], default_profile_id: 10 };
    const h = boot({ switcher: sw.api, profiles, showcase: { items: [trainer(1)] }, session: PHONE, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(101)] }) },
      { match: (c) => isPath(c, '/api/webapp/client/booking'), reply: () => resp(200, { success: true }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 1 });
    await tick();
    h.click({ 'data-act': 'slot', 'data-slot': 101 });
    await tick();
    h.click({ 'data-act': 'submit' });
    await tick();
    assert.equal(h.S.view, 'sent');
    h.click({ 'data-act': 'my-bookings' });
    assert.equal(sw.sets.length, 0);
  });
});

describe('заявка без города в сессии', () => {
  async function sendRequest(h) {
    h.click({ 'data-act': 'request' });
    h.sheetInput('rq-name', 'Анна');
    h.sheetClick({ 'data-act': 'rq-send' });
    await tick();
  }

  it('по личной ссылке — город тренера из карточки', async () => {
    const card = { id: 8, can_book: false, profile: { first_name: 'Ольга', city_id: 1 }, photos: [], arena_ids: [],
      services: [{ service_id: 1, service_name: 'С нуля', price_cents: 5000, price_tiers: [] }] };
    const h = boot({ search: '?trainer_id=8', session: { ...PHONE, city_id: null }, routes: [
      { match: (c) => c.url.startsWith('/api/webapp/client/catalog-trainer/8'), reply: () => resp(200, card) },
      { match: (c) => isPath(c, '/api/webapp/client/request'), reply: () => resp(200, { success: true, request_id: 1 }) },
    ] });
    await tick(80);
    await sendRequest(h);
    const p = h.posts('/api/webapp/client/request');
    assert.equal(p.length, 1);
    assert.equal(p[0].body.city_id, 1);
    assert.equal(p[0].body.trainer_id, 8);
    assert.equal(h.S.view, 'reqsent');
  });

  it('город неизвестен и у тренера — заявка всё равно уходит (город возьмёт сервер по тренеру)', async () => {
    const T = trainer(5, { can_book: false });
    const h = boot({ showcase: { items: [T] }, session: { ...PHONE, city_id: null }, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/request'), reply: () => resp(200, { success: true, request_id: 1 }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 5 });
    await tick();
    await sendRequest(h);
    const p = h.posts('/api/webapp/client/request');
    assert.equal(p.length, 1);
    assert.equal('city_id' in p[0].body, false);
    assert.equal(p[0].body.trainer_id, 5);
  });

  it('город в сессии есть — шлём его, как раньше', async () => {
    const T = trainer(5, { can_book: false });
    const h = boot({ showcase: { items: [T] }, session: { ...PHONE, city_id: 3 }, routes: [
      { match: (c) => isPath(c, '/api/webapp/client/request'), reply: () => resp(200, { success: true, request_id: 1 }) },
    ] });
    await tick();
    h.click({ 'data-act': 'trainer', 'data-tid': 5 });
    await tick();
    await sendRequest(h);
    assert.equal(h.posts('/api/webapp/client/request')[0].body.city_id, 3);
  });
});
