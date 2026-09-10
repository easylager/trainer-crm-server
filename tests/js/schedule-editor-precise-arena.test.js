/**
 * Precise-time drum must keep an explicit arena_id even for the primary venue.
 * Collapsing primary → null hid the chip and let save fall back to the wrong rink.
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const src = fs.readFileSync(
  path.join(__dirname, '..', '..', 'static', 'webapp', 'schedule-editor-main.js'),
  'utf8'
);
const html = fs.readFileSync(
  path.join(__dirname, '..', '..', 'static', 'webapp', 'schedule-editor.html'),
  'utf8'
);

const preciseFn = src.match(/function readPreciseArenaPickForSave\(\) \{[\s\S]*?\n      \}/);
assert.ok(preciseFn, 'readPreciseArenaPickForSave must exist');
assert.doesNotMatch(
  preciseFn[0],
  /primaryId != null && aid === primaryId\) return null/,
  'precise arena pick must not collapse primary to null'
);
assert.match(
  preciseFn[0],
  /Always keep the explicit venue/,
  'comment documents why primary stays explicit'
);

assert.match(
  src,
  /psRow\.arenaId = precArenaPick/,
  'adding a precise slot must store arenaId'
);
assert.match(
  src,
  /Выберите площадку для этого слота/,
  'multi-arena precise add requires a venue'
);

assert.match(
  html,
  /сохраняется на выбранную здесь площадку/,
  'precise arena help must explain per-slot venue'
);
assert.doesNotMatch(
  html,
  /Только окна, добавленные вручную на вкладке/,
  'old unhelpful precise help must be gone'
);

console.log('ok: precise-time arena attribution guards');
