/**
 * TASK-446 (5.2): «Я здесь» на РЕАЛЬНЫХ страницах Лёд / каток / «Я».
 * Те же приёмы, что в home-v2.check.mjs и ice-map-fullscreen.check.mjs:
 * статический сервер static/ + /photos/* из data/arena-cards/photos,
 * ymaps-stub (офлайн), Telegram-мок, стабы /api/*.
 *
 * Сценарии (390×844, Europe/Minsk, «сейчас» 22.11.2026 19:30):
 *   01 ice-on       — вкладка Лёд: 2 идущих сеанса (live «людно · 2 отметки» и без) + будущий;
 *   02 ice-sheet    — тап «✓ Я здесь» под карточкой открывает лист;
 *   03 arena        — arena.html?ref=11&s=401: блок «Сейчас свободно» + «Маршрут»→intent;
 *   04 me           — client-me.html: карточка сезона + «Помог выбрать»;
 *   05 me-newbie    — «Сезон ещё не начат»;
 *   07 arena-usual  — TASK-452: сетка «Когда свободнее» + blended «обычно» на шкалах;
 *   08 usual-quiet  — сетка без идущего сеанса;
 *   09 usual-none   — arena_usual=null → блока нет;
 *   06/10 flag-off  — флаг выключен: ни checkin-ассетов, ни узлов (все 3 страницы).
 *
 * Run: node tests/e2e/checkin-live.check.mjs
 * Скриншоты: tests/e2e/__shots__/checkin-live/
 */
import { chromium } from 'playwright';
import http from 'node:http';
import { mkdirSync, rmSync, readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { YMAPS_STUB } from './ymaps-stub.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(here, '../..');
const staticDir = path.join(repoRoot, 'static');
const photosDir = path.join(repoRoot, 'data', 'arena-cards', 'photos');
const shots = path.join(here, '__shots__', 'checkin-live');
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
    if (p.startsWith('/static/')) p = p.slice('/static'.length);
    file = path.join(staticDir, p);
    if (file.startsWith(staticDir) && !existsSync(file) && !path.extname(file) && existsSync(file + '.html')) {
      file += '.html';
    }
    if (!file.startsWith(staticDir) || !existsSync(file) || statSync(file).isDirectory()) {
      res.writeHead(404); res.end('no'); return;
    }
  }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, r));
const base = 'http://localhost:' + server.address().port;

const NOW = new Date('2026-11-22T16:30:00Z'); // 19:30 Минск, вс
const TODAY_ISO = '2026-11-22';

const TG_MOCK = `window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A42%7D&hash=x',
  initDataUnsafe: { user: { id: 42, first_name: 'Максим', allows_write_to_pm: true } },
  colorScheme: 'light', themeParams: {}, version: '8.0', platform: 'ios', isExpanded: true,
  isVersionAtLeast(v) { const c=(a,b)=>a.split('.').map(Number).reduce((d,x,i)=>d||x-(b[i]||0),0); return c(this.version,v)>=0; },
  ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
  onEvent() {}, offEvent() {}, openTelegramLink() {}, openLink() {}, shareURL() {},
  HapticFeedback: { selectionChanged() {}, impactOccurred() {}, notificationOccurred() {} },
  BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
  MainButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
} };`;

/* Кэш флага, чтобы оболочка видела s5 до первого запроса (как в проде после первой сессии). */
const FLAGS_CACHE = (s5) => `(function(){try{localStorage.setItem('cw_ui_flags_v1', JSON.stringify({u:'42',season_ui:true,bookings_tab:false,redesign_s1:true,redesign_s5:${s5},at:Date.now()}));}catch(e){}})()`;

const P = (n) => '/photos/' + n;

/* ── Стабы данных ───────────────────────────────────────────────────────── */

const ICE_ARENAS = [
  { id: 11, name: 'Каток на Немиге', slug: 'katok-na-nemige', district: 'Центральный', venue_type: 'ice', tier: 'A', on_map: true,
    latitude: 53.93, longitude: 27.51, thumb: P('arena-38/hero.webp'), address: 'пр-т Победителей, 1', distance_km: 1.2,
    live: { kind: 'session', session_id: 401, text: 'Идёт сеанс · до 21:15', starts_at_local: '19:45' } },
  { id: 12, name: 'Ледовый дворец', slug: 'ledoviy-dvorets', district: 'Фрунзенский', venue_type: 'ice', tier: 'A', on_map: true,
    latitude: 53.90, longitude: 27.48, thumb: P('arena-25/hero.jpg'), address: 'ул. Притыцкого, 27', distance_km: 3.4,
    live: { kind: 'session', session_id: 402, text: 'Идёт сеанс · до 20:30', starts_at_local: '19:00' } },
  { id: 13, name: 'Парк Горького', slug: 'park-gorkogo', district: 'Партизанский', venue_type: 'ice', tier: 'B', on_map: true,
    latitude: 53.90, longitude: 27.57, thumb: P('arena-11/hero.webp'), address: 'ул. Фрунзе, 2', distance_km: 4.1,
    live: { kind: 'session', session_id: 403, text: 'Сегодня с 21:30', starts_at_local: '21:30' } },
];

const ARENA_CARD = {
  id: 11, slug: 'katok-na-nemige', city_id: 1, city_name: 'Минск', public_path: '/p/minsk/katok-na-nemige',
  name: 'Каток на Немиге', venue_type: 'ice', venue_noun: 'каток', venue_chip: 'Каток', venue_site_label: 'Сайт',
  has_skating: true, district: 'Центральный', address: 'пр-т Победителей, 1',
  latitude: 53.93, longitude: 27.51, timezone: 'Europe/Minsk',
  short_description: 'Крытый каток в центре', phone: '+375 29 000-00-00', website_url: null, tickets_url: null,
  social_urls: {}, opening_hours: {}, season_start_month: 9, season_end_month: 5, in_season: true,
  amenities: {}, visit_info: {}, visit: {},
  contacts: { phone: '+375 29 000-00-00', website_url: null, social_urls: {} },
  hero: { mode: 'photo', url: P('arena-38/hero.webp'), variants: { thumb: P('arena-38/hero.webp'), card: P('arena-38/hero.webp'), hero: P('arena-38/hero.webp') }, urls: [P('arena-38/hero.webp')] },
  gallery: [], tier: 'A', currency_code: 'BYN', trainer_count: 0,
  freshness: { state: 'fresh', label: null },
};

const SESS = (id, s, e) => ({
  id, arena_id: 11, kind: 'public_skate',
  starts_at_utc: TODAY_ISO + 'T' + s + ':00+03:00', ends_at_utc: TODAY_ISO + 'T' + e + ':00+03:00',
  local_date: TODAY_ISO, starts_at_local: s, ends_at_local: e,
  price_minor: 1200, currency_code: 'BYN', status: 'active',
});

const ARENA_SESSIONS = {
  arena_id: 11, timezone: 'Europe/Minsk', from: TODAY_ISO, to: '2026-11-29',
  days: [{ local_date: TODAY_ISO, sessions: [SESS(401, '19:45', '21:15'), SESS(405, '21:30', '23:00')] }],
  ohm_days: [], figure_days: [], family_days: [],
  kinds: ['public_skate'], freshness: { state: 'fresh', label: null },
};

const ME = {
  name: 'Максим', initial: 'М', city: 'Минск', profile_name: null,
  stats: { trainings: 8, streak_weeks: 3, kk_points: 124, kk_place: 7 },
  club: { name: 'ХК Минск', label_ink: 'Мой клуб' },
  home_arena: { id: 11, name: 'Каток на Немиге', href: 'arena?ref=11', sessions_left_today: 0 },
  rows: {
    trainer: { name: 'Анна Коваль', href: 'client-requests' },
    bookings: { next_starts_at: '2026-11-24T18:30:00+03:00' },
    passes: { lessons_left: 4 },
    requests: { count: 1 },
    family: { people: [{ is_you: true, active: true, profile_id: null, name: 'Максим' }] },
  },
};

const STATE_ICE = {
  sessions: {
    401: { ongoing: true, checked_in: false, checkin_id: null, load_level: null, ends_local: '21:15', live: { level: 3, count: 2, last_min: 6 } },
    402: { ongoing: true, checked_in: true, checkin_id: 910, load_level: null, ends_local: '20:30', live: null },
    403: { ongoing: false, checked_in: false, checkin_id: null, load_level: null, ends_local: '23:00', live: null },
  },
  me: { season_days: 6, streak_weeks: 2, has_this_week: true, helped: 0 },
};
const STATE_ARENA = {
  sessions: { 401: { ongoing: true, checked_in: false, checkin_id: null, load_level: null, ends_local: '21:15', live: { level: 1, count: 3, last_min: 12 } } },
  me: { season_days: 6, streak_weeks: 2, has_this_week: true, helped: 0 },
};
const STATE_ME = { sessions: {}, me: { season_days: 12, streak_weeks: 3, has_this_week: false, helped: 5 } };
const STATE_ME_NEWBIE = { sessions: {}, me: { season_days: 0, streak_weeks: 0, has_this_week: false, helped: 0 } };

/* TASK-452 (5.5): «обычно» — сетка «Когда свободнее» + blended-уровень на шкалах. */
const SESS_LOAD = (id, s, e, lv) => ({ ...SESS(id, s, e), typical_load_level: lv });
const ARENA_SESSIONS_LOAD = {
  ...ARENA_SESSIONS,
  days: [{
    local_date: TODAY_ISO,
    sessions: [SESS_LOAD(401, '19:45', '21:15', 'medium'), SESS_LOAD(405, '21:30', '23:00', 'calm')],
  }],
};
const ARENA_USUAL = {
  total: 14,
  buckets: [10, 14, 18, 20],
  weekdays: ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'],
  cells: [
    [1, 1, 1, 1, 1, 2, null],
    [1, 1, 1, 1, 2, 3, null],
    [2, 2, 2, 2, 3, 3, 1],
    [2, 2, 2, 2, 3, 2, 1],
  ],
  best: 'Свободнее всего — будни в 10:00 и 14:00',
};
const STATE_ARENA_USUAL = {
  sessions: {
    401: { ongoing: true, checked_in: false, checkin_id: null, load_level: null, ends_local: '21:15',
           live: null, usual: { key: 'calm', word: 'свободно' } },
    405: { ongoing: false, checked_in: false, checkin_id: null, load_level: null, ends_local: '23:00',
           live: null, usual: { key: 'busy', word: 'людно' } },
  },
  me: { season_days: 6, streak_weeks: 2, has_this_week: true, helped: 0 },
  arena_usual: ARENA_USUAL,
};
/* Сетка без идущего сеанса: блок «Когда свободнее» не зависит от «Сейчас». */
const STATE_ARENA_USUAL_QUIET = {
  sessions: { 405: { ongoing: false, checked_in: false, checkin_id: null, load_level: null,
                     ends_local: '23:00', live: null, usual: { key: 'busy', word: 'людно' } } },
  me: { season_days: 6, streak_weeks: 2, has_this_week: true, helped: 0 },
  arena_usual: ARENA_USUAL,
};

let failures = 0;
function check(name, cond, extra) {
  console.log((cond ? '✔' : '✖') + ' ' + name + (cond || !extra ? '' : '  → ' + extra));
  if (!cond) failures++;
}
async function shot(page, name) {
  await page.screenshot({ path: path.join(shots, name + '.png') });
}

async function openPage(browser, { page: pagePath, s5 = true, state = STATE_ICE, track, arenaSessions }) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Minsk', locale: 'ru-RU' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|ERR_FAILED|net::|404|favicon/.test(m.text())) errors.push(m.text()); });
  const checkinAssets = [];
  page.on('request', (r) => { if (/checkin-(sheet|live)\.(js|css)/.test(r.url())) checkinAssets.push(r.url()); });
  await page.clock.setFixedTime(NOW);
  await page.addInitScript(YMAPS_STUB);
  await page.addInitScript(FLAGS_CACHE(s5));
  await page.route('https://telegram.org/**', (r) => r.fulfill({ contentType: 'text/javascript', body: TG_MOCK }));
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.route(/api-maps\.yandex|yastatic/, (r) => r.fulfill({ contentType: 'text/javascript', body: '' }));
  await page.route('**/api/**', (r) => {
    const url = new URL(r.request().url());
    const p = url.pathname;
    const json = (b, code = 200) => r.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(b) });
    if (track) track.push(p + ' ' + r.request().method() + (url.search || ''));
    if (p === '/api/webapp/client/ui-flags') {
      return json({ season_ui: true, bookings_tab: false, redesign_s1: true, redesign_s5: s5 });
    }
    if (p === '/api/webapp/client/session' || p.startsWith('/api/webapp/client/session/')) {
      return json({ city_id: 1, city_name: 'Минск' });
    }
    if (p === '/api/public/ice/cities') {
      return json({ items: [{ id: 1, name: 'Минск', skate_count: 3, trainer_count: 14, latitude: 53.9, longitude: 27.56 }] });
    }
    if (p === '/api/public/ice/map-config') return json({ yandex_maps_js_api_key: 'stub-key' });
    if (p === '/api/public/ice/arenas' || p === '/api/public/ice/arenas-map') {
      return json({ items: ICE_ARENAS, total: ICE_ARENAS.length, window: { key: 'today_evening', label: 'Сегодня вечером', hits: 3 } });
    }
    if (p.startsWith('/api/public/ice/')) return json({ items: [] });
    if (p === '/api/public/arenas/11') return json(ARENA_CARD);
    if (p === '/api/public/arenas/11/sessions') return json(arenaSessions || ARENA_SESSIONS);
    if (p === '/api/public/arenas/11/matches') return json({ matches: [] });
    if (p === '/api/public/arenas/11/trainers') return json({ trainers: [] });
    if (p === '/api/webapp/client/me') return json(ME);
    if (p === '/api/webapp/client/checkins/state') return json(state);
    if (p === '/api/webapp/client/checkins/intent') return r.fulfill({ status: 204, body: '' });
    if (p === '/api/webapp/client/checkins' && r.request().method() === 'POST') {
      return json({ checkin_id: 950, session_id: 401, load_level: null, season_days: 7, nth_label: '7-й раз за сезон', streak_weeks: 2, has_this_week: true, live: null });
    }
    if (/^\/api\/webapp\/client\/checkins\/\d+$/.test(p) && r.request().method() === 'PATCH') return json({ live: { level: 2, count: 3, last_min: 0 } });
    if (/^\/api\/webapp\/client\/checkins\/\d+\/share$/.test(p)) {
      return json({ prepared_message_id: null, share_url: 'https://t.me/share/url?url=x', text: 'Подъезжай!' });
    }
    return json({});
  });
  await page.goto(base + pagePath);
  await page.waitForTimeout(1600);
  return { page, ctx, errors, checkinAssets };
}

const S1_TABS = 'Главная|Лёд|Записи|Кто кого|Я';
async function tabBarCheck(page, name) {
  const labels = await page.evaluate(() =>
    [...document.querySelectorAll('.client-tab-bar__btn > span:last-child')].map((e) => e.textContent.trim()).join('|'));
  check(name + ': редизайн-бар «Главная · Лёд · Записи · Кто кого · Я»', labels === S1_TABS, labels);
}

/* «Позвать сюда» и «Готово» полностью в экране и не перекрыты (elementFromPoint). */
async function sheetFitCheck(page, name) {
  const m = await page.evaluate(() => {
    function covered(sel) {
      const el = document.querySelector(sel);
      if (!el) return 'missing:' + sel;
      const r = el.getBoundingClientRect();
      if (r.top < 0 || r.bottom > innerHeight || r.left < 0 || r.right > innerWidth) {
        return 'out:' + JSON.stringify({ t: r.top | 0, b: r.bottom | 0, l: r.left | 0, r: r.right | 0 });
      }
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return hit && (hit === el || el.contains(hit) || hit.contains(el)) ? 'ok' : 'covered:' + (hit ? hit.className : 'none');
    }
    return { share: covered('.cis__share'), close: covered('.cis__close') };
  });
  check(name + ': «Позвать сюда» в экране и не перекрыта', m.share === 'ok', m.share);
  check(name + ': «Готово» в экране и не перекрыто', m.close === 'ok', m.close);
}

async function sysCheck(page, name) {
  const m = await page.evaluate(() => ({
    scrollW: document.documentElement.scrollWidth,
    innerW: window.innerWidth,
    yellow: [...document.querySelectorAll('.cis__share, .hv2-btn--yellow')].filter((el) => el.offsetParent).length,
    cilBtns: [...document.querySelectorAll('.cil__btn')].map((b) => {
      const cs = getComputedStyle(b);
      return { ws: cs.whiteSpace, lines: Math.round(b.getBoundingClientRect().height / parseFloat(cs.lineHeight || '14')) };
    }),
  }));
  check(name + ': нет горизонтального скролла', m.scrollW <= m.innerW, `${m.scrollW}>${m.innerW}`);
  check(name + ': не больше одного жёлтого действия', m.yellow <= 1, `${m.yellow}`);
  check(name + ': «✓ Я здесь» не переносится', m.cilBtns.every((b) => b.ws === 'nowrap' && b.lines <= 1), JSON.stringify(m.cilBtns));
}

const browser = await chromium.launch();
try {
  /* 01. Лёд: живые строки на карточках идущих сеансов */
  {
    const { page, ctx, errors } = await openPage(browser, { page: '/webapp/ice', state: STATE_ICE });
    await page.waitForSelector('.ice-board[data-session-id]', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(800);
    await shot(page, '01-ice-live');
    await sysCheck(page, '01');
    await tabBarCheck(page, '01');
    const rows = await page.evaluate(() => [...document.querySelectorAll('.ice-board-wrap, .ice-board[data-session-id]')].map((w) => {
      const a = w.querySelector('[data-session-id]') || (w.getAttribute('data-session-id') ? w : null);
      return a ? {
        sid: a.getAttribute('data-session-id'),
        live: ((w.parentElement || w).querySelector('.cil__live') || {}).textContent || '',
        btn: ((w.parentElement || w).querySelector('.cil__btn') || {}).textContent || '',
      } : null;
    }).filter(Boolean));
    const by = Object.fromEntries(rows.map((r) => [r.sid, r]));
    check('01: у 401 живая строка «Сейчас людно · 2 отметки»', /людно · 2 отметки/.test(by['401']?.live || ''), by['401']?.live);
    check('01: у 401 кнопка «✓ Я здесь»', by['401']?.btn === '✓ Я здесь', by['401']?.btn);
    check('01: у 402 «Отмечено» без live', (by['402']?.live || '') === '' && by['402']?.btn === 'Отмечено', JSON.stringify(by['402']));
    check('01: у 403 (будущий) ничего нет', !by['403'] || (by['403'].live === '' && by['403'].btn === ''), JSON.stringify(by['403']));
    const vis = await page.evaluate(() => {
      const el = document.querySelector('.cil');
      if (!el) return 'missing';
      const r = el.getBoundingClientRect();
      return r.top >= 0 && r.bottom <= innerHeight ? 'in' : `out:${r.top.toFixed(0)}..${r.bottom.toFixed(0)}`;
    });
    check('01: живая строка внутри экрана', vis === 'in', vis);
    check('01: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 02. Лёд: тап «✓ Я здесь» открывает лист */
  {
    const { page, ctx, errors } = await openPage(browser, { page: '/webapp/ice', state: STATE_ICE });
    await page.waitForSelector('.ice-board-wrap .cil__btn, .cil__btn', { timeout: 15000 });
    await page.click('.cil__btn');
    await page.waitForSelector('.cis.cis-on', { timeout: 8000 });
    await page.waitForTimeout(600); /* дать доиграть выезду и пружине плашки */
    await shot(page, '02-ice-sheet');
    check('02: лист открыт', await page.locator('.cis.cis-on').count() === 1);
    check('02: три оценки', await page.locator('.cis__lvl').count() === 3);
    check('02: зелёная плашка галочки видна', await page.evaluate(() => {
      const r = document.querySelector('.cis__check').getBoundingClientRect();
      return r.width >= 40 && r.height >= 40;
    }));
    await sysCheck(page, '02');
    await tabBarCheck(page, '02');
    await sheetFitCheck(page, '02');
    check('02: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 03. Каток: блок «Сейчас свободно» и «Маршрут»→intent */
  {
    const track = [];
    const { page, ctx, errors } = await openPage(browser, { page: '/webapp/arena?ref=11&s=401', state: STATE_ARENA, track });
    await shot(page, '03-arena-live');
    await sysCheck(page, '03');
    const blk = page.locator('.cil-arena');
    check('03: блок «Сейчас» вставлен', await blk.count() === 1);
    if (await blk.count()) {
      check('03: «Сейчас свободно»', (await blk.locator('.cil-arena__t').textContent() || '') === 'Сейчас свободно');
      check('03: подстрока «3 отметки за 40 минут · сеанс до 21:15»',
        (await blk.locator('.cil-arena__s').textContent() || '').includes('3 отметки за 40 минут · сеанс до 21:15'),
        await blk.locator('.cil-arena__s').textContent());
      const vis = await page.evaluate(() => {
        const r = document.querySelector('.cil-arena').getBoundingClientRect();
        return r.top >= 0 && r.left >= 0 && r.right <= innerWidth ? 'in' : `out:${r.top.toFixed(0)},${r.right.toFixed(0)}`;
      });
      check('03: блок внутри экрана', vis === 'in', vis);
      const btnR = await page.evaluate(() => document.querySelector('.cil-arena .cil__btn').getBoundingClientRect().right);
      check('03: кнопка не упирается в край (right ≤ w−16)', btnR <= 390 - 16 + 1, String(btnR));
    }
    const arenaBar = await page.locator('.client-tab-bar').count();
    check('03: на катке (hidden-оболочка) бара нет — как в проде', arenaBar === 0, String(arenaBar));
    check('03: focus в запросе state', track.some((t) => t.includes('checkins/state') && t.includes('focus=401')), track.filter((t) => t.includes('state')).join('|'));
    await page.click('a.ga-onphoto').catch(() => {});
    await page.waitForTimeout(400);
    check('03: «Маршрут» → POST intent route', track.some((t) => t.includes('checkins/intent POST')), track.join('|'));
    await page.click('.cil-arena .cil__btn');
    await page.waitForSelector('.cis.cis-on', { timeout: 8000 });
    await page.waitForTimeout(600);
    await shot(page, '03b-arena-sheet');
    await sheetFitCheck(page, '03b');
    check('03: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 04. «Я»: карточка сезона + «Помог выбрать» */
  {
    const { page, ctx, errors } = await openPage(browser, { page: '/webapp/client-me', state: STATE_ME });
    await page.waitForSelector('.cil-me', { timeout: 10000 }).catch(() => {});
    await shot(page, '04-me-season');
    await sysCheck(page, '04');
    const txt = (await page.locator('.cil-me').textContent()) || '';
    check('04: «12 раз на льду»', /12 раз на льду/.test(txt), txt.slice(0, 120));
    check('04: серия 3 недели', /Серия 3 недели подряд/.test(txt));
    check('04: «Помог выбрать время 5 раз»', /Помог выбрать время 5 раз/.test(txt));
    check('04: пилюли ≤4', await page.locator('.cil-weeks i').count() <= 4);
    await tabBarCheck(page, '04');
    await page.evaluate(() => window.GlideCheckin && window.GlideCheckin.open({
      session_id: 401, arena_name: 'Каток на Немиге', checkin_id: 910, season_days: 12, streak_weeks: 3 }));
    await page.waitForSelector('.cis.cis-on', { timeout: 8000 });
    await page.waitForTimeout(600);
    await shot(page, '04b-me-sheet');
    await sheetFitCheck(page, '04b');
    check('04: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 05. «Я» новичок: «Сезон ещё не начат» */
  {
    const { page, ctx, errors } = await openPage(browser, { page: '/webapp/client-me', state: STATE_ME_NEWBIE });
    await page.waitForSelector('.cil-me', { timeout: 10000 }).catch(() => {});
    await shot(page, '05-me-newbie');
    const txt = (await page.locator('.cil-me').textContent()) || '';
    check('05: «Сезон ещё не начат»', /Сезон ещё не начат/.test(txt), txt.slice(0, 120));
    check('05: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 07. TASK-452: «Когда свободнее» на катке + blended «обычно» на шкалах сеансов */
  {
    const track = [];
    const { page, ctx, errors } = await openPage(browser, {
      page: '/webapp/arena?ref=11&s=401', state: STATE_ARENA_USUAL,
      track, arenaSessions: ARENA_SESSIONS_LOAD,
    });
    await page.waitForSelector('.cil-usual', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(400);
    await shot(page, '07-arena-usual');
    await sysCheck(page, '07');
    const blk = page.locator('.cil-usual');
    check('07: сетка «Когда свободнее» вставлена', await blk.count() === 1);
    if (await blk.count()) {
      check('07: заголовок «Когда свободнее»', (await blk.locator('.cil-usual__t').textContent()) === 'Когда свободнее');
      check('07: «по 14 отметкам»', (await blk.locator('.cil-usual__n').textContent()) === 'по 14 отметкам',
        await blk.locator('.cil-usual__n').textContent());
      check('07: плашка «Свободнее всего»', (await blk.locator('.cil-usual__best').textContent()) === 'Свободнее всего — будни в 10:00 и 14:00',
        await blk.locator('.cil-usual__best').textContent());
      check('07: сетка 4×7 ячеек', await blk.locator('.cil-usual__grid i').count() === 28);
      check('07: «мало данных» (h0) — 2 ячейки', await blk.locator('.cil-usual__grid i.h0').count() === 2);
      check('07: «людно» (h3) — 4 ячейки', await blk.locator('.cil-usual__grid i.h3').count() === 4);
      check('07: легенда — 4 пункта', await blk.locator('.cil-usual__legend span').count() === 4);
      /* сетка выше «Сейчас» (перед блоком сеансов) */
      const order = await page.evaluate(() => {
        const u = document.querySelector('.cil-usual');
        const a = document.querySelector('.cil-arena');
        return a ? u.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING : 'no-arena';
      });
      check('07: сетка выше блока «Сейчас»', typeof order === 'number' && (order & 4) === 4, String(order));
      const vis = await page.evaluate(() => {
        const r = document.querySelector('.cil-usual').getBoundingClientRect();
        return r.top >= 0 && r.left >= 0 && r.right <= innerWidth ? 'in' : `out:${r.top.toFixed(0)},${r.right.toFixed(0)}`;
      });
      check('07: сетка внутри экрана', vis === 'in', vis);
    }
    /* blended «обычно»: шкала сеанса 401 перепатчена medium → calm, слово «свободно» */
    const patched = await page.evaluate(() => {
      const out = { meters: [], smalls: [] };
      document.querySelectorAll('[data-session-id="401"]').forEach((el) => {
        el.querySelectorAll('.arena-load').forEach((m) => out.meters.push(m.getAttribute('data-level')));
        el.querySelectorAll('small').forEach((s) => out.smalls.push((s.textContent || '').trim()));
      });
      return out;
    });
    check('07: шкала 401 перепатчена в calm', patched.meters.length > 0 && patched.meters.every((l) => l === 'calm'),
      JSON.stringify(patched.meters));
    check('07: слово «обычно свободно» на сеансе 401', patched.smalls.some((t) => t === 'обычно свободно'),
      JSON.stringify(patched.smalls));
    check('07: arena_id в запросе state', track.some((t) => t.includes('checkins/state') && t.includes('arena_id=11')),
      track.filter((t) => t.includes('state')).join('|'));
    check('07: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 08. Сетка без идущего сеанса видна; arena_usual=null → блока нет */
  {
    const { page, ctx, errors } = await openPage(browser, {
      page: '/webapp/arena?ref=11&s=405', state: STATE_ARENA_USUAL_QUIET, arenaSessions: ARENA_SESSIONS_LOAD,
    });
    await page.waitForSelector('.cil-usual', { timeout: 10000 }).catch(() => {});
    await shot(page, '08-arena-usual-quiet');
    check('08: сетка видна без идущего сеанса', await page.locator('.cil-usual').count() === 1);
    check('08: блока «Сейчас» нет (не идёт ничего)', await page.locator('.cil-arena').count() === 0);
    check('08: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }
  {
    const { page, ctx, errors } = await openPage(browser, {
      page: '/webapp/arena?ref=11&s=401',
      state: { ...STATE_ARENA, arena_usual: null },
    });
    await page.waitForTimeout(1200);
    await shot(page, '09-arena-usual-none');
    check('09: arena_usual=null → сетки нет', await page.locator('.cil-usual').count() === 0);
    check('09: блок «Сейчас» на месте', await page.locator('.cil-arena').count() === 1);
    check('09: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 06→10. Флаг выключен: ни ассетов, ни узлов на всех трёх страницах */
  const OFF_PAGES = [['ice', '/webapp/ice'], ['arena', '/webapp/arena?ref=11&s=401'], ['me', '/webapp/client-me']];
  for (let i = 0; i < OFF_PAGES.length; i++) {
    const p = OFF_PAGES[i][1];
    const { page, ctx, errors, checkinAssets } = await openPage(browser, { page: p, s5: false });
    await shot(page, `06-off-${OFF_PAGES[i][0]}`);
    check(`06-${i}: ${p} без checkin-ассетов`, checkinAssets.length === 0, checkinAssets.join(','));
    check(`06-${i}: ${p} без узлов .cil*/.cis`, await page.locator('.cil, .cil-arena, .cil-me, .cis').count() === 0);
    check(`06-${i}: ${p} без JS-ошибок`, errors.length === 0, errors.join('; '));
    await ctx.close();
  }
} finally {
  await browser.close();
  server.close();
}

if (failures) {
  console.log(`\n✖ ${failures} проверок упало`);
  process.exit(1);
}
console.log('\n✔ все проверки прошли');
