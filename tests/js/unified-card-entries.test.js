/**
 * TASK-402: входы Mini App -> единая карточка под флагом (шим в booking-deeplink.js).
 * Run: node --test tests/js/unified-card-entries.test.js
 *
 * booking-deeplink.js — IIFE, который при загрузке сразу решает про редирект, поэтому
 * исполняем его настоящий исходник в vm с поддельным window.
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const SRC = fs.readFileSync(path.join(webapp, 'booking-deeplink.js'), 'utf8');

/** Загружает скрипт «на странице» pathname?search; возвращает куда сделали replace. */
function load(url, flag) {
  const u = new URL('https://x.test' + url);
  const replaced = [];
  const win = {
    location: { pathname: u.pathname, search: u.search, replace: (t) => replaced.push(t) },
  };
  if (flag !== undefined) win.__UNIFIED_TRAINER_CARD__ = flag;
  vm.runInNewContext(SRC, { window: win, URLSearchParams, encodeURIComponent });
  return replaced;
}

describe('шим единой карточки: флаг включён', () => {
  // [№ ENTRIES, откуда, куда]
  const entries = [
    ['5/20/21 бот: catalog?trainer_id', '/webapp/catalog?trainer_id=7', ['/webapp/trainers?trainer_id=7']],
    ['21 pass/cert со service_id', '/webapp/catalog?trainer_id=7&service_id=3', ['/webapp/trainers?trainer_id=7&service_id=3']],
    ['22 client_<city>_<svc>_<trainer>: book + force_service_choice', '/webapp/book?trainer_id=7&service_id=3&force_service_choice=1', ['/webapp/trainers?trainer_id=7&service_id=3']],
    ['22 book без service_id', '/webapp/book?trainer_id=7', ['/webapp/trainers?trainer_id=7']],
    ['23 «Новые слоты»: book?trainer_id', '/webapp/book?trainer_id=7', ['/webapp/trainers?trainer_id=7']],
    ['24 пуш «есть окно»: book + slot_id', '/webapp/book?trainer_id=7&slot_id=55', ['/webapp/trainers?trainer_id=7&slot_id=55']],
    ['28 /book: catalog', '/webapp/catalog?trainer_id=7&city_id=2', ['/webapp/trainers?trainer_id=7&city_id=2']],
    ['34 хаб «Мой тренер»', '/webapp/catalog?trainer_id=7&service_id=3&from=hub', ['/webapp/trainers?trainer_id=7&service_id=3&from=hub']],
    ['35 «Все окна»', '/webapp/catalog?trainer_id=7&service_id=3&arena_id=9&action=book&from=hub', ['/webapp/trainers?trainer_id=7&service_id=3&arena_id=9&from=hub&action=book']],
    ['37 «Снова к»', '/webapp/catalog?trainer_id=7&service_id=3&arena_id=9&action=book&entry=rebook&from=hub', ['/webapp/trainers?trainer_id=7&service_id=3&arena_id=9&from=hub&action=book&entry=rebook']],
    ['36 чип окна на хабе', '/webapp/catalog?trainer_id=7&slot_id=55&from=hub', ['/webapp/trainers?trainer_id=7&slot_id=55&from=hub']],
    ['39 сохранённые на хабе', '/webapp/catalog?trainer_id=7', ['/webapp/trainers?trainer_id=7']],
    ['41 «Сохранённые» -> «Записаться»', '/webapp/book?trainer_id=7&from=saved-trainers', ['/webapp/trainers?trainer_id=7&from=saved-trainers']],
    ['42 «Мои записи»', '/webapp/catalog?trainer_id=7&service_id=3&arena_id=9&service_price_variant_id=4&city_id=2', ['/webapp/trainers?trainer_id=7&service_id=3&arena_id=9&city_id=2']],
    ['44 сертификат', '/webapp/catalog?trainer_id=7', ['/webapp/trainers?trainer_id=7']],
    ['45 после покупки абонемента', '/webapp/catalog?trainer_id=7&city_id=2&service_id=3&arena_id=9&offset=2', ['/webapp/trainers?trainer_id=7&service_id=3&arena_id=9&city_id=2']],
    ['via доезжает', '/webapp/catalog?trainer_id=7&slot_id=1&via=k5', ['/webapp/trainers?trainer_id=7&slot_id=1&via=k5']],
    ['страница по /webapp/catalog.html', '/webapp/catalog.html?trainer_id=7', ['/webapp/trainers?trainer_id=7']],
  ];
  for (const [name, from, to] of entries) {
    it(name, () => assert.deepEqual(load(from, true), to));
  }
});

describe('шим не перехватывает (AC-003, AC-005)', () => {
  it('catalog?collective=…', () => assert.deepEqual(load('/webapp/catalog?collective=zamok&tab=catalog', true), []));
  it('catalog?collective + trainer_id', () => assert.deepEqual(load('/webapp/catalog?collective=zamok&trainer_id=7', true), []));
  it('catalog?…group_id=…', () => assert.deepEqual(load('/webapp/catalog?from=arena&arena_id=9&group_id=12', true), []));
  it('catalog?trainer_id + group_id (карточка арены)', () => assert.deepEqual(load('/webapp/catalog?trainer_id=7&from=arena&group_id=12', true), []));
  it('book.html…request_id (заявки)', () => {
    assert.deepEqual(load('/webapp/book?trainer_id=7&request_id=5&from=requests', true), []);
    assert.deepEqual(load('/webapp/book.html?trainer_id=7&request_id=5', true), []);
  });
  it('catalog без trainer_id', () => assert.deepEqual(load('/webapp/catalog?city_id=2', true), []));
  it('catalog?trainer_id=0 / мусор', () => {
    assert.deepEqual(load('/webapp/catalog?trainer_id=abc', true), []);
    assert.deepEqual(load('/webapp/catalog?trainer_id=0', true), []);
  });
  it('другие страницы (trainers, client-bookings)', () => {
    assert.deepEqual(load('/webapp/trainers?trainer_id=7', true), []);
    assert.deepEqual(load('/webapp/client-bookings?trainer_id=7', true), []);
  });
});

describe('флаг выключен — как раньше (AC-001)', () => {
  for (const flag of [undefined, false, 'true', 1]) {
    it('catalog?trainer_id не уходит на trainers, флаг=' + String(flag), () => {
      assert.deepEqual(load('/webapp/catalog?trainer_id=7&slot_id=1', flag), []);
    });
  }
  it('book со слотом по-прежнему уходит в catalog (старый страйнглер)', () => {
    assert.deepEqual(load('/webapp/book?trainer_id=7&slot_id=55&from=hub', false), ['/webapp/catalog?trainer_id=7&slot_id=55&from=hub']);
  });
  it('book с request_id остаётся на месте', () => {
    assert.deepEqual(load('/webapp/book?trainer_id=7&request_id=5', false), []);
  });
});

describe('источники входов всё ещё ходят через catalog?/book? (иначе таблица выше врёт)', () => {
  const must = [
    ['client-home-main.js', "'catalog?trainer_id='"],
    ['client-bookings.html', "'catalog?'"],
    ['client-saved-trainers-main.js', "'book?trainer_id='"],
    ['client-certificates.html', "'catalog?trainer_id='"],
    ['client-passes-certificates.html', "'catalog?trainer_id='"],
    ['client-buy-pass.html', "'catalog?'"],
    ['booking-client.js', "'catalog?trainer_id='"],
  ];
  for (const [file, needle] of must) {
    it(file, () => assert.ok(fs.readFileSync(path.join(webapp, file), 'utf8').includes(needle)));
  }
  it('catalog.html и book.html грузят шим', () => {
    for (const f of ['catalog.html', 'book.html']) {
      assert.match(fs.readFileSync(path.join(webapp, f), 'utf8'), /booking-deeplink\.js/);
    }
  });
});
