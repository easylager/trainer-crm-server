'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

function loadModel() {
  for (const dep of ['schedule-staleness-model.js', 'arena-schedule-mode-model.js']) {
    require(path.resolve(__dirname, '../../static/webapp/' + dep));
  }
  return require(path.resolve(__dirname, '../../static/webapp/arena-card-model.js'));
}

describe('превью тренера на катке (вариант А)', () => {
  const M = loadModel();
  const base = {
    profile: { rating_avg: 4.86, rating_count: 23, experience_years: 6 },
    services: [{ service_name: 'С нуля' }, { service_name: 'Техника' }, { service_name: 'Дети' }, { service_name: 'ОФП' }],
    min_session_price_cents: 4187,
    min_session_price_currency: 'BYN',
    has_pass_products: true,
    windows: [
      { starts_at: '2026-10-21T12:15:00+03:00', time: '12:15', day: 'завтра' },
      { starts_at: '2026-10-21T13:15:00+03:00', time: '13:15', day: 'завтра' },
    ],
  };

  it('рейтинг, опыт, услуги и цена — только то, что есть', () => {
    const v = M.trainerPreview(base, {});
    assert.equal(v.rate, '4,9 · 23');
    assert.equal(v.what, 'С нуля · Техника · Дети');
    assert.equal(v.facts, '6 лет на льду · есть абонементы');
    assert.match(v.price, /^от 41,87/);
    assert.equal(v.next, 'Завтра 12:15');
    assert.equal(v.fit, '');
  });

  it('окно сразу после выбранного сеанса — «Свободен в …» на фото', () => {
    const v = M.trainerPreview(base, { after: '2026-10-21T13:00' });
    assert.equal(v.fit, 'Свободен в 13:15');
    assert.equal(v.next, 'Профиль →');
  });

  it('без отзывов, цены и окон — пусто, а не «0 отзывов» и «по запросу»', () => {
    const v = M.trainerPreview({ profile: { rating_count: 0, experience_years: 1 }, services: [] }, {});
    assert.equal(v.rate, '');
    assert.equal(v.price, '');
    assert.equal(v.facts, '1 год на льду');
    assert.equal(v.next, 'Профиль →');
  });
});
