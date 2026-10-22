/**
 * Онбординг: что тренер видит по умолчанию (TASK-312/313).
 *
 * Run: node --test "tests/js/*.test.js"
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');
const read = (name) => fs.readFileSync(path.join(webapp, name), 'utf8');

describe('подсказанная неделя', () => {
  const js = read('trainer-onboarding-main.js');

  it('будни, три вечерних старта с 17:00 — без утренних', () => {
    assert.match(js, /var starts = pick\('eve', 17 \* 60, 3\);/);
    assert.doesNotMatch(js, /pick\('mor'/);
  });
});

describe('свой каток в онбординге', () => {
  const js = read('trainer-onboarding-main.js');

  it('привязанные к тренеру катки отмечены сразу при входе', () => {
    assert.match(js, /data\.linked_arena_ids/);
  });

  it('тип места — только «Каток» и «Зал»', () => {
    assert.match(js, /VENUE_CHOICES = \[\s*\{ key: 'ice', noun: 'Каток' \},\s*\{ key: 'gym', noun: 'Зал' \},\s*\]/);
    assert.doesNotMatch(js, /\(state\.venueTypes \|\| \[\]\)\.forEach/);
  });

  it('без фото — знак катка, а не эмодзи', () => {
    assert.doesNotMatch(js, /'🏟'/);
  });
});
