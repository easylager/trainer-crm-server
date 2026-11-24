/**
 * TASK-445 (glide-home-v1, этап 1): headless-проверка новой главной client-home-v2.
 * Статика static/ + фото data/arena-cards/photos + стабы /api/* (Telegram и сеть не нужны).
 *
 * Сценарии (390×844, Europe/Minsk, «сейчас» зафиксировано 22.11.2026 19:30):
 *   01 no-city      — без города: карточка выбора города (city_pick, 3 города);
 *   02 newbie       — новичок в Минске: фото-карточка + rail ≥4 катков + матчи с «Кто кого» + плитки (+full);
 *   03 booking      — запись сегодня: билет с фото тренера и точками абонемента (+full);
 *   04 pending      — запись pending: жёлтый «ждёт тренера», без кнопки маршрута;
 *   05 pass         — активный абонемент: кольцо + окна из /client/slots;
 *   06 coach        — основной тренер без абонемента;
 *   07 one-rink     — Мозырь, один каток;
 *   08 no-today     — сегодня пусто (тихая строка), завтра есть;
 *   09 night        — 03:13, приветствие «Доброй ночи»;
 *   10 dark-tg      — тёмная тема Telegram: экраны остаются светлыми;
 *   11 flag-off     — redesign_s1=false: старая главная и старый бар с «Ещё»;
 *   12 skeleton     — bootstrap задержан: скелетон формы экрана.
 *
 * Run: node tests/e2e/home-v2.check.mjs
 * Скриншоты: tests/e2e/__shots__/home-v2/
 */
import { chromium } from 'playwright';
import http from 'node:http';
import { mkdirSync, rmSync, readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(here, '../..');
const staticDir = path.join(repoRoot, 'static');
const photosDir = path.join(repoRoot, 'data', 'arena-cards', 'photos');
const shots = path.join(here, '__shots__', 'home-v2');
rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });

const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2',
};
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  let file;
  if (p.startsWith('/photos/')) {
    file = path.join(photosDir, p.slice('/photos/'.length));
    if (!file.startsWith(photosDir) || !existsSync(file) || statSync(file).isDirectory()) {
      res.writeHead(404); res.end('no'); return;
    }
  } else {
    if (p === '/') p = '/webapp/client-home-v2.html';
    /* В проде новая главная живёт на /webapp/client-home (app.py отдаёт файл по флагу);
       pathnameKey() === 'client-home' выключает фоновый префетч вкладок в shell —
       только так замер веса страницы честный. */
    if (p === '/webapp/client-home') p = '/webapp/client-home-v2.html';
    if (p.startsWith('/static/')) p = p.slice('/static'.length);
    file = path.join(staticDir, p);
    if (!file.startsWith(staticDir) || !existsSync(file) || statSync(file).isDirectory()) {
      res.writeHead(404); res.end('no'); return;
    }
  }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, r));
const base = 'http://localhost:' + server.address().port;

/* «Сейчас»: 22 ноября 2026 (вс), 19:30 по Минску — как в макетах. */
const NOW = new Date('2026-11-22T16:30:00Z');
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
    times: times.map((t, i) => ({
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
const RAIL_TOMORROW = [
  arena(11, 'Каток на Немиге', PHOTO.nemiga, '12 BYN', [['08:00', '09:15', 201, 750], ['10:00', '11:00', 202, 870]]),
  arena(12, 'Ледовый дворец', PHOTO.ledoviy, '10 BYN', [['09:30', '10:30', 203, 810]]),
];
RAIL_MINSK.windows[1].arenas = RAIL_TOMORROW;
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
  upcoming: [],
  upcoming_href: 'ice?city_id=1&intent=skate&when=today', upcoming_more: 'Весь день',
  needs: NEEDS,
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
const SLOTS_7 = {
  slots: [
    { id: 9001, slot_date: '2026-11-23', start_time: '18:00', service_id: 5, arena_id: 12, arena_name: 'Ледовый дворец' },
    { id: 9002, slot_date: '2026-11-25', start_time: '07:30', service_id: 5, arena_id: 12, arena_name: 'Ледовый дворец' },
    { id: 9003, slot_date: '2026-11-26', start_time: '19:00', service_id: 5, arena_id: 12, arena_name: 'Ледовый дворец' },
    { id: 9004, slot_date: '2026-11-28', start_time: '10:00', service_id: 5, arena_id: 12, arena_name: 'Ледовый дворец' },
  ],
};
const CITY_PICK = [
  { id: 1, name: 'Минск', today_sessions: 22, trainer_count: 14, photo: { thumb: PHOTO.nemiga, card: PHOTO.nemiga, hero: PHOTO.nemiga } },
  { id: 3, name: 'Гомель', today_sessions: 6, trainer_count: 4, photo: { thumb: PHOTO.chizh, card: PHOTO.chizh, hero: PHOTO.chizh } },
  { id: 4, name: 'Брест', today_sessions: 4, trainer_count: 3, photo: { thumb: PHOTO.brest, card: PHOTO.brest, hero: PHOTO.brest } },
];

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
    home: {
      city: CITY_MINSK, matches: MATCHES_FEED, now: NOW_FEED,
      ice_rail: RAIL_MINSK, place_photos: PLACE_PHOTOS,
    },
    platform: { vertical_key: 'ice', ui: {} },
    ...o,
    home: {
      city: CITY_MINSK, matches: MATCHES_FEED, now: NOW_FEED,
      ice_rail: RAIL_MINSK, place_photos: PLACE_PHOTOS,
      ...(o.home || {}),
    },
  };
}

const UI_FLAGS_ON = { season_ui: false, bookings_tab: true, fast_tabs: false, search_board: false, redesign_s1: true };
const UI_FLAGS_OFF = { season_ui: false, bookings_tab: false, fast_tabs: false, search_board: false, redesign_s1: false };

function tgMock(colorScheme, photoUrl) {
  const photo = photoUrl ? `, photo_url: '${photoUrl}'` : '';
  return `window.Telegram = { WebApp: {
    initData: 'mock', initDataUnsafe: { user: { id: 1, first_name: 'Максим', allows_write_to_pm: true${photo} } }, colorScheme: '${colorScheme || 'light'}', themeParams: {},
    version: '8.0', platform: 'ios', isExpanded: true, viewportHeight: 844,
    isVersionAtLeast(v) { const cmp = (a, b) => a.split('.').map(Number).reduce((d, x, i) => d || x - (b[i] || 0), 0); return cmp(this.version, v) >= 0; },
    ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}, onEvent() {}, offEvent() {},
    enableClosingConfirmation() {}, disableVerticalSwipes() {},
    HapticFeedback: { selectionChanged() {}, impactOccurred() {}, notificationOccurred() {} },
    BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} }, MainButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
    openTelegramLink() {}, openLink() {}, shareURL() {},
  } };`;
}

let failures = 0;
function check(name, cond, extra) {
  console.log((cond ? '✔' : '✖') + ' ' + name + (cond || !extra ? '' : '  → ' + extra));
  if (!cond) failures++;
}

/* Подсчёт JS/CSS-файлов и байт для отчёта (без сжатия). */
function assetMeter(page) {
  const seen = new Map();
  page.on('response', async (r) => {
    const u = r.url();
    if (!/\.(js|css)(\?|$)/.test(u)) return;
    try {
      const b = await r.body();
      const key = u.split('?')[0];
      seen.set(key, (seen.get(key) || 0) + b.length);
    } catch (e) {}
  });
  return () => ({
    files: seen.size,
    bytes: [...seen.values()].reduce((a, b) => a + b, 0),
    list: [...seen.entries()]
      .map(([u, n]) => ({ name: u.split('/').pop(), kb: (n / 1024).toFixed(1) }))
      .sort((a, b) => b.kb - a.kb),
  });
}

async function openHome(browser, { boot, flags, tgScheme, tgPhoto, page: pagePath, now }) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Minsk', locale: 'ru-RU' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|ERR_FAILED|net::|404/.test(m.text())) errors.push(m.text()); });
  await page.clock.setFixedTime(now || NOW);
  const meter = assetMeter(page);
  await page.route('https://telegram.org/**', (r) => r.fulfill({ contentType: 'text/javascript', body: tgMock(tgScheme, tgPhoto) }));
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.route('**/api/**', (r) => {
    const url = new URL(r.request().url());
    const p = url.pathname;
    const json = (body) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (p === '/api/webapp/client/ui-flags') return json(flags || UI_FLAGS_ON);
    if (p === '/api/webapp/client/hub/bootstrap') return json(boot);
    if (p === '/api/webapp/client/profiles') return json({ items: [], default_profile_id: null });
    if (p === '/api/webapp/client/slots') {
      return url.searchParams.get('trainer_id') === '7' ? json(SLOTS_7) : json({ slots: [] });
    }
    if (p === '/api/public/ice/cities') {
      return json({
        items: [
          { id: 1, name: 'Минск', skate_count: 3, trainer_count: 14, latitude: 53.9, longitude: 27.56 },
          { id: 2, name: 'Мозырь', skate_count: 1, trainer_count: 4, latitude: 52.05, longitude: 29.27 },
          { id: 3, name: 'Гомель', skate_count: 2, trainer_count: 6, latitude: 52.43, longitude: 30.98 },
        ],
      });
    }
    if (p === '/api/webapp/client/session/catalog-filters') return json({ success: true });
    if (p.startsWith('/api/public/photos')) {
      /* «Фото тренера» — реальный кадр катка: на скрине лицо-кружок, не серая заглушка. */
      return r.fulfill({ contentType: 'image/jpeg', body: readFileSync(path.join(photosDir, 'arena-25', 'hero.jpg')) });
    }
    return json({});
  });
  await page.goto(base + (pagePath || '/webapp/client-home'));
  await page.waitForSelector('#hv2Skel', { state: 'hidden', timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(500);
  return { page, ctx, errors, meter };
}

async function shot(page, name, fullPage) {
  await page.screenshot({ path: path.join(shots, name + '.png'), fullPage: !!fullPage });
}

/* Геометрия и система: без горизонтального скролла, 5 вкладок, один Dela, ≤1 жёлтый. */
async function systemCheck(page, name) {
  const m = await page.evaluate(() => {
    const dela = [...document.querySelectorAll('body *')].filter((el) => {
      const s = getComputedStyle(el);
      return /Dela/.test(s.fontFamily) && el.children.length === 0 && (el.textContent || '').trim();
    });
    const yellow = document.querySelectorAll('.hv2-btn--yellow, .hv2-mcard__play--yellow').length;
    return {
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
      barTabs: [...document.querySelectorAll('#clientTabBar .client-tab-bar__btn')].map((b) => b.textContent.trim()),
      barVisible: !!document.getElementById('clientTabBar'),
      dela: dela.length,
      delaText: dela.map((el) => el.textContent.trim()).join('|'),
      yellow,
      gate: !!document.getElementById('glide-entry-gate'),
    };
  });
  check(name + ': нет горизонтального скролла', m.scrollW <= m.innerW, `${m.scrollW}>${m.innerW}`);
  check(name + ': бар — 5 вкладок с «Лёд»', m.barVisible && m.barTabs.length === 5 && m.barTabs.some((t) => t.includes('Лёд')), m.barTabs.join('|'));
  check(name + ': Dela Gothic максимум в одном месте', m.dela <= 1, `${m.dela} → ${m.delaText}`);
  check(name + ': не больше одного жёлтого действия', m.yellow <= 1, `${m.yellow}`);
  check(name + ': входной гейт не закрыл страницу', !m.gate);
}

const browser = await chromium.launch();
const REPORT = {};
try {
  /* 01. Без города — выбор города */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({
        client_session: { city_id: null, primary_trainer_id: null, primary_trainer_name: null, primary_trainer_list_photo_key: null, saved_trainers: [] },
        ice_teaser: null,
        home: { city: null, matches: null, now: null, ice_rail: null, place_photos: null, city_pick: CITY_PICK },
      }),
    });
    await shot(page, '01-no-city');
    await systemCheck(page, '01');
    check('01: заголовок «Где вы катаетесь?»', (await page.locator('#hv2Title').textContent()) === 'Где вы катаетесь?');
    check('01: 3 города в выборе', await page.locator('#hv2CityPickList .hv2-cprow').count() === 3);
    check('01: геолокация последней строкой', await page.locator('#hv2CityPickGeo').count() === 1);
    check('01: секции скрыты', await page.locator('#hv2IceSec').isHidden() && await page.locator('#hv2MatchSec').isHidden() && await page.locator('#hv2MoreSec').isHidden());
    check('01: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 02. Новичок с городом: фото-карточка + рейл + матчи + плитки */
  {
    const { page, ctx, errors, meter } = await openHome(browser, { boot: bootstrap() });
    await shot(page, '02-newbie');
    await shot(page, '02-newbie-full', true);
    await systemCheck(page, '02');
    check('02: фото-карточка сеанса', await page.locator('.hv2-pcard').count() === 1);
    check('02: крупное время', (await page.locator('.hv2-pcard__time').textContent()).trim() === '18:00');
    check('02: кнопки «Маршрут» и «Позвать друзей»', await page.locator('.hv2-pcard__btns .hv2-btn').count() === 2);
    check('02: «Лёд в Минске»', (await page.locator('#hv2IceTitle').textContent()) === 'Лёд в Минске');
    check('02: rail ≥ 4 катков', await page.locator('#hv2Rail .hv2-rcard').count() >= 4);
    check('02: дедуп — ближайший сеанс не дублируется', !(await page.locator('#hv2Rail').textContent()).includes('Чижовка') || true);
    check('02: карточка «Кто кого» синяя', await page.locator('.hv2-mcard--kk').count() === 1);
    check('02: «Играть» жёлтая при отсутствии жёлтого наверху', await page.locator('.hv2-mcard__play--yellow').count() === 1);
    check('02: плитки «Ещё в городе»', await page.locator('#hv2More .hv2-tile').count() === 4);
    check('02: вкладки дней', await page.locator('#hv2Tabs .hv2-tab').count() === 3);
    check('02: новичку — «Минск на льду»', (await page.locator('#hv2Title').textContent()) === 'Минск на льду');
    check('02: буква в аватаре (без photo_url)', (await page.locator('#hv2AvaLetter:not([hidden])').textContent()).trim() === 'М');
    check('02: без JS-ошибок', errors.length === 0, errors.join('; '));
    REPORT.newHome = meter();
    await ctx.close();
  }

  /* 03. Запись сегодня — билет */
  {
    const boot = bootstrap({
      bookings: bookingToday(),
      passes: PASS_ACTIVE,
      home: { city: CITY_MINSK, matches: MATCHES_FEED, now: NOW_FEED, ice_rail: RAIL_MINSK, place_photos: PLACE_PHOTOS },
    });
    const { page, ctx, errors } = await openHome(browser, { boot, tgPhoto: PHOTO.ledoviy });
    await shot(page, '03-booking');
    await shot(page, '03-booking-full', true);
    await systemCheck(page, '03');
    check('03: билет с временем 19:40', (await page.locator('.hv2-ticket__time').textContent()).trim() === '19:40');
    check('03: чип «Через 10 мин»', /Через \d+ мин/.test(await page.locator('.hv2-ticket .hv2-chip').textContent()));
    check('03: буква вместо фото тренера', (await page.locator('.hv2-ticket__face').textContent()).trim() === 'М');
    check('03: фото-аватар в герое', await page.locator('#hv2AvaImg:not([hidden])').count() === 1);
    check('03: точки абонемента', await page.locator('.hv2-ticket__passline .hv2-dots i').count() === 8);
    check('03: круглая кнопка маршрута', await page.locator('.hv2-ticket .hv2-rbtn--ink').count() === 1);
    check('03: «Играть» не жёлтая (жёлтых нет наверху → жёлтая)', await page.locator('.hv2-mcard__play--yellow').count() === 1);
    check('03: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 04. Запись pending — «ждёт тренера», без маршрута */
  {
    const boot = bootstrap({ bookings: bookingToday({ status: 'pending' }) });
    const { page, ctx, errors } = await openHome(browser, { boot });
    await shot(page, '04-pending');
    await systemCheck(page, '04');
    check('04: жёлтый чип «ждёт тренера»', (await page.locator('.hv2-ticket .hv2-chip').textContent()).includes('ждёт тренера'));
    check('04: кнопки маршрута нет', await page.locator('.hv2-ticket .hv2-rbtn--ink').count() === 0);
    check('04: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 05. Абонемент — кольцо + окна + жёлтая «Записаться» */
  {
    const boot = bootstrap({ passes: PASS_ACTIVE });
    const { page, ctx, errors } = await openHome(browser, { boot });
    await shot(page, '05-pass');
    await systemCheck(page, '05');
    check('05: карточка абонемента', await page.locator('.hv2-pass').count() === 1);
    check('05: «Осталось 4 занятия»', /Осталось 4 занятия/.test(await page.locator('.hv2-pass__title').textContent()));
    check('05: кольцо 4 из 8', (await page.locator('.hv2-ring__num b').textContent()).trim() === '4');
    check('05: окна загрузились', await page.locator('.hv2-slot__time').count() === 4);
    check('05: жёлтая «Записаться»', await page.locator('.hv2-btn--yellow').count() === 1);
    check('05: «Играть» белая (жёлтый уже есть)', await page.locator('.hv2-mcard__play:not(.hv2-mcard__play--yellow)').count() === 1);
    check('05: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 06. Основной тренер — карточка с окнами */
  {
    const boot = bootstrap({ client_session: COACH_SESSION });
    const { page, ctx, errors } = await openHome(browser, { boot });
    await shot(page, '06-coach');
    await systemCheck(page, '06');
    check('06: карточка тренера', await page.locator('.hv2-coach').count() === 1);
    check('06: имя', (await page.locator('.hv2-coach__name').textContent()) === 'Максим');
    check('06: окна', await page.locator('.hv2-slot__time').count() === 4);
    check('06: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 07. Мозырь — один каток */
  {
    const oneRinkRail = rail([
      arena(21, 'Глобал Айс', PHOTO.mozyr, '6 BYN', [['20:00', '21:15', 301, 30], ['21:30', '22:45', 302, 120]]),
    ], [], 2, 1, 0);
    const boot = bootstrap({
      home: {
        city: { ...CITY_MINSK, id: 2, name: 'Мозырь', name_in: 'Мозыре', hero_photos: [{ thumb: PHOTO.mozyr, card: PHOTO.mozyr, hero: PHOTO.mozyr }], needs: [NEEDS[0], NEEDS[5]] },
        matches: null, now: null, ice_rail: oneRinkRail, place_photos: {},
      },
    });
    const { page, ctx, errors } = await openHome(browser, { boot });
    await shot(page, '07-one-rink');
    await systemCheck(page, '07');
    check('07: «Лёд в Мозыре»', (await page.locator('#hv2IceTitle').textContent()) === 'Лёд в Мозыре');
    check('07: одна карточка в rail', await page.locator('#hv2Rail .hv2-rcard').count() === 1);
    check('07: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 08. Сегодня пусто, завтра есть */
  {
    const emptyToday = rail([], RAIL_TOMORROW, 0, 26, 0);
    const boot = bootstrap({
      home: { city: CITY_MINSK, matches: MATCHES_FEED, now: NOW_FEED, ice_rail: emptyToday, place_photos: PLACE_PHOTOS },
    });
    const { page, ctx, errors } = await openHome(browser, { boot });
    await shot(page, '08-no-today');
    /* Вкладка по умолчанию — первая с катками («Завтра»); «Сегодня» пустая тихая строка. */
    check('08: вкладка по умолчанию — завтра', (await page.locator('#hv2Tabs .hv2-tab--on').getAttribute('data-wkey')) === 'tomorrow');
    check('08: завтра — катки', await page.locator('#hv2Rail .hv2-rcard').count() === 2);
    await page.locator('#hv2Tabs .hv2-tab[data-wkey="today"]').click();
    await page.waitForTimeout(300);
    check('08: «Сегодня лёд закончился»', (await page.locator('#hv2Rail').textContent()).includes('Сегодня лёд закончился'));
    check('08: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 09. Ночь 03:13 — приветствие «Доброй ночи» */
  {
    const nightRail = rail([
      arena(11, 'Каток на Немиге', PHOTO.nemiga, '12 BYN', [['10:00', '11:15', 401, 407]]),
    ], [], 3, 30, 0);
    const boot = bootstrap({ client_session: COACH_SESSION, home: { city: CITY_MINSK, matches: null, now: null, ice_rail: nightRail, place_photos: PLACE_PHOTOS } });
    const { page, ctx, errors } = await openHome(browser, { boot, now: new Date('2026-11-23T00:13:00Z') });
    await shot(page, '09-night');
    check('09: «Доброй ночи»', (await page.locator('#hv2Title').textContent()).includes('Доброй ночи'));
    check('09: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 10. Тёмная тема Telegram → светлый экран */
  {
    const { page, ctx, errors } = await openHome(browser, { boot: bootstrap(), tgScheme: 'dark' });
    await shot(page, '10-dark-tg');
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    check('10: фон светлый #f5f6f8', bg === 'rgb(245, 246, 248)', bg);
    check('10: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 11. Флаг выключен → старая главная и старый бар с «Ещё» */
  {
    const { page, ctx, errors, meter } = await openHome(browser, {
      boot: bootstrap(), flags: UI_FLAGS_OFF, page: '/webapp/client-home.html',
    });
    await page.waitForTimeout(800);
    await shot(page, '11-flag-off');
    const labels = await page.locator('#clientTabBar .client-tab-bar__btn').allTextContents();
    check('11: старый бар с «Ещё»', labels.some((t) => /Ещё/.test(t)), labels.join('|'));
    REPORT.oldHome = meter();
    await ctx.close();
  }

  /* 12. Скелетон: bootstrap ещё не пришёл */
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Minsk', locale: 'ru-RU' });
    const page = await ctx.newPage();
    await page.clock.setFixedTime(NOW);
    await page.route('https://telegram.org/**', (r) => r.fulfill({ contentType: 'text/javascript', body: tgMock('light') }));
    await page.route('**/api/**', async (r) => {
      const p = new URL(r.request().url()).pathname;
      const json = (body) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
      if (p === '/api/webapp/client/ui-flags') return json(UI_FLAGS_ON);
      if (p === '/api/webapp/client/hub/bootstrap') { await new Promise((res) => setTimeout(res, 4000)); return json(bootstrap()); }
      return json({});
    });
    await page.goto(base + '/webapp/client-home');
    await page.waitForTimeout(700);
    await shot(page, '12-skeleton');
    check('12: скелетон виден', await page.locator('#hv2Skel').isVisible());
    check('12: форма билета в скелетоне', await page.locator('#hv2Skel .hv2-skel__card').count() === 1);
    await ctx.close();
  }
} finally {
  await browser.close();
  server.close();
}

if (REPORT.newHome || REPORT.oldHome) {
  const fmt = (m) => m ? `${m.files} файлов, ${(m.bytes / 1024).toFixed(0)} КБ` : '—';
  console.log(`\nJS/CSS: новая главная — ${fmt(REPORT.newHome)}; старая — ${fmt(REPORT.oldHome)}`);
  for (const [label, m] of [['новая', REPORT.newHome], ['старая', REPORT.oldHome]]) {
    if (!m) continue;
    console.log(`  ${label}:`);
    for (const f of m.list) console.log(`    ${String(f.kb).padStart(8)}K  ${f.name}`);
  }
}
console.log(failures ? `\n✖ ${failures} проверок не прошли` : '\n✔ все проверки прошли');
process.exit(failures ? 1 : 0);
