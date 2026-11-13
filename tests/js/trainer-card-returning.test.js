/**
 * TASK-404: G «Мой тренер» и H «Время на две недели» за флагом.
 * Стенд — настоящий trainer-showcase-main.js. Адреса fetch проверяются целиком.
 * Run: node --test tests/js/trainer-card-returning.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { boot, resp, tick } = require('./helpers/trainer-showcase-harness');

function minskToday() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Minsk', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

const TODAY = minskToday();
const D1 = addDays(TODAY, 1);
const D2 = addDays(TODAY, 2);

const adult = { id: 9, tier_kind: 'adult', price_cents: 4500, currency_code: 'BYN' };
const child = { id: 8, tier_kind: 'child', price_cents: 4000, currency_code: 'BYN' };
const svcPast = {
  service_id: 3, service_name: 'Взрослое занятие', title: 'Взрослое занятие', is_public: true, is_online: false,
  currency_code: 'BYN', price_cents: null, price_tiers: [adult],
};
const svcOther = {
  service_id: 1, service_name: 'С нуля', title: 'С нуля', is_public: true, is_online: false,
  currency_code: 'BYN', price_cents: null, price_tiers: [child],
};

function trainer(extra = {}) {
  return {
    id: 7, name: 'Анна Соколова', first_name: 'Анна', photo_url: '', experience_years: 7,
    description: 'Учу кататься с нуля.', education: 'Диплом', can_book: true,
    contact_url: '/r/tg/7', phone: '', session_duration_minutes: 60,
    primary_arena_name: '«Замок»', city_name: 'Минск',
    services: [svcOther, svcPast],
    arenas: [{ id: 3, name: 'Замок', address: 'ул. Притыцкого, 156', map_link: 'https://yandex.by/maps/?pt=1,2' }],
    windows: [], ...extra,
  };
}

function slot(id, date, time, extra = {}) {
  return {
    id, slot_date: date, start_time: time, end_time: '', capacity: 1, spots_left: 1,
    arena_id: 3, arena_name: 'Замок', is_online: false, service_id: 3, ...extra,
  };
}

const SLOTS = [
  slot(1, TODAY, '10:00'),
  slot(2, TODAY, '11:30'),
  slot(3, D1, '09:00'),
];

function edgeRoute(last) {
  return {
    match: (c) => c.url.split('?')[0] === '/api/webapp/client/trainer-edges',
    reply: (c) => {
      assert.equal(c.url, '/api/webapp/client/trainer-edges');
      return resp(200, {
        all: [{ trainer_id: 7, is_saved: false, notify_when_slots: false, last_completed_at: last }],
        primary: null, saved: [], past: [],
      });
    },
  };
}

function slotsRoute(slots, status = 200) {
  return {
    match: (c) => c.url.split('?')[0] === '/api/webapp/client/slots',
    reply: (c) => resp(status, status === 200 ? { slots } : { detail: 'no' }),
  };
}

async function open(search, opts = {}) {
  const h = boot({
    unified: opts.unified !== false,
    search,
    historyLength: opts.historyLength == null ? 2 : opts.historyLength,
    initData: opts.initData === undefined ? 'init' : opts.initData,
    session: opts.session || {
      last_created_booking_service_id: 3,
      last_created_booking_service_price_variant_id: 9,
    },
    showcase: { items: [opts.trainer || trainer()] },
    routes: [slotsRoute(opts.slots === undefined ? SLOTS : opts.slots, opts.slotsStatus), edgeRoute(opts.last === undefined ? '2026-11-02' : opts.last), ...(opts.routes || [])],
  });
  await tick(80);
  return h;
}

describe('G · карточка вернувшегося', () => {
  it('шапка ужата, строки последнего занятия нет, прошлый формат, доверие свёрнуто', async () => {
    const h = await open('?trainer_id=7&service_id=1&from=hub');
    const html = h.app.innerHTML;
    assert.match(html, /class="tc tc-g"/);
    assert.match(html, /<h1>Анна Соколова<\/h1>/);
    assert.match(html, /Фигурное катание|С нуля|Взрослое|Минск/);
    assert.doesNotMatch(html, /Последнее занятие/);
    assert.equal(fs.readFileSync(path.join(__dirname, '../../static/webapp/trainer-showcase-main.js'), 'utf8').includes('lastCompletedAt'), false);
    assert.match(html, /Записаться снова/);
    assert.match(html, /Записаться снова на .*10:00/);
    assert.match(html, /Взрослый/);
    assert.match(html, /45 BYN/);
    assert.match(html, /основной каток/);
    assert.match(html, /aria-expanded="false"/);
    assert.doesNotMatch(html, /О тренере<\/h2>/);
    assert.doesNotMatch(html, /Вы занимались/);
    const slotsCall = h.calls.filter((c) => c.url.split('?')[0] === '/api/webapp/client/slots');
    assert.equal(slotsCall.length, 1);
    assert.match(slotsCall[0].url, /^\/api\/webapp\/client\/slots\?trainer_id=7&service_id=3$/);
  });

  it('нет last_completed_at — нет строки', async () => {
    const h = await open('?trainer_id=7&from=hub', { last: null });
    assert.doesNotMatch(h.app.innerHTML, /Последнее занятие/);
  });

  it('ошибка слотов — не «нет окон»', async () => {
    const h = await open('?trainer_id=7&from=hub', { slotsStatus: 500, slots: [] });
    assert.match(h.app.innerHTML, /Не удалось загрузить время/);
    assert.match(h.app.innerHTML, /Проверьте сеть и повторите/);
    assert.doesNotMatch(h.app.innerHTML, /свободного времени нет/);
  });

  it('запись без цены проходит: кнопки есть, строки цены нет', async () => {
    const bare = trainer({
      services: [{ ...svcPast, price_tiers: [], price_cents: null }],
    });
    const h = await open('?trainer_id=7&from=hub', { trainer: bare, session: {} });
    assert.match(h.app.innerHTML, /Записаться снова на /);
    assert.doesNotMatch(h.app.innerHTML, /class="tc-g-price"/);
    h.click({ 'data-act': 'slot', 'data-slot': '1' });
    await tick(20);
    assert.equal(h.S.view, 'book');
  });

  it('доверие раскрывается по кнопке', async () => {
    const h = await open('?trainer_id=7&from=hub');
    h.click({ 'data-act': 'trust' });
    assert.match(h.app.innerHTML, /aria-expanded="true"/);
    assert.match(h.app.innerHTML, /О тренере/);
    assert.match(h.app.innerHTML, /Образование и дипломы/);
  });

  it('«Назад» с G уходит на хаб', async () => {
    const h = await open('?trainer_id=7&from=hub');
    assert.equal(h.S.view, 'trainer');
    assert.equal(h.S.stack.length, 0);
    h.click({ 'data-act': 'back' });
    assert.equal(h.ctx.history.left, 1);
  });
});

describe('H · время на две недели', () => {
  it('дни, число окон, пустой день пунктиром, окна выбранного дня', async () => {
    const slots = [
      slot(1, TODAY, '10:00'),
      slot(2, TODAY, '11:30'),
      slot(3, TODAY, '16:00', { arena_id: 4, arena_name: 'Чижовка' }),
      slot(4, D2, '09:00'),
    ];
    const h = await open('?trainer_id=7&action=book&from=hub', { slots });
    const html = h.app.innerHTML;
    assert.equal(h.S.view, 'week');
    assert.match(html, /<h1>Время на две недели<\/h1>/);
    assert.match(html, /3 окна/);
    assert.match(html, /1 окно/);
    assert.match(html, /tc-h-day--empty/);
    assert.match(html, />нет</);
    assert.match(html, /10:00/);
    assert.match(html, /Чижовка/);
    assert.match(html, /Напишите тренеру, чтобы предложить своё время/);
    assert.doesNotMatch(html, /он предложит/);
    assert.match(html, /Записаться на .*10:00/);
    assert.doesNotMatch(html, /class="wk"/);
    const days = html.match(/class="tc-h-day/g) || [];
    assert.ok(days.length >= 8 && days.length <= 14, 'горизонт окна слотов, дней: ' + days.length);
  });

  it('выбор плитки меняет подпись кнопки', async () => {
    const h = await open('?trainer_id=7&action=book&from=hub');
    h.click({ 'data-act': 'week-slot', 'data-slot': '2' });
    assert.match(h.app.innerHTML, /Записаться на .*11:30/);
    assert.match(h.app.innerHTML, /data-slot="2"[^>]*aria-pressed="true"|aria-pressed="true"[^>]*data-slot="2"/);
  });

  it('«Назад» с H уходит на хаб', async () => {
    const h = await open('?trainer_id=7&action=book&from=hub');
    assert.equal(h.S.stack.length, 0);
    h.click({ 'data-act': 'back' });
    assert.equal(h.ctx.history.left, 1);
  });

  it('чип слота с хаба открывает запись, «Назад» — хаб', async () => {
    const h = await open('?trainer_id=7&slot_id=1&from=hub');
    assert.equal(h.S.view, 'book');
    assert.equal(h.S.stack.length, 0);
    h.click({ 'data-act': 'back' });
    assert.equal(h.ctx.history.left, 1);
  });
});

describe('доработка ревью', () => {
  it('№37 entry=rebook открывает G, а не неделю', async () => {
    const h = await open('?trainer_id=7&service_id=3&arena_id=9&action=book&entry=rebook&from=hub');
    assert.equal(h.S.view, 'trainer');
    assert.match(h.app.innerHTML, /class="tc tc-g"/);
    assert.doesNotMatch(h.app.innerHTML, /Время на две недели/);
  });

  it('занятый слот с хаба оставляет карточку тренера, не список', async () => {
    const h = await open('?trainer_id=7&slot_id=99&service_id=3&from=hub', {
      slots: [],
      routes: [{
        match: (c) => c.url.split('?')[0] === '/api/webapp/client/slot/99',
        reply: (c) => {
          assert.equal(c.url.split('?')[0], '/api/webapp/client/slot/99');
          return resp(200, { available: false });
        },
      }],
    });
    assert.equal(h.S.view, 'trainer');
    assert.match(h.app.innerHTML, /<h1>Анна Соколова<\/h1>/);
    assert.match(h.app.innerHTML, /class="tc"/);
  });

  it('нет окон на H — нет пустого tablist, есть «Назад к тренеру»', async () => {
    const h = await open('?trainer_id=7&action=book&service_id=3&from=hub', { slots: [] });
    assert.equal(h.S.view, 'week');
    assert.doesNotMatch(h.app.innerHTML, /role="tablist"/);
    assert.doesNotMatch(h.app.innerHTML, /tc-h-daytitle/);
    assert.match(h.app.innerHTML, /Назад к тренеру/);
  });

  it('нельзя записаться — «Оставить заявку», без полосы дней', async () => {
    const h = await open('?trainer_id=7&action=book&from=hub', {
      trainer: trainer({ can_book: false }),
      slots: [],
    });
    assert.match(h.app.innerHTML, /Оставить заявку/);
    assert.doesNotMatch(h.app.innerHTML, /role="tablist"/);
  });
});

describe('часть B ревью 404: чипы, стрелки, скелет, доверие, выход', () => {
  it('на G не больше двух чипов окон, кроме «Другое время»', async () => {
    const slots = [
      slot(1, TODAY, '10:00'),
      slot(2, TODAY, '11:00'),
      slot(3, TODAY, '12:00'),
      slot(4, D1, '09:00'),
      slot(5, D2, '09:30'),
    ];
    const h = await open('?trainer_id=7&from=hub', { slots });
    const times = (h.app.innerHTML.match(/<div class="tc-g-times">([\s\S]*?)<\/div>/) || [])[1] || '';
    const chips = times.match(/data-act="slot"/g) || [];
    assert.equal(chips.length, 2, times);
    assert.match(times, /Другое время/);
  });

  it('стрелки H переходят на день с окнами и пропускают пустой', async () => {
    const slots = [slot(1, TODAY, '10:00'), slot(4, D2, '09:00')];
    const h = await open('?trainer_id=7&action=book&from=hub', { slots });
    const days = h.app.querySelectorAll('[data-act="day"]');
    assert.ok(days.length >= 2);
    assert.equal(days[0].getAttribute('data-day'), TODAY);
    days[0].focus();
    const ev = h.key('ArrowRight');
    assert.equal(ev.defaultPrevented, true);
    assert.equal(h.S.day, D2);
    assert.equal(h.doc.activeElement.getAttribute('data-day'), D2);
    assert.notEqual(h.S.day, D1);
  });

  it('пока окна H не пришли, виден скелет', async () => {
    const h = await open('?trainer_id=7&action=book&from=hub');
    h.S.slots = null;
    h.S.view = 'week';
    h.ctx.__trainerShowcase.render();
    assert.match(h.app.innerHTML, /class="tc-h-sk"/);
    assert.match(h.app.innerHTML, /Загружаем время/);
    assert.doesNotMatch(h.app.innerHTML, /role="tablist"/);
  });

  it('доверие свёрнуто подписью «О тренере и дипломы»', async () => {
    const h = await open('?trainer_id=7&from=hub');
    assert.match(h.app.innerHTML, />О тренере и дипломы/);
    assert.doesNotMatch(h.app.innerHTML, /О тренере<\/h2>/);
  });

  it('«Назад к тренеру» с пустой H входа №35 открывает G', async () => {
    const h = await open('?trainer_id=7&action=book&service_id=3&from=hub', { slots: [] });
    assert.equal(h.S.view, 'week');
    h.click({ 'data-act': 'to-trainer' });
    assert.equal(h.S.view, 'trainer');
    assert.match(h.app.innerHTML, /class="tc tc-g"/);
    assert.doesNotMatch(h.app.innerHTML, /Время на две недели/);
  });

  it('пустая H: «2 недели», написать, сообщить и заявка', async () => {
    const h = await open('?trainer_id=7&action=book&from=hub', { slots: [] });
    const html = h.app.innerHTML;
    assert.match(html, /На ближайшие 2 недели свободного времени нет/);
    assert.doesNotMatch(html, /На ближайшие две недели/);
    assert.match(html, /Не подходит время\?/);
    assert.match(html, /Написать тренеру/);
    assert.match(html, /Сообщить, когда появится время/);
    assert.match(html, /Оставить заявку/);
    assert.match(html, /Назад к тренеру/);
  });

  it('пустая H без contact_url не рисует «Написать»', async () => {
    const h = await open('?trainer_id=7&action=book&from=hub', {
      trainer: trainer({ contact_url: '' }),
      slots: [],
    });
    assert.doesNotMatch(h.app.innerHTML, /Не подходит время/);
    assert.doesNotMatch(h.app.innerHTML, /data-act="write"/);
    assert.match(h.app.innerHTML, /Назад к тренеру/);
    assert.match(h.app.innerHTML, /Сообщить, когда появится время/);
  });

  it('нельзя записаться вне Telegram — есть кнопка, не пустой экран', async () => {
    const phone = await open('?trainer_id=7&action=book&from=hub', {
      trainer: trainer({ can_book: false, contact_url: '', phone: '+375291112233' }),
      slots: [],
      initData: '',
    });
    assert.match(phone.app.innerHTML, /Сейчас записаться онлайн нельзя/);
    assert.match(phone.app.innerHTML, /Скопировать телефон/);
    const write = await open('?trainer_id=7&action=book&from=hub', {
      trainer: trainer({ can_book: false, contact_url: '/r/tg/7', phone: '' }),
      slots: [],
      initData: '',
    });
    assert.match(write.app.innerHTML, /Написать тренеру/);
  });

  it('пустой день H — вкладка внутри tablist, без фокуса Tab', async () => {
    const h = await open('?trainer_id=7&action=book&from=hub', {
      slots: [slot(1, TODAY, '10:00'), slot(4, D2, '09:00')],
    });
    const html = h.app.innerHTML;
    assert.match(html, /role="tablist"/);
    assert.match(html, /role="tab" aria-selected="false" aria-disabled="true" tabindex="-1" disabled/);
    const empty = html.match(/<button type="button" class="tc-h-day tc-h-day--empty"[^>]*>/g) || [];
    assert.ok(empty.length > 0);
    for (const tag of empty) {
      assert.match(tag, /role="tab"/);
      assert.match(tag, /aria-disabled="true"/);
      assert.match(tag, /tabindex="-1"/);
      assert.match(tag, /\bdisabled\b/);
      assert.doesNotMatch(tag, /data-act="day"/);
    }
  });
});

describe('флаг выключен', () => {
  it('from=hub не меняет карточку', async () => {
    const off = await open('?trainer_id=7&from=hub', { unified: false, last: '2026-11-02' });
    const plain = await open('?trainer_id=7', { unified: false, last: '2026-11-02' });
    assert.equal(off.app.innerHTML, plain.app.innerHTML);
    assert.doesNotMatch(off.app.innerHTML, /Последнее занятие/);
    assert.doesNotMatch(off.app.innerHTML, /tc tc-g/);
  });
});
