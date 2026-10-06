/**
 * TASK-053: Ice tab view-model — lenses, caption, search groups, city fallback.
 * Run: node --test tests/js/ice-tab-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const stalePath = path.resolve(__dirname, '../../static/webapp/schedule-staleness-model.js');
const modelPath = path.resolve(__dirname, '../../static/webapp/ice-tab-model.js');

function loadModel() {
  delete require.cache[require.resolve(stalePath)];
  require(stalePath);
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

describe('фильтр по типу площадки', () => {
  it('без выбора venue_type в запрос не попадает', () => {
    const { buildListUrl } = loadModel();
    assert.ok(!buildListUrl({ cityId: 3, intent: 'skate' }).includes('venue_type'));
    assert.ok(!buildListUrl({ cityId: 3, intent: 'skate', venueTypes: [] }).includes('venue_type'));
  });

  it('выбранные типы едут списком через запятую', () => {
    const { buildListUrl } = loadModel();
    const url = buildListUrl({ cityId: 3, intent: 'skate', venueTypes: ['gym', 'choreo'] });
    assert.match(url, /venue_type=gym%2Cchoreo/);
  });

  it('дубли и регистр не плодят мусор в параметре', () => {
    const { buildListUrl } = loadModel();
    const url = buildListUrl({ cityId: 3, intent: 'skate', venueTypes: ['GYM', ' gym ', ''] });
    assert.match(url, /venue_type=gym(&|$)/);
  });

  it('карта фильтруется так же, как список', () => {
    // Карта тянет данные своим запросом (bbox/near). Пока venue_type в него не
    // попадал, чип «Зал» менял список, а на карте оставались все катки города.
    const { buildMapListUrl } = loadModel();
    const url = buildMapListUrl({
      intent: 'skate',
      bbox: '53.8,27.4,54.0,27.7',
      venueTypes: ['gym'],
    });
    assert.match(url, /venue_type=gym/);
    assert.match(url, /bbox=/);
  });

  it('город с одним типом площадок не показывает фильтр из одного варианта', () => {
    // Выбор из одной кнопки — шум, а не выбор: в чисто ледовом городе
    // чип «Лёд» не сообщает ничего, чего не сообщал бы сам список.
    const { venueChipsView } = loadModel();
    assert.deepEqual(venueChipsView([{ key: 'ice', chip: 'Лёд', count: 8 }], []), []);
  });

  it('смешанный город даёт «Все» плюс чип на каждый тип', () => {
    const { venueChipsView } = loadModel();
    const chips = venueChipsView(
      [
        { key: 'ice', chip: 'Лёд', count: 8 },
        { key: 'gym', chip: 'Зал', count: 1 },
      ],
      []
    );
    assert.deepEqual(chips.map((c) => c.label), ['Все', 'Лёд', 'Зал']);
    assert.equal(chips[0].active, true);
  });

  it('выбранный чип остаётся в списке — из фильтра должно быть куда выйти', () => {
    // Фасеты сервер считает ДО фильтра именно поэтому: иначе «Зал» исчезал бы
    // из собственного списка сразу после нажатия.
    const { venueChipsView } = loadModel();
    const chips = venueChipsView(
      [
        { key: 'ice', chip: 'Лёд', count: 8 },
        { key: 'gym', chip: 'Зал', count: 1 },
      ],
      ['gym']
    );
    assert.equal(chips.find((c) => c.key === 'gym').active, true);
    assert.equal(chips.find((c) => c.key === '').active, false);
    assert.ok(chips.some((c) => c.key === 'ice'));
  });
});

describe('catalog header (A′)', () => {
  it('catalogScope: shop filter is its own segment', () => {
    const { catalogScope } = loadModel();
    assert.equal(catalogScope('skate', ['shop']), 'shop');
    assert.equal(catalogScope('skate', []), 'places');
    assert.equal(catalogScope('coach', []), 'coach');
  });

  it('placeTabsView: choreo forces menu, not underline row', () => {
    const { placeTabsView, placeMenuNeeded } = loadModel();
    const facets = [
      { key: 'ice', chip: 'Лёд', count: 8 },
      { key: 'gym', chip: 'Зал', count: 1 },
      { key: 'choreo', chip: 'Хореография', count: 1 },
    ];
    assert.equal(placeMenuNeeded(facets), true);
    assert.deepEqual(placeTabsView(facets, []), []);
    const tabs = placeTabsView(
      [
        { key: 'ice', chip: 'Лёд', count: 8 },
        { key: 'gym', chip: 'Зал', count: 1 },
      ],
      []
    );
    assert.deepEqual(
      tabs.map((t) => t.label),
      ['Все', 'Лёд', 'Зал']
    );
  });

  it('whenPickerVisible: gym-only hides window; ice facet required for mixed', () => {
    const { whenPickerVisible } = loadModel();
    const facets = [
      { key: 'ice', chip: 'Лёд', count: 3 },
      { key: 'gym', chip: 'Зал', count: 1 },
    ];
    assert.equal(whenPickerVisible('skate', [], facets), true);
    assert.equal(whenPickerVisible('skate', ['gym'], facets), false);
    assert.equal(whenPickerVisible('skate', ['shop'], facets), false);
    assert.equal(whenPickerVisible('skate', [], [{ key: 'gym', chip: 'Зал', count: 2 }]), false);
    assert.equal(
      whenPickerVisible('skate', [], [{ key: 'gym', chip: 'Зал', count: 2 }], { activeWindow: true }),
      true,
      'активное окно с сервера — чип времени виден, даже если в фасетах нет льда'
    );
  });

  it('applyCatalogMode maps segments to intent and venueTypes', () => {
    const { applyCatalogMode } = loadModel();
    assert.deepEqual(applyCatalogMode('shop'), { intent: 'skate', venueTypes: ['shop'] });
    assert.deepEqual(applyCatalogMode('coach'), { intent: 'coach', venueTypes: [] });
    assert.deepEqual(applyCatalogMode('places'), { intent: 'skate', venueTypes: [] });
  });

  it('catalogStateAfterCityChange сбрасывает магазинный сегмент и фильтры', () => {
    const { catalogStateAfterCityChange } = loadModel();
    const next = catalogStateAfterCityChange(
      { skate_count: 2, trainer_count: 1 },
      {
        intent: 'skate',
        venueTypes: ['shop'],
        shopService: 'retail',
        shopOpenNow: true,
      }
    );
    assert.deepEqual(next.venueTypes, []);
    assert.equal(next.intent, 'skate');
    assert.equal(next.shopService, '');
    assert.equal(next.shopOpenNow, false);
    assert.equal(
      catalogStateAfterCityChange({ skate_count: 0, trainer_count: 3 }, { intent: 'skate', venueTypes: ['shop'] }).intent,
      'coach'
    );
  });
});

describe('shop catalog filters', () => {
  const shops = [
    {
      id: 1,
      shop_services: ['skate_sharpening', 'retail'],
      shop_disciplines: ['discipline_hockey'],
      opening_hours: { weekly: { mon: ['10:00', '20:00'] } },
    },
    {
      id: 2,
      shop_services: ['retail'],
      shop_disciplines: ['discipline_figure'],
      opening_hours: { weekly: { mon: ['11:00', '17:00'] } },
    },
  ];

  it('filterShopCatalog by service and discipline', () => {
    const { filterShopCatalog } = loadModel();
    const onlySharpen = filterShopCatalog(shops, { shopService: 'skate_sharpening' }, new Date('2026-10-06T12:00:00Z'));
    assert.equal(onlySharpen.length, 1);
    assert.equal(onlySharpen[0].id, 1);
    const hockey = filterShopCatalog(shops, { shopService: 'skate_sharpening', shopDiscipline: 'discipline_hockey' }, new Date());
    assert.equal(hockey.length, 1);
  });

  it('shopServiceChipsView hides zero-count services', () => {
    const { shopServiceChipsView } = loadModel();
    const chips = shopServiceChipsView(shops, {}, new Date());
    const keys = chips.map((c) => c.key);
    assert.ok(keys.includes(''));
    assert.ok(keys.includes('skate_sharpening'));
    assert.ok(!keys.includes('repair'));
  });

  it('shop discipline row hidden in catalog UI', () => {
    const { shopDisciplineChipsView, shopDisciplineRowVisible } = loadModel();
    assert.equal(shopDisciplineRowVisible('retail'), false);
    assert.equal(shopDisciplineRowVisible('skate_sharpening'), false);
    assert.equal(shopDisciplineChipsView(shops, { shopService: 'skate_sharpening' }, new Date()).length, 0);
  });

  it('open now uses Minsk weekly hours', () => {
    const { filterShopCatalog, shopMatchesHours } = loadModel();
    const mondayNoon = new Date('2026-10-05T09:00:00Z'); // 12:00 Minsk Monday
    assert.equal(shopMatchesHours(shops[0], { shopOpenNow: true }, mondayNoon), true);
    assert.equal(shopMatchesHours(shops[1], { shopOpenNow: true }, mondayNoon), true);
    const filtered = filterShopCatalog(shops, { shopOpenNow: true }, mondayNoon);
    assert.equal(filtered.length, 2);
  });

  it('shopMapToolbarLabel summarizes active filters on map', () => {
    const { shopMapToolbarLabel } = loadModel();
    assert.equal(shopMapToolbarLabel({}), 'Все магазины');
    assert.equal(
      shopMapToolbarLabel({ shopService: 'skate_sharpening', shopOpenNow: true }),
      'Заточка · ещё 1'
    );
  });

  it('shopMapResultsCta — кнопка «Готово» на карте', () => {
    const { shopMapResultsCta } = loadModel();
    assert.equal(shopMapResultsCta(0), 'Нет магазинов по фильтру');
    assert.match(shopMapResultsCta(4), /Показать 4 магазина/);
  });

  it('persists shop filter fields in session state', () => {
    const { saveIceState, loadIceState, ICE_STATE_KEY } = loadModel();
    const mem = {};
    const storage = {
      getItem: (k) => (k in mem ? mem[k] : null),
      setItem: (k, v) => {
        mem[k] = String(v);
      },
    };
    saveIceState(
      { intent: 'skate', shopService: 'retail', shopDiscipline: '', shopOpenNow: true, shopWhen: 'evening' },
      storage
    );
    const loaded = loadIceState(storage);
    assert.equal(loaded.shopService, 'retail');
    assert.equal(loaded.shopOpenNow, true);
    assert.equal(loaded.shopWhen, 'evening');
  });

  it('persists ice when filter in session state', () => {
    const { saveIceState, loadIceState } = loadModel();
    const mem = {};
    const storage = {
      getItem: (k) => (k in mem ? mem[k] : null),
      setItem: (k, v) => {
        mem[k] = String(v);
      },
    };
    saveIceState({ intent: 'skate', when: 'tomorrow', whenDay: '' }, storage);
    const loaded = loadIceState(storage);
    assert.equal(loaded.when, 'tomorrow');
    assert.equal(loaded.whenDay, '');
  });
});

describe('«Ближе» без геолокации', () => {
  it('при выбранном городе не зовёт менять город', () => {
    const { formatNearGeoBlockedMessage } = loadModel();
    const msg = formatNearGeoBlockedMessage({
      cityId: 1,
      cityName: 'Минск',
      reason: 'denied',
    });
    assert.match(msg, /Минск/);
    assert.match(msg, /менять его не нужно/);
    assert.ok(!/Выберите город/.test(msg));
  });

  it('без города предлагает выбрать город', () => {
    const { formatNearGeoBlockedMessage } = loadModel();
    const msg = formatNearGeoBlockedMessage({ reason: 'unsupported' });
    assert.match(msg, /Выберите город/);
  });
});

describe('buildListUrl (epic 2026-09-05 skate filter)', () => {
  it('«Где заниматься» asks the API for intent=skate; does not invent tiers', () => {
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

  it('prefers the street address over district when both are present', () => {
    const { formatMeta } = loadModel();
    assert.equal(
      formatMeta({ district: 'Центр', address: 'пр. Добролюбова, 18', distance_km: 1.2 }),
      'пр. Добролюбова, 18 · 1,2 км'
    );
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
  it('skate empty does not dump a catalog-moved banner into the list', () => {
    const { formatEmptyList } = loadModel();
    const empty = formatEmptyList('skate');
    assert.match(empty.title, /массового катания|катков/i);
    assert.ok(!/каталог тренеров теперь здесь/i.test(empty.title + empty.body));
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

  it('coach empty does not point at a hidden skate chip', () => {
    const { formatEmptyList } = loadModel();
    const noSkate = formatEmptyList('coach', { hasSkate: false });
    assert.ok(!/Где заниматься/i.test(noSkate.title + noSkate.body));
    assert.notEqual(noSkate.action && noSkate.action.kind, 'intent:skate');
    const withSkate = formatEmptyList('coach', { hasSkate: true });
    assert.equal(withSkate.action.kind, 'intent:skate');
  });

  it('shows coming-soon when the city has trainers but no map rinks', () => {
    const { formatEmptyList } = loadModel();
    const empty = formatEmptyList('skate', { trainerCount: 3, mapRinkCount: 0 });
    assert.equal(empty.kind, 'coming-soon');
    assert.match(empty.title, /скоро/i);
    assert.match(empty.cta, /кататься/i);
    assert.equal(formatEmptyList('skate', { trainerCount: 0, mapRinkCount: 0 }).kind, undefined);
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
    assert.equal(grouped[0].label, 'Места');
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

describe('rankServiceChips (2026-09-07 Тренеры service filter)', () => {
  it('drops services with zero bookable trainers in the current city', () => {
    const { rankServiceChips } = loadModel();
    const ranked = rankServiceChips([
      { id: 1, name: 'Обучение катанию «с нуля»', sort_order: 0, trainer_count: 2 },
      { id: 2, name: 'Совершенствование катания', sort_order: 1, trainer_count: 0 },
      { id: 3, name: 'Фигурное катание', sort_order: 2, trainer_count: 1 },
    ]);
    assert.deepEqual(ranked.map((s) => s.id), [1, 3]);
  });

  it('orders by sort_order then id', () => {
    const { rankServiceChips } = loadModel();
    const ranked = rankServiceChips([
      { id: 9, name: 'B', sort_order: 5, trainer_count: 1 },
      { id: 2, name: 'A', sort_order: 1, trainer_count: 1 },
    ]);
    assert.deepEqual(ranked.map((s) => s.id), [2, 9]);
  });

  it('buildTrainersUrl sends several services as service_ids (any-of)', () => {
    const { buildTrainersUrl } = loadModel();
    const url = buildTrainersUrl({ cityId: 2, serviceIds: [3, 5] });
    assert.match(url, /service_ids=3,5/);
    assert.doesNotMatch(url, /[?&]service_id=/);
    assert.doesNotMatch(buildTrainersUrl({ cityId: 2, serviceIds: [] }), /service_ids?=/);
  });

  it('buildTrainersUrl carries service_id only when set', () => {
    const { buildTrainersUrl } = loadModel();
    assert.match(buildTrainersUrl({ cityId: 2, serviceId: 3 }), /service_id=3/);
    assert.doesNotMatch(buildTrainersUrl({ cityId: 2 }), /service_id=/);
  });
});

describe('rankPopularCities (2026-09-07 city picker redesign)', () => {
  it('ranks by map rinks + trainers so a long city list surfaces the busy ones first', () => {
    const { rankPopularCities } = loadModel();
    const ranked = rankPopularCities([
      { id: 1, name: 'Минск', map_rink_count: 5, trainer_count: 6, sort_order: 0 },
      { id: 2, name: 'Раубичи', map_rink_count: 0, trainer_count: 0, sort_order: 29 },
      { id: 3, name: 'Гродно', map_rink_count: 2, trainer_count: 0, sort_order: 16 },
    ]);
    assert.deepEqual(ranked.map((c) => c.id), [1, 3, 2]);
  });

  it('caps the result so the picker never shows a wall of chips', () => {
    const { rankPopularCities } = loadModel();
    const cities = Array.from({ length: 25 }, (_, i) => ({
      id: i + 1,
      name: 'City ' + i,
      map_rink_count: 25 - i,
      trainer_count: 0,
    }));
    assert.equal(rankPopularCities(cities, 8).length, 8);
    assert.equal(rankPopularCities(cities).length, 8);
  });

  it('ties break by sort_order then id, never by insertion order alone', () => {
    const { rankPopularCities } = loadModel();
    const ranked = rankPopularCities([
      { id: 9, name: 'B', map_rink_count: 0, trainer_count: 0, sort_order: 5 },
      { id: 2, name: 'A', map_rink_count: 0, trainer_count: 0, sort_order: 1 },
    ]);
    assert.deepEqual(ranked.map((c) => c.id), [2, 9]);
  });
});

describe('hrefs', () => {
  it('arena rows open the TASK-052 card by slug or id', () => {
    const { arenaHref } = loadModel();
    // TASK-146: id важнее slug — slug уникален только в городе, а поиск идёт по стране.
    assert.equal(arenaHref({ slug: 'minsk-chizhovka', id: 12 }), 'arena?ref=12');
    assert.equal(arenaHref({ slug: 'minsk-chizhovka' }), 'arena?ref=minsk-chizhovka');
    assert.equal(arenaHref({ id: 12 }), 'arena?ref=12');
    // Карточка открывается на дне и сеансе с плитки ленты (выбрал «Завтра» — попал на завтра).
    assert.equal(
      arenaHref({ id: 12, live: { kind: 'session', local_date: '2026-10-03', session_id: 77 } }),
      'arena?ref=12&day=2026-10-03&s=77',
    );
    assert.equal(arenaHref({ id: 12, live: { kind: 'place', text: 'Заточка' } }), 'arena?ref=12');
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

describe('skate lens list rows', () => {
  it('MK list rows are read-only — no Записаться CTA', () => {
    const { listRowCta } = loadModel();
    assert.equal(listRowCta({ live: { kind: 'session' } }), null);
    assert.equal(listRowCta({ live: { kind: 'public_skate' } }), null);
    assert.equal(listRowCta({ live: { kind: 'open_ice' } }), null);
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

  it('prefers same-origin proxy over a CDN list_url that 404s in Mini App', () => {
    const { trainerCardView } = loadModel();
    const view = trainerCardView({
      ...trainer,
      photos: [
        {
          file_key: 'trainers/9/full.jpg',
          file_key_list: 'trainers/9/list.jpg',
          list_url: 'https://cdn.example/broken.jpg',
          url: 'https://cdn.example/broken-full.jpg',
        },
      ],
    });
    assert.equal(view.thumb, '/api/public/photos/trainers%2F9%2Flist.jpg');
  });

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

describe('group chip visibility', () => {
  it('hides Группы until the city has at least one open group', () => {
    const { shouldShowGroupChip, sanitizeIntent, buildGroupsProbeUrl } = loadModel();
    assert.equal(shouldShowGroupChip(0), false);
    assert.equal(shouldShowGroupChip(null), false);
    assert.equal(shouldShowGroupChip(2), true);
    assert.equal(sanitizeIntent('group', { hasGroups: false }), 'skate');
    assert.equal(sanitizeIntent('group', { hasGroups: true }), 'group');
    assert.equal(sanitizeIntent('coach', { hasGroups: false }), 'coach');
    assert.match(buildGroupsProbeUrl({ cityId: 2 }), /\/api\/public\/training-groups/);
  });
});

describe('skate chip visibility (2026-09-07 cities without a live rink)', () => {
  it('stays visible until probed, then hides once the city has zero skate arenas', () => {
    const { shouldShowSkateChip } = loadModel();
    assert.equal(shouldShowSkateChip(null), true);
    assert.equal(shouldShowSkateChip(undefined), true);
    assert.equal(shouldShowSkateChip(0), false);
    assert.equal(shouldShowSkateChip(3), true);
  });

  it('falls back «Где заниматься» -> Тренеры when the city has no skate arenas', () => {
    const { sanitizeIntent } = loadModel();
    assert.equal(sanitizeIntent('skate', { hasSkate: false }), 'coach');
    assert.equal(sanitizeIntent('skate', { hasSkate: true }), 'skate');
    assert.equal(sanitizeIntent(undefined, { hasSkate: false }), 'coach');
    assert.equal(sanitizeIntent('coach', { hasSkate: false }), 'coach');
    assert.equal(sanitizeIntent('group', { hasGroups: true, hasSkate: false }), 'group');
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
      {
        intent: 'coach',
        cityId: 5,
        cityName: 'Гродно',
        serviceId: 3,
        venueTypes: ['shop', 'SHOP', 'nope'],
        scrollY: 420,
        view: 'map',
      },
      storage
    );
    assert.ok(mem[ICE_STATE_KEY]);
    const loaded = loadIceState(storage);
    assert.equal(loaded.intent, 'coach');
    assert.equal(loaded.cityId, 5);
    assert.equal(loaded.cityName, 'Гродно');
    assert.equal(loaded.serviceId, 3);
    assert.deepEqual(loaded.venueTypes, ['shop']);
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
      {
        id: 9,
        name: 'Юность',
        district: 'Центральный район',
        tier: 'B',
        venue_cta: 'Открыть карточку катка',
        live: { kind: 'unknown' },
      },
      now
    );
    assert.equal(v.isSession, false);
    assert.equal(v.time, '');
    assert.ok(v.status.length > 0);
    assert.equal(v.depth, 'Открыть карточку катка');
  });

  it('зал не называется катком: подпись берётся из venue_cta сервера', () => {
    // Регрессия площадки #201 «Lifestyle»: тренажёрный зал в списке предлагал
    // «Открыть карточку катка». Склонение по типу считает сервер (venue_types.py),
    // здесь только проверяем, что модель его не перетирает хардкодом.
    const { boardCardView } = loadModel();
    const v = boardCardView(
      {
        id: 201,
        name: 'Lifestyle',
        tier: 'C',
        venue_type: 'gym',
        venue_cta: 'Открыть карточку зала',
        live: { kind: 'unknown' },
      },
      now
    );
    assert.equal(v.depth, 'Открыть карточку зала');
    assert.ok(!v.depth.includes('катк'));
  });

  it('ответ старого API без venue_cta не показывает «катка» наугад', () => {
    const { boardCardView } = loadModel();
    const v = boardCardView({ id: 9, name: 'Без типа', live: { kind: 'unknown' } }, now);
    assert.equal(v.depth, 'Открыть карточку места');
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
    // 10.09.2026 — четверг: под чипом «Выходные» голая дата не говорит, суббота ли это.
    assert.equal(boardCardView(later, now).day, 'Чт, 10.09');
  });

  it('«Сегодня» считается по Europe/Minsk, не по UTC-календарю', () => {
    const { boardCardView, sessionDayLabel } = loadModel();
    const afterUtcMidnight = new Date('2026-09-06T22:10:00Z');
    const minskToday = Object.assign({}, sessionItem, {
      live: Object.assign({}, sessionItem.live, {
        local_date: '2026-09-07',
        starts_at_local: '12:15',
      }),
    });
    assert.equal(boardCardView(minskToday, afterUtcMidnight).day, 'Сегодня');
    assert.equal(
      sessionDayLabel({ local_date: '2026-09-06' }, afterUtcMidnight),
      'Вс, 06.09'
    );
  });
});

describe('listPaintMode (lens switch must not re-skin leftover cards)', () => {
  it('shows trainer skeletons while skate rows are still in memory', () => {
    const { listPaintMode } = loadModel();
    assert.equal(
      listPaintMode({
        loading: true,
        intent: 'coach',
        loadedIntent: 'skate',
        items: [{ id: 3, name: 'ТЦ Замок', tier: 'A' }],
      }),
      'skeleton'
    );
  });

  it('does not paint leftover rows when loadedIntent was already cleared', () => {
    const { listPaintMode } = loadModel();
    assert.equal(
      listPaintMode({
        loading: true,
        intent: 'coach',
        loadedIntent: null,
        items: [{ id: 3, name: 'ТЦ Замок', tier: 'A' }],
      }),
      'skeleton'
    );
  });

  it('keeps live cards on a same-lens refresh', () => {
    const { listPaintMode } = loadModel();
    assert.equal(
      listPaintMode({
        loading: true,
        intent: 'skate',
        loadedIntent: 'skate',
        items: [{ id: 3, tier: 'A' }],
      }),
      'items'
    );
  });
});

describe('listHostId (skate boards and trainer rows are different DOM hosts)', () => {
  it('keeps катки and тренеры in separate list elements', () => {
    const { listHostId } = loadModel();
    assert.equal(listHostId('skate'), 'iceListSkate');
    assert.equal(listHostId('group'), 'iceListSkate');
    assert.equal(listHostId('coach'), 'iceListCoach');
  });
});

describe('formatSortCaption во время загрузки (TASK-095)', () => {
  it('пока идёт запрос, подпись не объявляет пустой результат', () => {
    const { formatSortCaption } = loadModel();
    assert.equal(formatSortCaption({ total: 0, items: [], intent: 'skate', loading: true }), 'Ищем катки…');
    assert.equal(formatSortCaption({ total: 0, items: [], intent: 'coach', loading: true }), 'Ищем тренеров…');
  });

  it('смена линзы не оставляет подпись «N катков» над скелетоном тренеров', () => {
    const { formatSortCaption } = loadModel();
    assert.equal(
      formatSortCaption({
        total: 4,
        items: [{ tier: 'A' }],
        intent: 'coach',
        loadedIntent: 'skate',
        loading: true,
      }),
      'Ищем тренеров…'
    );
  });

  it('после ответа пустой результат называется своим именем', () => {
    const { formatSortCaption } = loadModel();
    assert.match(formatSortCaption({ total: 0, items: [], intent: 'skate' }), /Пока нет катков/);
  });

  it('загрузка с уже показанными карточками не стирает счётчик', () => {
    const { formatSortCaption } = loadModel();
    const caption = formatSortCaption({ total: 5, items: [{ tier: 'A' }], intent: 'skate', loading: true });
    assert.match(caption, /^5 катков/);
  });
});

describe('TASK-146: подпись и строка ленты для магазинов и залов', () => {
  it('считает магазины магазинами, а не катками', () => {
    const { formatSortCaption } = loadModel();
    const shops = [{ venue_type: 'shop', tier: 'B' }];
    assert.equal(formatSortCaption({ total: 1, items: shops, intent: 'skate' }), '1 магазин');
    assert.equal(
      formatSortCaption({ total: 0, items: [], intent: 'skate', venueTypes: ['shop'] }),
      'Пока нет магазинов · смените город или чип'
    );
    const gyms = [{ venue_type: 'gym' }, { venue_type: 'choreo' }];
    assert.equal(formatSortCaption({ total: 2, items: gyms, intent: 'skate' }), '2 зала');
    const mixed = [{ venue_type: 'ice' }, { venue_type: 'gym' }, { venue_type: 'pool' }];
    assert.equal(formatSortCaption({ total: 3, items: mixed, intent: 'skate' }), '3 места');
  });

  it('лёд по-прежнему — катки с расписанием', () => {
    const { formatSortCaption } = loadModel();
    assert.equal(
      formatSortCaption({ total: 2, items: [{ venue_type: 'ice', tier: 'B' }, {}], intent: 'skate' }),
      '2 катка · расписание уточняется'
    );
  });
});

describe('TASK-146: строка ленты места без сеансов', () => {
  it('магазин показывает услуги и часы, а не «расписание уточняется»', () => {
    const { formatLiveLine } = loadModel();
    const line = formatLiveLine({ tier: 'B', live: { kind: 'place', text: 'Розница · Заточка · ежедневно 10:00–20:00' } });
    assert.equal(line, 'Розница · Заточка · ежедневно 10:00–20:00');
  });
});

describe('TASK-146 (Q-006): окно времени', () => {
  it('auto подсвечивает окно, выбранное сервером; явный выбор — его', () => {
    const { whenChipsView } = loadModel();
    const auto = whenChipsView('auto', 'weekend');
    assert.deepEqual(auto.filter((c) => c.active).map((c) => c.key), ['weekend']);
    const manual = whenChipsView('tomorrow', 'weekend');
    assert.deepEqual(manual.filter((c) => c.active).map((c) => c.key), ['tomorrow']);
  });

  it('чипы времени — только про лёд', () => {
    const { whenChipsVisible } = loadModel();
    assert.equal(whenChipsVisible('skate', []), true);
    assert.equal(whenChipsVisible('skate', ['shop']), false);
    assert.equal(whenChipsVisible('coach', []), false);
  });

  it('TASK-149: whenFromSearch — ровно ключи сервера (WHEN_KEYS в ice_time_windows.py)', () => {
    const { whenFromSearch } = loadModel();
    for (const key of ['auto', 'today_evening', 'today', 'tomorrow', 'weekend', 'any']) {
      assert.equal(whenFromSearch('?when=' + key), key);
    }
  });

  it('TASK-149: whenFromSearch — мусор, пустое и неизвестное дают null, не ошибку', () => {
    const { whenFromSearch } = loadModel();
    assert.equal(whenFromSearch(''), null);
    assert.equal(whenFromSearch(null), null);
    assert.equal(whenFromSearch(undefined), null);
    assert.equal(whenFromSearch('?'), null);
    assert.equal(whenFromSearch('?when='), null);
    assert.equal(whenFromSearch('?when=%20%20'), null);
    assert.equal(whenFromSearch('?when=junk'), null);
    assert.equal(whenFromSearch('?when=tonight'), null);
    assert.equal(whenFromSearch('?when=today_evening;drop'), null);
    assert.equal(whenFromSearch('?when=%E0%A4%A'), null);
    assert.equal(whenFromSearch('?intent=coach'), null);
  });

  it('TASK-149: whenFromSearch — регистр и пробелы нормализуются, как на сервере', () => {
    const { whenFromSearch } = loadModel();
    assert.equal(whenFromSearch('?when=TODAY_EVENING'), 'today_evening');
    assert.equal(whenFromSearch('?when=Weekend'), 'weekend');
    assert.equal(whenFromSearch('?when=%20tomorrow%20'), 'tomorrow');
    assert.equal(whenFromSearch('when=any'), 'any');
  });

  it('TASK-149: whenFromSearch читает своё поле независимо от intent/venue/city_id', () => {
    const { whenFromSearch, intentFromSearch, venueFromSearch, cityIdFromSearch } = loadModel();
    const s = '?city_id=7&intent=skate&venue=ice&when=today_evening';
    assert.equal(whenFromSearch(s), 'today_evening');
    assert.equal(intentFromSearch(s), 'skate');
    assert.equal(venueFromSearch(s), 'ice');
    assert.equal(cityIdFromSearch(s), 7);
    assert.equal(whenFromSearch('?city_id=7&intent=coach&venue=shop'), null);
  });

  it('TASK-149: применённое из ссылки окно подсвечивает свой чип; чипа «Сегодня» нет — не подсвечено ничего', () => {
    const { whenChipsView, whenFromSearch } = loadModel();
    const evening = whenChipsView(whenFromSearch('?when=today_evening'), 'tomorrow');
    assert.deepEqual(evening.filter((c) => c.active).map((c) => c.key), ['today_evening']);
    const today = whenChipsView(whenFromSearch('?when=today'), 'today');
    assert.deepEqual(today.filter((c) => c.active).map((c) => c.key), []);
  });

  it('подпись честна, когда в окне пусто', () => {
    const { formatSortCaption, buildListUrl } = loadModel();
    const items = [{ venue_type: 'ice', tier: 'A' }, { venue_type: 'ice', tier: 'A' }];
    assert.equal(
      formatSortCaption({ total: 2, items, intent: 'skate', window: { label: 'Сегодня вечером', hits: 0 } }),
      'Сегодня вечером сеансов нет · показываем ближайшие'
    );
    assert.equal(
      formatSortCaption({ total: 2, items, intent: 'skate', window: { label: 'Выходные', hits: 1 } }),
      '2 катка · выходные'
    );
    assert.match(buildListUrl({ cityId: 1, intent: 'skate', when: 'auto' }), /when=auto/);
  });

  it('whenMenuView: нет субботы в строках, выходные отдельно', () => {
    const { whenMenuView } = loadModel();
    const now = new Date('2026-10-04T09:00:00Z'); // вс
    const view = whenMenuView({ when: 'auto', whenDay: '', resolvedKey: 'weekend', now, menuExpanded: false });
    const dayRows = view.rows.filter((r) => r.kind === 'day');
    assert.equal(dayRows.length, 2, 'завтра + один будний');
    assert.ok(dayRows.every((r) => !/Сб|Вс/.test(r.label) || r.label === 'Завтра'));
    assert.deepEqual(view.anchors.map((a) => a.id), ['weekend', 'any']);
  });

  it('buildListUrl: конкретный день — day=, не when=', () => {
    const { buildListUrl } = loadModel();
    const url = buildListUrl({ cityId: 1, intent: 'skate', when: 'day', whenDay: '2026-10-08' });
    assert.match(url, /day=2026-10-08/);
    assert.doesNotMatch(url, /when=/);
  });

  it('whenBootFromSearch читает day= и when=', () => {
    const { whenBootFromSearch } = loadModel();
    assert.deepEqual(whenBootFromSearch('?day=2026-10-08'), { when: 'day', whenDay: '2026-10-08' });
    assert.deepEqual(whenBootFromSearch('?when=weekend'), { when: 'weekend', whenDay: '' });
  });

  it('hydrateWhenFromSaved — только лёд, валидные ключи', () => {
    const { hydrateWhenFromSaved } = loadModel();
    assert.deepEqual(hydrateWhenFromSaved({ when: 'tomorrow' }, 'skate', []), {
      when: 'tomorrow',
      whenDay: '',
    });
    assert.equal(hydrateWhenFromSaved({ when: 'tomorrow' }, 'coach', []), null);
    assert.equal(hydrateWhenFromSaved({ when: 'nope' }, 'skate', []), null);
  });
});

describe('TASK-146: окно сортирует, а не фильтрует — две группы карточек', () => {
  const win = { key: 'tomorrow', label: 'Завтра', hits: 1 };
  const now = new Date('2026-10-02T08:00:00Z'); // пятница, Минск
  const hit = { id: 1, name: 'Чижовка', venue_type: 'ice', distance_km: 9,
    live: { kind: 'session', local_date: '2026-10-03', starts_at_local: '12:00', session_id: 11 } };
  const off = { id: 2, name: 'ТЦ Замок', venue_type: 'ice', distance_km: 2,
    live: { kind: 'session', outside_window: true, local_date: '2026-10-02', starts_at_local: '16:15', session_id: 22 } };
  const unknown = { id: 3, name: 'Юность', venue_type: 'ice', distance_km: 1, live: { kind: 'unknown' } };

  it('в окне — сеанс без outside_window; без сеанса (unknown) — в основной ленте', () => {
    const { splitByWindow } = loadModel();
    const parts = splitByWindow([off, hit, unknown], win);
    assert.deepEqual(parts.hits.map((i) => i.id), [1, 3]);
    assert.deepEqual(parts.rest.map((i) => i.id), [2]);
    assert.equal(splitByWindow([off, unknown], null).rest.length, 0, 'без окна делить нечего');
  });

  it('карточка вне окна говорит «Завтра нет · ближайший», а не выдаёт «Сегодня» за ответ', () => {
    const { boardCardView } = loadModel();
    const v = boardCardView(off, now, { window: win });
    assert.equal(v.offWindow, true);
    assert.equal(v.offLabel, 'Завтра нет · ближайший');
    assert.equal(v.day, 'Сегодня');
    assert.equal(boardCardView(hit, now, { window: win }).offWindow, false);
    assert.equal(boardCardView(off, now).offWindow, false, 'без окна приглушать нечего');
  });

  it('разделитель называет окно и число мест ниже', () => {
    const { windowBreakView } = loadModel();
    assert.deepEqual(windowBreakView({ key: 'weekend', label: 'Выходные' }, [off]), {
      title: 'На выходных нет',
      sub: '1 каток · их ближайшее время',
    });
    assert.equal(windowBreakView(win, []), null);
  });

  it('строка ленты и шторка карты помечают сеанс вне окна как ближайший', () => {
    const { formatLiveLine } = loadModel();
    assert.match(formatLiveLine(off, now), /^Ближайший: Сегодня 16:15/);
    assert.match(formatLiveLine(hit, now), /^Завтра 12:00/);
  });

  it('«Рядом» сортирует по расстоянию внутри групп, а не смешивает их', () => {
    const { orderForFeed } = loadModel();
    const far = Object.assign({}, hit, { id: 4, distance_km: 20 });
    const parts = orderForFeed([far, off, unknown, hit], win, true);
    assert.deepEqual(parts.hits.map((i) => i.id), [3, 1, 4]);
    assert.deepEqual(parts.rest.map((i) => i.id), [2]);
    const asServer = orderForFeed([far, off, unknown, hit], win, false);
    assert.deepEqual(asServer.hits.map((i) => i.id), [4, 3, 1], 'без «Рядом» — порядок сервера');
  });
});

describe('TASK-180: устаревшее расписание в ленте', () => {
  it('schedule_stale помечает карточку и подпись глубины', () => {
    const { boardCardView } = loadModel();
    const item = { id: 1, name: 'Каток', live: { kind: 'session', local_date: '2026-10-02', starts_at_local: '18:00', more_count: 5, session_id: 3 } };
    const now = new Date('2026-10-02T10:00:00Z');
    const v = boardCardView(
      { ...item, freshness: { schedule_stale: true, schedule_very_stale: false } },
      now,
      {}
    );
    assert.equal(v.stale, true);
    assert.match(v.depth, /могло измениться/);
    assert.match(v.depth, /сеанс/);
  });
});

describe('TASK-180: очень устаревшее расписание в ленте (> 72 ч)', () => {
  const now = new Date('2026-10-06T10:00:00Z');
  const base = {
    id: 1,
    name: 'Каток',
    tier: 'A',
    phone: '+375 17 000-00-00',
    live: {
      kind: 'session',
      session_id: 3,
      local_date: '2026-10-06',
      starts_at_local: '18:00',
      price_adult_minor: 1000,
      currency_code: 'BYN',
      more_count: 5,
    },
    freshness: {
      schedule_stale: true,
      schedule_very_stale: true,
      schedule_observed_at: '2026-10-02T09:00:00+00:00',
    },
  };

  it('старый ответ API (kind=session) не показывает день, время и цену как текущие', () => {
    const { boardCardView } = loadModel();
    const v = boardCardView(base, now, {});
    assert.equal(v.isSession, false);
    assert.equal(v.veryStale, true);
    assert.equal(v.day, '');
    assert.equal(v.time, '');
    assert.equal(v.prices, '');
    assert.equal(v.sessionId, null);
    assert.equal(v.status, 'Расписание не обновлялось 4 дня — уточните по телефону');
    assert.doesNotMatch(v.depth, /сеанс/);
  });

  it('kind=unconfirmed от сервера — берём его строку', () => {
    const { boardCardView, formatLiveLine } = loadModel();
    const item = {
      ...base,
      live: { kind: 'unconfirmed', text: 'Расписание не обновлялось 5 дней — уточните по телефону' },
    };
    const v = boardCardView(item, now, {});
    assert.equal(v.isSession, false);
    assert.equal(v.status, 'Расписание не обновлялось 5 дней — уточните по телефону');
    assert.equal(formatLiveLine(item, now), 'Расписание не обновлялось 5 дней — уточните по телефону');
  });

  it('не отвечает на выбранное окно и не помечается «могло измениться»', () => {
    const { boardCardView, splitByWindow } = loadModel();
    const parts = splitByWindow([base], 'today_evening');
    assert.equal(parts.hits.length, 0);
    assert.equal(parts.rest.length, 1);
    const v = boardCardView(base, now, {});
    assert.equal(v.stale, false);
    assert.doesNotMatch(v.depth, /могло измениться/);
  });

  it('formatLiveLine для сеанса с very_stale — строка «не обновлялось», без времени', () => {
    const { formatLiveLine } = loadModel();
    const line = formatLiveLine(base, now);
    assert.match(line, /не обновлялось 4 дня/);
    assert.doesNotMatch(line, /18:00/);
  });
});
