/**
 * TASK-052: arena card model — ribbon, prices, freshness, empty states.
 * Run: node --test tests/js/arena-card-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const stalePath = path.resolve(__dirname, '../../static/webapp/schedule-staleness-model.js');
const modelPath = path.resolve(
  __dirname,
  '../../static/webapp/arena-card-model.js'
);

function loadModel() {
  delete require.cache[require.resolve(stalePath)];
  require(stalePath);
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

describe('formatSessionPrices', () => {
  it('renders adult, child and rental as three prices, not one string from the API', () => {
    const { formatSessionPrices } = loadModel();
    const text = formatSessionPrices({
      price_adult_minor: 1200,
      price_child_minor: 800,
      price_rental_minor: 600,
      currency_code: 'BYN',
    });
    assert.match(text, /взр/);
    assert.match(text, /дет/);
    assert.match(text, /прокат/);
    assert.ok(!text.includes('12 / 8'));
    assert.ok(text.includes('12'));
    assert.ok(text.includes('8'));
    assert.ok(text.includes('6'));
  });

  it('says без проката when rental is missing', () => {
    const { formatSessionPrices } = loadModel();
    const text = formatSessionPrices({
      price_adult_minor: 2000,
      price_child_minor: null,
      price_rental_minor: null,
      currency_code: 'BYN',
    });
    assert.match(text, /без проката/);
    assert.match(text, /20/);
  });
});

describe('formatFreshness', () => {
  it('uses schedule_observed_at and source_label when both exist', () => {
    const { formatFreshness } = loadModel();
    const now = new Date('2026-09-06T12:00:00Z');
    const text = formatFreshness(
      {
        schedule_observed_at: '2026-09-04T10:00:00+00:00',
        source_label: 'сайт катка',
        source_url: 'https://rink.example',
      },
      now
    );
    assert.match(text, /2 дн/);
    assert.match(text, /сайт катка/);
  });

  it('does not invent a date when observed_at is missing', () => {
    const { formatFreshness } = loadModel();
    const text = formatFreshness(
      {
        schedule_observed_at: null,
        source_label: null,
        source_url: null,
      },
      new Date('2026-09-06T12:00:00Z')
    );
    assert.equal(text, null);
  });
});

describe('sessionNowState', () => {
  it('marks a session as live when now is between start and end', () => {
    const { sessionNowState } = loadModel();
    const state = sessionNowState(
      {
        starts_at_utc: '2026-09-06T10:00:00+00:00',
        ends_at_utc: '2026-09-06T11:00:00+00:00',
      },
      new Date('2026-09-06T10:30:00Z')
    );
    assert.equal(state, 'live');
  });

  it('marks a session as upcoming before start', () => {
    const { sessionNowState } = loadModel();
    const state = sessionNowState(
      {
        starts_at_utc: '2026-09-06T10:00:00+00:00',
        ends_at_utc: '2026-09-06T11:00:00+00:00',
      },
      new Date('2026-09-06T09:00:00Z')
    );
    assert.equal(state, 'upcoming');
  });

  it('is live at starts_at and past at ends_at (half-open interval)', () => {
    const { sessionNowState } = loadModel();
    const session = {
      starts_at_utc: '2026-09-06T10:00:00+00:00',
      ends_at_utc: '2026-09-06T11:00:00+00:00',
    };
    assert.equal(sessionNowState(session, new Date('2026-09-06T10:00:00Z')), 'live');
    assert.equal(sessionNowState(session, new Date('2026-09-06T11:00:00Z')), 'past');
  });
});

describe('buildRibbonForDay', () => {
  it('merges ice sessions and group lessons on one time axis', () => {
    const { buildRibbonForDay } = loadModel();
    const rows = buildRibbonForDay({
      localDate: '2026-09-06',
      sessions: [
        {
          id: 1,
          kind: 'public_skate',
          session_label: 'Массовое катание',
          starts_at_local: '11:00',
          starts_at_utc: '2026-09-06T08:00:00+00:00',
          ends_at_utc: '2026-09-06T09:00:00+00:00',
          price_adult_minor: 1200,
          price_child_minor: 800,
          price_rental_minor: 600,
          currency_code: 'BYN',
        },
      ],
      groups: [
        {
          id: 9,
          name: 'Первый лёд',
          trainer_id: 4,
          spots_left: 2,
          schedule_rules: [
            { day_of_week: 0, start_time: '17:30', duration_minutes: 45 },
          ],
        },
      ],
      weekday: 0,
      now: new Date('2026-09-06T06:00:00Z'),
    });
    assert.equal(rows.length, 2);
    assert.equal(rows[0].nature, 'ice');
    assert.equal(rows[0].stripe, 'ice');
    // Ни ссылки сеанса, ни кассы места — кнопки нет: «Билет на месте» было бы выдумкой.
    assert.equal(rows[0].cta, '');
    assert.equal(rows[0].href, null);
    assert.equal(rows[1].nature, 'lesson');
    assert.equal(rows[1].stripe, 'lesson');
    assert.equal(rows[1].cta, 'Заявка');
    assert.equal(rows[1].ctaKind, 'solid');
    assert.ok(rows[0].time < rows[1].time);
  });

  it('never puts Записаться on public_skate or open_ice, even with external_url', () => {
    const { buildRibbonForDay } = loadModel();
    ['public_skate', 'open_ice'].forEach((kind) => {
      const rows = buildRibbonForDay({
        localDate: '2026-09-06',
        sessions: [
          {
            id: 3,
            kind,
            starts_at_local: '11:00',
            starts_at_utc: '2026-09-06T08:00:00+00:00',
            ends_at_utc: '2026-09-06T09:00:00+00:00',
            price_adult_minor: 1200,
            price_child_minor: 800,
            price_rental_minor: 600,
            currency_code: 'BYN',
            external_url: 'https://rink.example/tickets',
            can_book: true,
          },
        ],
        groups: [],
        weekday: 0,
        now: new Date('2026-09-06T06:00:00Z'),
      });
      assert.equal(rows.length, 1);
      assert.equal(rows[0].nature, 'ice');
      assert.equal(rows[0].bookable, false);
      assert.equal(rows[0].ctaKind, 'link');
      assert.notEqual(rows[0].cta, 'Записаться');
      assert.ok(!/запис/i.test(rows[0].cta));
      assert.equal(rows[0].href, 'https://rink.example/tickets');
    });
  });

  it('drops an in-progress ice session from the ribbon (PDEC-005)', () => {
    const { buildRibbonForDay } = loadModel();
    const rows = buildRibbonForDay({
      localDate: '2026-09-06',
      sessions: [
        {
          id: 2,
          kind: 'open_ice',
          starts_at_local: '10:00',
          starts_at_utc: '2026-09-06T07:00:00+00:00',
          ends_at_utc: '2026-09-06T08:00:00+00:00',
          price_adult_minor: 2000,
          currency_code: 'BYN',
        },
      ],
      groups: [],
      weekday: 6,
      now: new Date('2026-09-06T07:20:00Z'),
    });
    assert.equal(rows.length, 0);
  });

  it('drops live and ended ice rows, keeps the next start', () => {
    const { buildRibbonForDay } = loadModel();
    const rows = buildRibbonForDay({
      localDate: '2026-09-06',
      sessions: [
        {
          id: 1,
          kind: 'public_skate',
          session_label: 'Утреннее МК',
          starts_at_local: '08:00',
          starts_at_utc: '2026-09-06T05:00:00+00:00',
          ends_at_utc: '2026-09-06T06:00:00+00:00',
          price_adult_minor: 1200,
          currency_code: 'BYN',
        },
        {
          id: 2,
          kind: 'public_skate',
          session_label: 'Массовое катание',
          starts_at_local: '10:00',
          starts_at_utc: '2026-09-06T07:00:00+00:00',
          ends_at_utc: '2026-09-06T08:00:00+00:00',
          price_adult_minor: 1200,
          currency_code: 'BYN',
        },
        {
          id: 3,
          kind: 'open_ice',
          session_label: 'Свободный лёд',
          starts_at_local: '19:00',
          starts_at_utc: '2026-09-06T16:00:00+00:00',
          ends_at_utc: '2026-09-06T17:00:00+00:00',
          price_adult_minor: 2000,
          currency_code: 'BYN',
        },
      ],
      groups: [],
      weekday: 6,
      now: new Date('2026-09-06T07:20:00Z'),
    });
    assert.equal(rows.length, 1);
    assert.equal(rows[0].nowState, 'upcoming');
    assert.equal(rows[0].title, 'Свободный лёд');
    assert.ok(!/идёт/i.test(rows[0].meta));
  });
});

describe('ribbonLegend', () => {
  it('matches the prototype legend under the ribbon', () => {
    const { ribbonLegend } = loadModel();
    const items = ribbonLegend();
    assert.equal(items.length, 2);
    assert.equal(items[0].nature, 'ice');
    assert.equal(items[0].stripe, 'ice');
    assert.match(items[0].text, /открытый лёд/);
    assert.match(items[0].text, /информац/);
    assert.equal(items[1].nature, 'lesson');
    assert.equal(items[1].stripe, 'lesson');
    assert.match(items[1].text, /занятие/);
    assert.match(items[1].text, /записаться/i);
  });
});

describe('buildWeekSummaries', () => {
  it('shows Данных нет for a weekday with no sessions or lessons', () => {
    const { buildWeekSummaries } = loadModel();
    const days = buildWeekSummaries({
      from: '2026-09-07',
      to: '2026-09-10',
      sessionDays: [
        { local_date: '2026-09-07', sessions: [{ id: 1 }, { id: 2 }] },
      ],
      groups: [],
    });
    const empty = days.find((d) => d.localDate === '2026-09-08');
    assert.ok(empty);
    assert.equal(empty.empty, true);
    assert.equal(empty.title, 'Данных нет');
  });
});

describe('heroPhotoUrl', () => {
  it('returns null when there is no hero so the UI can show a placeholder', () => {
    const { heroPhotoUrl } = loadModel();
    assert.equal(heroPhotoUrl({ hero: null, gallery: [] }), null);
    assert.equal(heroPhotoUrl({}), null);
  });

  it('prefers the list card frame, then thumb, then hero', () => {
    const { heroPhotoUrl, heroPhotoUrls } = loadModel();
    assert.equal(
      heroPhotoUrl({
        hero: { variants: { thumb: '/t.jpg', hero: '/h.jpg', card: '/c.jpg' } },
      }),
      '/c.jpg'
    );
    assert.deepEqual(
      heroPhotoUrls({
        hero: { variants: { thumb: '/t.jpg', hero: '/h.jpg', card: '/c.jpg' } },
      }),
      ['/c.jpg', '/t.jpg', '/h.jpg']
    );
  });

  it('still shows a photo when only the thumb variant exists', () => {
    const { heroPhotoUrl } = loadModel();
    assert.equal(heroPhotoUrl({ hero: { variants: { thumb: '/t.jpg' } } }), '/t.jpg');
  });

  it('puts the mini-card photo first when we already showed it', () => {
    const { heroPhotoUrls } = loadModel();
    assert.deepEqual(
      heroPhotoUrls(
        { hero: { variants: { thumb: '/t.jpg', hero: '/h.jpg', card: '/c.jpg' } } },
        '/t.jpg'
      ),
      ['/t.jpg', '/c.jpg', '/h.jpg']
    );
  });
});

describe('heroView', () => {
  it('uses placeholder mode when there is no hero photo', () => {
    const { heroView } = loadModel();
    const view = heroView({ hero: null, gallery: [] });
    assert.equal(view.mode, 'placeholder');
    assert.equal(view.url, null);
  });

  it('uses photo mode when a hero variant exists', () => {
    const { heroView } = loadModel();
    const view = heroView({
      hero: { variants: { hero: '/h.jpg' } },
    });
    assert.equal(view.mode, 'photo');
    assert.equal(view.url, '/h.jpg');
    assert.deepEqual(view.urls, ['/h.jpg']);
  });

  it('prefetch record is the list photo and matches id or slug', () => {
    const { heroPrefetchRecord, heroPrefetchMatches } = loadModel();
    const rec = heroPrefetchRecord({
      id: 3,
      slug: 'tc-zamok',
      card: '/c.jpg',
      thumb: '/t.jpg',
    });
    assert.deepEqual(rec, { id: 3, slug: 'tc-zamok', url: '/c.jpg' });
    assert.equal(heroPrefetchMatches(rec, '3'), true);
    assert.equal(heroPrefetchMatches(rec, 'tc-zamok'), true);
    assert.equal(heroPrefetchMatches(rec, '9'), false);
    assert.equal(heroPrefetchRecord({ id: 1 }), null);
  });
});

describe('iceRowCta', () => {
  it('без ссылки — без кнопки; ничего не обещаем «на месте»', () => {
    const { iceRowCta } = loadModel();
    assert.deepEqual(iceRowCta({ kind: 'public_skate' }), { cta: '', ctaKind: '', href: null, bookable: false });
    assert.equal(iceRowCta({ kind: 'public_skate' }, 'javascript:alert(1)').href, null);
  });

  it('ссылка сеанса важнее общей кассы места; это ссылка, не запись', () => {
    const { iceRowCta } = loadModel();
    const linked = iceRowCta({ kind: 'open_ice', external_url: 'https://chizhovka.example/e/1' }, 'https://kassa.example');
    assert.equal(linked.cta, 'Билеты');
    assert.equal(linked.ctaKind, 'link');
    assert.equal(linked.bookable, false);
    assert.equal(linked.href, 'https://chizhovka.example/e/1');
    assert.equal(iceRowCta({ kind: 'public_skate' }, 'https://koronaticket.by/rink').href, 'https://koronaticket.by/rink');
  });

  it('касса места доходит до каждой строки ленты', () => {
    const { buildRibbonForDay } = loadModel();
    const rows = buildRibbonForDay({
      localDate: '2026-09-06',
      sessions: [{ kind: 'public_skate', local_date: '2026-09-06', starts_at_local: '20:15:00',
        starts_at_utc: '2026-09-06T17:15:00Z', ends_at_utc: '2026-09-06T18:00:00Z' }],
      groups: [],
      weekday: 6,
      now: new Date('2026-09-06T06:00:00Z'),
      ticketsUrl: 'https://koronaticket.by/rink',
    });
    assert.equal(rows[0].cta, 'Билеты');
    assert.equal(rows[0].href, 'https://koronaticket.by/rink');
  });
});

describe('ticketCta', () => {
  it('shows Купить билет only for an http(s) tickets_url', () => {
    const { ticketCta } = loadModel();
    assert.equal(ticketCta({}), null);
    assert.equal(ticketCta({ tickets_url: '  ' }), null);
    assert.equal(ticketCta({ tickets_url: 'javascript:alert(1)' }), null);
    assert.deepEqual(ticketCta({ tickets_url: 'https://koronaticket.by/rink' }), {
      href: 'https://koronaticket.by/rink',
      label: 'Купить билет',
    });
  });
});

describe('trainerCta', () => {
  it('uses Записаться only when can_book is true, otherwise Написать', () => {
    const { trainerCta } = loadModel();
    assert.deepEqual(trainerCta({ can_book: true }), {
      label: 'Записаться',
      kind: 'solid',
    });
    assert.deepEqual(trainerCta({ can_book: false }), {
      label: 'Написать',
      kind: 'ghost',
    });
  });
});

describe('buildBookingHref', () => {
  it('preselects this arena on the catalog booking path', () => {
    const { buildBookingHref } = loadModel();
    const href = buildBookingHref({ trainerId: 15, arenaId: 42 });
    assert.match(href, /catalog/);
    assert.match(href, /trainer_id=15/);
    assert.match(href, /arena_id=42/);
    assert.match(href, /from=arena/);
  });
});

describe('parseArenaRef', () => {
  it('reads ?ref= then start_param arena_*', () => {
    const { parseArenaRef } = loadModel();
    assert.equal(parseArenaRef('?ref=chizhovka', null), 'chizhovka');
    assert.equal(parseArenaRef('', 'arena_88'), '88');
    assert.equal(parseArenaRef('', 'arena_88_s_15'), '88');
    assert.equal(parseArenaRef('?arena_id=12', 'arena_other'), '12');
  });

  it('сеанс из start_param и день этого сеанса в ленте', () => {
    const { sessionIdFromStartParam, dayForSession } = loadModel();
    assert.equal(sessionIdFromStartParam('arena_88_s_15'), '15');
    assert.equal(sessionIdFromStartParam('arena_88'), null);
    assert.equal(
      dayForSession(
        [{ local_date: '2026-10-04', sessions: [{ id: 15 }] }, { local_date: '2026-10-05', sessions: [] }],
        '15'
      ),
      '2026-10-04'
    );
    assert.equal(dayForSession([{ local_date: '2026-10-04', sessions: [{ id: 1 }] }], '15'), null);
  });
});

describe('tierBlocks', () => {
  it('level B asks to уточняется with phone and site; C does not promise a schedule', () => {
    const { iceSectionMode } = loadModel();
    assert.equal(iceSectionMode({ tier: 'A', hasSessions: true }), 'ribbon');
    assert.equal(iceSectionMode({ tier: 'B', hasSessions: false }), 'pending');
    assert.equal(iceSectionMode({ tier: 'C', hasSessions: false }), 'none');
  });
});

describe('seasonClosedBanner', () => {
  it('wins over the ribbon when the arena is out of season', () => {
    const { seasonClosedBanner } = loadModel();
    const text = seasonClosedBanner({
      in_season: false,
      season_end_month: 4,
      season_start_month: 9,
    });
    assert.ok(text);
    assert.match(text, /закрыт до/i);
    assert.match(text, /сентября/);
  });

  it('is null while in season', () => {
    const { seasonClosedBanner } = loadModel();
    assert.equal(
      seasonClosedBanner({ in_season: true, season_start_month: 1, season_end_month: 12 }),
      null
    );
  });
});

describe('iceFeedView', () => {
  it('shows закрыт до above the feed and hides the ribbon even when sessions exist', () => {
    const { iceFeedView } = loadModel();
    const view = iceFeedView({
      card: { in_season: false, season_start_month: 9, tier: 'A' },
      hasSessions: true,
    });
    assert.equal(view.mode, 'closed');
    assert.equal(view.showRibbon, false);
    assert.match(view.banner, /закрыт до/i);
    assert.match(view.banner, /сентября/);
  });

  it('keeps the ribbon while the arena is in season and has sessions', () => {
    const { iceFeedView } = loadModel();
    const view = iceFeedView({
      card: { in_season: true, tier: 'A' },
      hasSessions: true,
    });
    assert.equal(view.mode, 'ribbon');
    assert.equal(view.showRibbon, true);
    assert.equal(view.banner, null);
  });
});

describe('amenityChips', () => {
  it('lists only true amenities with prototype labels', () => {
    const { amenityChips } = loadModel();
    const chips = amenityChips({
      skate_rental: true,
      skate_sharpening: true,
      parking: false,
      locker_rooms: true,
      cafe: true,
    });
    assert.deepEqual(chips, ['Прокат', 'Заточка', 'Раздевалки', 'Кафе']);
  });
});

describe('dayTabFromIso', () => {
  it('maps the clicked week date to today, tomorrow, or that ISO day', () => {
    const { dayTabFromIso } = loadModel();
    const today = '2026-09-06';
    assert.equal(dayTabFromIso('2026-09-06', today), 'today');
    assert.equal(dayTabFromIso('2026-09-07', today), 'tomorrow');
    assert.equal(dayTabFromIso('2026-09-10', today), '2026-09-10');
  });
});

describe('ribbonIsoForDay', () => {
  it('resolves today/tomorrow/week and a specific YYYY-MM-DD onto one local date', () => {
    const { ribbonIsoForDay } = loadModel();
    const today = '2026-09-06';
    assert.equal(ribbonIsoForDay('today', today), '2026-09-06');
    assert.equal(ribbonIsoForDay('tomorrow', today), '2026-09-07');
    assert.equal(ribbonIsoForDay('week', today), null);
    assert.equal(ribbonIsoForDay('2026-09-10', today), '2026-09-10');
  });
});

describe('practiceContacts', () => {
  it('exposes website, known socials, and short_description without inventing URLs', () => {
    const { practiceContacts } = loadModel();
    const filled = practiceContacts({
      website_url: 'https://chizhovka-arena.by/',
      venue_site_label: 'Сайт катка',
      short_description: 'Крытый каток в Чижовке.',
      social_urls: {
        instagram: 'https://instagram.com/chizhovka',
        facebook: 'https://facebook.com/chizhovka',
        vk: 'https://vk.com/chizhovka',
        telegram: 'https://t.me/chizhovka',
        youtube: 'https://youtube.com/should-not-show',
      },
    });
    assert.equal(filled.shortDescription, 'Крытый каток в Чижовке.');
    assert.deepEqual(filled.website, {
      href: 'https://chizhovka-arena.by/',
      label: 'Сайт катка',
    });
    // Подпись ссылки склоняет сервер по типу площадки: у зала это «Сайт зала».
    // Модель её не выдумывает — только подставляет нейтральный фолбэк, если
    // ответ пришёл от старого API без поля.
    assert.deepEqual(
      practiceContacts({ website_url: 'https://fitness-club.by/', venue_site_label: 'Сайт зала' })
        .website,
      { href: 'https://fitness-club.by/', label: 'Сайт зала' }
    );
    assert.equal(
      practiceContacts({ website_url: 'https://example.by/' }).website.label,
      'Сайт площадки'
    );
    assert.deepEqual(
      filled.socials.map((s) => s.key),
      ['instagram', 'facebook', 'vk', 'telegram']
    );
    assert.equal(filled.socials[0].href, 'https://instagram.com/chizhovka');
    assert.ok(!filled.socials.some((s) => s.key === 'youtube'));

    const empty = practiceContacts({
      website_url: '  ',
      short_description: '',
      social_urls: { instagram: '', facebook: null },
    });
    assert.equal(empty.website, null);
    assert.equal(empty.shortDescription, null);
    assert.deepEqual(empty.socials, []);
  });
});

describe('shareSlotsGrouped (TASK-158)', () => {
  it('группирует сеансы по дням для share sheet', () => {
    const { shareSlotsGrouped } = loadModel();
    const days = [
      {
        local_date: '2026-10-02',
        sessions: [
          { id: 1, starts_at_local: '19:00:00', price_adult_minor: 1100, currency_code: 'BYN' },
          { id: 2, starts_at_local: '21:00:00', price_adult_minor: 1100, currency_code: 'BYN' },
        ],
      },
      { local_date: '2026-10-03', sessions: [{ id: 3, starts_at_local: '11:00:00', price_adult_minor: 1100, currency_code: 'BYN' }] },
    ];
    const g = shareSlotsGrouped(days, '2026-10-02');
    assert.equal(g.length, 2);
    assert.equal(g[0].dayLabel, 'Сегодня');
    assert.equal(g[0].localDate, '2026-10-02');
    assert.equal(g[0].dayNum, '2');
    assert.deepEqual(g[0].rows.map((r) => r.time), ['19:00', '21:00']);
    assert.equal(g[0].rows[0].meta, '11 BYN');
    assert.equal(g[1].dayLabel, 'Завтра');
  });
});

describe('shareSlots (TASK-146)', () => {
  it('ближайшие сеансы с человеческими подписями и лимитом', () => {
    const { shareSlots } = loadModel();
    const days = [
      { local_date: '2026-10-02', sessions: [{ id: 1, starts_at_local: '19:00' }, { id: 2, starts_at_local: '20:45:00' }] },
      { local_date: '2026-10-03', sessions: [{ id: 3, starts_at_local: '11:00' }] },
      { local_date: '2026-10-04', sessions: [{ id: 4, starts_at_local: '18:30' }, { id: 5, starts_at_local: '' }] },
    ];
    assert.deepEqual(shareSlots(days, '2026-10-02', 3), [
      { id: 1, label: 'Сегодня 19:00', localDate: '2026-10-02', time: '19:00' },
      { id: 2, label: 'Сегодня 20:45', localDate: '2026-10-02', time: '20:45' },
      { id: 3, label: 'Завтра 11:00', localDate: '2026-10-03', time: '11:00' },
    ]);
    assert.deepEqual(shareSlots(days, '2026-10-02', 10).slice(-1), [
      { id: 4, label: 'Вс 18:30', localDate: '2026-10-04', time: '18:30' },
    ]);
    assert.deepEqual(shareSlots([], '2026-10-02'), []);
  });
});

describe('магазин и доверие (TASK-146)', () => {
  it('плитки услуг в порядке показа, специализация отдельно, false не рисуется', () => {
    const { shopServicesView } = loadModel();
    const v = shopServicesView({
      repair: true,
      retail: true,
      skate_molding: true,
      foot_scan: false,
      discipline_hockey: true,
      discipline_figure: false,
    });
    assert.deepEqual(v.tiles.map((t) => t.title), ['Розница', 'Формовка', 'Ремонт']);
    assert.deepEqual(v.disciplines, ['Хоккей']);
  });

  it('свежесть карточки без расписания — по последней правке; улица — про погоду', () => {
    const { trustLines } = loadModel();
    const now = new Date('2026-10-02T12:00:00Z');
    const shop = trustLines(
      { venue_type: 'shop', freshness: { profile_updated_at: '2026-09-29T10:00:00Z' } },
      now
    );
    assert.equal(shop.length, 1);
    assert.match(shop[0], /^Данные обновлены 3 дня назад$/);
    assert.deepEqual(trustLines({ venue_type: 'gym', freshness: {} }, now), [
      'Карточку собрала команда Glide по открытым данным',
    ]);
    const outdoor = trustLines({ venue_type: 'outdoor', freshness: { schedule_observed_at: '2026-10-02T08:00:00Z' } }, now);
    assert.deepEqual(outdoor, ['Открытый лёд зависит от погоды — уточняйте перед выездом']);
    const verified = trustLines(
      { venue_type: 'shop', freshness: { verified_at: '2026-09-06T10:00:00Z' } },
      now
    );
    assert.deepEqual(verified, ['Проверено командой Glide']);
  });
});

describe('formatChildTicketAgeNote', () => {
  it('добавляет «Детский билет» к голому возрастному лимиту и типовым формулировкам', () => {
    const { formatChildTicketAgeNote, showtimesForDay } = loadModel();
    assert.equal(formatChildTicketAgeNote('до 16 лет'), 'Детский билет — до 16 лет');
    assert.equal(formatChildTicketAgeNote('детский до 14 лет'), 'Детский билет — до 14 лет');
    assert.equal(formatChildTicketAgeNote('детский от 3 до 12 лет'), 'Детский билет — от 3 до 12 лет');
    assert.equal(formatChildTicketAgeNote('дети до 14 лет'), 'Детский билет — до 14 лет');
    const now = new Date('2026-10-02T10:00:00Z');
    const v = showtimesForDay({
      sessions: [{
        id: 1,
        kind: 'public_skate',
        starts_at_local: '14:15:00',
        ends_at_local: '14:59:00',
        starts_at_utc: '2026-10-02T11:15:00Z',
        ends_at_utc: '2026-10-02T11:59:00Z',
        price_adult_minor: 1000,
        price_child_minor: 800,
        currency_code: 'BYN',
        age_note: 'до 16 лет',
      }],
      now,
    });
    assert.equal(v.groups[0].note, 'Детский билет — до 16 лет');
  });
});

describe('TASK-146: расписание как сеансы в кино', () => {
  const now = new Date('2026-10-02T10:00:00Z'); // 13:00 по Минску
  const s = (id, t, extra = {}) => ({
    id, kind: 'public_skate', local_date: '2026-10-02',
    starts_at_local: t + ':00', ends_at_local: t.replace(/:\d+$/, ':59') + ':00',
    starts_at_utc: '2026-10-02T' + String(Number(t.slice(0, 2)) - 3).padStart(2, '0') + t.slice(2) + ':00Z',
    ends_at_utc: '2026-10-02T' + String(Number(t.slice(0, 2)) - 2).padStart(2, '0') + t.slice(2) + ':00Z',
    price_adult_minor: 1000, price_child_minor: 800, price_rental_minor: 900, currency_code: 'BYN', ...extra,
  });

  it('«Ближайший» — по starts_at_utc, не по порядку в ленте и не лексикографии', () => {
    const { showtimesForDay } = loadModel();
    const now = new Date('2026-10-04T09:28:00Z'); // 12:28 Минск
    const v = showtimesForDay({
      sessions: [
        {
          id: 99,
          kind: 'public_skate',
          local_date: '2026-10-04',
          starts_at_local: '16:15:00',
          ends_at_local: '16:59:00',
          starts_at_utc: '2026-10-04T13:15:00Z',
          ends_at_utc: '2026-10-04T14:00:00Z',
          currency_code: 'BYN',
        },
        {
          id: 10,
          kind: 'public_skate',
          local_date: '2026-10-04',
          starts_at_local: '13:00:00',
          ends_at_local: '13:44:00',
          starts_at_utc: '2026-10-04T10:00:00Z',
          ends_at_utc: '2026-10-04T10:45:00Z',
          currency_code: 'BYN',
        },
      ],
      now,
      markNext: true,
      pickedId: '99',
    });
    const times = v.groups[0].times;
    assert.equal(times.find((t) => t.time === '13:00').next, true);
    assert.equal(times.find((t) => t.time === '13:00').picked, false);
    assert.equal(times.find((t) => t.time === '16:15').next, false);
    assert.equal(times.find((t) => t.time === '16:15').picked, true);
  });

  it('одинаковые сеансы — одна группа, цены один раз, ближайший подсвечен, прошедшие скрыты', () => {
    const { showtimesForDay } = loadModel();
    const v = showtimesForDay({
      sessions: [s(1, '11:15'), s(2, '14:15'), s(3, '15:15'), s(4, '18:00', { price_adult_minor: 1200 })],
      now, ticketsUrl: 'https://koronaticket.by/rink', markNext: true,
    });
    assert.equal(v.count, 3);
    assert.equal(v.groups.length, 2);
    assert.deepEqual(v.groups[0].times.map((t) => t.time), ['14:15', '15:15']);
    assert.equal(v.groups[0].times[0].next, true);
    assert.equal(v.groups[0].times[1].next, false);
    assert.equal(v.groups[0].times[0].ticketHref, 'https://koronaticket.by/rink');
    assert.deepEqual(v.groups[0].prices.map((p) => p.label + ' ' + p.value), ['Взрослый 10 BYN', 'Детский 8 BYN', 'Прокат 9 BYN']);
    assert.equal(v.groups[1].prices[0].value, '12 BYN');
  });

  it('без кассы время — не ссылка', () => {
    const { showtimesForDay } = loadModel();
    const v = showtimesForDay({ sessions: [s(2, '14:15')], now });
    assert.equal(v.groups[0].times[0].ticketHref, null);
  });

  it('полоса дней считает только будущие сеансы; по умолчанию — первый день со льдом', () => {
    const { dayStrip, defaultScheduleDay } = loadModel();
    const strip = dayStrip([{ local_date: '2026-10-02', sessions: [s(1, '11:15')] },
      { local_date: '2026-10-04', sessions: [s(5, '18:00', { local_date: '2026-10-04' })] }], '2026-10-02', now, 7);
    assert.equal(strip.length, 7);
    assert.equal(strip[0].top, 'Сегодня');
    assert.equal(strip[1].top, 'Завтра');
    assert.equal(strip[2].top, 'Вс');
    assert.equal(strip[0].count, 0); // единственный сеанс сегодня уже прошёл
    assert.equal(defaultScheduleDay(strip), '2026-10-04');
  });

  it('быстрые действия — только то, что есть; сайт важнее инстаграма', () => {
    const { quickActions } = loadModel();
    assert.deepEqual(quickActions({}), []);
    const a = quickActions({ latitude: 53.9, longitude: 27.5, phone: '+375 (29) 111-22-33',
      social_urls: { instagram: 'https://instagram.com/x' } });
    assert.deepEqual(a.map((x) => x.id), ['route', 'copyPhone', 'insta']);
    assert.equal(a[1].label, 'Телефон');
    assert.equal(a[1].phone, '+375 (29) 111-22-33');
    const multi = quickActions({ phone: '+375447838518; +375173095476' });
    assert.equal(multi[0].phone, '+375447838518');
    assert.deepEqual(multi[0].phones, ['+375447838518', '+375173095476']);
  });

  it('часы по дням: сегодня отмечен, одинаковые дни — «ежедневно»', () => {
    const { weekHours } = loadModel();
    assert.equal(weekHours(null, now), null);
    assert.equal(weekHours({ daily: { open: '10:00', close: '23:00' } }, now).uniform, true);
    const w = weekHours({ weekly: { mon: ['10:00', '20:00'], tue: ['10:00', '20:00'], wed: ['10:00', '20:00'],
      thu: ['10:00', '20:00'], fri: ['10:00', '20:00'], sat: ['11:00', '18:00'], sun: null } }, now);
    assert.equal(w.uniform, false);
    assert.equal(w.rows.filter((r) => r.today)[0].label, 'Пт');
    assert.equal(w.rows[6].value, 'выходной');
  });
});

describe('TASK-146: карточка открывается на дне и сеансе из ленты', () => {
  it('parseScheduleFocus читает day и s, мусор отбрасывает', () => {
    const { parseScheduleFocus } = loadModel();
    assert.deepEqual(parseScheduleFocus('?ref=1&day=2026-10-03&s=77'), { day: '2026-10-03', sessionId: '77' });
    assert.deepEqual(parseScheduleFocus('?ref=1&day=завтра&s=x'), { day: null, sessionId: null });
  });

  it('сеанс из ленты подсвечен, «Ближайший» — у реально следующего по времени', () => {
    const { showtimesForDay } = loadModel();
    const mk = (id, h) => ({ id, kind: 'public_skate', starts_at_local: h + ':15:00', ends_at_local: h + ':59:00',
      starts_at_utc: '2026-10-02T' + String(h - 3).padStart(2, '0') + ':15:00Z',
      ends_at_utc: '2026-10-02T' + String(h - 3).padStart(2, '0') + ':59:00Z', currency_code: 'BYN' });
    const now = new Date('2026-10-02T10:00:00Z');
    const v = showtimesForDay({ sessions: [mk(1, 14), mk(2, 18)], now, markNext: true, pickedId: '2' });
    assert.deepEqual(v.groups[0].times.map((t) => [t.time, t.next, t.picked]), [['14:15', true, false], ['18:15', false, true]]);
    const w = showtimesForDay({ sessions: [mk(1, 14), mk(2, 18)], now, markNext: true, pickedId: '999' });
    assert.equal(w.groups[0].times[0].next, true);
  });
});

describe('TASK-180: устаревшее расписание в карточке', () => {
  it('schedule_stale — баннер, слоты остаются', () => {
    const { staleScheduleNote, shouldWarnScheduleStale, iceFeedView } = loadModel();
    const now = new Date('2026-10-02T10:00:00Z');
    const fresh = {
      schedule_stale: true,
      schedule_very_stale: false,
      schedule_observed_at: '2026-10-01T11:00:00Z',
    };
    assert.equal(shouldWarnScheduleStale(fresh), true);
    assert.match(staleScheduleNote(fresh, now), /могло измениться/);
    const feed = iceFeedView({ card: { freshness: fresh, tier: 'A' }, hasSessions: true });
    assert.equal(feed.mode, 'ribbon');
  });

  it('schedule_very_stale — не показываем ленту сеансов', () => {
    const { iceFeedView } = loadModel();
    const very = {
      schedule_stale: true,
      schedule_very_stale: true,
      schedule_observed_at: '2026-09-28T10:00:00Z',
    };
    const feed = iceFeedView({
      card: { freshness: very, tier: 'A', phone: '+375 17 1' },
      hasSessions: true,
      now: new Date('2026-10-02T10:00:00Z'),
    });
    assert.equal(feed.mode, 'unconfirmed');
    assert.match(feed.banner, /не обновлялось/);
  });
});

describe('massAccessView', () => {
  const lyzhHours = {
    weekly: {
      mon: [['11:00', '15:00'], ['19:00', '22:00']],
      sat: [['11:00', '22:00']],
      sun: [['08:00', '22:00']],
    },
    rental_close: '21:00',
    track_close: '22:00',
    free_entry: true,
    access_note: 'Бронь не нужна.',
    rental_catalog: [{ label: 'Ролики', price: '8 BYN', per: 'час' }],
  };

  it('включает окна, прокат и не требует сеансов льда', () => {
    const { massAccessView } = loadModel();
    const v = massAccessView({ opening_hours: lyzhHours });
    assert.equal(v.enabled, true);
    assert.equal(v.freeEntry, true);
    assert.equal(v.rentalClose, '21:00');
    assert.equal(v.rentalCatalog.length, 1);
    assert.match(v.week.rows[0].value, /11:00/);
  });

  it('выключен без данных массового доступа', () => {
    const { massAccessView } = loadModel();
    assert.equal(massAccessView({ opening_hours: { weekly: { mon: [['10:00', '18:00']] } } }).enabled, false);
    assert.equal(massAccessView({}).enabled, false);
  });
});
