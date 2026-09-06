/**
 * TASK-053: Ice tab view-model — lenses, caption, search groups, city fallback.
 * Run: node --test tests/js/ice-tab-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/ice-tab-model.js');

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

describe('buildListUrl (epic 2026-09-05 skate filter)', () => {
  it('Покататься asks the API for intent=skate; does not invent tiers', () => {
    const { buildListUrl } = loadModel();
    const url = buildListUrl({ cityId: 3, intent: 'skate' });
    assert.match(url, /\/api\/public\/ice\/arenas/);
    assert.match(url, /city_id=3/);
    assert.match(url, /intent=skate/);
    assert.ok(!url.includes('tier='));
  });

  it('Группы keep venues without MK via intent=group', () => {
    const { buildListUrl } = loadModel();
    const url = buildListUrl({ cityId: 3, intent: 'group' });
    assert.match(url, /intent=group/);
  });

  it('defaults missing intent to skate', () => {
    const { buildListUrl } = loadModel();
    assert.match(buildListUrl({ cityId: 1 }), /intent=skate/);
  });

  it('map pan sends bbox without dumping the city as a second query shape', () => {
    const { buildListUrl } = loadModel();
    const url = buildListUrl({
      bbox: '53.8,27.4,54.0,27.7',
      intent: 'skate',
      limit: 50,
    });
    assert.match(url, /bbox=53\.8%2C27\.4%2C54\.0%2C27\.7|bbox=53\.8,27\.4,54\.0,27\.7/);
    assert.match(url, /intent=skate/);
    assert.ok(!url.includes('city_id='));
  });
});

describe('trainer catalog chip (AC-001 / AC-006)', () => {
  it('Тренеры chip is one tap into the existing catalog, not a new funnel', () => {
    const { catalogHref, intentChipAction } = loadModel();
    assert.equal(catalogHref(), 'catalog?tab=catalog');
    assert.deepEqual(intentChipAction('coach'), { type: 'catalog', href: 'catalog?tab=catalog' });
    assert.deepEqual(intentChipAction('skate'), { type: 'list', intent: 'skate' });
    assert.deepEqual(intentChipAction('group'), { type: 'list', intent: 'group' });
  });

  it('exposes a hint that the trainers catalog moved to the chip', () => {
    const { trainersMovedHint } = loadModel();
    assert.match(trainersMovedHint(), /Тренер/);
    assert.match(trainersMovedHint(), /чип/);
  });
});

describe('formatSortCaption (AC-003 + EDGE-002)', () => {
  it('says сначала с актуальным расписанием when an A-tier rink is present', () => {
    const { formatSortCaption } = loadModel();
    const text = formatSortCaption({
      total: 14,
      items: [{ tier: 'A' }, { tier: 'B' }],
    });
    assert.match(text, /14/);
    assert.match(text, /катков/);
    assert.match(text, /актуальн/);
  });

  it('does not claim актуальное расписание when no A-tier rinks', () => {
    const { formatSortCaption } = loadModel();
    const text = formatSortCaption({
      total: 3,
      items: [{ tier: 'B' }, { tier: 'C' }],
    });
    assert.match(text, /3/);
    assert.ok(!/актуальн/.test(text));
  });
});

describe('formatMeta / live tone (AC-003)', () => {
  it('renders district · distance and does not invent a close time', () => {
    const { formatMeta } = loadModel();
    assert.equal(
      formatMeta({ district: 'Заводской', distance_km: 2.4 }),
      'Заводской · 2,4 км'
    );
    assert.equal(formatMeta({ district: 'Центр' }), 'Центр');
  });

  it('uses API tier for live tone, never computes A/B/C on the client', () => {
    const { liveTone } = loadModel();
    assert.equal(liveTone({ tier: 'A', live: { kind: 'session' } }), 'a');
    assert.equal(liveTone({ tier: 'B' }), 'b');
    assert.equal(liveTone({ tier: 'C' }), 'c');
    assert.equal(liveTone({}), 'c');
  });
});

describe('formatLiveLine (prototype: three prices, not mashed live.text)', () => {
  const sessionItem = {
    tier: 'A',
    live: {
      kind: 'session',
      text: 'Сегодня 11:00 · 12 BYN · ещё 3 сеанса',
      local_date: '2026-09-06',
      starts_at_local: '11:00',
      price_adult_minor: 1200,
      price_child_minor: 800,
      price_rental_minor: 600,
      currency_code: 'BYN',
      more_count: 3,
    },
    live_line: 'Сегодня 11:00 · 12 BYN · ещё 3 сеанса',
  };

  it('labels взр/дет/прокат from structured minors and ignores mashed live.text', () => {
    const { formatLiveLine } = loadModel();
    const text = formatLiveLine(sessionItem, new Date('2026-09-06T08:00:00Z'));
    assert.match(text, /Сегодня 11:00/);
    assert.match(text, /взр/);
    assert.match(text, /дет/);
    assert.match(text, /прокат/);
    assert.match(text, /ещё 3/);
    assert.ok(!text.includes('12 / 8'));
    assert.ok(!/11:00 · 12 BYN/.test(text));
  });

  it('keeps trainer/group live.text as-is', () => {
    const { formatLiveLine } = loadModel();
    assert.equal(
      formatLiveLine({
        live: { kind: 'trainers', text: '4 тренера · 12 свободных слотов на неделе' },
      }),
      '4 тренера · 12 свободных слотов на неделе'
    );
    assert.equal(
      formatLiveLine({ live: { kind: 'groups', text: '2 группы с набором' } }),
      '2 группы с набором'
    );
  });

  it('uses prototype B/C copy when there is no session', () => {
    const { formatLiveLine } = loadModel();
    assert.match(
      formatLiveLine({ tier: 'B', live: { kind: 'unknown', text: 'Расписание уточняется' } }),
      /телефон|сайт/
    );
    assert.match(
      formatLiveLine({ tier: 'C', live: { kind: 'unknown', text: 'Расписание уточняется' } }),
      /справочник/
    );
  });
});

describe('formatEmptyList', () => {
  it('skate empty does not dump the trainers-moved hint into the list', () => {
    const { formatEmptyList, trainersMovedHint } = loadModel();
    const empty = formatEmptyList('skate');
    assert.match(empty.title, /массового катания|катков/i);
    assert.ok(!empty.body.includes(trainersMovedHint()));
    assert.match(empty.body, /город|Тренер/i);
  });
});

describe('groupSearchResults (AC-004)', () => {
  it('keeps arena / trainer / city groups with type labels', () => {
    const { groupSearchResults } = loadModel();
    const grouped = groupSearchResults({
      groups: [
        { type: 'arena', items: [{ id: 1, name: 'Чижовка', address: 'ул. Ташкентская' }] },
        { type: 'trainer', items: [{ id: 9, last_name: 'Иванова', name: 'Мария Иванова' }] },
        { type: 'city', items: [{ id: 2, name: 'Минск' }] },
      ],
    });
    assert.deepEqual(
      grouped.map((g) => g.type),
      ['arena', 'trainer', 'city']
    );
    assert.equal(grouped[0].label, 'Катки');
    assert.equal(grouped[1].label, 'Тренеры');
    assert.equal(grouped[2].label, 'Города');
    assert.equal(grouped[1].items[0].last_name, 'Иванова');
  });
});

describe('pickFallbackCity (EDGE-001)', () => {
  it('picks the first city by sort_order when session and geo are missing', () => {
    const { pickFallbackCity } = loadModel();
    const city = pickFallbackCity([
      { id: 8, name: 'Брест', sort_order: 20 },
      { id: 1, name: 'Минск', sort_order: 0 },
      { id: 4, name: 'Гомель', sort_order: 10 },
    ]);
    assert.equal(city.id, 1);
    assert.equal(city.name, 'Минск');
  });
});

describe('hrefs', () => {
  it('arena rows open the TASK-052 card by slug or id', () => {
    const { arenaHref } = loadModel();
    assert.equal(arenaHref({ slug: 'minsk-chizhovka', id: 12 }), 'arena?ref=minsk-chizhovka');
    assert.equal(arenaHref({ id: 12 }), 'arena?ref=12');
  });

  it('trainer search hits reuse the old catalog deep link', () => {
    const { trainerHref } = loadModel();
    assert.equal(trainerHref({ id: 77 }), 'catalog?tab=catalog&trainer_id=77');
  });

  it('map toggle stays on the Ice tab (TASK-054 in-place Yandex map)', () => {
    const { mapHref } = loadModel();
    assert.equal(mapHref(), '');
  });
});

describe('skate lens filter (TASK-075 AC-001)', () => {
  const withSession = {
    id: 1,
    name: 'Чижовка',
    tier: 'A',
    live: { kind: 'session', starts_at_local: '11:00' },
  };
  const openIce = {
    id: 2,
    name: 'Свободный лёд',
    tier: 'A',
    live: { kind: 'open_ice', starts_at_local: '18:00' },
  };
  const publicSkateSlot = {
    id: 3,
    name: 'Слоты в массиве',
    tier: 'A',
    live: { kind: 'unknown' },
    sessions: [{ kind: 'public_skate', starts_at_local: '19:00' }],
  };
  const noSlot = {
    id: 4,
    name: 'Только профиль',
    tier: 'B',
    live: { kind: 'unknown', text: 'Расписание уточняется' },
  };

  it('Покататься keeps only arenas with a future public_skate|open_ice slot', () => {
    const { filterSkateLens } = loadModel();
    const kept = filterSkateLens([withSession, openIce, publicSkateSlot, noSlot], 'skate');
    assert.deepEqual(
      kept.map((it) => it.id),
      [1, 2, 3]
    );
  });

  it('Группы keep venues without MK', () => {
    const { filterSkateLens } = loadModel();
    const kept = filterSkateLens([withSession, noSlot], 'group');
    assert.deepEqual(
      kept.map((it) => it.id),
      [1, 4]
    );
  });

  it('MK list rows are read-only — no Записаться CTA', () => {
    const { listRowCta } = loadModel();
    assert.equal(listRowCta({ live: { kind: 'session' } }), null);
    assert.equal(listRowCta({ live: { kind: 'public_skate' } }), null);
    assert.equal(listRowCta({ live: { kind: 'open_ice' } }), null);
  });
});

describe('session restore', () => {
  it('round-trips lens, city and scroll', () => {
    const { saveIceState, loadIceState, ICE_STATE_KEY } = loadModel();
    const mem = {};
    const storage = {
      getItem: (k) => (k in mem ? mem[k] : null),
      setItem: (k, v) => {
        mem[k] = String(v);
      },
    };
    saveIceState(
      { intent: 'group', cityId: 5, cityName: 'Гродно', scrollY: 420, view: 'list' },
      storage
    );
    assert.ok(mem[ICE_STATE_KEY]);
    const loaded = loadIceState(storage);
    assert.equal(loaded.intent, 'group');
    assert.equal(loaded.cityId, 5);
    assert.equal(loaded.cityName, 'Гродно');
    assert.equal(loaded.scrollY, 420);
  });
});
