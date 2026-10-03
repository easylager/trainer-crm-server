/**
 * TASK-148 (AC-3, AC-4): интеграционные гварды новых блоков хаба.
 * Проверяет статическую обвязку так же, как client-bookings-profile-race.test.js:
 * секции есть в разметке, модели подключены до client-home-main.js, рендеры
 * вызываются из applyHubState и скрываются в аварийных ветках.
 *
 * Run: node --test tests/js/hub-catalog-blocks-wiring.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');

function read(name) {
  return fs.readFileSync(path.join(webapp, name), 'utf8');
}

const homeHtml = read('client-home.html');
const homeMain = read('client-home-main.js');

describe('разметка и подключение моделей', () => {
  it('в client-home.html есть секции подборок и «Сегодня на льду», обе скрыты', () => {
    assert.match(homeHtml, /id="hubCollections"[^>]*hidden/);
    assert.match(homeHtml, /id="hubIceToday"[^>]*hidden/);
  });

  it('новые секции стоят после существующих блоков (upcomingSection) и до футера', () => {
    const upcoming = homeHtml.indexOf('id="upcomingSection"');
    const collections = homeHtml.indexOf('id="hubCollections"');
    const iceToday = homeHtml.indexOf('id="hubIceToday"');
    const footer = homeHtml.indexOf('id="hubFooterAside"');
    assert.ok(upcoming > -1 && collections > upcoming, 'hubCollections после upcomingSection');
    assert.ok(iceToday > collections, 'hubIceToday после hubCollections');
    assert.ok(footer > iceToday, 'обе секции до футера');
  });

  it('модели подключены до client-home-main.js', () => {
    const collectionsModel = homeHtml.indexOf('hub-collections-model.js');
    const iceTodayModel = homeHtml.indexOf('hub-ice-today-model.js');
    // preload в <head> не считается: важен тег <script>, который грузит код.
    const mainJs = homeHtml.lastIndexOf('src="client-home-main.js');
    assert.ok(collectionsModel > -1 && collectionsModel < mainJs);
    assert.ok(iceTodayModel > -1 && iceTodayModel < mainJs);
  });

  it('ice-teaser-model.js и renderIceTeaser не тронуты', () => {
    assert.match(homeMain, /function renderIceTeaser\(payload\)/);
    assert.match(homeHtml, /ice-teaser-model\.js/);
  });
});

describe('вызовы рендеров в client-home-main.js', () => {
  it('«Сегодня на льду» монтируется сразу после renderIceTeaser из того же payload', () => {
    assert.match(homeMain, /renderIceTeaser\(iceTeaser\);\s*\n\s*\/\*[^*]*\*\/\s*\n\s*renderIceTodaySessions\(iceTeaser\);/);
  });

  it('«Подборки» монтируются после вычисления discoveryCityId', () => {
    assert.match(homeMain, /renderHubCollections\(discoveryCityId\);/);
  });

  it('аварийные ветки (без initData и при ошибке) скрывают новые блоки', () => {
    // Без initData.
    assert.match(homeMain, /renderIceTeaser\(null\);\s*\n\s*renderIceTodaySessions\(null\);\s*\n\s*renderHubCollections\(null\);/);
    // Ошибка загрузки.
    assert.match(homeMain, /hideUpcomingSection\(\);\s*\n\s*renderIceTodaySessions\(null\);\s*\n\s*renderHubCollections\(null\);/);
  });

  it('счётчики берутся из существующих публичных запросов, новых эндпоинтов нет', () => {
    assert.match(homeMain, /\/api\/public\/ice\/arenas\?intent=skate&city_id=/);
    assert.match(homeMain, /when=today_evening/);
    assert.match(homeMain, /venue_type_facets/);
  });
});
