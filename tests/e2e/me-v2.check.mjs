/* TASK-449 (этап 4B): e2e «Я» v2 — /webapp/client-me, 390×844, стабы /api/*.
 * Скриншоты: tests/e2e/__shots__/me-v2/ */
import { chromium } from 'playwright';
import http from 'node:http';
import { mkdirSync, rmSync, readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(here, '../..');
const staticDir = path.join(repoRoot, 'static');
const photosDir = path.join(repoRoot, 'data', 'arena-cards', 'photos');
const shots = path.join(here, '__shots__', 'me-v2');
rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });

const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2' };

let ME_V2_SERVE = true;
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  let file;
  if (p === '/webapp/client-me') {
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end(readFileSync(path.join(staticDir, 'webapp', ME_V2_SERVE ? 'client-me-v2.html' : 'client-me.html')));
    return;
  }
  if (p.startsWith('/photos/')) {
    file = path.join(photosDir, p.slice('/photos/'.length));
  } else {
    if (p.startsWith('/static/')) p = p.slice('/static'.length);
    file = path.join(staticDir, p);
  }
  const baseDir = p.startsWith('/photos/') ? photosDir : staticDir;
  if (!file.startsWith(baseDir) || !existsSync(file) || statSync(file).isDirectory()) { res.writeHead(404); res.end('no'); return; }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, r));
const base = 'http://localhost:' + server.address().port;

const NOW = new Date('2026-11-22T16:30:00Z'); /* 19:30 Минск */
const P = (n) => '/photos/' + n;

const FLAGS_S4 = { season_ui: false, bookings_tab: true, fast_tabs: false, search_board: false,
  redesign_s1: true, redesign_s2: true, redesign_s3: true, redesign_s4: true, redesign_s5: true };
const FLAGS_NO_S5 = { ...FLAGS_S4, redesign_s5: false };

function tgMock() {
  return `window.Telegram = { WebApp: {
    initData: 'mock', initDataUnsafe: { user: { id: 1, first_name: 'Максим', photo_url: '', allows_write_to_pm: true } },
    colorScheme: 'light', themeParams: {}, version: '8.0', platform: 'ios', isExpanded: true, viewportHeight: 844,
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
  console.log((cond ? '✔' : '✖') + ' ' + name + (cond || !extra ? '' : ' → ' + extra));
  if (!cond) failures++;
}

const ME_SOLO = {
  name: 'Максим', initial: 'М', city: 'Минск', joined_label: 'в Glide с октября',
  club: { name: 'Динамо-Минск', short: 'ДМ', color: '#06c', logo: P('arena-25/hero.jpg'), label_ink: '#fff',
    next_match: { starts_at: '2026-11-22T19:00:00+03:00', opponent: 'Барыс', href: 'kto-kogo', label: 'Сегодня 19:00 · Барыс' } },
  home_arena: { id: 25, name: 'Ледовый дворец', href: 'arena?id=25', sessions_left_today: 3, tomorrow_first: null,
    subscribed: true, photo: { thumb: P('arena-25/hero.jpg'), card: P('arena-25/hero.jpg') },
    today_times: ['20:00', '21:30'] },
  stats: { trainings: 12, streak_weeks: 3, kk_points: 40, kk_place: 7 },
  rows: { bookings: { next_starts_at: '2026-11-23T18:00:00+03:00' }, passes: null,
    saved: { count: 3, line: '2 катка · 1 тренер' },
    family: { count: 0 }, requests: null, trainer: null },
  profile_name: null,
  saved_detail: { arenas: 2, trainers: 1, line: '2 катка · 1 тренер' },
  pass: null,
};
const ME_PASS = {
  ...ME_SOLO,
  pass: { left: 5, total: 8, trainer_id: 77, trainer_name: 'Ольга Смирнова',
    trainer_photo_key: 't77.jpg', expires_label: 'до 15 декабря', book_href: 'catalog?trainer_id=77' },
};
const ME_NEWBIE = {
  name: 'Миша', initial: 'М', city: 'Минск', joined_label: 'в Glide с ноября',
  club: null, home_arena: null,
  stats: { trainings: 0, streak_weeks: 0, kk_points: null, kk_place: null },
  rows: { bookings: null, passes: null, saved: { count: 0 }, family: { count: 0 }, requests: null, trainer: null },
  profile_name: null, saved_detail: null, pass: null,
};
const ME_COMPANY = { code: 'abc12345', name: '', session_id: 401, arena_id: 11,
  arena_name: 'Конькобежный', starts_local: '17:45', day_label: 'сб, 28', going_count: 3,
  going_names: ['Аня', 'Дима', 'Света'], crowd_line: 'Трое — это уже компания',
  my_status: 'going', page_url: '/k/abc12345', photo: { thumb: null, card: null } };
const ME_WITH_COMPANIES = { ...ME_SOLO, companies: [ME_COMPANY, { ...ME_COMPANY, code: 'def67890', day_label: 'завтра', my_status: 'organizer', arena_name: 'Ледовый дворец', starts_local: '10:00' }] };
const ME_PARENT = {
  ...ME_SOLO, name: 'Максим', profile_name: 'Миша Ковалёв',
  rows: { ...ME_SOLO.rows, family: { count: 2, value: 'Максим, Миша' } },
};

const SEASON = { sessions: {}, me: { season_days: 14, streak_weeks: 3, has_this_week: true, helped: 0 } };
const SEASON_ZERO = { sessions: {}, me: { season_days: 0, streak_weeks: 0, has_this_week: false, helped: 0 } };

/* TASK-451: значки волны 1 — полка/коллекция/лист вручения в «Я». */
const BADGES_FULL = [
  { key: 'first_ice', name: 'Вышел на лёд', name_gen: 'Выхода на лёд', family: 'intro', total: 1, earned: true,
    earned_at: '2026-09-12T15:00:00+00:00', progress: { done: 1, total: 1 } },
  { key: 'streak_3', name: 'Не растаял', name_gen: 'Не растаял', family: 'streak', total: 3, earned: true,
    earned_at: '2026-11-03T15:00:00+00:00', progress: { done: 3, total: 3 } },
  { key: 'streak_5', name: 'Крепкий лёд', name_gen: 'Крепкого льда', family: 'streak', total: 5, earned: false,
    earned_at: null, progress: { done: 3, total: 5 } },
  { key: 'streak_10', name: 'Вечная мерзлота', name_gen: 'Вечной мерзлоты', family: 'streak', total: 10, earned: false,
    earned_at: null, progress: { done: 3, total: 10 } },
  { key: 'days_10', name: 'Разогрелся', name_gen: 'Разогрелся', family: 'season', total: 10, earned: false,
    earned_at: null, progress: { done: 8, total: 10 } },
  { key: 'days_25', name: 'Завсегдатай', name_gen: 'Завсегдатая', family: 'season', total: 25, earned: false,
    earned_at: null, progress: { done: 8, total: 25 } },
];
const ME_BADGES = { ...ME_SOLO, badges: BADGES_FULL };
const ME_BADGES_BROKEN = {
  ...ME_SOLO,
  badges: BADGES_FULL.map((b) => ({ ...b,
    progress: { ...b.progress, done: 0 },
    earned: b.key === 'first_ice' ? b.earned : false })),
};
const SEASON_BROKEN = { sessions: {}, me: { season_days: 7, streak_weeks: 0, has_this_week: false, helped: 0 } };

let ME_BODY = ME_SOLO, SEASON_BODY = SEASON, REMIND = true, REMIND_PUTS = [], PROFILE_ID = null, SEEN_POSTS = [];

async function openMe(browser, { me, season, flags, url, flagsCache } = {}) {
  ME_BODY = me || ME_SOLO; SEASON_BODY = season === undefined ? SEASON : season;
  REMIND_PUTS = []; SEEN_POSTS = [];
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Minsk', locale: 'ru-RU' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|ERR_FAILED|net::|404/.test(m.text())) errors.push(m.text()); });
  await page.clock.setFixedTime(NOW);
  await page.addInitScript((fl) => {
    try { localStorage.setItem('cw_ui_flags_v1', JSON.stringify({ u: '1', ...(fl || {}), at: Date.now() })); } catch (e) {}
  }, flagsCache || FLAGS_S4);
  await page.route('https://telegram.org/**', (r) => r.fulfill({ contentType: 'text/javascript', body: tgMock() }));
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.route('**/api/**', async (r) => {
    const u = new URL(r.request().url()); const p = u.pathname;
    const json = (b) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(b) });
    if (p === '/api/webapp/client/ui-flags') return json(flags || FLAGS_S4);
    if (p === '/api/webapp/client/me') { PROFILE_ID = r.request().headers()['x-profile-id'] || null; return json(ME_BODY); }
    if (p === '/api/webapp/client/checkins/state') return json(SEASON_BODY);
    if (p === '/api/webapp/client/hockey/remind') {
      if (r.request().method() === 'PUT') { REMIND_PUTS.push(JSON.parse(r.request().postData() || '{}')); REMIND = !REMIND; }
      return json({ on: REMIND });
    }
    if (p === '/api/webapp/client/slots') return json({ next: { label: 'ср, 25 · 07:30' }, slots: [] });
    if (p === '/api/webapp/client/badges/seen') { SEEN_POSTS.push(JSON.parse(r.request().postData() || '{}')); return json({ shown: 1 }); }
    if (p.startsWith('/api/webapp/client/badges/') && p.endsWith('/share')) {
      return json({ share_url: 'https://t.me/glidebot/app?startapp=badge_streak_3',
        share_body: 'x', share_text: 'Максим получил значок «Не растаял» в Glide' });
    }
    if (p === '/api/webapp/client/profiles') return json({ items: [], default_profile_id: null });
    if (p === '/api/webapp/client/session' && r.request().method() === 'GET') return json({ city_id: 1 });
    return json({});
  });
  await page.route('**/api/public/photos/**', (r) => r.fulfill({ contentType: 'image/jpeg', body: readFileSync(path.join(photosDir, 'arena-25', 'hero.jpg')) }));
  await page.goto(base + (url || '/webapp/client-me'));
  await page.waitForTimeout(700);
  return { page, ctx, errors };
}

async function shot(page, name, fullPage) {
  await page.screenshot({ path: path.join(shots, name + '.png'), fullPage: !!fullPage });
}

async function systemCheck(page, name) {
  const m = await page.evaluate(() => {
    const dela = [...document.querySelectorAll('body *')].filter((el) => {
      const s = getComputedStyle(el);
      return /Dela/.test(s.fontFamily) && el.children.length === 0 && (el.textContent || '').trim();
    });
    const yellow = [...document.querySelectorAll('body *')].some((el) => {
      const s = getComputedStyle(el);
      const c = s.backgroundColor + s.color;
      return /rgb\(2[0-4]\d,\s*(1[6-9]\d|2[0-4]\d),\s*[0-5]?\d\)/.test(c) && !/rgb\(255,\s*255,\s*255\)/.test(c);
    });
    const tabs = [...document.querySelectorAll('#clientTabBar .client-tab-bar__btn')]
      .map((b) => ({ t: b.textContent.trim(), on: b.classList.contains('client-tab-bar__btn--active') }));
    return { dela: dela.length, yellow, scrollW: document.documentElement.scrollWidth, innerW: innerWidth, tabs };
  });
  check(name + ': нет горизонтального скролла', m.scrollW <= m.innerW, `${m.scrollW}>${m.innerW}`);
  check(name + ': Dela нет', m.dela === 0, `${m.dela}`);
  check(name + ': жёлтого нет', !m.yellow);
  const tabsOk = m.tabs.length === 5 && m.tabs.some((t) => t.t === 'Я' && t.on);
  check(name + ': бар 5 вкладок, «Я» активна', tabsOk, JSON.stringify(m.tabs));
}

const browser = await chromium.launch();

/* 01 «Катается сам»: сезон (s5) + Мой каток + Болею за, без абонемента */
{
  const { page, ctx, errors } = await openMe(browser, { me: ME_SOLO });
  await systemCheck(page, '01');
  await shot(page, '01-solo');
  await shot(page, '01b-solo-full', true);
  check('01: имя', (await page.locator('.mv2-head__name').textContent()) === 'Максим');
  check('01: «Минск · в Glide с октября»', (await page.locator('.mv2-head__sub').textContent()).includes('в Glide с октября'));
  check('01: сезон «14 раз на льду»', (await page.locator('.mv2-season').textContent()).includes('14'));
  check('01: серия недель', (await page.locator('.mv2-season').textContent()).includes('Серия 3'));
  check('01: «Мой каток» карточка', await page.locator('.mv2-rink').count() === 1);
  check('01: время сегодня', (await page.locator('.mv2-rink__times').textContent()).includes('20:00'));
  check('01: «Болею за Динамо-Минск»', (await page.locator('.mv2-row__t').first().textContent()).includes('Болею за'));
  check('01: матч', (await page.locator('.mv2-row__s').first().textContent()).includes('Барыс'));
  check('01: плитка Семья', (await page.locator('.mv2-tiles').textContent()).includes('Семья'));
  check('01: плитка Сохранённое с линией', (await page.locator('.mv2-tiles').textContent()).includes('2 катка · 1 тренер'));
  check('01: абонемента нет', await page.locator('.mv2-pass').count() === 0);
  check('01: настройки: чат/история/город/написать', (await page.locator('.mv2-set').textContent()).includes('Написать нам'));
  check('01: без JS-ошибок', errors.length === 0, errors.join('; '));
  await ctx.close();
}

/* 02 «С абонементом» */
{
  const { page, ctx, errors } = await openMe(browser, { me: ME_PASS });
  await systemCheck(page, '02');
  await shot(page, '02-pass');
  await shot(page, '02b-pass-full', true);
  check('02: «Осталось 5 занятий»', (await page.locator('.mv2-pass').textContent()).includes('Осталось 5 занятий'));
  check('02: «Абонемент у … · до 15 декабря»', (await page.locator('.mv2-pass__s').textContent()).includes('до 15 декабря'));
  check('02: окно тренера', (await page.locator('#mv2PassWindow').textContent()).includes('07:30'));
  check('02: «Записаться»', await page.locator('.mv2-pass__book').count() === 1);
  check('02: без JS-ошибок', errors.length === 0, errors.join('; '));
  await ctx.close();
}

/* 03 «Новичок»: пустой сезон, «Выбрать каток», пустые плитки */
{
  const { page, ctx, errors } = await openMe(browser, { me: ME_NEWBIE, season: SEASON_ZERO });
  await shot(page, '03-newbie');
  check('03: «Сезон ещё не начат»', (await page.locator('.mv2-season').textContent()).includes('Сезон ещё не начат'));
  check('03: «Выбрать каток»', (await page.locator('#mv2RinkPick').textContent()).includes('Выбрать каток'));
  check('03: без «Болею за»', !(await page.locator('.mv2__page').textContent()).includes('Болею за'));
  check('03: «Добавить ребёнка»', (await page.locator('.mv2-tiles').textContent()).includes('Добавить ребёнка'));
  check('03: полки значков нет', await page.locator('.mv2-badges').count() === 0);
  check('03: без JS-ошибок', errors.length === 0, errors.join('; '));
  await ctx.close();
}

/* 04 родительский аккаунт с активным профилем ребёнка */
{
  const { page, ctx, errors } = await openMe(browser, { me: ME_PARENT });
  await shot(page, '04-parent');
  check('04: Семья — имена', (await page.locator('.mv2-tiles').textContent()).includes('Миша'));
  check('04: без JS-ошибок', errors.length === 0, errors.join('; '));
  await ctx.close();
}

/* 05 переключатель «Сообщения в чате» */
{
  const { page, ctx, errors } = await openMe(browser, { me: ME_SOLO });
  const sw = page.locator('#mv2Remind');
  await page.waitForTimeout(300);
  const before = await sw.getAttribute('aria-checked');
  await sw.click();
  await page.waitForTimeout(200);
  const after = await sw.getAttribute('aria-checked');
  check('05: переключатель инвертировался', before !== after, `${before}->${after}`);
  check('05: PUT /client/hockey/remind', REMIND_PUTS.length === 1 && 'on' in REMIND_PUTS[0], JSON.stringify(REMIND_PUTS));
  await shot(page, '05-toggle');
  check('05: без JS-ошибок', errors.length === 0, errors.join('; '));
  await ctx.close();
}

/* 06 без s5 — нет сезонной карточки */
{
  const { page, ctx, errors } = await openMe(browser, { me: ME_SOLO, flags: FLAGS_NO_S5, flagsCache: FLAGS_NO_S5 });
  await shot(page, '06-no-s5');
  check('06: сезонной карточки нет', await page.locator('.mv2-season').count() === 0);
  check('06: без JS-ошибок', errors.length === 0, errors.join('; '));
  await ctx.close();
}

/* 08 «Мои компании» (s4+s5) */
{
  const { page, ctx, errors } = await openMe(browser, { me: ME_WITH_COMPANIES });
  await shot(page, '08-companies');
  check('08: секция «Мои компании»', (await page.locator('.mv2-sec__h').textContent()).includes('Мои компании'));
  check('08: заголовок 22/700 вне карточки', await page.locator('.mv2-sec__h').evaluate((el) => {
    const s = getComputedStyle(el);
    return s.fontSize === '22px' && s.fontWeight === '700' && !el.closest('.mv2-card');
  }));
  check('08: имена через «и»', (await page.locator('[data-company]').first().textContent()).includes('Аня, Дима и Света'));
  check('08: 2 строки', await page.locator('[data-company]').count() === 2);
  check('08: «ты идёшь»', (await page.locator('[data-company]').first().textContent()).includes('ты идёшь'));
  check('08: «организатор»', (await page.locator('[data-company]').nth(1).textContent()).includes('организатор'));
  check('08: без JS-ошибок', errors.length === 0, errors.join('; '));
  await ctx.close();
}

/* 09 полка значков + «Первый шаг» + коллекция (s4+s5) */
{
  const { page, ctx, errors } = await openMe(browser, { me: ME_BADGES });
  await shot(page, '09-badges-shelf');
  await shot(page, '09b-badges-full', true);
  const sec = page.locator('.mv2-badges');
  check('09: секция «Значки»', await sec.count() === 1);
  check('09: «Первый шаг» строкой', (await sec.locator('.mv2-bfirst').textContent()).includes('Первый шаг'));
  check('09: плиток 5 (без вводного)', await sec.locator('.mv2-btile').count() === 5);
  check('09: первая плитка открыта с датой',
    (await sec.locator('.mv2-btile.is-earned').first().textContent()).includes('03.11'));
  check('09: закрытая «3 из 5»',
    (await sec.locator('.mv2-btile.is-locked[data-badge="streak_5"]').textContent()).includes('3 из 5'));
  check('09: «до «Крепкого льда»» в сезоне',
    (await page.locator('.mv2-season').textContent()).includes('Крепкого льда'));
  /* коллекция */
  await page.locator('#mv2BadgesAll').click();
  await page.waitForTimeout(300);
  const col = page.locator('#mv2Collection');
  check('09: коллекция открылась', await col.isVisible());
  check('09: «Ближе всего»', (await col.textContent()).includes('Ближе всего'));
  check('09: сетки Серии/Сезон', (await col.textContent()).includes('Серии') && (await col.textContent()).includes('Сезон'));
  check('09: в коллекции 5 трофейных + ближайший', await col.locator('.mv2-btile').count() === 6);
  await shot(page, '09c-collection');
  /* тап по открытому значку → лист вручения */
  await col.locator('.mv2-btile.is-earned').first().click();
  await page.waitForTimeout(400);
  check('09: лист вручения из коллекции', await page.locator('.baw').isVisible());
  check('09: имя значка в листе', (await page.locator('.baw__name').textContent()).includes('Не растаял'));
  await shot(page, '09d-award');
  await page.locator('.baw__later').click();
  await ctx.close();
}

/* 10 полки нет, когда ни одного значка (серия оборвалась) */
{
  const { page, ctx, errors } = await openMe(browser, { me: ME_BADGES_BROKEN, season: SEASON_BROKEN });
  await shot(page, '10-broken-streak');
  check('10: «Первый шаг» открыт, трофеи серые',
    (await page.locator('.mv2-bfirst').textContent()).includes('Первый шаг') &&
    await page.locator('.mv2-btile.is-earned').count() === 0);
  check('10: «Серия оборвалась · начни новую»',
    (await page.locator('.mv2-season').textContent()).includes('Серия оборвалась'));
  check('10: без JS-ошибок', errors.length === 0, errors.join('; '));
  await ctx.close();
}

/* 07 s4 off — старая страница */
{
  ME_V2_SERVE = false;
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await page.route('https://telegram.org/**', (r) => r.fulfill({ contentType: 'text/javascript', body: tgMock() }));
  await page.route('**/api/**', (r) => r.fulfill({ contentType: 'application/json', body: '{}' }));
  await page.goto(base + '/webapp/client-me');
  await page.waitForTimeout(500);
  const hasV2 = await page.locator('.mv2__page').count();
  check('07: s4 off — старая страница', hasV2 === 0);
  await ctx.close();
}

await browser.close();
server.close();
console.log(failures ? `\n${failures} FAILED` : '\nall checks pass');
process.exit(failures ? 1 : 0);
