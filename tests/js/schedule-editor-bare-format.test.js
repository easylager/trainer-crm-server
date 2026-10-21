/**
 * No rink + both formats: slot editor asks очно / онлайн and defaults to очно.
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const src = fs.readFileSync(
  path.join(__dirname, '..', '..', 'static', 'webapp', 'schedule-editor-main.js'),
  'utf8'
);

assert.match(src, /var SCHEDULE_IN_PERSON_VENUE = 'in_person'/);
assert.match(src, /function scheduleEditorNeedsBareFormatPick\(\)/);
assert.match(src, /appendChip\(SCHEDULE_IN_PERSON_VENUE, 'Очно', false\)/);
assert.match(
  src,
  /scheduleEditorNeedsBareFormatPick\(\)\s*\?\s*SCHEDULE_IN_PERSON_VENUE/,
  'with no arenas the default chip is очно, not online'
);

const slotOnline = src.match(/function scheduleEditorSlotIsOnline\(s\) \{[\s\S]*?\n      \}/);
assert.ok(slotOnline, 'scheduleEditorSlotIsOnline must exist');
assert.doesNotMatch(
  slotOnline[0],
  /arena_id == null && !!state\.onlineEnabled/,
  'a venue-less slot is online only when the row says so'
);
