/**
 * TASK-181 AC-2: имя арены в выборе площадки Mini App — только текстом.
 * Имя может задать тренер при самостоятельном создании площадки, а страница держит initData.
 * Run: node --test tests/js/catalog-arena-name-escaping.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SRC = fs.readFileSync(path.resolve(__dirname, '../../static/webapp/catalog-main.js'), 'utf8');

function sliceBetween(src, startMarker, endMarker) {
  const start = src.indexOf(startMarker);
  assert.ok(start >= 0, 'marker not found: ' + startMarker);
  const end = src.indexOf(endMarker, start);
  assert.ok(end > start, 'end marker not found: ' + endMarker);
  return src.slice(start, end + endMarker.length);
}

/** Карточка арены из настоящего renderArenaListCheckboxes, вынутая из исходника. */
function loadArenaCardRenderer() {
  const escapeFn = sliceBetween(SRC, 'function escapeHtml(s) {', '\n      }');
  const renderFn = sliceBetween(
    SRC.slice(SRC.indexOf('function renderArenaListCheckboxes(')),
    'var html = filtered.map(function(a) {',
    "}).join('');"
  );
  const code =
    escapeFn +
    '\nfunction formatServiceOfferCount(n) { return n + " тренеров"; }' +
    '\nfunction renderCards(filtered, selectedSet, state) {\n' +
    renderFn +
    '\nreturn html;\n}';
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(code, ctx);
  return ctx.renderCards;
}

const EVIL_NAME = 'Rink<img src=x onerror=alert(1)>"\' __JSONLD__';
const EVIL_ADDR = '<img src=x onerror=alert(2)>';

describe('выбор арены: имя и адрес из API экранируются', () => {
  const render = loadArenaCardRenderer();
  const html = render([{ id: 7, name: EVIL_NAME, address: EVIL_ADDR }], {}, { cityId: null, serviceId: null });

  it('в разметке нет живого тега <img> — только текст', () => {
    assert.doesNotMatch(html, /<img/i);
    assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
    assert.match(html, /&lt;img src=x onerror=alert\(2\)&gt;/);
  });

  it('data-name не разрывается кавычкой', () => {
    const m = html.match(/data-name="([^"]*)"/);
    assert.ok(m, 'data-name attribute present');
    assert.ok(m[1].includes('&quot;'), 'кавычка в имени экранирована');
    assert.ok(!m[1].includes('<'), 'в атрибуте нет сырого <');
  });

  it('обычное имя с «» и кавычками остаётся читаемым', () => {
    const plain = render([{ id: 1, name: 'Арена «Минск»' }], {}, {});
    assert.match(plain, /<span class="arena-card__name">Арена «Минск»<\/span>/);
  });
});

describe('другие поля каталога, идущие в innerHTML', () => {
  it('имя тренера на карточке списка и в деталях экранируется', () => {
    assert.match(SRC, /<div class="info"><div class="name">' \+ escapeHtml\(trainerName\(t\)\)/);
    assert.match(SRC, /<div class="trainer-detail-name">' \+ escapeHtml\(name\)/);
  });

  it('названия арен в мета-строке списка тренеров экранируются', () => {
    assert.match(SRC, /metaBottom\.push\(escapeHtml\(t\.arena_names\.slice\(0, 2\)\.join\(', '\)\)\)/);
  });
});
