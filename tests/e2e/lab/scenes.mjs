/**
 * Сценарии лабы редизайна — те же формы данных, что в home-v2 / ice-v2 / me-v2 e2e.
 * Лаба: node tools/redesign-lab.mjs
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const ICE_FIX = JSON.parse(readFileSync(path.join(here, '../fixtures/ice-v2.json'), 'utf-8'));

export const NOW_DEFAULT = new Date('2026-11-22T16:30:00Z'); /* 19:30 Минск */
export const NOW_NIGHT = new Date('2026-11-23T00:13:00Z'); /* 03:13 */
export const NOW_LATE = new Date('2026-11-22T20:10:00Z'); /* 23:10 */
const TODAY = '2026-11-22';
const TOMORROW = '2026-11-23';

const P = (n) => '/photos/' + n;
const PHOTO = {
  nemiga: P('arena-38/hero.webp'),
  ledoviy: P('arena-25/hero.jpg'),
  gorky: P('arena-11/hero.webp'),
  chizh: P('arena-115/hockey-rink-interior.jpg'),
  mozyr: P('mozyr-global-ice/hero.jpg'),
  brest: P('arena-12/track.jpg'),
};
const LOGO_DIN = '/static/webapp/hockey-logos/dinamo-moscow.png';
const LOGO_BAR = '/static/webapp/hockey-logos/barys.png';

function rail(arenasToday, arenasTomorrow = [], countT = 22, countTm = 34, countW = 28) {
  return {
    windows: [
      { key: 'today', label: 'Сегодня', count: countT, href: 'ice?city_id=1&intent=skate&when=today', arenas: arenasToday },
      { key: 'tomorrow', label: 'Завтра', count: countTm, href: 'ice?city_id=1&intent=skate&when=tomorrow', arenas: arenasTomorrow },
      { key: 'weekend', label: 'Выходные', count: countW, href: 'ice?city_id=1&intent=skate&when=weekend', arenas: [] },
    ],
  };
}
function arena(arenaId, name, photo, price, times) {
  return {
    arena_id: arenaId, name, photo: { thumb: photo, card: photo, hero: photo },
    href: 'arena?ref=' + arenaId + '&s=' + times[0].session_id,
    price,
    times: times.map((t) => ({
      time: t[0], end: t[1], session_id: t[2], minutes_until: t[3],
      href: 'arena?ref=' + arenaId + '&s=' + t[2],
    })),
  };
}
const RAIL_MINSK = rail([
  arena(11, 'Каток на Немиге', PHOTO.nemiga, '12 BYN · прокат 8', [['18:00', '19:15', 101, 25], ['19:30', '20:45', 104, 115], ['21:00', '22:00', 105, 205]]),
  arena(12, 'Ледовый дворец', PHOTO.ledoviy, '10 BYN · прокат 5', [['18:00', '19:30', 102, 25], ['20:15', '21:30', 106, 160]]),
  arena(13, 'Парк Горького', PHOTO.gorky, '5 BYN', [['19:00', '21:00', 103, 85], ['21:30', '23:00', 107, 230]]),
  arena(14, 'Чижовка-арена', PHOTO.chizh, '8 BYN', [['20:00', '21:15', 108, 145]]),
]);
RAIL_MINSK.windows[1].arenas = [
  arena(11, 'Каток на Немиге', PHOTO.nemiga, '12 BYN', [['08:00', '09:15', 201, 750], ['10:00', '11:00', 202, 870]]),
  arena(12, 'Ледовый дворец', PHOTO.ledoviy, '10 BYN', [['09:30', '10:30', 203, 810]]),
];
RAIL_MINSK.windows[0].arenas[0].times[0].invite_url = 'https://t.me/glidebot?start=arena_11_s_101';

const NEEDS = [
  { key: 'skate', title: 'Покататься', line: '10 катков', href: 'ice?city_id=1&intent=skate', windows: [] },
  { key: 'ohm', title: 'С клюшкой', line: 'ОХМ на 2 катках · ближайший в 20:45', href: 'ice?city_id=1&intent=ohm', windows: [] },
  { key: 'matches', title: 'Хоккей', line: '3 матча на неделе', href: 'client-matches?city=Минск', windows: [] },
  { key: 'service', title: 'Заточка', line: '12 мест · 5 открыты сейчас', href: 'ice?city_id=1&intent=service', windows: [] },
  { key: 'shop', title: 'Магазины', line: '8 магазинов · 8 открыты сейчас', href: 'ice?city_id=1&venue=shop', windows: [] },
  { key: 'coach', title: 'Учиться с тренером', line: '14 тренеров', href: 'trainers?city_id=1', windows: [] },
];
const CITY_MINSK = {
  id: 1, name: 'Минск', name_in: 'Минске', kicker: '4 катка сегодня', counts_line: '4 катка',
  hero_photo: { thumb: PHOTO.gorky, card: PHOTO.gorky, hero: PHOTO.gorky },
  hero_photos: [
    { thumb: PHOTO.gorky, card: PHOTO.gorky, hero: PHOTO.gorky },
    { thumb: PHOTO.nemiga, card: PHOTO.nemiga, hero: PHOTO.nemiga },
  ],
  upcoming: [], upcoming_href: 'ice?city_id=1&intent=skate&when=today', upcoming_more: 'Весь день', needs: NEEDS,
};
const PLACE_PHOTOS = {
  11: { thumb: PHOTO.nemiga, card: PHOTO.nemiga },
  12: { thumb: PHOTO.ledoviy, card: PHOTO.ledoviy },
  13: { thumb: PHOTO.gorky, card: PHOTO.gorky },
  14: { thumb: PHOTO.chizh, card: PHOTO.chizh },
};
const KK_ITEM = {
  kind: 'kk_before',
  hockey: {
    mode: 'before', event_href: 'client-match?id=501',
    match: {
      id: 501, status: 'scheduled', starts_at: '2026-11-22T16:00:00+00:00',
      home: { name: 'Динамо-Минск', short: 'ДИН', color: '#2c4dd0', logo: LOGO_DIN },
      away: { name: 'Барыс', short: 'БАР', color: '#0aa', logo: LOGO_BAR },
      arena: 'Минск-Арена', city: 'Минск', result: null,
    },
    my_pick: null,
  },
};
const XL_MATCH = {
  kind: 'extraliga', id: 502, href: 'client-match?id=502',
  home: { name: 'Юность', short: 'ЮН', color: '#0047AB', logo: null },
  away: { name: 'Локомотив', short: 'ЛОК', color: '#D0202E', logo: null },
  starts_at: '2026-11-24T16:30:00+00:00', arena: 'Чижовка-Арена', city: 'Минск',
  live: false, result: null, sticker: null,
};
const NOW_FEED = { kind: 'feed', items: [XL_MATCH, KK_ITEM, { kind: 'more', count: 6, href: 'client-matches?city=Минск' }] };
const MATCHES_FEED = { week_count: 6, all_href: 'client-matches?city=Минск', matches: [XL_MATCH] };
const CITY_PICK = [
  { id: 1, name: 'Минск', today_sessions: 22, trainer_count: 14, photo: { thumb: PHOTO.nemiga, card: PHOTO.nemiga, hero: PHOTO.nemiga } },
  { id: 3, name: 'Гомель', today_sessions: 6, trainer_count: 4, photo: { thumb: PHOTO.chizh, card: PHOTO.chizh, hero: PHOTO.chizh } },
  { id: 4, name: 'Брест', today_sessions: 4, trainer_count: 3, photo: { thumb: PHOTO.brest, card: PHOTO.brest, hero: PHOTO.brest } },
];
const SLOTS_7 = {
  slots: [
    { id: 9001, slot_date: '2026-11-23', start_time: '18:00', service_id: 5, arena_id: 12, arena_name: 'Ледовый дворец' },
    { id: 9002, slot_date: '2026-11-25', start_time: '07:30', service_id: 5, arena_id: 12, arena_name: 'Ледовый дворец' },
    { id: 9003, slot_date: '2026-11-26', start_time: '19:00', service_id: 5, arena_id: 12, arena_name: 'Ледовый дворец' },
  ],
};
const PASS_ACTIVE = [{
  id: 9, pass_product_id: 4, status: 'active', is_expired: false,
  sessions_remaining: 4, sessions_total: 8,
  product_name: 'Абонемент 8 занятий', trainer_name: 'Максим',
  service_name: 'Индивидуальное занятие', trainer_id: 7,
  expires_at: '2026-12-15T00:00:00+00:00', issued_at: '2026-09-01T00:00:00+00:00',
}];
const COACH_SESSION = {
  city_id: 1, primary_trainer_id: 7, primary_trainer_name: 'Максим',
  primary_trainer_list_photo_key: null, primary_trainer_telegram_username: 'maxim_coach',
  primary_trainer_can_book: true, primary_catalog_service_id: null,
  saved_trainers: [], saved_trainers_ids: [], has_past_sessions: true,
};

function bookingToday(over) {
  return {
    days: [{
      date: TODAY, day_label: 'вс',
      bookings: [{
        id: 501, status: 'confirmed', start_time: '19:40', end_time: '20:30', duration_minutes: 50,
        trainer_id: 7, trainer_name: 'Максим', trainer_telegram_username: 'maxim_coach',
        trainer_list_photo_key: null,
        service_name: 'Индивидуальное занятие',
        arena_name: 'Ледовый дворец', arena_id: 12, place_display: 'Ледовый дворец',
        map_link: 'https://yandex.ru/maps/?pt=27.5,53.9&z=16',
        slot_date: TODAY, ...over,
      }],
    }],
  };
}

function bootstrap(over) {
  const o = over || {};
  return {
    bookings: { days: [] },
    requests: { items: [] },
    client_session: { city_id: 1, primary_trainer_id: null, primary_trainer_name: null, primary_trainer_list_photo_key: null, saved_trainers: [] },
    activity: { streak_weeks: 0, completed_total: 0 },
    passes: [],
    certificates: [],
    ice_teaser: null,
    pending_referral: null,
    platform: { vertical_key: 'ice', ui: {} },
    ...o,
    home: {
      city: CITY_MINSK, matches: MATCHES_FEED, now: NOW_FEED,
      ice_rail: RAIL_MINSK, place_photos: PLACE_PHOTOS,
      ...(o.home || {}),
    },
  };
}

const FLAGS_ALL = {
  season_ui: false, bookings_tab: true, fast_tabs: false, search_board: false,
  redesign_s1: true, redesign_s2: true, redesign_s3: true, redesign_s4: true, redesign_s5: true,
};
const FLAGS_S1 = { season_ui: false, bookings_tab: true, fast_tabs: false, search_board: false, redesign_s1: true };
const FLAGS_OFF = { season_ui: false, bookings_tab: false, fast_tabs: false, search_board: false, redesign_s1: false };

const ON_ICE = {
  session_id: 401, arena_id: 11, arena_name: 'Каток на Немиге',
  photo: { thumb: PHOTO.nemiga, card: PHOTO.nemiga, hero: PHOTO.nemiga },
  starts_local: '19:45', ends_local: '21:15', minutes_left: 95,
  live: { level: 2, count: 3, last_min: 4 },
  checked_in: false, checkin_id: null, load_level: null,
  season_days: 5, streak_weeks: 2, has_this_week: false,
  invite_url: 'https://t.me/glidebot?start=arena_11_s_401',
};
/* «На неделе» под карточкой «Лёд закончился» / «Один каток» — массив, не {days:[]}. */
const LAB_WEEK = [
  { date: TODAY, label: 'Сегодня', sub: '22', times: [] },
  { date: TOMORROW, label: 'Завтра', sub: '23', times: [
    { time: '10:00', session_id: 293, href: 'arena?ref=12&s=293' },
    { time: '18:30', session_id: 294, href: 'arena?ref=12&s=294' },
  ] },
  { date: '2026-11-24', label: 'Вт', sub: '24', times: [] },
  { date: '2026-11-25', label: 'Ср', sub: '25', times: [] },
  { date: '2026-11-26', label: 'Чт', sub: '26', times: [] },
  { date: '2026-11-27', label: 'Пт', sub: '27', times: [] },
  { date: '2026-11-28', label: 'Сб', sub: '28', times: [
    { time: '20:15', session_id: 299, href: 'arena?ref=12&s=299' },
  ] },
];
const COMPANY_TODAY = {
  code: 'abc12345', name: '', session_id: 401, arena_id: 11, arena_name: 'Каток на Немиге',
  starts_local: '19:00', day_label: 'сегодня', going_count: 3, going_names: ['Аня', 'Дима', 'Света'],
  crowd_line: 'Трое — это уже компания', my_status: 'maybe', page_url: '/k/abc12345',
  photo: { thumb: PHOTO.nemiga, card: PHOTO.nemiga },
};

const ME_SOLO = {
  name: 'Максим', initial: 'М', city: 'Минск', joined_label: 'в Glide с октября',
  club: {
    name: 'Динамо-Минск', short: 'ДМ', color: '#06c', logo: P('arena-25/hero.jpg'), label_ink: '#fff',
    next_match: { starts_at: '2026-11-22T19:00:00+03:00', opponent: 'Барыс', href: 'kto-kogo', label: 'Сегодня 19:00 · Барыс' },
  },
  home_arena: {
    id: 25, name: 'Ледовый дворец', href: 'arena?id=25', sessions_left_today: 3, tomorrow_first: null,
    subscribed: true, photo: { thumb: P('arena-25/hero.jpg'), card: P('arena-25/hero.jpg') },
    today_times: ['20:00', '21:30'],
  },
  stats: { trainings: 12, streak_weeks: 3, kk_points: 40, kk_place: 7 },
  rows: { bookings: { next_starts_at: '2026-11-23T18:00:00+03:00' }, passes: null,
    saved: { count: 3, line: '2 катка · 1 тренер' }, family: { count: 0 }, requests: null, trainer: null },
  profile_name: null,
  saved_detail: { arenas: 2, trainers: 1, line: '2 катка · 1 тренер' },
  pass: null,
};
const ME_PASS = {
  ...ME_SOLO,
  pass: {
    left: 5, total: 8, trainer_id: 77, trainer_name: 'Ольга Смирнова',
    trainer_photo_key: 't77.jpg', expires_label: 'до 15 декабря', book_href: 'catalog?trainer_id=77',
  },
};
const ME_NEWBIE = {
  name: 'Миша', initial: 'М', city: 'Минск', joined_label: 'в Glide с ноября',
  club: null, home_arena: null,
  stats: { trainings: 0, streak_weeks: 0, kk_points: null, kk_place: null },
  rows: { bookings: null, passes: null, saved: { count: 0 }, family: { count: 0 }, requests: null, trainer: null },
  profile_name: null, saved_detail: null, pass: null,
};
const ME_COMPANY = {
  code: 'abc12345', name: '', session_id: 401, arena_id: 11,
  arena_name: 'Конькобежный', starts_local: '17:45', day_label: 'сб, 28', going_count: 3,
  going_names: ['Аня', 'Дима', 'Света'], crowd_line: 'Трое — это уже компания',
  my_status: 'going', page_url: '/k/abc12345', photo: { thumb: null, card: null },
};
const SEASON = { sessions: {}, me: { season_days: 14, streak_weeks: 3, has_this_week: true, helped: 0 } };
const SEASON_ZERO = { sessions: {}, me: { season_days: 0, streak_weeks: 0, has_this_week: false, helped: 0 } };

function iceSchedule(variant, day, kind) {
  return ICE_FIX[`${variant}|${day}|${kind}`] || ICE_FIX[`base|${day}|${kind}`] || ICE_FIX['base|today|skate'];
}

/** @typedef {{ id: string, group: string, title: string, page: string, now?: Date, tgScheme?: string, flags: object, boot?: object, me?: object, season?: object, iceVariant?: string, iceCompany?: boolean, note?: string }} LabScene */

/** @type {LabScene[]} */
export const SCENES = [
  /* ── Главная ── */
  {
    id: 'home-no-city', group: 'Главная', title: 'Без города',
    page: '/webapp/client-home', flags: FLAGS_ALL,
    boot: bootstrap({
      client_session: { city_id: null, primary_trainer_id: null, primary_trainer_name: null, primary_trainer_list_photo_key: null, saved_trainers: [] },
      home: { city: null, matches: null, now: null, ice_rail: null, place_photos: null, city_pick: CITY_PICK },
    }),
  },
  {
    id: 'home-newbie', group: 'Главная', title: 'Новичок · Минск',
    page: '/webapp/client-home', flags: FLAGS_ALL, boot: bootstrap(),
  },
  {
    id: 'home-booking', group: 'Главная', title: 'Запись сегодня',
    page: '/webapp/client-home', flags: FLAGS_ALL,
    boot: bootstrap({ bookings: bookingToday() }),
  },
  {
    id: 'home-pending', group: 'Главная', title: 'Ждёт тренера',
    page: '/webapp/client-home', flags: FLAGS_ALL,
    boot: bootstrap({ bookings: bookingToday({ status: 'pending' }) }),
  },
  {
    id: 'home-pass', group: 'Главная', title: 'Абонемент без записи',
    page: '/webapp/client-home', flags: FLAGS_ALL,
    boot: bootstrap({ passes: PASS_ACTIVE }),
  },
  {
    id: 'home-coach', group: 'Главная', title: 'Тренер без абонемента',
    page: '/webapp/client-home', flags: FLAGS_ALL,
    boot: bootstrap({ client_session: COACH_SESSION }),
  },
  {
    id: 'home-night', group: 'Главная', title: 'Ночь · «Доброй ночи»',
    page: '/webapp/client-home', flags: FLAGS_ALL, now: NOW_NIGHT,
    boot: bootstrap({ client_session: COACH_SESSION }),
  },
  {
    id: 'home-dark-tg', group: 'Главная', title: 'Тёмная тема TG → светлый UI',
    page: '/webapp/client-home', flags: FLAGS_ALL, tgScheme: 'dark', boot: bootstrap(),
  },
  {
    id: 'home-flag-off', group: 'Главная', title: 'Флаг выключен · старая',
    page: '/webapp/client-home.html', flags: FLAGS_OFF, boot: bootstrap(),
    note: 'Старая главная — регрессия без redesign_s1',
  },
  {
    id: 'home-on-ice', group: 'Главная', title: 'На катке · «Я здесь»',
    page: '/webapp/client-home', flags: FLAGS_ALL,
    boot: bootstrap({ home: { on_ice: ON_ICE } }),
  },
  {
    id: 'home-on-ice-done', group: 'Главная', title: 'Уже отмечен',
    page: '/webapp/client-home', flags: FLAGS_ALL,
    boot: bootstrap({
      home: { on_ice: { ...ON_ICE, checked_in: true, checkin_id: 900, season_days: 6, streak_weeks: 3, has_this_week: true } },
    }),
  },
  {
    id: 'home-company', group: 'Главная', title: 'Компания сегодня',
    page: '/webapp/client-home', flags: FLAGS_ALL,
    boot: bootstrap({ home: { companies: [COMPANY_TODAY] } }),
  },
  {
    id: 'home-return', group: 'Главная', title: 'С возвращением',
    page: '/webapp/client-home', flags: FLAGS_ALL,
    boot: bootstrap({
      client_session: { ...COACH_SESSION, has_past_sessions: true },
      home: { variant: 'return', return_coach: { name: 'Максим', together: 12, weeks_ago: 3 } },
    }),
  },
  {
    id: 'home-one-rink', group: 'Главная', title: 'Один каток (Пинск-стиль)',
    page: '/webapp/client-home', flags: FLAGS_ALL,
    boot: bootstrap({
      home: {
        city: { ...CITY_MINSK, id: 9, name: 'Пинск', name_in: 'Пинске', kicker: 'один каток', counts_line: '1 каток' },
        ice_rail: rail([arena(90, 'Ледовый дворец Пинск', PHOTO.mozyr, '4,40 BYN', [['19:45', '21:00', 801, 82]])], [], 1, 3, 5),
        one_rink: true, week: [], nearby: [],
      },
    }),
  },
  {
    id: 'home-ice-ended', group: 'Главная', title: 'Лёд закончился (вечер)',
    page: '/webapp/client-home', flags: FLAGS_ALL, now: NOW_LATE,
    boot: bootstrap({
      client_session: { city_id: 3, primary_trainer_id: null, primary_trainer_name: null, primary_trainer_list_photo_key: null, saved_trainers: [] },
      home: {
        city: { ...CITY_MINSK, id: 3, name: 'Гомель', name_in: 'в Гомеле' },
        ice_rail: rail([], RAIL_MINSK.windows[1].arenas, 0, 2, 4),
        /* Контракт iceEndedCardHtml: date_label/date_sub/time/arena_name/photo(url)/arena_id. */
        next_ice: {
          date_label: 'сб, 28', date_sub: 'сб 28', time: '20:15',
          arena_id: 12, arena_name: 'Гомельский ледовый дворец',
          photo: PHOTO.chizh, href: 'arena?ref=12&s=901',
        },
        week: LAB_WEEK,
      },
    }),
  },

  /* ── Лёд ── */
  {
    id: 'ice-minsk', group: 'Лёд', title: 'Вечер · Минск',
    page: '/webapp/ice', flags: FLAGS_ALL, iceVariant: 'base',
  },
  {
    id: 'ice-ohm', group: 'Лёд', title: 'С клюшкой',
    page: '/webapp/ice?kind=ohm', flags: FLAGS_ALL, iceVariant: 'base',
  },
  {
    id: 'ice-night', group: 'Лёд', title: 'Ночь',
    page: '/webapp/ice', flags: FLAGS_ALL, iceVariant: 'night', now: NOW_NIGHT,
  },
  {
    id: 'ice-late', group: 'Лёд', title: 'Лёд закончился',
    page: '/webapp/ice', flags: FLAGS_ALL, iceVariant: 'late', now: NOW_LATE,
  },
  {
    id: 'ice-one-rink', group: 'Лёд', title: 'Один каток',
    page: '/webapp/ice', flags: FLAGS_ALL, iceVariant: 'onerink',
  },
  {
    id: 'ice-company', group: 'Лёд', title: 'Плашка компании',
    page: '/webapp/ice', flags: FLAGS_ALL, iceVariant: 'base', iceCompany: true,
  },
  {
    id: 'ice-flag-off', group: 'Лёд', title: 'Флаг выключен · старая',
    page: '/webapp/ice', flags: FLAGS_OFF, iceVariant: 'base',
    note: 'Должен открыться старый ice.html',
  },

  /* ── Я ── */
  {
    id: 'me-solo', group: 'Я', title: 'Катается сам',
    page: '/webapp/client-me', flags: FLAGS_ALL, me: ME_SOLO, season: SEASON,
  },
  {
    id: 'me-pass', group: 'Я', title: 'С абонементом',
    page: '/webapp/client-me', flags: FLAGS_ALL, me: ME_PASS, season: SEASON,
  },
  {
    id: 'me-newbie', group: 'Я', title: 'Новичок',
    page: '/webapp/client-me', flags: FLAGS_ALL, me: ME_NEWBIE, season: SEASON_ZERO,
  },
  {
    id: 'me-companies', group: 'Я', title: 'Мои компании',
    page: '/webapp/client-me', flags: FLAGS_ALL,
    me: {
      ...ME_SOLO,
      companies: [
        ME_COMPANY,
        { ...ME_COMPANY, code: 'def67890', day_label: 'завтра', my_status: 'organizer', arena_name: 'Ледовый дворец', starts_local: '10:00' },
      ],
    },
    season: SEASON,
  },
  {
    id: 'me-flag-off', group: 'Я', title: 'Флаг выключен · старая',
    page: '/webapp/client-me', flags: { ...FLAGS_OFF, redesign_s4: false }, me: ME_SOLO, season: SEASON_ZERO,
  },
];

export function sceneById(id) {
  return SCENES.find((s) => s.id === id) || SCENES[1];
}

export function apiForScene(scene, pathname, method, searchParams) {
  const flags = scene.flags || FLAGS_ALL;
  if (pathname === '/api/webapp/client/ui-flags') return flags;

  if (pathname === '/api/webapp/client/hub/bootstrap') {
    return scene.boot || bootstrap();
  }
  if (pathname === '/api/webapp/client/me') {
    return scene.me || ME_SOLO;
  }
  if (pathname === '/api/webapp/client/checkins/state') {
    return scene.season || SEASON;
  }
  if (pathname === '/api/webapp/client/ice/schedule') {
    const day = searchParams.get('day') || 'today';
    const kind = searchParams.get('kind') || 'skate';
    const variant = scene.iceVariant || 'base';
    const base = iceSchedule(variant, day, kind);
    if (!scene.iceCompany) return base;
    const d = JSON.parse(JSON.stringify(base));
    const row = (d.ongoing || [])[0] || (d.upcoming || [])[0] || ((d.groups || [])[0] || { rows: [] }).rows[0];
    if (row) row.company = { code: 'abc12345', going_count: 3, page_url: '/k/abc12345' };
    return d;
  }
  if (pathname === '/api/webapp/client/slots') {
    if (searchParams.get('trainer_id') === '7') return SLOTS_7;
    return { next: { label: 'ср, 25 · 07:30' }, slots: [] };
  }
  if (pathname === '/api/webapp/client/profiles') return { items: [], default_profile_id: null };
  if (pathname === '/api/webapp/client/session' && method === 'GET') return { city_id: 1 };
  if (pathname === '/api/webapp/client/session/catalog-filters') return { success: true };
  if (pathname === '/api/webapp/client/hockey/remind') return { on: true };
  if (pathname === '/api/public/ice/cities') {
    return {
      items: [
        { id: 1, name: 'Минск', skate_count: 3, trainer_count: 14, latitude: 53.9, longitude: 27.56 },
        { id: 2, name: 'Мозырь', skate_count: 1, trainer_count: 4, latitude: 52.05, longitude: 29.27 },
        { id: 3, name: 'Гомель', skate_count: 2, trainer_count: 6, latitude: 52.43, longitude: 30.98 },
      ],
    };
  }
  if (pathname === '/api/webapp/client/checkins' && method === 'POST') {
    return {
      checkin_id: 900, session_id: 401, load_level: null, season_days: 6,
      nth_label: '6-й раз за сезон', streak_weeks: 2, has_this_week: true,
      live: { level: 2, count: 3, last_min: 0 },
    };
  }
  if (/^\/api\/webapp\/client\/checkins\/\d+$/.test(pathname) && method === 'PATCH') {
    return { live: { level: 2, count: 4, last_min: 0 } };
  }
  if (/^\/api\/webapp\/client\/checkins\/\d+\/share$/.test(pathname)) {
    return {
      prepared_message_id: null,
      share_url: 'https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fglidebot',
      text: 'Максим на «Каток на Немиге» до 21:15\nПодъезжай!',
    };
  }
  if (pathname === '/api/webapp/client/ice-watches' && method === 'POST') {
    return { ok: true, watch_id: 1 };
  }
  if (/^\/api\/public\/ice-companies\/[^/]+\/responses$/.test(pathname) && method === 'POST') {
    return { ok: true };
  }
  return {};
}

export { FLAGS_ALL, bootstrap, iceSchedule };
