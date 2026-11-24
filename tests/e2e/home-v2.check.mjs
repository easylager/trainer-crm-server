/**
 * TASK-445 (glide-home-v1, этап 1): headless-проверка новой главной client-home-v2.
 * Статика static/ + стабы /api/* (Telegram и сеть не нужны).
 *
 * Сценарии (390×844, Europe/Minsk, «сейчас» зафиксировано на 19:30):
 *   newbie-no-city  — без города: карточка выбора города, «Лёд в городе» из тизера;
 *   newbie-city     — новичок с городом: фото-карточка ближайшего сеанса;
 *   booking-today   — запись сегодня: Билет с временем и «Маршрут»;
 *   pass            — активный абонемент: кольцо остатка;
 *   coach           — основной тренер: карточка тренера;
 *   empty-city      — город без сеансов: секции льда/матчей скрыты, «Ещё» на месте;
 *   matches         — город с матчами Экстралиги: секция «Матчи»;
 *   dark-tg         — тёмная тема Telegram: экраны остаются светлыми (#f5f6f8);
 *   flag-off        — redesign_s1=false: старый бар с «Ещё» (поведение как раньше).
 *
 * Run: node tests/e2e/home-v2.check.mjs
 * Скриншоты: tests/e2e/__shots__/home-v2/ (каталог в .gitignore)
 */
import { chromium } from 'playwright';
import http from 'node:http';
import { mkdirSync, rmSync, readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.join(here, '../../static');
const shots = path.join(here, '__shots__', 'home-v2');
rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });

const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.woff2': 'font/woff2',
};
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/') p = '/webapp/client-home-v2.html';
  const file = path.join(staticDir, p);
  if (!file.startsWith(staticDir) || !existsSync(file) || statSync(file).isDirectory()) {
    res.writeHead(404); res.end('no'); return;
  }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, r));
const base = 'http://localhost:' + server.address().port;

/* «Сейчас»: 4 октября 2026 (вс), 19:30 по Минску. */
const NOW = new Date('2026-10-04T16:30:00Z');
const TODAY = '2026-10-04';

function minskParts(date) {
  const f = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Minsk', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).reduce((a, p) => ({ ...a, [p.type]: p.value }), {});
  return { date: `${f.year}-${f.month}-${f.day}`, time: `${f.hour}:${f.minute}` };
}

function session(id, arenaId, name, minutesAhead, priceMinor) {
  const at = new Date(NOW.getTime() + minutesAhead * 60000);
  const m = minskParts(at);
  return {
    session_id: id, arena_id: arenaId, arena_slug: 'a' + arenaId, arena_name: name,
    venue_type: 'ice', kind: 'public_skate', starts_at_utc: at.toISOString(),
    local_date: m.date, starts_at_local: m.time,
    price_adult_minor: priceMinor, currency_code: 'BYN',
  };
}

const ICE_TEASER = {
  arena_id: 11, arena_slug: 'chizhovka', arena_name: 'Чижовка-арена',
  city_id: 1, city_name: 'Минск', kind: 'public_skate',
  starts_at_local: '20:00', local_date: TODAY, price_adult_minor: 1200, currency_code: 'BYN',
  thumb: null, card: null, distance_km: null,
  sessions: [
    session(101, 11, 'Чижовка-арена', 30, 1200),
    session(102, 12, 'Парк Горького', 75, 500),
    session(103, 13, 'Ледовый дворец', 120, 800),
  ],
  session_id: 101, is_country_fallback: false, far_confirmed: false,
};

const CITY_MINSK = {
  id: 1, name: 'Минск', kicker: '3 катка сегодня', counts_line: '3 катка',
  hero_photo: null, hero_photos: [],
  upcoming: [
    { time: '20:00', day: 'сегодня', badge: '20:00', place: 'Чижовка-арена', price: '12 BYN', arena_id: 11, session_id: 101, minutes_until: 30, href: 'arena?ref=11&s=101', photo: { thumb: null, card: null, hero: null }, invite_url: null },
    { time: '21:30', day: 'сегодня', badge: '21:30', place: 'Парк Горького', price: '5 BYN', arena_id: 12, session_id: 102, minutes_until: 75, href: 'arena?ref=12&s=102', photo: { thumb: null, card: null, hero: null }, invite_url: null },
    { time: '07:00', day: 'завтра', badge: 'завтра 07:00', place: 'Ледовый дворец', price: '8 BYN', arena_id: 13, session_id: 103, minutes_until: 690, href: 'arena?ref=13&s=103', photo: { thumb: null, card: null, hero: null }, invite_url: null },
  ],
  upcoming_href: 'ice?city_id=1&intent=skate&when=today', upcoming_more: 'Весь день',
  needs: [
    { key: 'skate', title: 'Покататься', line: '3 катка · расписание есть', href: 'ice?city_id=1&intent=skate', windows: [] },
    { key: 'ohm', title: 'С клюшкой', line: 'ОХМ на 2 катках · ближайший в 18:00', href: 'ice?city_id=1&intent=ohm', windows: [] },
    { key: 'matches', title: 'Хоккей', line: 'Матчи недели в Минске', href: 'client-matches?city=Минск', windows: [] },
    { key: 'coach', title: 'Учиться с тренером', line: '14 тренеров', href: 'trainers?city_id=1', windows: [] },
  ],
};

const CITY_ONE_RINK = {
  ...CITY_MINSK, id: 2, name: 'Мозырь', kicker: '1 каток сегодня',
  upcoming: [CITY_MINSK.upcoming[0]],
  needs: [CITY_MINSK.needs[0], CITY_MINSK.needs[3]],
};

const MATCHES_FEED = {
  week_count: 3,
  all_href: 'client-matches?city=Минск',
  matches: [
    {
      kind: 'extraliga', id: 501, href: 'client-match?id=501',
      home: { name: 'Динамо', short: 'ДИН', color: '#0047AB', logo: null },
      away: { name: 'Юность', short: 'ЮН', color: '#D0202E', logo: null },
      starts_at: '2026-10-04T16:00:00+00:00', arena: 'Минск-Арена', city: 'Минск',
      live: true, result: null, sticker: 'СЕГОДНЯ',
    },
    {
      kind: 'extraliga', id: 502, href: 'client-match?id=502',
      home: { name: 'Металлург', short: 'МЕТ', color: '#FFD241', logo: null },
      away: { name: 'Неман', short: 'НЕМ', color: '#2C4DD0', logo: null },
      starts_at: '2026-10-06T14:00:00+00:00', arena: 'Ледовый дворец', city: 'Жлобин',
      live: false, result: null, sticker: 'ЗАВТРА',
    },
  ],
};

const BOOKING_TODAY = {
  days: [{
    date: TODAY, day_label: 'вс',
    bookings: [{
      id: 501, status: 'confirmed', start_time: '18:15', end_time: '19:00', duration_minutes: 45,
      trainer_id: 7, trainer_name: 'Анна Коваль', service_name: 'Индивидуальное занятие',
      arena_name: 'Ледовый дворец', arena_id: 13, place_display: 'Ледовый дворец',
      map_link: 'https://yandex.ru/maps/?pt=27.5,53.9&z=16',
    }],
  }],
};

const PASS_ACTIVE = [{
  id: 9, pass_product_id: 4, status: 'active', is_expired: false,
  sessions_remaining: 6, sessions_total: 8,
  product_name: 'Абонемент 8 занятий', trainer_name: 'Анна Коваль',
  service_name: 'Индивидуальное занятие', trainer_id: 7,
  expires_at: '2026-12-01T00:00:00+00:00', issued_at: '2026-09-01T00:00:00+00:00',
}];

const COACH_SESSION = {
  city_id: 1, selected_trainer_id: 7, primary_trainer_id: 7,
  primary_trainer_name: 'Анна Коваль', primary_trainer_list_photo_key: null,
  saved_trainers: [], saved_trainer_ids: [], has_past_sessions: true,
};

function bootstrap(overrides) {
  return {
    bookings: { days: [] },
    requests: { items: [] },
    client_session: { city_id: 1, primary_trainer_id: null, primary_trainer_name: null, primary_trainer_list_photo_key: null, saved_trainers: [] },
    activity: { streak_weeks: 0, completed_total: 0 },
    passes: [],
    certificates: [],
    ice_teaser: ICE_TEASER,
    pending_referral: null,
    home: { city: CITY_MINSK, matches: null, now: null },
    platform: { vertical_key: 'ice', ui: {} },
    ...(overrides || {}),
  };
}

const UI_FLAGS_ON = { season_ui: false, bookings_tab: true, fast_tabs: false, search_board: false, redesign_s1: true };
const UI_FLAGS_OFF = { season_ui: false, bookings_tab: false, fast_tabs: false, search_board: false, redesign_s1: false };

function tgMock(colorScheme) {
  return `window.Telegram = { WebApp: {
    initData: 'mock', initDataUnsafe: { user: { id: 1, first_name: 'Максим' } }, colorScheme: '${colorScheme || 'light'}', themeParams: {},
    version: '7.0', platform: 'ios', isExpanded: true, viewportHeight: 844,
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

async function openHome(browser, { boot, flags, tgScheme }) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Minsk', locale: 'ru-RU' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|ERR_FAILED|net::/.test(m.text())) errors.push(m.text()); });
  await page.clock.setFixedTime(NOW);
  await page.route('https://telegram.org/**', (r) => r.fulfill({ contentType: 'text/javascript', body: tgMock(tgScheme) }));
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.route('**/api/**', (r) => {
    const url = new URL(r.request().url());
    const p = url.pathname;
    const json = (body) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (p === '/api/webapp/client/ui-flags') return json(flags || UI_FLAGS_ON);
    if (p === '/api/webapp/client/hub/bootstrap') return json(boot);
    if (p === '/api/webapp/client/profiles') return json({ items: [], default_profile_id: null });
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
    if (p.startsWith('/api/public/photos')) return r.fulfill({ status: 404, body: '' });
    return json({});
  });
  await page.goto(base + '/webapp/client-home-v2.html');
  await page.waitForSelector('#hv2Skel', { state: 'hidden', timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(400);
  return { page, ctx, errors };
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(shots, name + '.png'), fullPage: false });
}

/* Геометрия: без горизонтального скролла, бар из 5 вкладок «Лёд» на месте. */
async function layoutCheck(page, name) {
  const m = await page.evaluate(() => ({
    scrollW: document.documentElement.scrollWidth,
    innerW: window.innerWidth,
    barTabs: [...document.querySelectorAll('#clientTabBar .client-tab-bar__btn')].map((b) => b.textContent.trim()),
    barVisible: !!document.getElementById('clientTabBar'),
  }));
  check(name + ': нет горизонтального скролла', m.scrollW <= m.innerW, `${m.scrollW}>${m.innerW}`);
  check(name + ': бар — 5 вкладок с «Лёд»', m.barVisible && m.barTabs.length === 5 && m.barTabs.some((t) => t.includes('Лёд')), m.barTabs.join('|'));
}

const browser = await chromium.launch();
try {
  /* 1. Новичок без города */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({
        client_session: { city_id: null, primary_trainer_id: null, primary_trainer_name: null, primary_trainer_list_photo_key: null, saved_trainers: [] },
        home: { city: null, matches: null, now: null },
      }),
    });
    await shot(page, '01-newbie-no-city');
    await layoutCheck(page, 'no-city');
    check('no-city: карточка выбора города', await page.locator('.hv2-citypick').count() === 1);
    check('no-city: заголовок «Лёд рядом»', (await page.locator('#hv2Title').textContent()) === 'Лёд рядом');
    check('no-city: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 2. Новичок с городом: фото-карточка ближайшего сеанса */
  {
    const { page, ctx, errors } = await openHome(browser, { boot: bootstrap() });
    await shot(page, '02-newbie-city');
    await layoutCheck(page, 'city');
    check('city: фото-карточка сеанса', await page.locator('.hv2-photo').count() === 1);
    check('city: «Лёд в городе» с 3 строками', await page.locator('#hv2Ice .hv2-row').count() === 3);
    check('city: «Ещё» со строками needs', await page.locator('#hv2More .hv2-row').count() >= 3);
    check('city: город в шапке', (await page.locator('#hv2CityLabel').textContent()) === 'Минск');
    check('city: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 3. Запись сегодня → Билет */
  {
    const { page, ctx, errors } = await openHome(browser, { boot: bootstrap({ bookings: BOOKING_TODAY }) });
    await shot(page, '03-booking-today');
    await layoutCheck(page, 'booking');
    check('booking: билет с временем 18:15', await page.locator('.hv2-ticket__time').textContent() === '18:15');
    check('booking: «Маршрут» ведёт на yandex', await page.locator('[data-act="map"]').getAttribute('data-href').then((h) => /yandex/.test(h || '')));
    check('booking: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 4. Абонемент → кольцо остатка */
  {
    const { page, ctx, errors } = await openHome(browser, { boot: bootstrap({ passes: PASS_ACTIVE }) });
    await shot(page, '04-pass');
    check('pass: карточка абонемента', await page.locator('.hv2-pass').count() === 1);
    check('pass: остаток 6 из 8', (await page.locator('.hv2-pass__ring-num').textContent()).includes('6'));
    check('pass: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 5. Основной тренер → карточка тренера */
  {
    const { page, ctx, errors } = await openHome(browser, { boot: bootstrap({ client_session: COACH_SESSION }) });
    await shot(page, '05-coach');
    check('coach: карточка тренера', await page.locator('.hv2-coach').count() === 1);
    check('coach: имя тренера', (await page.locator('.hv2-coach__name').textContent()) === 'Анна Коваль');
    check('coach: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 6. Город без сеансов: секции льда и матчей скрыты */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({
        ice_teaser: null,
        home: { city: { ...CITY_ONE_RINK, upcoming: [], needs: CITY_MINSK.needs.slice(0, 2) }, matches: null, now: null },
      }),
    });
    await shot(page, '06-empty-city');
    check('empty: «Лёд в городе» скрыт', await page.locator('#hv2IceSec').isHidden());
    check('empty: «Матчи» скрыты', await page.locator('#hv2MatchSec').isHidden());
    check('empty: «Ещё» виден', await page.locator('#hv2MoreSec').isVisible());
    check('empty: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 7. Матчи города → секция «Матчи» */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({ home: { city: CITY_MINSK, matches: MATCHES_FEED, now: null } }),
    });
    await shot(page, '07-matches');
    await layoutCheck(page, 'matches');
    check('matches: секция видна', await page.locator('#hv2MatchSec').isVisible());
    check('matches: 2 строки', await page.locator('#hv2Matches .hv2-match').count() === 2);
    check('matches: «Все» → client-matches', (await page.locator('#hv2MatchMore').getAttribute('href')) === 'client-matches?city=Минск');
    check('matches: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 8. Тёмная тема Telegram → экран всё равно светлый */
  {
    const { page, ctx, errors } = await openHome(browser, { boot: bootstrap(), tgScheme: 'dark' });
    await shot(page, '08-dark-tg');
    await layoutCheck(page, 'dark-tg');
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    check('dark-tg: фон страницы светлый #f5f6f8', bg === 'rgb(245, 246, 248)', bg);
    check('dark-tg: html без tg-dark', await page.evaluate(() => !document.documentElement.classList.contains('tg-dark')));
    check('dark-tg: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 9. Флаг выключен → старый бар с «Ещё» */
  {
    const { page, ctx, errors } = await openHome(browser, { boot: bootstrap(), flags: UI_FLAGS_OFF });
    await page.waitForTimeout(600); // флаги с «сервера» применились
    const labels = await page.locator('#clientTabBar .client-tab-bar__btn').allTextContents();
    check('flag-off: старый бар с «Ещё»', labels.some((t) => /Ещё/.test(t)), labels.join('|'));
    check('flag-off: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }
} finally {
  await browser.close();
  server.close();
}

console.log(failures ? `\n✖ ${failures} проверок не прошли` : '\n✔ все проверки прошли');
process.exit(failures ? 1 : 0);
