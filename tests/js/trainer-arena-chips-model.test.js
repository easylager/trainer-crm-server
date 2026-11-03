/**
 * TASK-055: trainer-card arena chips — primary mark, overflow, hrefs, slot place.
 * Run: node --test tests/js/trainer-arena-chips-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(
  __dirname,
  '../../static/webapp/trainer-arena-chips-model.js'
);

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

function trainer(overrides) {
  return Object.assign(
    {
      arena_ids: [10, 11],
      arena_names: ['Чижовка', 'ТЦ «Замок»'],
      primary_arena_id: 10,
    },
    overrides || {}
  );
}

describe('buildTrainerArenaChips (AC-003)', () => {
  it('builds tappable chips that open the arena card and marks the primary', () => {
    const { buildTrainerArenaChips } = loadModel();
    const view = buildTrainerArenaChips(trainer());
    assert.equal(view.hidden, false);
    assert.equal(view.items.length, 2);
    assert.equal(view.moreCount, 0);
    assert.equal(view.items[0].name, 'Чижовка');
    assert.equal(view.items[0].primary, true);
    assert.equal(view.items[0].href, 'arena?ref=10');
    assert.equal(view.items[1].name, 'ТЦ «Замок»');
    assert.equal(view.items[1].primary, false);
    assert.equal(view.items[1].href, 'arena?ref=11');
  });

  it('puts the primary chip first even when it is not first in arena_ids', () => {
    const { buildTrainerArenaChips } = loadModel();
    const view = buildTrainerArenaChips(
      trainer({ arena_ids: [11, 10], arena_names: ['ТЦ «Замок»', 'Чижовка'], primary_arena_id: 10 })
    );
    assert.equal(view.items[0].id, 10);
    assert.equal(view.items[0].primary, true);
    assert.equal(view.items[1].id, 11);
  });

  it('keeps id in href even when the trainer payload includes arena_slugs', () => {
    // TASK-146: slug уникален только в городе — ссылка по нему могла открыть чужую арену.
    const { buildTrainerArenaChips } = loadModel();
    const view = buildTrainerArenaChips(
      trainer({ arena_slugs: ['chizhovka', 'zamok'] })
    );
    assert.equal(view.items[0].href, 'arena?ref=10');
    assert.equal(view.items[1].href, 'arena?ref=11');
  });

  it('hides the block when the trainer has no arenas', () => {
    const { buildTrainerArenaChips } = loadModel();
    const view = buildTrainerArenaChips(trainer({ arena_ids: [], arena_names: [] }));
    assert.equal(view.hidden, true);
    assert.equal(view.items.length, 0);
  });
});

describe('buildTrainerArenaChips overflow (EDGE-001)', () => {
  it('shows N chips and ещё M when the trainer works at 6+ arenas', () => {
    const { buildTrainerArenaChips, VISIBLE_ARENA_CHIPS } = loadModel();
    const ids = [1, 2, 3, 4, 5, 6, 7];
    const names = ids.map((id) => 'Арена ' + id);
    const view = buildTrainerArenaChips(
      trainer({ arena_ids: ids, arena_names: names, primary_arena_id: 1 })
    );
    assert.equal(view.items.length, VISIBLE_ARENA_CHIPS);
    assert.equal(view.moreCount, ids.length - VISIBLE_ARENA_CHIPS);
    assert.ok(view.moreCount >= 1);
    assert.match(view.moreLabel, new RegExp('ещё ' + view.moreCount));
  });

  it('shows every chip when there are fewer than 6 arenas', () => {
    const { buildTrainerArenaChips } = loadModel();
    const ids = [1, 2, 3, 4, 5];
    const view = buildTrainerArenaChips(
      trainer({
        arena_ids: ids,
        arena_names: ids.map((id) => 'A' + id),
        primary_arena_id: 1,
      })
    );
    assert.equal(view.items.length, 5);
    assert.equal(view.moreCount, 0);
  });
});

describe('renderTrainerArenaChipsHtml (AC-003)', () => {
  it('marks the primary chip and keeps overflow as ещё M', () => {
    const { renderTrainerArenaChipsHtml } = loadModel();
    const html = renderTrainerArenaChipsHtml({
      hidden: false,
      eyebrow: 'Работает на аренах',
      items: [
        { id: 10, name: 'Чижовка', href: 'arena?ref=10', primary: true },
        { id: 11, name: 'ТЦ «Замок»', href: 'arena?ref=11', primary: false },
      ],
      moreCount: 3,
      moreLabel: 'ещё 3',
    });
    assert.match(html, /Работает на аренах/);
    assert.match(html, /Чижовка/);
    assert.match(html, /arena\?ref=10/);
    assert.match(html, /aria-pressed="true"/);
    assert.match(html, /ещё 3/);
  });

  it('returns empty when hidden', () => {
    const { renderTrainerArenaChipsHtml } = loadModel();
    assert.equal(renderTrainerArenaChipsHtml({ hidden: true, items: [] }), '');
  });
});

describe('formatSlotPlaceCaption (TASK-056 place)', () => {
  it('uses that slot’s arena, not the trainer primary', () => {
    const { formatSlotPlaceCaption } = loadModel();
    const text = formatSlotPlaceCaption({ arena_name: 'ТЦ «Замок»', price: 60 });
    assert.match(text, /ТЦ «Замок»/);
    assert.ok(!/Чижовка/.test(text));
  });

  it('returns empty when the slot has no arena name', () => {
    const { formatSlotPlaceCaption } = loadModel();
    assert.equal(formatSlotPlaceCaption({}), '');
    assert.equal(formatSlotPlaceCaption(null), '');
  });
});

describe('buildArenaSlotFilter / renderArenaSlotFilterHtml (единый блок «Показать слоты»)', () => {
  const many = () =>
    trainer({
      arena_ids: [1, 2, 3, 4],
      arena_names: ['Пустая А', 'Замок', 'Минск Арена', 'Пустая Б'],
      primary_arena_id: 1,
    });

  it('puts arenas with slots first (more slots first), empty ones last in original order', () => {
    const { buildArenaSlotFilter } = loadModel();
    const view = buildArenaSlotFilter(many(), { 2: 6, 3: 12 }, []);
    assert.deepEqual(view.items.map((i) => i.id), [3, 2, 1, 4]);
    assert.equal(view.total, 18);
    assert.equal(view.allActive, true);
    assert.equal(view.items[0].hasSlots, true);
    assert.equal(view.items[2].hasSlots, false);
  });

  it('without counts keeps the order and shows no marks', () => {
    const { buildArenaSlotFilter, renderArenaSlotFilterHtml } = loadModel();
    const view = buildArenaSlotFilter(many(), null, []);
    assert.deepEqual(view.items.map((i) => i.id), [1, 2, 3, 4]);
    assert.equal(view.marked, false);
    const html = renderArenaSlotFilterHtml(view);
    assert.ok(!html.includes('trainer-detail-arena-dot'));
    assert.ok(!html.includes('trainer-detail-arena-legend'));
  });

  it('marks the selected arena and offers a link to its page', () => {
    const { buildArenaSlotFilter, renderArenaSlotFilterHtml } = loadModel();
    const view = buildArenaSlotFilter(many(), { 2: 6 }, [2]);
    assert.equal(view.allActive, false);
    assert.equal(view.selectedArena.id, 2);
    const html = renderArenaSlotFilterHtml(view);
    assert.ok(html.includes('href="arena?ref=2"'));
    assert.ok(html.includes('Страница арены Замок'));
    assert.ok(html.includes('trainer-detail-arena-chip--none'));
  });

  it('no link when all venues are shown; names are escaped', () => {
    const { buildArenaSlotFilter, renderArenaSlotFilterHtml } = loadModel();
    const view = buildArenaSlotFilter(
      trainer({ arena_names: ['<b>x</b>', 'Y'] }),
      { 10: 1 },
      []
    );
    const html = renderArenaSlotFilterHtml(view);
    assert.ok(!html.includes('trainer-detail-arena-link'));
    assert.ok(!html.includes('<b>x</b>'));
  });
});
