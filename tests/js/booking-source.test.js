/**
 * TASK-351: источник записи на сеанс Mini App (booking-source.js) и его место в теле записи.
 * Run: node --test tests/js/booking-source.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const sourceJs = fs.readFileSync(path.join(webapp, 'booking-source.js'), 'utf8');
const bookingJs = fs.readFileSync(path.join(webapp, 'booking-client.js'), 'utf8');

function memoryStorage() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) };
}

/** Страница Mini App: адрес, start_param из Telegram, общий sessionStorage сеанса. */
function page({ search = '', startParam = '', storage = memoryStorage() } = {}) {
  const win = {
    location: { search, hash: '', pathname: '/webapp/catalog' },
    sessionStorage: storage,
    Telegram: { WebApp: { initDataUnsafe: startParam ? { start_param: startParam } : {} } },
    URLSearchParams,
  };
  win.window = win;
  vm.createContext(win);
  vm.runInContext(sourceJs, win);
  vm.runInContext(bookingJs, win);
  return { win, storage, S: win.GlideBookingSource, BC: win.BookingClient };
}

describe('GlideBookingSource', () => {
  const { S } = page();
  const plain = (v) => JSON.parse(JSON.stringify(v));

  it('разбирает метки и start_param как booking_source.py', () => {
    assert.deepEqual(plain(S.fromVia('link')), { source: 'link' });
    assert.deepEqual(plain(S.fromVia('p3')), { source: 'site_place', source_arena_id: 3 });
    assert.deepEqual(plain(S.fromVia('k12')), { source: 'site_catalog', source_city_id: 12 });
    assert.equal(S.fromVia('app_button'), null);
    assert.deepEqual(plain(S.fromStartParam('trainer_7_v_c12')), { source: 'site_city', source_city_id: 12 });
    assert.deepEqual(plain(S.fromStartParam('trainer_7')), { source: 'site_trainer' });
    assert.deepEqual(plain(S.fromStartParam('trainer_7_a_3')), { source: 'site_place', source_arena_id: 3 });
    assert.deepEqual(plain(S.fromStartParam('catalog_12_coach')), { source: 'site_city', source_city_id: 12 });
    assert.equal(S.fromStartParam('arena_42'), null);
  });

  it('start_param с сайта доезжает до тела записи', () => {
    const { BC } = page({ startParam: 'trainer_7_v_p3' });
    const body = BC.buildBookingPayload({ slotId: 1, phone: '+375291112233' });
    assert.equal(body.source, 'site_place');
    assert.equal(body.source_arena_id, 3);
  });

  it('?via=link кнопки бота переживает переход на другую страницу сеанса', () => {
    const storage = memoryStorage();
    page({ search: '?via=link', storage });
    const { BC } = page({ search: '?trainer_id=7', storage });
    assert.equal(BC.buildBookingPayload({ slotId: 1, phone: 'x' }).source, 'link');
  });

  it('выбор в Mini App — только если сеанс начался без источника', () => {
    const fresh = page({ search: '?trainer_id=7' });
    fresh.S.noteInApp({ arenaId: 5, cityId: 1 });
    assert.deepEqual(
      JSON.parse(JSON.stringify(fresh.BC.currentBookingSource())),
      { source: 'miniapp', source_arena_id: 5, source_city_id: 1 }
    );
    const fromSite = page({ startParam: 'trainer_7' });
    fromSite.S.noteInApp({ cityId: 1 });
    assert.equal(fromSite.BC.currentBookingSource().source, 'site_trainer');
  });

  it('без источника поля нет — запись как раньше', () => {
    const { BC } = page();
    const body = BC.buildBookingPayload({ slotId: 1, phone: 'x' });
    assert.equal('source' in body, false);
  });
});
