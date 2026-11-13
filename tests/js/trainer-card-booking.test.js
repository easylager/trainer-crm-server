/**
 * TASK-401: запись и регистрация по ссылке тренера за флагом window.__UNIFIED_TRAINER_CARD__.
 * Флаг выключен — тексты шторки и подпись кнопки как до этой задачи.
 * Run: node --test tests/js/trainer-card-booking.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { boot, resp, tick } = require('./helpers/trainer-showcase-harness');
const { STATES } = require('./fixtures/trainer-card-states');
const { capture } = require('./helpers/trainer-booking-flag-off-scenarios');
const FLAG_OFF = require('./fixtures/trainer-booking-flag-off.snapshot.json');

const FORBIDDEN = ['Время за вами', 'Если ответа не будет', 'Устанавливать ничего не нужно', 'Вы занимались', 'каталог', 'Ледовая арена «Замок»', 'запись после согласования цены', 'за 2 часа'];

const slotsRoute = (slots, status = 200) => ({
  match: (c) => c.url.split('?')[0] === '/api/webapp/client/slots',
  reply: () => resp(status, { slots }),
});

const trainer = STATES.A.trainer;
const slots = STATES.A.slots;

/** Ответ /client/catalog-trainer/{id} для тренера A (форма карточки каталога). */
const catalogCard = {
  id: trainer.id, can_book: true, contact_telegram_url: '/r/tg/1',
  profile: { first_name: 'Анна', last_name: 'Соколова', session_duration_minutes: 60 },
  services: trainer.services, arena_ids: [3], arena_names: ['Замок'],
};

/** Тренер не из выдачи города: /client/catalog-trainer/{id}. status 0 — обрыв сети. */
const trainerFallback = (status) => ({
  match: (c) => c.url.indexOf('/catalog-trainer/') >= 0,
  reply: () => (status ? resp(status, { detail: 'x' }) : Promise.reject(new TypeError('Failed to fetch'))),
});

function openBook(opts = {}) {
  return boot({
    unified: opts.unified !== false,
    search: opts.search || '?trainer_id=' + trainer.id,
    initData: 'x',
    showcase: { items: [opts.trainer || trainer] },
    profiles: opts.profiles || { items: [], default_profile_id: null },
    session: opts.session || { client_phone: '+375291112233', client_first_name: 'Анна' },
    routes: opts.routes || [slotsRoute(opts.slots || slots)],
    miniAppBack: opts.miniAppBack,
    tg: opts.tg,
    sessionStore: opts.sessionStore,
  });
}

describe('флаг выключен — запись как раньше', () => {
  it('D, D2, E, «Назад» с E, L1, L2, L3, listed=1, ссылка со слотом — побайтно как на базе d4419b77', async () => {
    const now = await capture();
    assert.deepEqual(Object.keys(now), Object.keys(FLAG_OFF));
    for (const k of Object.keys(FLAG_OFF)) assert.deepEqual(now[k], FLAG_OFF[k], k);
  });

  it('шторка «время недоступно» и подпись кнопки не меняются', async () => {
    const h = await openBook({ unified: false, routes: [
      slotsRoute(slots),
      { match: (c) => c.url.split('?')[0] === '/api/webapp/client/booking', reply: () => resp(400, { detail: 'Slot not available' }) },
    ] });
    await tick(40);
    h.click({ 'data-act': 'slot', 'data-slot': '101' });
    assert.match(h.app.innerHTML, /Анна подтвердит запись/);
    assert.doesNotMatch(h.app.innerHTML, /tc-book|сообщение придёт в Telegram/);
    h.click({ 'data-act': 'pick', 'data-k': 'adult' });
    h.input('name', 'Анна', 'self');
    h.click({ 'data-act': 'submit' });
    await tick(40);
    assert.ok(h.sheet.innerHTML.includes('10:00 уже недоступно'));
    assert.ok(h.sheet.innerHTML.includes('Данные запомнили.'));
    assert.ok(h.sheet.innerHTML.includes('Другое время'));
    assert.ok(!h.sheet.innerHTML.includes('уже заняли'));
  });
});

describe('D и D2', () => {
  it('разные тарифы — цена справа; равные — без цены; без цены запись всё равно уходит', async () => {
    const h = await openBook();
    await tick(40);
    h.click({ 'data-act': 'slot', 'data-slot': '101' });
    const html = h.app.innerHTML;
    assert.match(html, /<h2 class="tc-h2" id="whoLbl">Кто будет заниматься\?<\/h2>/);
    assert.match(html, /<em>45 BYN<\/em>/);
    assert.match(html, /<em>50 BYN<\/em>/);
    assert.match(html, /Анна подтвердит — сообщение придёт в Telegram/);
    for (const bad of FORBIDDEN) assert.ok(!html.includes(bad), bad);

    const same = structuredClone(trainer);
    same.services = [structuredClone(trainer.services[0])];
    same.services[0].price_tiers = [
      { id: 1, tier_kind: 'child', price_cents: 5000, currency_code: 'BYN' },
      { id: 2, tier_kind: 'adult', price_cents: 5000, currency_code: 'BYN' },
    ];
    const eq = await openBook({ trainer: same });
    await tick(40);
    eq.click({ 'data-act': 'slot', 'data-slot': '101' });
    assert.doesNotMatch(eq.app.innerHTML, /<em>50 BYN<\/em>/);
    assert.match(eq.app.innerHTML, /Кто будет заниматься/);

    const free = structuredClone(trainer);
    free.services = [{
      service_id: 9, service_name: 'Без цены', title: 'С нуля', is_public: true, is_online: false,
      currency_code: 'BYN', price_cents: null, group_price_cents: null, price_tiers: [],
    }];
    const noPrice = await openBook({ trainer: free, slots: [{ ...slots[0], arena_id: 3 }] });
    await tick(40);
    noPrice.click({ 'data-act': 'slot', 'data-slot': '101' });
    noPrice.click({ 'data-act': 'pick', 'data-k': 'adult' });
    assert.match(noPrice.app.innerHTML, /Цену уточните у тренера/);
    assert.doesNotMatch(noPrice.app.innerHTML, /согласован/);
    assert.match(noPrice.app.innerHTML, /data-act="submit"/);
    assert.doesNotMatch(noPrice.app.innerHTML, /data-act="submit" disabled/);
  });

  it('D2: профили, «как в прошлый раз · детский», абонемент', async () => {
    const h = await openBook({
      profiles: {
        items: [
          { client_id: 9, role: 'self', first_name: 'Анна' },
          { client_id: 10, role: 'guardian', first_name: 'Соня' },
        ],
        default_profile_id: 10,
      },
      session: {
        client_phone: '+375291112233',
        client_first_name: 'Анна',
        last_created_booking_service_id: 1,
        last_created_booking_service_price_variant_id: 11,
      },
      routes: [
        slotsRoute(slots),
        {
          match: (c) => c.url.split('?')[0] === '/api/webapp/client/passes',
          reply: () => resp(200, {
            items: [{
              trainer_id: 1, status: 'active', sessions_remaining: 4, sessions_total: 8,
              product_name: '8 занятий', service_ids: [1], tier_kinds: ['child'], is_expired: false,
            }],
          }),
        },
      ],
    });
    await tick(80);
    h.click({ 'data-act': 'slot', 'data-slot': '101' });
    await tick(80);
    assert.match(h.app.innerHTML, /как в прошлый раз · детский/);
    assert.match(h.app.innerHTML, /Добавить ребёнка/);
    assert.match(h.app.innerHTML, /aria-checked="true"/);
    assert.match(h.app.innerHTML, /Абонемент «8 занятий»/);
    assert.match(h.app.innerHTML, /спишем 1, останется 3/);
  });
});

describe('E, L, N', () => {
  it('E: без «напомним», три кнопки, «Назад» не в форму', async () => {
    const back = { fn: null, isNative() { return true; }, set(fn) { this.fn = fn; }, clear() { this.fn = null; } };
    const h = await openBook({
      miniAppBack: back,
      tg: {
        initData: 'x',
        initDataUnsafe: { user: { id: 5, allows_write_to_pm: true } },
        isVersionAtLeast: () => true,
        requestWriteAccess(cb) { cb(true); },
      },
      routes: [
        slotsRoute(slots),
        {
          match: (c) => c.url.split('?')[0] === '/api/webapp/client/booking',
          reply: () => resp(200, { success: true, reminder_plan: 'сегодня в 15:15, за 2 часа' }),
        },
      ],
    });
    await tick(40);
    h.click({ 'data-act': 'slot', 'data-slot': '101' });
    h.click({ 'data-act': 'pick', 'data-k': 'adult' });
    h.input('name', 'Анна', 'self');
    h.S.book.phone = '+375291112233';
    h.click({ 'data-act': 'submit' });
    await tick(40);
    const html = h.app.innerHTML;
    assert.match(html, /<h1>Запись отправлена Анне<\/h1>/);
    assert.match(html, /подтвердит запись — сообщение в Telegram/);
    assert.match(html, /Что дальше/);
    assert.match(html, /Что взять с собой/);
    assert.match(html, /Мои записи/);
    assert.match(html, /Маршрут до катка/);
    assert.match(html, /Готово/);
    assert.doesNotMatch(html, /Напомним|за 2 часа/);
    assert.equal(h.S.view, 'sent');
    back.fn();
    assert.equal(h.S.view, 'trainer');
    assert.doesNotMatch(h.app.innerHTML, /Кто будет заниматься/);
    h.ctx.__trainerShowcase.render();
  });

  it('L2: «уже заняли» и «Всё время тренера»', async () => {
    const h = await openBook({
      routes: [
        slotsRoute(slots),
        { match: (c) => c.url.split('?')[0] === '/api/webapp/client/booking', reply: () => resp(400, { detail: 'Slot not available' }) },
      ],
    });
    await tick(40);
    h.click({ 'data-act': 'slot', 'data-slot': '101' });
    h.click({ 'data-act': 'pick', 'data-k': 'adult' });
    h.input('name', 'Анна', 'self');
    h.S.book.phone = '+375291112233';
    h.click({ 'data-act': 'submit' });
    await tick(40);
    assert.match(h.sheet.innerHTML, /Сб, 10:00 уже заняли/);
    assert.match(h.sheet.innerHTML, /Ваши данные сохранены/);
    assert.match(h.sheet.innerHTML, /Всё время тренера/);
    assert.doesNotMatch(h.sheet.innerHTML, /Время за вами/);
  });

  it('L1: «Написать» рядом с «Повторить»; L3: тренера нет', async () => {
    const err = await openBook({ routes: [slotsRoute([], 500)] });
    await tick(40);
    assert.match(err.app.innerHTML, /Не удалось загрузить время/);
    assert.match(err.app.innerHTML, /data-act="reslots">Повторить/);
    assert.match(err.app.innerHTML, /data-act="write">Написать</);
    const miss = boot({
      unified: true,
      search: '?trainer_id=99',
      initData: 'x',
      showcase: { items: [] },
      session: { city_name: 'Минск' },
      routes: [trainerFallback(404)],
    });
    await tick(40);
    assert.match(miss.app.innerHTML, /<h1>Такого тренера нет<\/h1>/);
    assert.match(miss.app.innerHTML, /Другие тренеры · Минск/);
    assert.doesNotMatch(miss.app.innerHTML, /Не удалось загрузить тренера/);
  });

  for (const [name, route] of [['503', () => trainerFallback(503)], ['сеть', () => trainerFallback(0)]]) {
    it('L3 только на 404: ' + name + ' при загрузке тренера — «Не удалось загрузить тренера», «Повторить» перезагружает', async () => {
      let fail = true;
      const h = boot({
        unified: true,
        search: '?trainer_id=99',
        initData: 'x',
        showcase: { items: [] },
        session: { city_name: 'Минск' },
        routes: [{ match: (c) => c.url.indexOf('/catalog-trainer/99') >= 0, reply: (c) => (fail ? route().reply(c) : resp(200, catalogCard)) }, slotsRoute(slots)],
      });
      await tick(40);
      assert.doesNotMatch(h.app.innerHTML, /Такого тренера нет/);
      assert.match(h.app.innerHTML, /<h1>Не удалось загрузить тренера<\/h1>/);
      assert.match(h.app.innerHTML, /Проверьте сеть и повторите\./);
      assert.match(h.app.innerHTML, /data-act="retry-trainer">Повторить</);
      fail = false;
      h.click({ 'data-act': 'retry-trainer' });
      await tick(60);
      assert.equal(h.S.view, 'trainer');
      assert.match(h.app.innerHTML, /<h1>Анна Соколова<\/h1>/);
    });
  }

  it('N: «Вы в списке» и абонемент только после регистрации', async () => {
    const pass = {
      match: (c) => c.url.split('?')[0] === '/api/webapp/client/passes',
      reply: () => resp(200, {
        items: [{
          trainer_id: 1, status: 'active', sessions_remaining: 3, sessions_total: 8,
          product_name: '8 занятий', service_ids: [], tier_kinds: [], is_expired: false,
        }],
      }),
    };
    const profiles = { items: [{ client_id: 9, role: 'self', first_name: 'Анна' }], default_profile_id: 9 };
    const linked = { trainer_crm_listed_trainer_id: '1' };
    const listed = await openBook({ search: '?trainer_id=1&listed=1', profiles, routes: [slotsRoute(slots), pass], sessionStore: linked });
    await tick(80);
    assert.match(listed.app.innerHTML, /Вы в списке у Анны/);
    assert.match(listed.app.innerHTML, /Абонемент: осталось 3 занятия из 8/);
    const plain = await openBook({ profiles, routes: [slotsRoute(slots), pass], sessionStore: linked });
    await tick(80);
    assert.doesNotMatch(plain.app.innerHTML, /Вы в списке/);
  });

  it('N: &listed=1 без привязки формой K — плашки нет', async () => {
    const h = await openBook({ search: '?trainer_id=1&listed=1' });
    await tick(60);
    assert.equal(h.S.view, 'trainer');
    assert.doesNotMatch(h.app.innerHTML, /Вы в списке/);
  });

  it('N: привязка к другому тренеру — плашки нет', async () => {
    const h = await openBook({ search: '?trainer_id=1&listed=1', sessionStore: { trainer_crm_listed_trainer_id: '2' } });
    await tick(60);
    assert.doesNotMatch(h.app.innerHTML, /Вы в списке/);
  });

  it('N: «Назад» → список → другой тренер — у него плашки нет, у своего есть', async () => {
    const other = { ...STATES.B.trainer };
    const h = boot({
      unified: true,
      search: '?trainer_id=1&listed=1&via=link',
      initData: 'x',
      showcase: { items: [trainer, other] },
      session: { client_phone: '+375291112233', client_first_name: 'Анна' },
      routes: [slotsRoute(slots)],
      sessionStore: { trainer_crm_listed_trainer_id: '1' },
    });
    await tick(60);
    assert.match(h.app.innerHTML, /Вы в списке у Анны/);
    h.click({ 'data-act': 'back' });
    await tick(20);
    assert.equal(h.S.view, 'list');
    h.click({ 'data-act': 'trainer', 'data-tid': String(other.id) });
    await tick(60);
    assert.equal(h.S.trainer.id, other.id);
    assert.doesNotMatch(h.app.innerHTML, /Вы в списке/);
  });
});
