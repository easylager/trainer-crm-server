/**
 * TASK-250: display_rules.json — те же примеры, что tests/unit/test_display_rules_fixture.py.
 * Run: TZ=UTC node --test tests/js/display-rules.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');
const fixturePath = path.join(root, 'tests/fixtures/display_rules.json');
const PD = require(path.join(root, 'static/webapp/public-display-model.js'));
const Arena = require(path.join(root, 'static/webapp/arena-card-model.js'));
const Sched = require(path.join(root, 'static/webapp/arena-schedule-mode-model.js'));

const payload = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
const today = payload.today;
const cases = payload.cases;

function runCase(caseRow) {
  const fn = caseRow.fn;
  const args = caseRow.args || {};
  if (fn === 'format_clock') return PD.formatClock(args.hhmm);
  if (fn === 'short_day_word') return PD.shortDayWord(args.day, today);
  if (fn === 'session_day_phrase') return PD.sessionDayPhrase(args.day, args.hhmm, today);
  if (fn === 'sentence_when') return PD.sentenceWhen(args.day, args.hhmm, today);
  if (fn === 'format_price_minor') return PD.formatPriceMinor(args.minor, args.currency || 'BYN');
  if (fn === 'open_status') {
    const now = new Date(args.now_utc);
    return Arena.openUntilLabel(args.opening_hours, now, args.timezone || 'Europe/Minsk');
  }
  if (fn === 'schedule_phone_line') return Sched.phoneLine();
  if (fn === 'schedule_season_closed') {
    return Sched.seasonClosedLine({
      schedule_reopen_date: args.reopen_date || null,
      schedule_mode_note: args.note || '',
    });
  }
  throw new Error('unknown fn ' + fn + ' in ' + caseRow.id);
}

describe('TASK-250 display_rules.json', () => {
  it('has at least 40 shared examples', () => {
    assert.ok(cases.length >= 40);
  });

  for (const caseRow of cases) {
    it(caseRow.id || caseRow.fn, () => {
      const got = runCase(caseRow);
      assert.equal(got, caseRow.expect, caseRow.id + ': got ' + JSON.stringify(got));
    });
  }
});
