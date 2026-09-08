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

  it('map pan with a selected city always keeps city_id so other cities cannot appear', () => {
    const { buildListUrl, buildMapListUrl } = loadModel();
    const url = buildMapListUrl({
      bbox: '53.8,27.4,54.0,27.7',
      cityId: 2,
      intent: 'skate',
      limit: 50,
    });
    assert.match(url, /city_id=2/);
    assert.match(url, /bbox=/);
  });
});

describe('trainer catalog chip (TASK-076 AC-002)', () => {
  it('Тренеры chip stays on ice.html as a list lens, not catalog navigate', () => {
    const { catalogHref, iceCoachHref, intentChipAction } = loadModel();
    assert.equal(catalogHref(), 'catalog?tab=catalog');
    assert.equal(iceCoachHref(), 'ice?intent=coach');
    assert.deepEqual(intentChipAction('coach'), { type: 'list', intent: 'coach' });
    assert.notEqual(intentChipAction('coach').type, 'catalog');
    assert.equal(intentChipAction('coach').href, undefined);
    assert.deepEqual(intentChipAction('skate'), { type: 'list', intent: 'skate' });
    assert.deepEqual(intentChipAction('group'), { type: 'list', intent: 'group' });
  });

  it('URL intent=coach opens the coaches lens even if session had skate', () => {
    const { intentFromSearch } = loadModel();
    assert.equal(intentFromSearch('?intent=coach'), 'coach');
    assert.equal(intentFromSearch('?intent=group'), 'group');
    assert.equal(intentFromSearch('?intent=skate'), 'skate');
    assert.equal(intentFromSearch(''), null);
    assert.equal(intentFromSearch('?intent=nope'), null);
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

  it('coach empty stays in Ice chrome and does not send the user to catalog.html', () => {
    const { formatEmptyList } = loadModel();
    const empty = formatEmptyList('coach');
    assert.match(empty.title, /тренер/i);
    assert.ok(!/catalog\.html/i.test(empty.title + empty.body));
    assert.ok(!/воронк/i.test(empty.body));
  });

  it('coach empty with a service filter tells the user to drop the chip', () => {
    const { formatEmptyList } = loadModel();
    const empty = formatEmptyList('coach', { serviceName: 'Фигурное катание' });
    assert.match(empty.title, /услуг/i);
    assert.match(empty.body, /фильтр|город/i);
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

  it('trainer search hits open the catalog trainer card, not the browse funnel', () => {
    const { trainerHref } = loadModel();
    assert.equal(trainerHref({ id: 77 }), 'catalog?trainer_id=77');
  });

  it('coach list reuses GET /api/public/trainers for the city, not a booking API', () => {
    const { buildTrainersUrl } = loadModel();
    const url = buildTrainersUrl({ cityId: 3, limit: 50 });
    assert.match(url, /\/api\/public\/trainers/);
    assert.match(url, /city_id=3/);
    assert.match(url, /limit=50/);
    assert.ok(!url.includes('/book'));
    assert.ok(!url.includes('/api/webapp'));
  });

  it('coach list can filter trainers by catalog service_id', () => {
    const { buildTrainersUrl, buildServicesUrl } = loadModel();
    const url = buildTrainersUrl({ cityId: 2, serviceId: 3, limit: 50 });
    assert.match(url, /service_id=3/);
    assert.match(url, /city_id=2/);
    assert.equal(buildServicesUrl({ cityId: 2 }), '/api/public/services?city_id=2');
  });

  it('Ice city picker asks /api/public/ice/cities, not the full catalog city dump', () => {
    const { buildIceCitiesUrl } = loadModel();
    assert.equal(buildIceCitiesUrl(), '/api/public/ice/cities');
  });

  it('hides cities with neither skating nor trainers; trainer-only opens Тренеры', () => {
    const { filterIceCities, pickCityIntent } = loadModel();
    const cities = [
      { id: 1, name: 'Пустой', skate_count: 0, trainer_count: 0 },
      { id: 2, name: 'Минск', skate_count: 4, trainer_count: 9 },
      { id: 3, name: 'Гомель', skate_count: 0, trainer_count: 2 },
    ];
    assert.deepEqual(
      filterIceCities(cities).map((c) => c.name),
      ['Минск', 'Гомель']
    );
    assert.equal(pickCityIntent({ skate_count: 4, trainer_count: 9 }, 'skate'), 'skate');
    assert.equal(pickCityIntent({ skate_count: 0, trainer_count: 2 }, 'skate'), 'coach');
    assert.equal(pickCityIntent({ skate_count: 0, trainer_count: 2 }, 'coach'), 'coach');
    assert.equal(pickCityIntent({ skate_count: 3, trainer_count: 0 }, 'coach'), 'skate');
  });

  it('service chips use short labels; empty service is «Все»', () => {
    const { serviceChipLabel } = loadModel();
    assert.equal(serviceChipLabel(''), 'Все');
    assert.equal(serviceChipLabel('Фигурное катание'), 'Фигурное');
    assert.equal(serviceChipLabel('Хоккейное катание'), 'Хоккей');
    assert.equal(serviceChipLabel('Катание на роликах'), 'Ролики');
    assert.equal(serviceChipLabel('Обучение катанию «с нуля»'), 'С нуля');
    assert.equal(serviceChipLabel('Совершенствование катания'), 'Техника');
    assert.equal(serviceChipLabel('ОХМ(отработка хоккейного мастерства)'), 'ОХМ');
  });

  it('city picker shows country as a second line', () => {
    const { cityCountryLabel } = loadModel();
    assert.equal(cityCountryLabel('BY'), 'Беларусь');
    assert.equal(cityCountryLabel('RU'), 'Россия');
    assert.equal(cityCountryLabel(null), '');
  });

  it('group intent is not a first-class Ice lens anymore', () => {
    const { coerceIntent } = loadModel();
    assert.equal(coerceIntent('group'), 'skate');
    assert.equal(coerceIntent('coach'), 'coach');
    assert.equal(coerceIntent('skate'), 'skate');
  });

  it('map toggle stays on the Ice tab (TASK-054 in-place Yandex map)', () => {
    const { mapHref } = loadModel();
    assert.equal(mapHref(), '');
  });

  it('coach map listUrl does not hit ice/arenas; city-geo helper still may', () => {
    const { buildMapListUrl, buildListUrl, mapShowsArenas, formatCoachMapEmpty } = loadModel();
    assert.equal(mapShowsArenas('coach'), false);
    assert.equal(mapShowsArenas('skate'), true);
    assert.equal(mapShowsArenas('group'), true);
    const coachMap = buildMapListUrl({
      cityId: 3,
      intent: 'coach',
      bbox: '53.8,27.4,54.0,27.7',
      limit: 50,
    });
    assert.equal(coachMap, '');
    assert.ok(!String(coachMap).includes('/api/public/ice/arenas'));
    const skateMap = buildMapListUrl({ cityId: 3, intent: 'skate', limit: 50 });
    assert.match(skateMap, /\/api\/public\/ice\/arenas/);
    assert.match(skateMap, /intent=skate/);
    const geoBypass = buildListUrl({ near: '53.9,27.56', intent: 'coach', limit: 1 });
    assert.match(geoBypass, /\/api\/public\/ice\/arenas/);
    assert.match(geoBypass, /intent=coach/);
    assert.match(geoBypass, /limit=1/);
    const empty = formatCoachMapEmpty();
    assert.match(empty.title, /тренер/i);
    assert.match(empty.body, /список/i);
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

  it('Покататься still hides arenas without a future public_skate|open_ice slot', () => {
    const { filterSkateLens } = loadModel();
    const kept = filterSkateLens(
      [
        { id: 1, live: { kind: 'session' } },
        { id: 2, live: { kind: 'trainers' } },
        { id: 3, live: { kind: 'unknown' } },
      ],
      'skate'
    );
    assert.deepEqual(
      kept.map((it) => it.id),
      [1]
    );
  });
});

describe('coach lens cards (TASK-076 AC-003 / AC-004)', () => {
  const trainer = {
    id: 77,
    profile: {
      first_name: 'Мария',
      last_name: 'Иванова',
      rating_avg: 4.8,
      rating_count: 12,
    },
    photos: [{ list_url: '/api/public/photos/t.jpg', url: '/full.jpg' }],
    primary_arena_name: 'Чижовка',
    can_book: true,
    free_slots_14d: 5,
  };

  it('maps public trainer payload into ice-acard fields and the existing profile deep-link', () => {
    const { trainerCardView } = loadModel();
    const view = trainerCardView(trainer);
    assert.equal(view.name, 'Мария Иванова');
    assert.equal(view.href, 'catalog?trainer_id=77');
    assert.equal(view.thumb, '/api/public/photos/t.jpg');
    assert.match(view.meta, /Чижовка/);
    assert.ok(!view.href.includes('ice.html'));
    assert.equal(view.kind, 'trainer');
  });

  it('coach caption counts trainers, not rinks', () => {
    const { formatSortCaption } = loadModel();
    const text = formatSortCaption({
      total: 2,
      intent: 'coach',
      items: [{ id: 1 }, { id: 2 }],
    });
    assert.match(text, /2/);
    assert.match(text, /тренер/);
    assert.ok(!/каток/.test(text));
  });

  it('does not put a booking CTA on MK rows even when rendering a mixed list', () => {
    const { listRowCta } = loadModel();
    assert.equal(listRowCta({ live: { kind: 'session' }, can_book: true }), null);
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
      { intent: 'coach', cityId: 5, cityName: 'Гродно', serviceId: 3, scrollY: 420, view: 'map' },
      storage
    );
    assert.ok(mem[ICE_STATE_KEY]);
    const loaded = loadIceState(storage);
    assert.equal(loaded.intent, 'coach');
    assert.equal(loaded.cityId, 5);
    assert.equal(loaded.cityName, 'Гродно');
    assert.equal(loaded.serviceId, 3);
    assert.equal(loaded.view, 'map');
    assert.equal(loaded.scrollY, 420);
  });
});

describe('boardCardView (TASK-090: карточка-табло)', () => {
  const sessionItem = {
    id: 3,
    slug: 'tts-zamok',
    name: 'ТЦ Замок',
    district: 'Центральный район',
    tier: 'A',
    thumb: '/photos/3_thumb.jpg',
    card: '/photos/3_card.jpg',
    live: {
      kind: 'session',
      local_date: '2026-09-06',
      starts_at_local: '18:15',
      price_adult_minor: 1000,
      price_child_minor: 800,
      price_rental_minor: 900,
      currency_code: 'BYN',
      more_count: 69,
    },
  };
  const now = new Date('2026-09-06T08:00:00Z');

  it('AC-002: время и день — отдельные слоты, а не склеенная строка', () => {
    const { boardCardView } = loadModel();
    const v = boardCardView(sessionItem, now);
    assert.equal(v.time, '18:15');
    assert.equal(v.day, 'Сегодня');
    assert.equal(v.isSession, true);
  });

  it('AC-001: полноширинный кадр берёт card (800px), а не thumb (320px)', () => {
    const { boardCardView } = loadModel();
    assert.equal(boardCardView(sessionItem, now).photo, '/photos/3_card.jpg');
    const noCard = Object.assign({}, sessionItem, { card: null });
    assert.equal(boardCardView(noCard, now).photo, '/photos/3_thumb.jpg');
  });

  it('AC-004: глубина предложения — свой слот, без обещания недельного окна', () => {
    const { boardCardView } = loadModel();
    const v = boardCardView(sessionItem, now);
    assert.equal(v.depth, 'Ещё 69 сеансов в расписании');
    assert.ok(!v.depth.includes('недел'));
    assert.ok(!v.prices.includes('69'));
    assert.match(v.prices, /взр\. 10 · дет\. 8 · прокат \+9 BYN/);
  });

  it('единственный сеанс не превращается в «ещё 0»', () => {
    const { boardCardView } = loadModel();
    const one = Object.assign({}, sessionItem, {
      live: Object.assign({}, sessionItem.live, { more_count: 0 }),
    });
    assert.equal(boardCardView(one, now).depth, 'Расписание и цены');
  });

  it('AC-006: каток без расписания отдаёт текст статуса, а не пустые слоты', () => {
    const { boardCardView } = loadModel();
    const v = boardCardView(
      { id: 9, name: 'Юность', district: 'Центральный район', tier: 'B', live: { kind: 'unknown' } },
      now
    );
    assert.equal(v.isSession, false);
    assert.equal(v.time, '');
    assert.ok(v.status.length > 0);
    assert.equal(v.depth, 'Открыть карточку катка');
  });

  it('AC-006: каток без кадра получает монограмму, а не пустой прямоугольник', () => {
    const { boardCardView } = loadModel();
    const v = boardCardView({ id: 9, name: 'Юность', live: { kind: 'unknown' } }, now);
    assert.equal(v.photo, '');
    assert.equal(v.initial, 'Ю');
  });

  it('монограмма тренера пропускает эмодзи в имени', () => {
    const { trainerCardView } = loadModel();
    const v = trainerCardView({ id: 1, name: '🌱 Максим Василенко' });
    assert.equal(v.initial, 'М');
  });

  it('завтрашний сеанс подписан «Завтра», послезавтрашний — датой', () => {
    const { boardCardView } = loadModel();
    const tomorrow = Object.assign({}, sessionItem, {
      live: Object.assign({}, sessionItem.live, { local_date: '2026-09-07' }),
    });
    assert.equal(boardCardView(tomorrow, now).day, 'Завтра');
    const later = Object.assign({}, sessionItem, {
      live: Object.assign({}, sessionItem.live, { local_date: '2026-09-10' }),
    });
    assert.equal(boardCardView(later, now).day, '10.09');
  });
});
