/**
 * TASK-236: варианты шита «Поделиться» и адрес открытки.
 * Run: node --test tests/js/zovi-entry.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('path');
const vm = require('node:vm');
const { URL } = require('node:url');

const jsPath = path.resolve(__dirname, '../../static/webapp/mini-app-share-sheet.js');
const src = fs.readFileSync(jsPath, 'utf8');

function loadShareSheet() {
  const context = {
    URL,
    window: {},
    document: {
      createElement: () => ({
        hidden: true,
        className: '',
        innerHTML: '',
        addEventListener: () => {},
        querySelector: () => null,
      }),
      body: { appendChild: () => {} },
    },
    fetch: () => Promise.reject(new Error('no fetch')),
    location: { href: 'https://app.test/webapp/arena' },
    navigator: {},
    requestAnimationFrame: (fn) => fn(),
    setTimeout: (fn) => fn(),
    clearTimeout: () => {},
  };
  context.window = context;
  vm.runInNewContext(src, context);
  return context.GlideShareSheet;
}

describe('варианты шита', () => {
  const sheet = loadShareSheet();
  const ice = { venueType: 'ice' };

  function labelsOf(sheetState) {
    return Array.from(sheet.variantsFor(sheetState), (variant) => variant.label);
  }

  it('у катка три варианта в этом порядке', () => {
    assert.deepEqual(labelsOf(ice), ['Погнали кататься', 'Открытка', 'Расписание']);
  });

  it('у не-катка открытки нет', () => {
    const labels = labelsOf({ venueType: 'shop' });
    assert.deepEqual(labels, ['Место', 'Позвать с собой']);
    assert.equal(labels.includes('Открытка'), false);
  });

  it('у подборки переключателя нет', () => {
    assert.deepEqual(labelsOf({ endpoint: '/api/public/ice/selection/share', venueType: 'ice' }), []);
  });

  it('«Позвать» открывает «Погнали кататься», «Поделиться» — «Расписание»', () => {
    assert.equal(sheet.initialVariantId({ invite: true }), 'invite');
    assert.equal(sheet.initialVariantId({ invite: false }), 'schedule');
    const byId = Object.fromEntries(Array.from(sheet.variantsFor(ice), (variant) => [variant.id, variant.label]));
    assert.equal(byId.invite, 'Погнали кататься');
    assert.equal(byId.schedule, 'Расписание');
  });

  it('открытка без сеанса — кнопка неактивна', () => {
    const html = sheet.postcardButtonHtml({ venueType: 'ice', sessionId: null, context: 'arena_card' });
    assert.match(html, /disabled/);
    assert.equal(html.includes('data-href'), false);
    assert.match(html, /Создать открытку/);
  });

  it('превью открытки — день, время и каток', () => {
    const copy = sheet.postcardCopy({
      venueType: 'ice',
      sessionId: '9001',
      placeName: 'Ледовый дворец',
      slotSections: [
        {
          dayLabel: 'Сегодня',
          localDate: '2026-10-12',
          dayNum: '12',
          rows: [{ id: '9001', time: '20:00', meta: '' }],
        },
      ],
    });
    assert.equal(copy.question, 'Пойдёшь со мной на каток?');
    assert.equal(copy.meta, 'Пн, 12 окт · 20:00 · Ледовый дворец');
    assert.equal(copy.note, 'Кнопка «Нет» убегает');

    const hockey = sheet.postcardCopy({
      venueType: 'ice',
      sessionId: '7',
      placeName: 'Чижовка',
      slotSections: [
        {
          localDate: '2026-10-16',
          rows: [{ id: '7', time: '19:00', meta: 'ОХМ' }],
        },
      ],
    });
    assert.equal(hockey.question, 'Пойдёшь со мной на хоккей?');
    assert.equal(hockey.meta, 'Пт, 16 окт · 19:00 · Чижовка');
  });

  it('адрес с s и via', () => {
    assert.equal(
      sheet.postcardHref({ venueType: 'ice', sessionId: '9001', context: 'arena_card' }),
      '/zovi?s=9001&via=arena_card'
    );
    assert.equal(
      sheet.postcardHref({ venueType: 'ice', sessionId: 42, context: 'ice_list' }),
      '/zovi?s=42&via=ice_list'
    );
    const html = sheet.postcardButtonHtml({ venueType: 'ice', sessionId: '9001', context: 'arena_card' });
    assert.equal(html.includes('disabled'), false);
    assert.match(html, /data-href="\/zovi\?s=9001&amp;via=arena_card"/);
  });
});
