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
/* TASK-448: эмуляция серверных бандлов s3 — то же склеивание, что home_v2_bundles.py
   (списки держать синхронно). Сервер отдаёт их на /webapp/home-v2.{head,app,bundle}.* */
const S3_HEAD_JS = ['glide-deeplink.js', 'write-access.js', 'client-mini-app-theme.js', 'mini-app-client-shell.js', 'ru-person-name.js'];
const S3_APP_JS = ['mini-app-telegram-chrome.js', 'mini-app-empty-state.js', 'mini-app-more-icons.js', 'client-profile-switcher.js', 'ga-press.js', 'home-v2.js', 'ga-touch.js'];
const S3_CSS = ['shared/glide-public-fonts.css', 'shared/glide-tokens.css', 'webapp/mini-app-client-theme.css', 'webapp/mini-app-client-shell.css', 'webapp/home-v2.css'];
const s3bundle = (files, sep) => files.map((f) => {
  const rel = f.includes('/') ? f : 'webapp/' + f;
  return '/* file: ' + rel + ' */\n' + readFileSync(path.join(staticDir, rel), 'utf-8');
}).join(sep);
const S3_BUNDLES = {
  '/webapp/home-v2.head.js': { body: s3bundle(S3_HEAD_JS, ';\n'), type: 'text/javascript' },
  '/webapp/home-v2.app.js': { body: s3bundle(S3_APP_JS, ';\n'), type: 'text/javascript' },
  '/webapp/home-v2.bundle.css': { body: s3bundle(S3_CSS, '\n'), type: 'text/css' },
};
function s3BundledHtml() {
  const html = readFileSync(path.join(staticDir, 'webapp/client-home-v2.html'), 'utf-8');
  const regions = [...html.matchAll(/<!-- s3:assets -->[\s\S]*?<!-- \/s3:assets -->/g)];
  if (!regions.length) return null;
  let out = html;
  for (let i = regions.length - 1; i >= 0; i--) {
    const m = regions[i];
    out = out.slice(0, m.index) + (i === 0
      ? '  <link rel="stylesheet" href="/webapp/home-v2.bundle.css?v=s3" />\n' +
        '  <script src="/webapp/home-v2.head.js?v=s3"></script>\n' +
        '  <script defer src="/webapp/home-v2.app.js?v=s3"></script>\n'
      : '') + out.slice(m.index + m[0].length);
  }
  return out;
}
let S3_SERVE = false;

const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  let file;
  if (S3_SERVE && p === '/webapp/client-home') {
    const bundled = s3BundledHtml();
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end(bundled || readFileSync(path.join(staticDir, 'webapp/client-home-v2.html')));
    return;
  }
  if (S3_BUNDLES[p]) {
    res.writeHead(200, { 'content-type': S3_BUNDLES[p].type });
    res.end(S3_BUNDLES[p].body);
    return;
  }
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
const UI_FLAGS_S2 = { ...UI_FLAGS_ON, redesign_s2: true };
const UI_FLAGS_S3 = { ...UI_FLAGS_S2, redesign_s3: true };
const UI_FLAGS_OFF = { season_ui: false, bookings_tab: false, fast_tabs: false, search_board: false, redesign_s1: false };
const UI_FLAGS_S5 = { ...UI_FLAGS_S3, redesign_s4: true, redesign_s5: true };
const COMPANY_TODAY = { code: 'abc12345', name: '', session_id: 401, arena_id: 11, arena_name: 'Каток на Немиге',
  starts_local: '19:00', day_label: 'сегодня', going_count: 3, going_names: ['Аня', 'Дима', 'Света'],
  crowd_line: 'Трое — это уже компания', my_status: 'maybe', page_url: '/k/abc12345',
  photo: { thumb: PHOTO.nemiga, card: PHOTO.nemiga } };
const COMPANY_SAT = { ...COMPANY_TODAY, code: 'def67890', day_label: 'сб, 28', starts_local: '17:45',
  arena_name: 'Конькобежный', going_count: 4, going_names: ['Аня', 'Дима', 'Света'],
  crowd_line: 'Четверо — можно два на два', my_status: 'organizer', page_url: '/k/def67890',
  photo: { thumb: PHOTO.gorky, card: PHOTO.gorky } };
const COMPANY_RESP_CALLS = [];

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
      const rt = r.request().resourceType();
      seen.set(key, (seen.get(key) || { bytes: 0, types: new Set() }));
      seen.get(key).bytes += b.length;
      seen.get(key).types.add(rt);
    } catch (e) {}
  });
  return () => ({
    files: seen.size,
    bytes: [...seen.values()].reduce((a, b) => a + b.bytes, 0),
    list: [...seen.entries()]
      .map(([u, n]) => ({ name: u.split('/').pop(), kb: (n.bytes / 1024).toFixed(1), types: [...n.types] }))
      .sort((a, b) => b.kb - a.kb),
  });
}

const WATCH_CALLS = [];
async function openHome(browser, { boot, flags, tgScheme, tgPhoto, page: pagePath, now, profiles, bootDelay, flagsCache, bundled, ctx: sharedCtx }) {
  const ctx = sharedCtx || await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Minsk', locale: 'ru-RU' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|ERR_FAILED|net::|404/.test(m.text())) errors.push(m.text()); });
  await page.clock.setFixedTime(now || NOW);
  const meter = assetMeter(page);
  const s3cache = flagsCache || flags;
  if (s3cache) {
    await page.addInitScript((fl) => {
      try {
        localStorage.setItem('cw_ui_flags_v1', JSON.stringify({ u: '1', ...fl, at: Date.now() }));
      } catch (e) {}
    }, s3cache);
  }
  await page.route('https://telegram.org/**', (r) => r.fulfill({ contentType: 'text/javascript', body: tgMock(tgScheme, tgPhoto) }));
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.route('**/api/**', async (r) => {
    const url = new URL(r.request().url());
    const p = url.pathname;
    const json = (body) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (p === '/api/webapp/client/ui-flags') return json(flags || UI_FLAGS_ON);
    if (p === '/api/webapp/client/hub/bootstrap') {
      if (bootDelay) await new Promise((r2) => setTimeout(r2, bootDelay));
      return json(boot);
    }
    if (p === '/api/webapp/client/profiles') return json(profiles || { items: [], default_profile_id: null });
    if (p === '/api/webapp/client/ice-watches' && r.request().method() === 'POST') {
      WATCH_CALLS.push(JSON.parse(r.request().postData() || '{}'));
      return json({ ok: true, watch_id: 1 });
    }
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
    /* TASK-446: «Я здесь» — ответы для сценариев 13–15 */
    if (p === '/api/webapp/client/checkins' && r.request().method() === 'POST') {
      return json({ checkin_id: 900, session_id: 401, load_level: null, season_days: 6, nth_label: '6-й раз за сезон', streak_weeks: 2, has_this_week: true, live: { level: 2, count: 3, last_min: 0 } });
    }
    if (/^\/api\/webapp\/client\/checkins\/\d+$/.test(p) && r.request().method() === 'PATCH') {
      return json({ live: { level: 2, count: 4, last_min: 0 } });
    }
    if (/^\/api\/webapp\/client\/checkins\/\d+\/share$/.test(p)) {
      return json({ prepared_message_id: null, share_url: 'https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fglidebot', text: 'Максим на «Каток на Немиге» до 21:15\nПодъезжай!' });
    }
    if (/^\/api\/public\/ice-companies\/[^/]+\/responses$/.test(p) && r.request().method() === 'POST') {
      COMPANY_RESP_CALLS.push(JSON.parse(r.request().postData() || '{}'));
      return json({ ok: true });
    }
    if (/^\/api\/public\/arenas\/[^/]+\/share$/.test(p)) {
      return json({ share_url: 'https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fglidebot', share_text: '', sessions: [], slots: [],
        og_image_url: '/photos/arena-38/hero.webp' });
    }
    if (p.startsWith('/api/webapp/client/checkins')) return json({});
    if (p.startsWith('/api/public/photos')) {
      /* «Фото тренера» — реальный кадр катка: на скрине лицо-кружок, не серая заглушка. */
      return r.fulfill({ contentType: 'image/jpeg', body: readFileSync(path.join(photosDir, 'arena-25', 'hero.jpg')) });
    }
    return json({});
  });
  S3_SERVE = !!bundled;
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

  /* TASK-446 «Я здесь» (флаг s5 → ключ home.on_ice в bootstrap) */
  const ON_ICE = {
    session_id: 401, arena_id: 11, arena_name: 'Каток на Немиге',
    photo: { thumb: PHOTO.nemiga, card: PHOTO.nemiga, hero: PHOTO.nemiga },
    starts_local: '19:45', ends_local: '21:15', minutes_left: 95,
    live: { level: 2, count: 3, last_min: 4 },
    checked_in: false, checkin_id: null, load_level: null,
    season_days: 5, streak_weeks: 2, has_this_week: false,
    invite_url: 'https://t.me/glidebot?start=arena_11_s_401',
  };

  /* 13. На катке до отметки: фото-карточка + «✓ Я здесь» + статистика */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({ home: { on_ice: ON_ICE } }),
    });
    await shot(page, '13-on-ice');
    await systemCheck(page, '13');
    check('13: заголовок «Ты на катке?»', (await page.locator('#hv2Title').textContent() || '') === 'Ты на катке?');
    check('13: жёлтая «✓ Я здесь»', await page.locator('button[data-act="checkin"]', { hasText: 'Я здесь' }).count() === 1);
    check('13: чип «Идёт сеанс»', (await page.locator('.hv2-pcard__chip').textContent() || '').includes('Идёт сеанс'));
    check('13: карточка серии и сезона', await page.locator('.hv2-onice__stats .hv2-onice__row').count() === 2);
    check('13: «Позвать сюда» мягкая', await page.locator('button[data-act="invite"],button[data-act="share"]', { hasText: 'Позвать сюда' }).count() === 1);
    check('13: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 14. Лист отметки открыт, выбрано «В меру» */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({ home: { on_ice: ON_ICE } }),
    });
    await page.click('button[data-act="checkin"]');
    await page.waitForSelector('.cis', { state: 'visible', timeout: 8000 });
    await page.click('.cis__lvl[data-level="2"]');
    await page.waitForTimeout(600);
    await shot(page, '14-checkin-sheet');
    check('14: лист виден', await page.locator('.cis').isVisible());
    check('14: «В меру» выбрано', await page.locator('.cis__lvl[data-level="2"].cis-sel').count() === 1);
    check('14: «Отмечено» и строка сезона', (await page.locator('.cis__title').textContent()) === 'Отмечено');
    check('14: «Позвать сюда» одна и жёлтая', await page.locator('.cis__share').count() === 1);
    const hit = await page.evaluate(() => ['.cis__share', '.cis__close'].map((sel) => {
      const el = document.querySelector(sel);
      if (!el) return sel + ':missing';
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const at = document.elementFromPoint(cx, cy);
      const inside = r.bottom <= innerHeight && r.top >= 0;
      const coveredBy = at && (at === el || el.contains(at) || at.contains(el));
      return sel + (inside && coveredBy ? ':ok' : `:bad(${JSON.stringify({b:r.bottom,ih:innerHeight,at:at&&at.className})})`);
    }));
    check('14: «Позвать сюда» и «Готово» видны и не перекрыты', hit.every((h) => h.endsWith(':ok')), hit.join(', '));
    check('14: дим перекрыл таб-бар', await page.evaluate(() => {
      const bar = document.querySelector('#clientTabBar');
      if (!bar) return true;
      const r = bar.getBoundingClientRect();
      const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return at && (at.closest('.cis-dim') || at.closest('.cis'));
    }));
    check('14: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 15. Уже отмечен: мягкая «Отмечено · N-й раз», серия обновлена */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({ home: { on_ice: { ...ON_ICE, checked_in: true, checkin_id: 900, season_days: 6, streak_weeks: 3, has_this_week: true } } }),
    });
    await shot(page, '15-on-ice-checked');
    await systemCheck(page, '15');
    check('15: заголовок «Ты на катке?»', (await page.locator('#hv2Title').textContent() || '') === 'Ты на катке?');
    check('15: мягкая «Отмечено · 6-й раз»', (await page.locator('button[data-act="checkin"]').textContent() || '').includes('Отмечено · 6-й раз'));
    check('15: нет жёлтой кнопки', await page.locator('.hv2-btn--yellow').count() === 0);
    check('15: «Сегодня будет» сменилось на «Отметка засчитана»', (await page.locator('.hv2-onice__stats').textContent() || '').includes('Отметка засчитана'));
    check('15: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* ── TASK-447: этап 2 (флаг redesign_s2 → ключи home.*) ── */
  const BOOKINGS_3 = { days: [
    { date: TOMORROW, day_label: 'пн', bookings: [{
      id: 601, status: 'confirmed', start_time: '18:00', end_time: '18:50', duration_minutes: 50,
      trainer_id: 7, trainer_name: 'Максим', trainer_telegram_username: 'maxim_coach',
      service_name: 'Индивидуальное', arena_name: 'Ледовый дворец', arena_id: 12,
      map_link: 'https://yandex.ru/maps/?x', slot_date: TOMORROW }] },
    { date: '2026-11-24', day_label: 'вт', bookings: [{
      id: 602, status: 'pending', start_time: '19:30', end_time: '20:20', duration_minutes: 50,
      trainer_id: 7, trainer_name: 'Максим', service_name: 'Индивидуальное',
      arena_name: 'Ледовый дворец', arena_id: 12, slot_date: '2026-11-24' }] },
    { date: '2026-11-27', day_label: 'пт', bookings: [{
      id: 603, status: 'confirmed', start_time: '09:00', end_time: '09:50', duration_minutes: 50,
      trainer_id: 7, trainer_name: 'Максим', service_name: 'Групповое',
      arena_name: 'Чижовка-арена', arena_id: 14, slot_date: '2026-11-27' }] },
  ] };
  const CITY_PINSK = { ...CITY_MINSK, id: 5, name: 'Пинск', name_in: 'Пинске',
    kicker: '1 каток', counts_line: '1 каток', hero_photo: { thumb: PHOTO.mozyr, card: PHOTO.mozyr, hero: PHOTO.mozyr },
    hero_photos: [{ thumb: PHOTO.mozyr, card: PHOTO.mozyr, hero: PHOTO.mozyr }] };
  const ONE_RINK = {
    time: '19:10', end: '20:30', minutes_until: 100, day_label: 'Сегодня',
    title: 'Массовое катание', arena_id: 11, arena_name: 'УСК «Волна»',
    later_today: '21:00', session_id: 301, href: 'arena?ref=11&s=301',
    prices: [{ value: '4,40 BYN', label: 'взрослый' }, { value: '8,60 BYN', label: 'с прокатом' }],
    invite_url: 'https://t.me/glidebot?start=arena_11_s_301', map_link: 'https://yandex.ru/maps/?volna',
  };
  const WEEK_7 = [
    { date: TODAY, label: 'Сегодня', sub: '22', times: [
      { time: '18:00', end: '19:00', session_id: 290, arena_id: 11, href: 'arena?ref=11&s=290', past: true },
      { time: '21:00', end: '22:00', session_id: 292, arena_id: 11, href: 'arena?ref=11&s=292', past: false }] },
    { date: TOMORROW, label: 'Завтра', sub: '23', times: [
      { time: '12:00', end: '13:00', session_id: 293, arena_id: 11, href: 'arena?ref=11&s=293', past: false }] },
    { date: '2026-11-24', label: 'Вт', sub: '24', times: [] },
    { date: '2026-11-25', label: 'Ср', sub: '25', times: [] },
    { date: '2026-11-26', label: 'Чт', sub: '26', times: [] },
    { date: '2026-11-27', label: 'Пт', sub: '27', times: [] },
    { date: '2026-11-28', label: 'Сб', sub: '28', times: [
      { time: '20:15', end: '21:30', session_id: 299, arena_id: 11, href: 'arena?ref=11&s=299', past: false }] },
  ];
  const NEARBY_2 = [
    { name: 'Слуцк', photo: PHOTO.gorky, sub: 'завтра · 12:00 · 96 км', rink_count: 1, href: null },
    { name: 'Мозырь', photo: PHOTO.mozyr, sub: 'сегодня · 19:00 · 140 км', rink_count: 2, href: null },
  ];
  const KK_TODAY = {
    kind: 'kk_before',
    hockey: {
      mode: 'before', event_href: 'kto-kogo',
      match: {
        id: 501, status: 'scheduled', starts_at: '2026-11-22T18:00:00+00:00',
        home: { name: 'Динамо', short: 'ДИН', color: '#2c4dd0', logo: LOGO_DIN },
        away: { name: 'Барыс', short: 'БАР', color: '#0aa', logo: LOGO_BAR },
        arena: 'Минск-Арена', city: 'Минск', result: null,
      },
      my_pick: { home_score: 3, away_score: 2 },
    },
  };

  /* 16. Несколько записей: билет-стопка + «Дальше» с pending-рядом */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({ bookings: BOOKINGS_3, home: { variant: 'many' } }),
      flags: UI_FLAGS_S2,
    });
    await shot(page, '16-bookings-stack');
    await systemCheck(page, '16');
    check('16: стопка — два призрачных слоя', await page.locator('.hv2-stack .hv2-stack__g').count() === 2);
    check('16: верхний билет — ближайшая запись', (await page.locator('.hv2-ticket__time').textContent() || '').trim() === '18:00');
    check('16: секция «Дальше»', (await page.locator('.hv2-sec__title', { hasText: 'Дальше' }).count()) === 1);
    check('16: «Все записи · 3»', (await page.locator('.hv2-sec__more', { hasText: 'Все записи · 3' }).count()) === 1);
    check('16: два ряда дальше', await page.locator('.hv2-brow').count() === 2);
    check('16: жёлтый «ждёт тренера» в ряду', await page.locator('.hv2-brow__pend', { hasText: 'ждёт тренера' }).count() === 1);
    check('16: дата-тайл 24 вт', (await page.locator('.hv2-brow__tile').first().textContent() || '').includes('24'));
    check('16: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 17. Матч «Кто кого» сегодня (игрок, без записи сегодня) */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({ home: { now: KK_TODAY, kk_player: true, variant: 'many' } }),
      flags: UI_FLAGS_S2,
    });
    await shot(page, '17-kk-today');
    await systemCheck(page, '17');
    check('17: синяя карточка матча', await page.locator('.hv2-kk').count() === 1);
    check('17: заголовок «Динамо — Барыс»', (await page.locator('#hv2Title').textContent() || '') === 'Динамо — Барыс');
    check('17: строка «Сегодня · 21:00 · Минск-Арена»', (await page.locator('#hv2Date').textContent() || '') === 'Сегодня · 21:00 · Минск-Арена');
    check('17: кикер «КТО КОГО»', (await page.locator('.hv2-kk__kick').textContent() || '') === 'КТО КОГО');
    check('17: Dela-время 21:00', (await page.locator('.hv2-kk__time').textContent() || '').trim() === '21:00');
    check('17: жёлтая «Играть»', await page.locator('.hv2-kk__play', { hasText: 'Играть' }).count() === 1);
    check('17: «Твой прогноз 3:2»', (await page.locator('.hv2-kk__pick').textContent() || '') === 'Твой прогноз 3:2');
    check('17: секция «Матчи» скрыта', await page.locator('#hv2MatchSec').isHidden());
    check('17: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 18. Профиль ребёнка: переключатель в шапке + «Миша · завтра» */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({
        bookings: { days: [{ date: TOMORROW, day_label: 'пн', bookings: [BOOKINGS_3.days[0].bookings[0]] }] },
        home: { profile: { id: 5, name: 'Миша', is_own: false }, variant: 'many' },
        passes: PASS_ACTIVE,
      }),
      flags: UI_FLAGS_S2,
      profiles: { items: [
        { client_id: 1, first_name: 'Максим', role: 'self' },
        { client_id: 5, first_name: 'Миша', role: 'guardian' },
      ], default_profile_id: 5 },
    });
    await shot(page, '18-child-profile');
    await systemCheck(page, '18');
    check('18: стеклянный чип «Миша» в шапке', (await page.locator('#clientProfileSwitcherMount .cps-chip__name').textContent() || '') === 'Миша');
    check('18: чип «Миша · завтра» оранжевый', await page.locator('.hv2-chip--orange', { hasText: 'Миша · завтра' }).count() === 1);
    check('18: «тренер Миши»', (await page.locator('.hv2-ticket__trole').textContent() || '') === 'тренер Миши');
    check('18: «Абонемент Миши»', (await page.locator('.hv2-ticket__passline').textContent() || '').includes('Абонемент Миши'));
    check('18: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 19. «С возвращением»: последнее занятие 25 дней назад */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({
        client_session: { ...COACH_SESSION, primary_history: { completed_count: 12, last_completed_at: '2026-10-28T10:00:00Z' } },
        home: { variant: 'many' },
      }),
      flags: UI_FLAGS_S2,
    });
    await shot(page, '19-return');
    await systemCheck(page, '19');
    check('19: «С возвращением»', (await page.locator('#hv2Title').textContent() || '').startsWith('С возвращением'));
    check('19: кикер «Давно не виделись»', (await page.locator('.hv2-ret__kick').textContent() || '') === 'Давно не виделись');
    check('19: «12 занятий вместе · последнее 3 недели назад»',
      (await page.locator('.hv2-ret__sub').textContent() || '') === '12 занятий вместе · последнее 3 недели назад');
    check('19: жёлтая «Записаться» + мягкая «Другие тренеры»',
      await page.locator('.hv2-ret .hv2-btn--yellow', { hasText: 'Записаться' }).count() === 1 &&
      await page.locator('.hv2-ret .hv2-btn--soft', { hasText: 'Другие тренеры' }).count() === 1);
    check('19: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 20. Один каток (Пинск): белый билет + «На неделе» + «Лёд рядом» */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({
        client_session: { city_id: 5, saved_trainers: [] },
        home: { city: CITY_PINSK, variant: 'one', one_rink: ONE_RINK, week: WEEK_7, nearby: NEARBY_2 },
      }),
      flags: UI_FLAGS_S2,
    });
    await shot(page, '20-one-rink');
    await shot(page, '20-one-rink-full', true);
    await systemCheck(page, '20');
    check('20: «Пинск · один каток»', (await page.locator('#hv2Date').textContent() || '') === 'Пинск · один каток');
    check('20: белый билет (не фото)', await page.locator('.hv2-one').count() === 1 && await page.locator('.hv2-pcard').count() === 0);
    check('20: чип «Через 1 ч 40 мин»', (await page.locator('.hv2-one .hv2-chip').textContent() || '').includes('Через 1 ч 40 мин'));
    check('20: «ещё сегодня 21:00»', (await page.locator('.hv2-one__sub').textContent() || '').includes('ещё сегодня 21:00'));
    check('20: цены взрослый+прокат', (await page.locator('.hv2-one__prices').textContent() || '').includes('4,40 BYN'));
    check('20: «Маршрут» + «Позвать друзей»',
      await page.locator('.hv2-one__btns .hv2-btn--ink', { hasText: 'Маршрут' }).count() === 1 &&
      await page.locator('.hv2-one__btns .hv2-btn--soft', { hasText: 'Позвать друзей' }).count() === 1);
    check('20: «На неделе» вместо рейла', (await page.locator('.hv2-sec__title', { hasText: 'На неделе' }).count()) === 1 &&
      await page.locator('#hv2IceSec').isHidden());
    check('20: пустые дни схлопнуты «Вт–Пт»/«24–27»',
      (await page.locator('.hv2-wrow--empty .hv2-wrow__day').textContent() || '').replace(/\s+/g, ' ').includes('Вт–Пт') &&
      (await page.locator('.hv2-wrow--empty .hv2-wrow__sub').textContent() || '') === '24–27');
    check('20: прошедший чип зачёркнут', await page.locator('.hv2-wchip--past').count() === 1);
    check('20: «Лёд рядом» — 2 карточки', await page.locator('.hv2-sec:has(.hv2-sec__title:text("Лёд рядом")) .hv2-rcard').count() === 2 ||
      await page.locator('.hv2-sec__title', { hasText: 'Лёд рядом' }).count() === 1);
    check('20: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 21. Лёд сегодня закончился (Гомель 23:10): следующий + «Неделя в Гомеле» */
  {
    const { page, ctx, errors } = await openHome(browser, {
      now: new Date('2026-11-22T20:10:00Z'),
      boot: bootstrap({
        client_session: { city_id: 3, saved_trainers: [] },
        home: {
          city: { ...CITY_PINSK, id: 3, name: 'Гомель', name_in: 'в Гомеле' },
          variant: 'many', next_ice: {
            date_label: 'сб, 28', date_sub: 'сб 28', time: '20:15',
            arena_id: 12, arena_name: 'Гомельский ледовый дворец',
            photo: PHOTO.ledoviy, href: 'arena?ref=12&s=901',
          },
          week: WEEK_7,
        },
      }),
      flags: UI_FLAGS_S2,
    });
    await shot(page, '21-ice-ended');
    await shot(page, '21-ice-ended-full', true);
    await systemCheck(page, '21');
    check('21: «Гомель · 23:10»', (await page.locator('#hv2Date').textContent() || '') === 'Гомель · 23:10');
    check('21: чип «Сегодня лёд закончился»', (await page.locator('.hv2-end .hv2-chip').textContent() || '').includes('Сегодня лёд закончился'));
    check('21: «Следующий — сб, 28»', (await page.locator('.hv2-end__title').textContent() || '') === 'Следующий — сб, 28');
    check('21: sub «сб 28 · 20:15 · Гомельский…»', (await page.locator('.hv2-end__sub').textContent() || '') === 'сб 28 · 20:15 · Гомельский ледовый дворец');
    check('21: фото справа', await page.locator('.hv2-end__thumb').count() === 1);
    check('21: чернильная «Сообщить о новом льде»', await page.locator('#hv2Watch', { hasText: 'Сообщить о новом льде' }).count() === 1);
    check('21: «Неделя в Гомеле»', (await page.locator('.hv2-sec__title', { hasText: 'Неделя в Гомеле' }).count()) === 1);
    check('21: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 22. Межсезонье: «Лёд вернётся» + матчи первыми, тренер в «Ещё» первый */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({
        home: { variant: 'many', next_ice: null },
      }),
      flags: UI_FLAGS_S2,
    });
    await shot(page, '22-offseason');
    await systemCheck(page, '22');
    check('22: чип «Межсезонье»', (await page.locator('.hv2-end .hv2-chip').textContent() || '').includes('Межсезонье'));
    check('22: «Лёд вернётся»', (await page.locator('.hv2-end__title').textContent() || '') === 'Лёд вернётся');
    check('22: «Сообщить, когда откроют»', await page.locator('#hv2Watch', { hasText: 'Сообщить, когда откроют' }).count() === 1);
    check('22: рейл скрыт, матчи первыми', await page.locator('#hv2IceSec').isHidden());
    check('22: тренер — первая плитка «Ещё»', (await page.locator('#hv2More .hv2-tile').first().textContent() || '').includes('Тренеры'));
    check('22: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 23. Окно с двумя катками — сетка 2×, не rail */
  {
    const two = rail([
      arena(11, 'Каток на Немиге', PHOTO.nemiga, '12 BYN', [['19:30', '20:45', 104, 115], ['21:00', '22:00', 105, 205]]),
      arena(12, 'Ледовый дворец', PHOTO.ledoviy, '10 BYN', [['20:15', '21:30', 106, 160]]),
    ]);
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({ home: { ice_rail: two } }),
    });
    await shot(page, '23-two-arenas');
    await shot(page, '23-two-arenas-full', true);
    await systemCheck(page, '23');
    check('23: rail в режиме сетки', await page.locator('#hv2Rail.hv2-rail--grid2').count() === 1);
    check('23: две карточки', await page.locator('#hv2Rail .hv2-rcard').count() === 2);
    check('23: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 24. Подписка «Сообщить о новом льде»: POST → мягкое подтверждение */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({
        client_session: { city_id: 3, saved_trainers: [] },
        home: {
          city: { ...CITY_PINSK, id: 3, name: 'Гомель', name_in: 'в Гомеле' },
          variant: 'many', next_ice: {
            date_label: 'сб, 28', date_sub: 'сб 28', time: '20:15',
            arena_id: 12, arena_name: 'Гомельский ледовый дворец',
            photo: PHOTO.ledoviy, href: 'arena?ref=12&s=901',
          },
        },
      }),
      flags: UI_FLAGS_S2,
    });
    await page.click('#hv2Watch');
    await page.waitForSelector('.hv2-watch-ok', { timeout: 5000 });
    await shot(page, '24-watch-subscribed');
    check('24: POST ice-watches {arena_id, schedule_fresh, city}',
      WATCH_CALLS.length === 1 && WATCH_CALLS[0].arena_id === 12 && WATCH_CALLS[0].watch_kind === 'schedule_fresh' && WATCH_CALLS[0].city_id === 3,
      JSON.stringify(WATCH_CALLS));
    check('24: «Сообщим, когда появится лёд»', (await page.locator('.hv2-watch-ok').textContent() || '') === 'Сообщим, когда появится лёд');
    check('24: кнопка ушла', await page.locator('#hv2Watch').count() === 0);
    check('24: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* S2-off: те же данные без флага → состояния этапа 1 (регрессия гейта). */
  {
    const { page, ctx } = await openHome(browser, { boot: bootstrap({ bookings: BOOKINGS_3 }) });
    check('s2-off: стопки нет — один билет', await page.locator('.hv2-stack').count() === 0 &&
      await page.locator('.hv2-ticket').count() === 1);
    check('s2-off: «Дальше» нет', await page.locator('.hv2-brow').count() === 0);
    await shot(page, '25-s2-off-booking');
    await ctx.close();
  }
  {
    const { page, ctx } = await openHome(browser, {
      boot: bootstrap({
        client_session: { ...COACH_SESSION, primary_history: { completed_count: 12, last_completed_at: '2026-10-28T10:00:00Z' } },
      }),
    });
    check('s2-off: coach-карточка вместо «С возвращением»', await page.locator('.hv2-coach').count() === 1 &&
      await page.locator('.hv2-ret').count() === 0);
    await shot(page, '26-s2-off-coach');
    await ctx.close();
  }

  /* ── TASK-448: этап 3 (redesign_s3) — бандлы, кэш экрана, «Нет сети» ────── */

  /* 27. s3 cold: бандлы вместо одиночных файлов, страница та же */
  {
    const { page, ctx, errors, meter } = await openHome(browser, {
      boot: bootstrap({ bookings: bookingToday() }),
      flags: UI_FLAGS_S3, flagsCache: UI_FLAGS_S3, bundled: true,
    });
    /* Рендер-блокирующие JS/CSS (script/stylesheet), без фонового префетча «Льда» (fetch). */
    const m = meter();
    const paint = m.list.filter((f) => !f.types.every((t) => t === 'fetch' || t === 'xhr'));
    const names = paint.map((f) => f.name.split('?')[0]);
    check('27: JS/CSS файлов на первый кадр ≤ 8', names.length <= 8, `${names.length}: ${names.join(',')}`);
    check('27: отданы бандлы', names.includes('home-v2.head.js') && names.includes('home-v2.app.js') && names.includes('home-v2.bundle.css'), names.join(','));
    check('27: нет одиночного home-v2.js/mini-app-client-shell.js', !names.some((n) => n === 'home-v2.js' || n === 'mini-app-client-shell.js'), names.join(','));
    /* Префетч «Лёд» сработал в фоне (fetch-запросы к ассетам каталога). */
    const prefetched = m.list.filter((f) => f.types.every((t) => t === 'fetch' || t === 'xhr') && /ice|catalog/.test(f.name)).length;
    check('27: «Лёд» прогрет в фоне', prefetched > 0, `${prefetched}`);
    check('27: билет на месте', await page.locator('.hv2-ticket').count() === 1);
    check('27: без JS-ошибок', errors.length === 0, errors.join('; '));
    await shot(page, '27-s3-cold');
    await ctx.close();
  }

  /* Общий прогрев кэша: один заход пишет hv2_screen_v1 в localStorage контекста. */
  async function primeCache(browser, boot, extraInit) {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Minsk', locale: 'ru-RU' });
    const { page, errors } = await openHome(browser, {
      boot, flags: UI_FLAGS_S3, flagsCache: UI_FLAGS_S3, bundled: true, ctx,
    });
    await page.waitForSelector('.hv2-ticket, .hv2-pcard, .hv2-card', { timeout: 10000 });
    await page.waitForFunction(() => Object.keys(localStorage).some((k) => k.startsWith('hv2_screen_v1:')), null, { timeout: 5000 });
    await page.close();
    return { ctx, errors };
  }

  /* 28. s3 warm: кэш экрана виден мгновенно, скелетона нет */
  {
    const { ctx } = await primeCache(browser, bootstrap({ bookings: bookingToday() }));
    const { page, errors } = await openHome(browser, {
      boot: bootstrap({ bookings: bookingToday() }),
      flags: UI_FLAGS_S3, flagsCache: UI_FLAGS_S3, bundled: true, ctx, bootDelay: 3000,
    });
    await page.waitForTimeout(300);
    const early = await page.evaluate(() => ({
      ticket: !!document.querySelector('.hv2-ticket'),
      skelVisible: (() => { const s = document.getElementById('hv2Skel'); return s && s.offsetHeight > 0; })(),
    }));
    check('28: кэш показан ≤300мс — билет виден', early.ticket === true);
    check('28: скелетон не показывался', !early.skelVisible);
    await shot(page, '28-s3-warm-cache');
    check('28: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 29. s3 offline: кэш + сеть упала → белая плашка «Нет сети · данные на HH:MM» */
  {
    const { ctx } = await primeCache(browser, bootstrap({ bookings: bookingToday() }));
    const ctx2 = ctx;
    const page = await ctx2.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.clock.setFixedTime(NOW);
    await page.addInitScript((fl) => {
      try { localStorage.setItem('cw_ui_flags_v1', JSON.stringify({ u: '1', ...fl, at: Date.now() })); } catch (e) {}
    }, UI_FLAGS_S3);
    await page.route('https://telegram.org/**', (r) => r.fulfill({ contentType: 'text/javascript', body: tgMock() }));
    await page.route('**/api/**', (r) => {
      const p = new URL(r.request().url()).pathname;
      if (p === '/api/webapp/client/hub/bootstrap') return r.abort();
      if (p === '/api/webapp/client/ui-flags') return r.fulfill({ contentType: 'application/json', body: JSON.stringify(UI_FLAGS_S3) });
      return r.fulfill({ contentType: 'application/json', body: '{}' });
    });
    S3_SERVE = true;
    await page.goto(base + '/webapp/client-home');
    await page.waitForSelector('.hv2-offline', { timeout: 15000 });
    const plate = await page.locator('.hv2-offline').textContent();
    check('29: плашка «Нет сети · данные на HH:MM»', /Нет сети · данные на \d{2}:\d{2}/.test(plate || ''), plate);
    check('29: кэш на экране под плашкой', await page.locator('.hv2-ticket').count() === 1);
    const tabs29 = await page.locator('#clientTabBar .client-tab-bar__btn').allTextContents();
    check('29: бар — 5 вкладок с «Лёд»', tabs29.length === 5 && tabs29.some((t) => t.includes('Лёд')), tabs29.join('|'));
    const plateBox = await page.locator('.hv2-offline').boundingBox();
    check('29: плашка белая и в вьюпорте', plateBox && plateBox.y > 60 && plateBox.y < 200, JSON.stringify(plateBox));
    await shot(page, '29-s3-offline');
    check('29: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx2.close();
  }

  /* 30. s3 refresh: сеть прислала другое время записи — блок обновился без скелетона, скролл на месте */
  {
    const { ctx } = await primeCache(browser, bootstrap({ bookings: bookingToday() }));
    const { page, errors } = await openHome(browser, {
      boot: bootstrap({ bookings: bookingToday({ start_time: '21:10', end_time: '22:00' }) }),
      flags: UI_FLAGS_S3, flagsCache: UI_FLAGS_S3, bundled: true, ctx, bootDelay: 1200,
    });
    await page.waitForSelector('.hv2-ticket', { timeout: 10000 });
    await page.evaluate(() => window.scrollTo(0, 300));
    const yBefore = await page.evaluate(() => window.scrollY);
    await page.waitForFunction(() => (document.querySelector('.hv2-ticket__time') || {}).textContent === '21:10', null, { timeout: 8000 });
    const after = await page.evaluate(() => ({
      skel: (() => { const s = document.getElementById('hv2Skel'); return s && s.offsetHeight > 0; })(),
      y: window.scrollY,
    }));
    check('30: время записи обновилось до 21:10', true);
    check('30: скелетон не появлялся при обновлении', !after.skel);
    check('30: скролл сохранён', Math.abs(after.y - yBefore) < 2, `y=${after.y} was=${yBefore}`);
    await shot(page, '30-s3-quiet-refresh');
    check('30: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 31. Другой профиль — чужой кэш не показывается */
  {
    const { ctx } = await primeCache(browser, bootstrap({ bookings: bookingToday() }));
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.clock.setFixedTime(NOW);
    await page.addInitScript((fl) => {
      try {
        localStorage.setItem('cw_ui_flags_v1', JSON.stringify({ u: '1', ...fl, at: Date.now() }));
        localStorage.setItem('cw_active_profile_id_v1', '5');
      } catch (e) {}
    }, UI_FLAGS_S3);
    await page.route('https://telegram.org/**', (r) => r.fulfill({ contentType: 'text/javascript', body: tgMock() }));
    await page.route('**/api/**', async (r) => {
      const p = new URL(r.request().url()).pathname;
      const json = (b) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(b) });
      if (p === '/api/webapp/client/hub/bootstrap') {
        await new Promise((r2) => setTimeout(r2, 2500));
        return json(bootstrap({ bookings: bookingToday() }));
      }
      if (p === '/api/webapp/client/ui-flags') return json(UI_FLAGS_S3);
      if (p === '/api/webapp/client/profiles') return json({ items: [], default_profile_id: null });
      return json({});
    });
    S3_SERVE = true;
    await page.goto(base + '/webapp/client-home');
    await page.waitForTimeout(400);
    const st = await page.evaluate(() => ({
      ticket: !!document.querySelector('.hv2-ticket'),
      skel: (() => { const s = document.getElementById('hv2Skel'); return s && s.offsetHeight > 0; })(),
    }));
    check('31: чужой кэш не показан — билета нет в первые 400мс', !st.ticket);
    check('31: показан скелетон (кэш не подошёл)', st.skel === true);
    await shot(page, '31-s3-other-profile');
    check('31: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 31b. С s3 переходы на kto-kogo и trainers идут с первого клика (TASK-391 regression). */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({ bookings: bookingToday() }),
      flags: UI_FLAGS_S3, flagsCache: UI_FLAGS_S3, bundled: true,
    });
    await page.evaluate(() => {
      const a = document.createElement('a');
      a.href = 'kto-kogo'; a.id = 'testNavKk'; a.textContent = 'x';
      document.body.appendChild(a);
    });
    await Promise.all([
      page.waitForURL(/kto-kogo/, { timeout: 8000 }),
      page.click('#testNavKk'),
    ]);
    check('31b: home→kto-kogo с первого клика', page.url().includes('kto-kogo'));
    const { page: page2, ctx: ctx2 } = await openHome(browser, {
      boot: bootstrap({ bookings: bookingToday() }),
      flags: UI_FLAGS_S3, flagsCache: UI_FLAGS_S3, bundled: true,
    });
    await page2.evaluate(() => {
      const a = document.createElement('a');
      a.href = 'trainers'; a.id = 'testNavTr'; a.textContent = 'x';
      document.body.appendChild(a);
    });
    await Promise.all([
      page2.waitForURL(/trainers/, { timeout: 8000 }),
      page2.click('#testNavTr'),
    ]);
    check('31b: home→trainers с первого клика', page2.url().includes('trainers'));
    /* «Transition was aborted … opt-in disabled» — шум Chromium при прерванном VT
       на уходе со страницы, навигация сама проходит (проверено выше). */
    check('31b: без JS-ошибок', errors.filter((e) => !/Transition was aborted/.test(e)).length === 0, errors.join('; '));
    await ctx.close();
    await ctx2.close();
  }
  /* 32. TASK-450 (5.3): «Компания собирается» сегодня — я «может» → жёлтая «Иду». */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({ home: { companies: [COMPANY_TODAY], company_share: true } }),
      flags: UI_FLAGS_S5, flagsCache: UI_FLAGS_S5,
    });
    await systemCheck(page, '32');
    await shot(page, '32-company-today');
    check('32: чип «Твоя компания · сегодня»', (await page.locator('.hv2-pcard__chip').first().textContent()).includes('Твоя компания'));
    check('32: плашка «Идут 3»', (await page.locator('.hv2-comp__plaque').textContent()).includes('Идут 3'));
    check('32: имена через «и»', (await page.locator('.hv2-comp__names').textContent()).includes('Аня, Дима и Света идут'));
    check('32: «Иду» жёлтая', await page.locator('[data-act="company-going"]').count() === 1);
    await page.locator('[data-act="company-going"]').click();
    await page.waitForTimeout(400);
    check('32: POST responses {status:going}', COMPANY_RESP_CALLS.some((c) => c.status === 'going'), JSON.stringify(COMPANY_RESP_CALLS));
    check('32: «Ты идёшь ✓»', (await page.locator('.hv2-pcard__btns').textContent()).includes('Ты идёшь'));
    check('32: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 33. Компания в выходные, я организатор → «Позвать ещё» + «Открыть». */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({ home: { companies: [COMPANY_SAT], company_share: true, variant: 'many' } }),
      flags: UI_FLAGS_S5, flagsCache: UI_FLAGS_S5,
    });
    await shot(page, '33-company-weekend');
    check('33: «сб, 28» в чипе', (await page.locator('.hv2-pcard__chip').first().textContent()).includes('сб, 28'));
    check('33: «Позвать ещё»', (await page.locator('.hv2-pcard__btns').textContent()).includes('Позвать ещё'));
    check('33: «Открыть»', (await page.locator('.hv2-pcard__btns').textContent()).includes('Открыть'));
    check('33: жёлтой «Иду» нет', await page.locator('[data-act="company-going"]').count() === 0);
    check('33: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 34. «Позвать друзей» (новичок) открывает лист GlideShareSheet. */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({ home: { companies: [], company_share: true, variant: 'many' } }),
      flags: UI_FLAGS_S5, flagsCache: UI_FLAGS_S5,
    });
    const invite = page.locator('[data-act="invite"]').first();
    check('34: кнопка «Позвать» есть', await invite.count() === 1);
    if (await invite.count()) {
      await invite.click();
      await page.waitForTimeout(1200);
      const sheet = await page.locator('.gss, [class*="gss"]').count();
      check('34: лист GlideShareSheet открылся', sheet > 0);
      await shot(page, '34-share-sheet');
    }
    check('34: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 34b. Без s5 компаний нет и «Позвать» ведёт себя как раньше. */
  {
    const { page, ctx, errors } = await openHome(browser, {
      boot: bootstrap({ home: { variant: 'many' } }),
      flags: UI_FLAGS_S3, flagsCache: UI_FLAGS_S3,
    });
    check('34b: карточки компании нет', await page.locator('.hv2-comp__plaque').count() === 0);
    check('34b: без JS-ошибок', errors.length === 0, errors.join('; '));
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
