'use strict';
/**
 * TASK-401: сценарии записи при ВЫКЛЮЧЕННОМ флаге единой карточки — D, D2, E, «Назад» с E, L1, L2, L3,
 * карточка с `listed=1`. Снимок снят этим же кодом на базе d4419b77 (до TASK-401) и лежит в
 * tests/js/fixtures/trainer-booking-flag-off.snapshot.json; тест сверяет текущую ветку с ним побайтно.
 * Снимается всё, что видит человек и сервер: разметка #app и шторки, экран, вызовы API, история, переходы.
 */
const { boot, resp, tick } = require('./trainer-showcase-harness');
const { STATES } = require('../fixtures/trainer-card-states');

const trainer = STATES.A.trainer;
const slots = STATES.A.slots;

const slotsRoute = (list, status = 200) => ({
  match: (c) => c.url.split('?')[0] === '/api/webapp/client/slots',
  reply: () => resp(status, { slots: list }),
});
const bookingRoute = (status, data) => ({
  match: (c) => c.url.split('?')[0] === '/api/webapp/client/booking',
  reply: () => resp(status, data),
});
const passRoute = {
  match: (c) => c.url.split('?')[0] === '/api/webapp/client/passes',
  reply: () => resp(200, {
    items: [{
      trainer_id: 1, status: 'active', sessions_remaining: 4, sessions_total: 8,
      product_name: '8 занятий', service_ids: [1], tier_kinds: ['child'], is_expired: false,
    }],
  }),
};

function snap(h, extra = {}) {
  return {
    view: h.S.view,
    app: h.app.innerHTML,
    sheet: h.sheet.innerHTML,
    sheetHidden: h.sheet.hidden,
    calls: h.calls.map((c) => c.method + ' ' + c.url),
    history: JSON.stringify(h.ctx.history.entries) + ' ' + JSON.stringify(h.ctx.history.state),
    navigated: h.ctx.navigated.slice(),
    ...extra,
  };
}

function open(opts = {}) {
  return boot({
    unified: false,
    search: opts.search || '?trainer_id=' + trainer.id,
    initData: 'x',
    showcase: opts.showcase || { items: [trainer] },
    profiles: opts.profiles || { items: [], default_profile_id: null },
    session: opts.session || { client_phone: '+375291112233', client_first_name: 'Анна', city_name: 'Минск' },
    routes: opts.routes || [slotsRoute(slots)],
    miniAppBack: opts.miniAppBack,
    tg: opts.tg,
  });
}

function fillAndSubmit(h) {
  h.click({ 'data-act': 'slot', 'data-slot': '101' });
  h.click({ 'data-act': 'pick', 'data-k': 'adult' });
  h.input('name', 'Анна', 'self');
  h.S.book.phone = '+375291112233';
  h.click({ 'data-act': 'submit' });
}

async function capture() {
  const out = {};

  // D: новый клиент — форма до и после выбора тарифа.
  {
    const h = open();
    await tick(40);
    h.click({ 'data-act': 'slot', 'data-slot': '101' });
    out['D:open'] = snap(h);
    h.click({ 'data-act': 'pick', 'data-k': 'adult' });
    out['D:picked'] = snap(h);
  }

  // D2: постоянный клиент — профили, тариф прошлой записи, абонемент.
  {
    const h = open({
      profiles: {
        items: [{ client_id: 9, role: 'self', first_name: 'Анна' }, { client_id: 10, role: 'guardian', first_name: 'Соня' }],
        default_profile_id: 10,
      },
      session: {
        client_phone: '+375291112233', client_first_name: 'Анна',
        last_created_booking_service_id: 1, last_created_booking_service_price_variant_id: 11,
      },
      routes: [slotsRoute(slots), passRoute],
    });
    await tick(80);
    h.click({ 'data-act': 'slot', 'data-slot': '101' });
    await tick(80);
    out.D2 = snap(h);
  }

  // E и «Назад» с E (нативная стрелка Telegram).
  {
    const back = { fn: null, isNative() { return true; }, set(fn) { this.fn = fn; }, clear() { this.fn = null; } };
    const h = open({
      miniAppBack: back,
      tg: {
        initData: 'x',
        initDataUnsafe: { user: { id: 5, allows_write_to_pm: true } },
        isVersionAtLeast: () => true,
        requestWriteAccess(cb) { cb(true); },
      },
      routes: [slotsRoute(slots), bookingRoute(200, { success: true, reminder_plan: 'сегодня в 15:15, за 2 часа' })],
    });
    await tick(40);
    fillAndSubmit(h);
    await tick(40);
    out.E = snap(h, { backSet: typeof back.fn === 'function' });
    if (back.fn) back.fn();
    await tick(20);
    out['E:back'] = snap(h);
  }

  // E в браузере (своя кнопка «‹ Назад» вместо нативной) — тот же экран и возврат кнопкой.
  {
    const h = open({ routes: [slotsRoute(slots), bookingRoute(200, { success: true })] });
    await tick(40);
    fillAndSubmit(h);
    await tick(40);
    out['E:browser'] = snap(h);
    h.click({ 'data-act': 'back' });
    await tick(20);
    out['E:browser:back'] = snap(h);
  }

  // L2: время заняли — есть другие окна / других окон нет.
  {
    const h = open({ routes: [slotsRoute(slots), bookingRoute(400, { detail: 'Slot not available' })] });
    await tick(40);
    fillAndSubmit(h);
    await tick(60);
    out['L2:alt'] = snap(h);
  }
  {
    const h = open({ routes: [slotsRoute([slots[0]]), bookingRoute(400, { detail: 'Slot not available' })] });
    await tick(40);
    fillAndSubmit(h);
    await tick(60);
    out['L2:none'] = snap(h);
  }

  // L1: окна не загрузились.
  {
    const h = open({ routes: [slotsRoute([], 500)] });
    await tick(40);
    out.L1 = snap(h);
  }

  // L3: тренера нет (404) и сеть/5xx при загрузке тренера по ссылке.
  {
    const h = open({
      search: '?trainer_id=99',
      showcase: { items: [] },
      routes: [{ match: (c) => c.url.indexOf('/catalog-trainer/99') >= 0, reply: () => resp(404, { detail: 'Trainer not found' }) }],
    });
    await tick(40);
    out['L3:404'] = snap(h);
  }
  {
    const h = open({
      search: '?trainer_id=99',
      showcase: { items: [] },
      routes: [{ match: (c) => c.url.indexOf('/catalog-trainer/99') >= 0, reply: () => resp(503, { detail: 'down' }) }],
    });
    await tick(40);
    out['L3:503'] = snap(h);
  }

  // N: ссылка с listed=1 при выключенном флаге — карточка как раньше.
  {
    const h = open({
      search: '?trainer_id=1&listed=1&via=link',
      profiles: { items: [{ client_id: 9, role: 'self', first_name: 'Анна' }], default_profile_id: 9 },
      routes: [slotsRoute(slots), passRoute],
    });
    await tick(80);
    out.listed = snap(h);
  }

  // Ссылка со слотом (slot_id) — сразу запись.
  {
    const h = open({
      search: '?trainer_id=1&slot_id=102&via=link',
      routes: [
        slotsRoute(slots),
        { match: (c) => c.url.split('?')[0] === '/api/webapp/client/slot/102', reply: () => resp(200, { available: true, slot: slots[1] }) },
      ],
    });
    await tick(80);
    out.slotLink = snap(h);
  }

  return out;
}

module.exports = { capture };
