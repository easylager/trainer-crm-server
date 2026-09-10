/**
 * TASK-052: arena card model — ribbon, prices, freshness, empty states.
 * Run: node --test tests/js/arena-card-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(
  __dirname,
  '../../static/webapp/arena-card-model.js'
);

function loadModel() {
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
    assert.equal(rows[0].cta, 'Билет на месте');
    assert.equal(rows[0].ctaKind, 'ghost');
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
      assert.equal(rows[0].ctaKind, 'ghost');
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

  it('prefers hero variant then card then thumb', () => {
    const { heroPhotoUrl } = loadModel();
    assert.equal(
      heroPhotoUrl({
        hero: { variants: { thumb: '/t.jpg', hero: '/h.jpg', card: '/c.jpg' } },
      }),
      '/h.jpg'
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
  });
});

describe('iceRowCta', () => {
  it('is informational Билет на месте; external_url is a link, never booking', () => {
    const { iceRowCta } = loadModel();
    assert.deepEqual(iceRowCta({ kind: 'public_skate' }), {
      cta: 'Билет на месте',
      ctaKind: 'ghost',
      href: null,
      bookable: false,
    });
    const linked = iceRowCta({
      kind: 'open_ice',
      external_url: 'https://chizhovka.example',
    });
    assert.equal(linked.cta, 'Билет на месте');
    assert.equal(linked.ctaKind, 'ghost');
    assert.equal(linked.bookable, false);
    assert.equal(linked.href, 'https://chizhovka.example');
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
    assert.equal(parseArenaRef('?arena_id=12', 'arena_other'), '12');
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
