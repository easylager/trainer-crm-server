/**
 * TASK-184: Europe/Minsk time, board refresh, hub teaser.
 * Run: node --test tests/js/task-184-minsk-time.test.js
 * TZ cases: TZ=America/New_York node --test tests/js/task-184-minsk-time.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');
const mtPath = path.join(webapp, 'minsk-time.js');
const iceModelPath = path.join(webapp, 'ice-tab-model.js');
const arenaModelPath = path.join(webapp, 'arena-card-model.js');
const teaserPath = path.join(webapp, 'ice-teaser-model.js');
const iceTabPath = path.join(webapp, 'ice-tab.js');
const arenaCardPath = path.join(webapp, 'arena-card.js');
const stalenessPath = path.join(webapp, 'schedule-staleness-model.js');

function load(rel) {
  const resolved = require.resolve(path.join(webapp, rel));
  delete require.cache[resolved];
  return require(resolved);
}

const sessionItem = {
  id: 3,
  name: 'ТЦ Замок',
  tier: 'A',
  live: {
    kind: 'session',
    local_date: '2026-10-06',
    starts_at_local: '18:00',
    starts_at_utc: '2026-10-06T15:00:00+00:00',
    price_adult_minor: 1000,
    currency_code: 'BYN',
  },
};

describe('AC-1 boardCardView hides started session after time passes', () => {
  it('shows 18:00 at 17:50 Minsk, hides session slot at 18:05', () => {
    const { boardCardView } = load('ice-tab-model.js');
    const at1750 = new Date('2026-10-06T14:50:00Z');
    const at1805 = new Date('2026-10-06T15:05:00Z');
    const before = boardCardView(sessionItem, at1750);
    assert.equal(before.isSession, true);
    assert.equal(before.time, '18:00');
    const after = boardCardView(sessionItem, at1805);
    assert.equal(after.isSession, false);
    assert.notEqual(after.time, '18:00');
  });
});

describe('AC-1 ice-tab visibility refresh', () => {
  it('wires pageshow/visibilitychange to onAppVisible (re-render + stale refetch)', () => {
    const src = fs.readFileSync(iceTabPath, 'utf8');
    assert.match(src, /function onAppVisible\(/);
    assert.match(src, /visibilitychange[\s\S]*onAppVisible/);
    assert.match(src, /pageshow[\s\S]*onAppVisible/);
    assert.match(src, /LIST_STALE_MS/);
    assert.match(src, /boardCardView\(item, new Date\(\)/);
  });
});

describe('AC-2 openUntilLabel and today use Minsk, not device TZ', () => {
  const hours = { daily: { open: '10:00', close: '22:00' } };
  /** 23:30 Europe/Minsk */
  const at2330Minsk = new Date('2026-10-06T20:30:00Z');

  it('closed after 22:00 Minsk even when process TZ is America/New_York', () => {
    const { openUntilLabel } = load('arena-card-model.js');
    const label = openUntilLabel(hours, at2330Minsk);
    assert.equal(label, '');
  });

  it('sessionDayLabel «Сегодня» by Minsk calendar with Asia/Tokyo process TZ', () => {
    const { sessionDayLabel } = load('ice-tab-model.js');
    /** 02:00 Oct 7 in Tokyo = still Oct 6 evening in Minsk */
    const now = new Date('2026-10-06T17:00:00Z');
    const label = sessionDayLabel(
      { local_date: '2026-10-06', starts_at_local: '20:00' },
      now
    );
    assert.equal(label, 'Сегодня');
  });

  it('arena-card todayIso before card load uses Minsk date', () => {
    const MT = load('minsk-time.js');
    const now = new Date('2026-10-06T17:00:00Z');
    assert.equal(MT.dateIso(now), '2026-10-06');
    const src = fs.readFileSync(arenaCardPath, 'utf8');
    assert.match(src, /MT\.dateIso\(now\)/);
  });
});

describe('AC-3 hub teaser shows next session after first started', () => {
  it('formatIceCard picks second session from payload.sessions', () => {
    const { formatIceCard } = load('ice-teaser-model.js');
    const payload = {
      arena_id: 1,
      arena_name: 'Чижовка',
      sessions: [
        {
          session_id: 10,
          arena_id: 1,
          starts_at_utc: '2026-10-06T15:00:00+00:00',
          local_date: '2026-10-06',
          starts_at_local: '18:00',
          kind: 'public_skate',
          price_adult_minor: 1000,
          currency_code: 'BYN',
        },
        {
          session_id: 11,
          arena_id: 2,
          arena_name: 'Юность',
          starts_at_utc: '2026-10-06T16:00:00+00:00',
          local_date: '2026-10-06',
          starts_at_local: '19:00',
          kind: 'public_skate',
          price_adult_minor: 1100,
          currency_code: 'BYN',
        },
      ],
      session_id: 10,
      starts_at_utc: '2026-10-06T15:00:00+00:00',
      local_date: '2026-10-06',
      starts_at_local: '18:00',
      kind: 'public_skate',
      price_adult_minor: 1000,
      currency_code: 'BYN',
    };
    const at1805 = new Date('2026-10-06T15:05:00Z');
    const view = formatIceCard(payload, at1805);
    assert.equal(view.hidden, false);
    assert.equal(view.time, '19:00');
    assert.match(view.name, /Юность/);
  });
});

describe('AC-4 catalog models avoid device getHours/getDay/toISOString date slices', () => {
  const files = [
    'ice-tab-model.js',
    'arena-card-model.js',
    'ice-teaser-model.js',
    'hub-ice-today-model.js',
    'minsk-time.js',
  ];
  const bad = [
    /\.getHours\(\)/,
    /\.getDay\(\)/,
    /toISOString\(\)\.slice\(0,\s*10\)/,
  ];

  for (const file of files) {
    it(file + ' has no device-local date hacks for business logic', () => {
      const src = fs.readFileSync(path.join(webapp, file), 'utf8');
      for (const re of bad) {
        assert.doesNotMatch(src, re, file + ' matched ' + re);
      }
    });
  }

  it('models require minsk-time.js', () => {
    for (const file of ['ice-tab-model.js', 'arena-card-model.js', 'ice-teaser-model.js', 'hub-ice-today-model.js']) {
      const src = fs.readFileSync(path.join(webapp, file), 'utf8');
      assert.match(src, /minsk-time\.js/, file);
    }
  });
});

describe('staleness «N дней» uses Minsk calendar', () => {
  it('veryStaleNote counts days in Minsk', () => {
    const S = load('schedule-staleness-model.js');
    const now = new Date('2026-10-06T20:00:00Z');
    const observed = new Date('2026-10-04T10:00:00Z');
    const note = S.veryStaleNote(
      { schedule_stale: true, schedule_very_stale: true, schedule_observed_at: observed.toISOString() },
      now,
      { hasPhone: true }
    );
    assert.match(note, /2 дня/);
  });
});
