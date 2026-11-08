/**
 * CTA-матрица витрины: при любом «нельзя записаться сейчас» есть выход
 * (Написать / Заявка / Телефон / Telegram), текст не врёт про кнопку.
 * Run: node --test tests/js/trainer-showcase-cta.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { boot, resp, tick } = require('./helpers/trainer-showcase-harness');

const trainer = (id, extra = {}) => ({
  id, name: 'Анна ' + id, first_name: 'Анна', can_book: true,
  services: [{ service_id: 1, service_name: 'С нуля', is_public: true, is_online: false, currency_code: 'BYN', price_cents: 5000,
    price_tiers: [{ id: 1, tier_kind: 'child', price_cents: 5000, currency_code: 'BYN' }] }],
  arenas: [{ id: 3, name: 'Каток' }], windows: [], ...extra,
});
const slot = (id, extra = {}) => ({
  id, slot_date: '2026-11-20', start_time: '10:00', end_time: '10:45', capacity: 1, spots_left: 1, arena_id: 3, is_online: false, ...extra,
});
const isPath = (c, p) => c.url.split('?')[0] === p;
const PHONE = { client_phone: '+375291234567' };
const noSlots = { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [] }) };
const failSlots = { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(500, { detail: 'x' }) };
const withSlots = { match: (c) => isPath(c, '/api/webapp/client/slots'), reply: () => resp(200, { slots: [slot(101)] }) };

async function open(items, opts = {}) {
  const h = boot({
    showcase: { items },
    session: PHONE,
    routes: opts.routes || [noSlots],
    initData: opts.initData === undefined ? 'x' : opts.initData,
    tg: opts.tg,
  });
  await tick();
  h.click({ 'data-act': 'trainer', 'data-tid': items[0].id });
  await tick();
  return h;
}

describe('пустые слоты у can_book', () => {
  it('в Telegram: notify + заявка + написать (если есть ник)', async () => {
    const h = await open([trainer(1, { contact_url: '/r/tg/1' })]);
    assert.ok(h.app.innerHTML.includes('data-act="notify"'));
    assert.ok(h.app.innerHTML.includes('data-act="request">Оставить заявку'));
    assert.ok(h.app.innerHTML.includes('data-act="write">Написать тренеру'));
  });

  it('без ника: заявка всё равно есть — sticky не пустой', async () => {
    const h = await open([trainer(1)]);
    assert.ok(h.app.innerHTML.includes('data-act="request">Оставить заявку'));
    assert.ok(!h.app.innerHTML.includes('data-act="write"'));
  });

  it('браузер без initData: Telegram-выход, а не только «нет времени»', async () => {
    const h = await open([trainer(1, { telegram_url: '/api/public/catalog/open-telegram?startapp=trainer_1&surface=trainer_showcase' })], { initData: '' });
    assert.ok(h.app.innerHTML.includes('свободного времени нет'));
    assert.ok(h.app.innerHTML.includes('data-act="open-tg">Открыть в Telegram'));
    assert.ok(!h.app.innerHTML.includes('data-act="notify"'));
    assert.ok(!h.app.innerHTML.includes('data-act="request"'));
  });

  it('телефон в анкете — «Скопировать телефон»', async () => {
    const h = await open([trainer(1, { phone: '+375291112233' })]);
    assert.ok(h.app.innerHTML.includes('data-act="copy-phone">Скопировать телефон'));
  });
});

describe('ошибка загрузки слотов', () => {
  it('не только «Повторить»: есть заявка / написать / телефон', async () => {
    const h = await open([trainer(1, { contact_url: '/r/tg/1', phone: '+375291112233' })], { routes: [failSlots] });
    assert.ok(h.app.innerHTML.includes('data-act="reslots">Повторить'));
    assert.ok(h.app.innerHTML.includes('data-act="request">Оставить заявку'));
    assert.ok(h.app.innerHTML.includes('data-act="write">Написать тренеру'));
    assert.ok(h.app.innerHTML.includes('data-act="copy-phone"'));
  });

});

describe('free-card без ника', () => {
  it('текст не обещает «напишите», заявка есть', async () => {
    const h = await open([trainer(1, { can_book: false })]);
    assert.ok(h.app.innerHTML.includes('оставьте заявку'));
    assert.ok(!/напишите и договоритесь/.test(h.app.innerHTML));
    assert.ok(h.app.innerHTML.includes('data-act="request">Оставить заявку'));
  });

  it('браузер: «Открыть в Telegram»', async () => {
    const h = await open(
      [trainer(1, { can_book: false, telegram_url: '/api/public/catalog/open-telegram?x=1' })],
      { initData: '' },
    );
    assert.ok(h.app.innerHTML.includes('откройте Telegram'));
    assert.ok(h.app.innerHTML.includes('data-act="open-tg">Открыть в Telegram'));
  });
});

describe('смена вкладки без слотов — без мигания длительности', () => {
  it('на время повторного запроса не вспыхивает «N мин · ближайшее время»', async () => {
    let n = 0;
    const slowEmpty = {
      match: (c) => isPath(c, '/api/webapp/client/slots'),
      reply: () => { n += 1; return resp(200, { slots: [] }, n === 1 ? 0 : 40); },
    };
    const card = trainer(1, {
      session_duration_minutes: 45,
      services: [
        { service_id: 1, service_name: 'С нуля', is_public: true, is_online: false, currency_code: 'BYN', price_cents: 5000,
          price_tiers: [{ id: 1, tier_kind: 'child', price_cents: 5000, currency_code: 'BYN' }] },
        { service_id: 2, service_name: 'Фигурное катание', is_public: true, is_online: false, currency_code: 'BYN', price_cents: 0,
          price_tiers: [] },
      ],
    });
    const h = await open([card], { routes: [slowEmpty] });
    assert.ok(!h.app.innerHTML.includes('ближайшее время'), 'пусто — подписи с длительностью нет');
    h.click({ 'data-act': 'dir', 'data-key': 'figurnoe' });
    // Сразу после клика (запрос ещё летит) — не должно быть вспышки.
    assert.ok(!h.app.innerHTML.includes('ближайшее время'), h.app.innerHTML);
    assert.ok(!h.app.innerHTML.includes('Загружаем время'), 'retain: пустой экран не уходит в «Загружаем»');
    await tick(60);
    assert.ok(!h.app.innerHTML.includes('ближайшее время'));
  });
});

describe('неделя: карточка «Не нашли время?»', () => {
  it('без ника и без initData и без телефона — блок не рисуем (нет orphan-текста)', async () => {
    const h = await open([trainer(1)], { routes: [withSlots], initData: '' });
    h.click({ 'data-act': 'week' });
    await tick();
    assert.ok(!h.app.innerHTML.includes('Не нашли подходящее время'));
  });

  it('есть ник — «Напишите» и кнопка', async () => {
    const h = await open([trainer(1, { contact_url: '/r/tg/1' })], { routes: [withSlots] });
    h.click({ 'data-act': 'week' });
    await tick();
    assert.ok(h.app.innerHTML.includes('Не нашли подходящее время? Напишите'));
    assert.ok(h.app.innerHTML.includes('data-act="write">Написать тренеру'));
    assert.ok(h.app.innerHTML.includes('data-act="request">Оставить заявку'));
  });

  it('только initData — заявка, без orphan «Напишите»', async () => {
    const h = await open([trainer(1)], { routes: [withSlots] });
    h.click({ 'data-act': 'week' });
    await tick();
    assert.ok(h.app.innerHTML.includes('Оставьте заявку'));
    assert.ok(h.app.innerHTML.includes('data-act="request">Оставить заявку'));
    assert.ok(!h.app.innerHTML.includes('Напишите Анне'));
  });
});
