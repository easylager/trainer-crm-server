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

  it('uses slug in href when the trainer payload includes arena_slugs', () => {
    const { buildTrainerArenaChips } = loadModel();
    const view = buildTrainerArenaChips(
      trainer({ arena_slugs: ['chizhovka', 'zamok'] })
    );
    assert.equal(view.items[0].href, 'arena?ref=chizhovka');
    assert.equal(view.items[1].href, 'arena?ref=zamok');
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
