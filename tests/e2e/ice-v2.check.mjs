/* TASK-449 (этап 4): e2e «Лёд» v2 — /webapp/ice, 390×844, prod-путь.
 * Статика static/ + фото data/arena-cards/photos + стабы /api/* (Telegram и сеть не нужны).
 * Скриншоты: tests/e2e/__shots__/ice-v2/
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
const shots = path.join(here, '__shots__', 'ice-v2');
rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });

const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2',
};

/* Эмуляция диспетча app.py: s4 + чистые параметры → client-ice-v2.html;
   map=1 / чужие параметры / s4 off → старый ice.html. */
let ICE_V2_SERVE = true;
const ICE_V2_PARAMS = new Set(['city_id', 'day', 'kind', 'when', 'intent', 'init_data', 'tgWebAppStartParam']);

const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  let file;
  if (p === '/webapp/ice') {
    const q = new URL(req.url, 'http://x').searchParams;
    const legacy = q.has('map') || [...q.keys()].some((k) => !ICE_V2_PARAMS.has(k));
    const target = (ICE_V2_SERVE && !legacy) ? 'client-ice-v2.html' : 'ice.html';
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end(readFileSync(path.join(staticDir, 'webapp', target)));
    return;
  }
  if (p.startsWith('/photos/')) {
    file = path.join(photosDir, p.slice('/photos/'.length));
    if (!file.startsWith(photosDir) || !existsSync(file) || statSync(file).isDirectory()) {
      res.writeHead(404); res.end('no'); return;
    }
  } else {
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

const NOW = new Date('2026-11-22T16:30:00Z'); /* 19:30 Минск */

const P = (n) => '/photos/' + n;
const PHOTO = {
  nemiga: P('arena-38/hero.webp'),
  ledoviy: P('arena-25/hero.jpg'),
  gorky: P('arena-11/hero.webp'),
  chizh: P('arena-115/hockey-rink-interior.jpg'),
  mozyr: P('mozyr-global-ice/hero.jpg'),
};

const UI_FLAGS = { season_ui: false, bookings_tab: true, fast_tabs: false, search_board: false, redesign_s1: true, redesign_s2: true, redesign_s3: true, redesign_s4: true };

function tgMock() {
  return `window.Telegram = { WebApp: {
    initData: 'mock', initDataUnsafe: { user: { id: 1, first_name: 'Максим', allows_write_to_pm: true } }, colorScheme: 'light', themeParams: {},
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

/* Ответ /ice/schedule — сгенерирован tests/e2e/fixtures/build_ice_v2_fixtures.py
   из реального shape_schedule; ключ "<variant>|<day>|<kind>". */
const ICE_FIX = JSON.parse(readFileSync(path.join(here, 'fixtures', 'ice-v2.json'), 'utf-8'));
let WITH_COMPANY = false;
let WITH_USUAL = false;
function scheduleFor(variant, q) {
  const day = q.get('day') || 'today';
  const kind = q.get('kind') || 'skate';
  const base = ICE_FIX[`${variant}|${day}|${kind}`] || ICE_FIX[`base|${day}|${kind}`];
  if (!WITH_COMPANY && !WITH_USUAL) return base;
  const d = JSON.parse(JSON.stringify(base));
  if (WITH_COMPANY) {
    /* TASK-450 (5.3): сервер докидывает company на строки с моей открытой компанией — имитируем на первой видимой. */
    const row = (d.ongoing || [])[0] || (d.upcoming || [])[0] || ((d.groups || [])[0] || { rows: [] }).rows[0];
    if (row) row.company = { code: 'abc12345', going_count: 3, page_url: '/k/abc12345' };
  }
  if (WITH_USUAL) {
    /* TASK-452 (5.5): blended «обычно» с сервера — usual на строках сеансов. */
    for (const list of [d.ongoing, d.upcoming]) {
      for (const r of list || []) {
        if (r.session_id === 401) r.usual = { key: 'busy', word: 'людно' };
        if (r.session_id === 403) r.usual = { key: 'calm', word: 'свободно' };
      }
    }
  }
  return d;
}

const WATCH_CALLS = [];
let SCHED_VARIANT = 'base';
let CHECKIN_STATE = {};

async function openIce(browser, { variant, flags, url, now, flagsCache, company, usual } = {}) {
  SCHED_VARIANT = variant || 'base';
  WITH_COMPANY = !!company;
  WITH_USUAL = !!usual;
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Minsk', locale: 'ru-RU' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|ERR_FAILED|net::|404/.test(m.text())) errors.push(m.text()); });
  await page.clock.setFixedTime(now || NOW);
  if (flagsCache) {
    await page.addInitScript((fl) => {
      try { localStorage.setItem('cw_ui_flags_v1', JSON.stringify({ u: '1', ...fl, at: Date.now() })); } catch (e) {}
    }, flagsCache);
  }
  await page.route('https://telegram.org/**', (r) => r.fulfill({ contentType: 'text/javascript', body: tgMock() }));
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.route('**/api/**', async (r) => {
    const url2 = new URL(r.request().url());
    const p = url2.pathname;
    const json = (body) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (p === '/api/webapp/client/ui-flags') return json(flags || UI_FLAGS);
    if (p === '/api/webapp/client/ice/schedule') return json(scheduleFor(SCHED_VARIANT, url2.searchParams));
    if (p === '/api/webapp/client/session' && r.request().method() === 'GET') return json({ city_id: 1 });
    if (p === '/api/webapp/client/session/catalog-filters') return json({ success: true });
    if (p === '/api/public/ice/cities') {
      return json({ items: [
        { id: 1, name: 'Минск', skate_count: 16 },
        { id: 5, name: 'Пинск', skate_count: 4 },
        { id: 3, name: 'Гомель', skate_count: 6 },
      ] });
    }
    if (p === '/api/webapp/client/ice-watches' && r.request().method() === 'POST') {
      WATCH_CALLS.push(JSON.parse(r.request().postData() || '{}'));
      return json({ ok: true, watch_id: 1 });
    }
    if (p === '/api/webapp/client/checkins/state') return json(CHECKIN_STATE);
    if (p === '/api/webapp/client/profiles') return json({ items: [], default_profile_id: null });
    if (p.startsWith('/api/public/photos')) {
      return r.fulfill({ contentType: 'image/jpeg', body: readFileSync(path.join(photosDir, 'arena-25', 'hero.jpg')) });
    }
    return json({});
  });
  await page.goto(base + (url || '/webapp/ice'));
  await page.waitForTimeout(700);
  return { page, ctx, errors };
}

async function shot(page, name, fullPage) {
  await page.screenshot({ path: path.join(shots, name + '.png'), fullPage: !!fullPage });
}

/* Система «Льда» v2: без горизонтального скролла, 5 вкладок, «Лёд» активен,
   ровно один Dela, жёлтого нет вообще, имена без ellipsis. */
async function systemCheck(page, name) {
  const m = await page.evaluate(() => {
    const dela = [...document.querySelectorAll('body *')].filter((el) => {
      const s = getComputedStyle(el);
      return /Dela/.test(s.fontFamily) && el.children.length === 0 && (el.textContent || '').trim();
    });
    const yellow = [...document.querySelectorAll('body *')].some((el) => {
      const c = getComputedStyle(el).backgroundColor;
      const m2 = /^rgb\((2[3-5]\d), (1[6-9]\d|2\d\d), (\d{1,2}|1[0-3]\d)\)$/.exec(c);
      return !!m2;
    });
    const ellip = [...document.querySelectorAll('.iv2-card__name')].some((el) => el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).textOverflow === 'ellipsis');
    const tabs = [...document.querySelectorAll('#clientTabBar .client-tab-bar__btn')];
    return {
      scrollW: document.documentElement.scrollWidth, innerW: window.innerWidth,
      tabs: tabs.map((b) => ({ t: b.textContent.trim(), on: b.classList.contains('client-tab-bar__btn--active') })),
      dela: dela.length, delaText: dela.map((el) => el.textContent.trim()).join('|'),
      yellow, ellip,
    };
  });
  check(name + ': нет горизонтального скролла', m.scrollW <= m.innerW, `${m.scrollW}>${m.innerW}`);
  check(name + ': бар — 5 вкладок', m.tabs.length === 5, m.tabs.map((t) => t.t).join('|'));
  check(name + ': «Лёд» активен', !!m.tabs.find((t) => t.t.includes('Лёд') && t.on), JSON.stringify(m.tabs));
  check(name + ': ровно один Dela', m.dela === 1, `${m.dela} → ${m.delaText}`);
  check(name + ': жёлтого нет', !m.yellow);
  check(name + ': имена без ellipsis', !m.ellip);
}

const browser = await chromium.launch();
try {
  /* 01. Минск вечер: «Идёт сейчас» + красная линия + ближайшие + «Завтра с утра». */
  {
    const { page, ctx, errors } = await openIce(browser);
    await shot(page, '01-minsk-evening');
    await shot(page, '01b-minsk-full', true);
    await systemCheck(page, '01');
    check('01: заголовок «сеансов массового»', (await page.locator('#iv2Title').textContent()).includes('сеансов массового'));
    check('01: живой кусок подзаголовка — «2 идут сейчас»', (await page.locator('.iv2-live').textContent()) === '2 идут сейчас');
    check('01: подзаголовок «из N сегодня»', (await page.locator('#iv2Sub').textContent()).includes('сегодня'));
    check('01: саб строки — «до … · цена»', /^до \d{2}:\d{2} · /.test((await page.locator('.iv2-card__sub').first().textContent()).trim()));
    check('01: плитки видов — 3', await page.locator('#iv2Kinds .iv2-kind').count() === 3);
    check('01: пилюли дней — 4', await page.locator('#iv2Days .iv2-day').count() === 4);
    check('01: «Идёт сейчас» + 2 строки', await page.locator('.iv2-card__going').count() === 2);
    check('01: красная линия «Сейчас 19:30»', (await page.locator('.iv2-nowline').textContent()) === 'Сейчас 19:30');
    check('01: 5 карточек (2 идут + 3 ближайшие)', await page.locator('.iv2-card').count() === 5);
    check('01: «Завтра с утра · пн, 23 ноября»', (await page.locator('.iv2-end').textContent()).includes('Завтра с утра'));
    check('01: «Весь понедельник · N»', /Весь понедельник · \d+/.test(await page.locator('.iv2-end').textContent()));
    check('01: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 02. «С клюшкой» выбран. */
  {
    const { page, ctx, errors } = await openIce(browser);
    await page.click('[data-kind="ohm"]');
    await page.waitForTimeout(600);
    await shot(page, '02-ohm');
    await systemCheck(page, '02');
    check('02: плитка «С клюшкой» выбрана', await page.locator('[data-kind="ohm"].iv2-kind--on').count() === 1);
    check('02: заголовок с клюшкой', (await page.locator('#iv2Title').textContent()).includes('клюшк'));
    check('02: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 03. Пустой вид (Фигурное 0) → прыжок в ближайший день с сеансами. */
  {
    const { page, ctx, errors } = await openIce(browser);
    check('03: «Фигурное» бледное', await page.locator('[data-kind="figure"].iv2-kind--empty').count() === 1);
    await page.click('[data-kind="figure"]');
    await page.waitForSelector('.iv2-grouphead', { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(300);
    await shot(page, '03-figure-weekend');
    check('03: после тапа — группы выходных', await page.locator('.iv2-grouphead').count() >= 1);
    check('03: пилюля «Выходные» выбрана', await page.locator('[data-day="weekend"].iv2-day--on').count() === 1);
    check('03: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 04. «Завтра». */
  {
    const { page, ctx, errors } = await openIce(browser);
    await page.click('[data-day="tomorrow"]');
    await page.waitForSelector('.iv2-card', { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(300);
    await shot(page, '04-tomorrow');
    await systemCheck(page, '04');
    check('04: «завтра» в подзаголовке', (await page.locator('#iv2Sub').textContent()).includes('завтра'));
    check('04: строк завтра — 6', await page.locator('.iv2-card').count() === 6);
    check('04: без «Идёт сейчас»/линии', await page.locator('.iv2-card__going, .iv2-nowline').count() === 0);
    check('04: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 05. «Выходные» — группы по дням. */
  {
    const { page, ctx, errors } = await openIce(browser);
    await page.click('[data-day="weekend"]');
    await page.waitForSelector('.iv2-grouphead', { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(300);
    await shot(page, '05-weekend');
    check('05: две группы Сб/Вс', await page.locator('.iv2-grouphead').count() === 2);
    check('05: «Сб, 28» и «Вс, 29»', (await page.locator('#iv2List').textContent()).includes('Сб, 28') && (await page.locator('#iv2List').textContent()).includes('Вс, 29'));
    check('05: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 06. Ночь 03:13. */
  {
    const { page, ctx, errors } = await openIce(browser, { variant: 'night', now: new Date('2026-11-23T00:13:00Z') });
    await shot(page, '06-night');
    await systemCheck(page, '06');
    check('06: линия «Сейчас 03:13» первой', (await page.locator('.iv2-nowline').textContent()) === 'Сейчас 03:13');
    check('06: «ближайший в …» в подзаголовке', (await page.locator('#iv2Sub').textContent()).includes('ближайший в'));
    check('06: без «Идёт сейчас»', await page.locator('.iv2-card__going').count() === 0);
    check('06: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 07. Поздно: «Сегодня лёд закончился». */
  {
    const { page, ctx, errors } = await openIce(browser, { variant: 'late', now: new Date('2026-11-22T20:10:00Z') });
    await shot(page, '07-late');
    await systemCheck(page, '07');
    check('07: заголовок «Сегодня лёд закончился»', (await page.locator('#iv2Title').textContent()).includes('лёд закончился'));
    check('07: блок «Завтра с утра» раскрыт', await page.locator('.iv2-end__row').count() === 3);
    check('07: без строк/линии', await page.locator('.iv2-row, .iv2-nowline, .iv2-card').count() === 0);
    check('07: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 08. Завтра пусто → «Следующий лёд: сб, 28» + подписка. */
  {
    const { page, ctx, errors } = await openIce(browser, { variant: 'tomorrow-empty' });
    await page.click('[data-day="tomorrow"]');
    await page.waitForSelector('.iv2-end__card--empty', { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(300);
    await shot(page, '08-next-ice');
    check('08: «Следующий лёд: сб, 28»', (await page.locator('#iv2List').textContent()).includes('Следующий лёд: сб, 28'));
    check('08: кнопка подписки', await page.locator('[data-watch]').count() === 1);
    await page.click('[data-watch]');
    await page.waitForTimeout(300);
    check('08: POST ice-watches schedule_fresh', WATCH_CALLS.some((w) => w.watch_kind === 'schedule_fresh'), JSON.stringify(WATCH_CALLS));
    check('08: подтверждение после тапа', (await page.locator('#iv2List').textContent()).includes('Сообщим'));
    check('08: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 09. Один каток (Пинск): плиток нет, когда вид один. */
  {
    const { page, ctx, errors } = await openIce(browser, { variant: 'onerink', url: '/webapp/ice?city_id=5' });
    await shot(page, '09-one-rink');
    await shot(page, '09b-one-rink-full', true);
    await systemCheck(page, '09');
    check('09: плитки скрыты (один вид)', await page.locator('#iv2Kinds .iv2-kind').count() === 0);
    check('09: пилюли дней скрыты', await page.locator('#iv2Days .iv2-day').count() === 0);
    check('09: карточка катка с адресом', await page.locator('.iv2-rink').count() === 1 && (await page.locator('.iv2-rink').textContent()).includes('Завальная'));
    check('09: «На неделе» с чипсами', (await page.locator('#iv2List').textContent()).includes('На неделе') && await page.locator('.iv2-wchip').count() >= 4);
    check('09: строки без имени катка', await page.locator('.iv2-card--bare .iv2-card__name').count() === 0);
    check('09: Пинск в пилюле города', (await page.locator('#iv2City').textContent()).includes('Пинск'));
    check('09: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 10. Sticky: плитки+дни прилипают при скролле. */
  {
    const { page, ctx, errors } = await openIce(browser);
    await page.evaluate(() => window.scrollTo(0, 500));
    await page.waitForTimeout(400);
    await shot(page, '10-sticky');
    const st = await page.evaluate(() => {
      const el = document.getElementById('iv2Stick');
      const r = el.getBoundingClientRect();
      return { pos: getComputedStyle(el).position, top: r.top, stuck: el.classList.contains('iv2-stick--on') || r.top <= 80 };
    });
    check('10: блок sticky', st.pos === 'sticky' || st.pos === '-webkit-sticky', st.pos);
    check('10: прилип под шапкой', st.top <= 80, `top=${st.top}`);
    check('10: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 11. Шторка поиска. */
  {
    const { page, ctx, errors } = await openIce(browser);
    await page.click('#iv2Search');
    await page.waitForTimeout(300);
    check('11: шторка открыта', await page.locator('#iv2SearchSheet:not([hidden])').count() === 1);
    check('11: все 5 катков', await page.locator('#iv2SearchList .iv2-srow').count() === 5);
    await page.fill('#iv2SearchInput', 'немиг');
    await page.waitForTimeout(200);
    check('11: фильтр «немиг» → 1 каток', await page.locator('#iv2SearchList .iv2-srow').count() === 1);
    await shot(page, '11-search');
    check('11: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 12. s5: живая загрузка + «Я здесь» в идущих строках. */
  {
    CHECKIN_STATE = { sessions: { '401': { live: { level: 2, count: 7, last_min: 5 }, checked_in: false } } };
    const { page, ctx, errors } = await openIce(browser, { flags: { ...UI_FLAGS, redesign_s5: true }, flagsCache: { ...UI_FLAGS, redesign_s5: true } });
    await page.waitForTimeout(500);
    await shot(page, '12-checkins');
    check('12: «Я здесь» в идущей строке', await page.locator('[data-checkin="401"]').count() === 1);
    check('12: живая загрузка', (await page.locator('#iv2List').textContent()).includes('Сейчас в меру'));
    check('12: без JS-ошибок', errors.length === 0, errors.join('; '));
    CHECKIN_STATE = {};
    await ctx.close();
  }

  /* 14. TASK-452: «Обычно …» на строках под s5; у идущего с live — без дубли. */
  {
    CHECKIN_STATE = { sessions: { '401': { live: { level: 2, count: 7, last_min: 5 }, checked_in: false } } };
    const { page, ctx, errors } = await openIce(browser, {
      usual: true,
      flags: { ...UI_FLAGS, redesign_s5: true },
      flagsCache: { ...UI_FLAGS, redesign_s5: true },
    });
    await page.waitForTimeout(500);
    await page.evaluate(() => {
      const c = [...document.querySelectorAll('.iv2-card')].find((el) => el.getAttribute('data-session') === '403');
      if (c) c.scrollIntoView({ block: 'center' });
    });
    await page.waitForTimeout(300);
    await shot(page, '14-usual');
    const rows = await page.evaluate(() => [...document.querySelectorAll('.iv2-card')].map((c) => ({
      sid: c.getAttribute('data-session'),
      usual: ((c.querySelector('.iv2-card__usual') || {}).textContent || '').trim(),
    })));
    const by = Object.fromEntries(rows.map((r) => [r.sid, r.usual]));
    check('14: у 403 «Обычно свободно»', /Обычно свободно/.test(by['403'] || ''), JSON.stringify(by));
    check('14: у 401 с live «Обычно» скрыто', !(by['401'] || ''), by['401']);
    /* без флага s5 — «Обычно» нет, даже если сервер прислал поле */
    check('14: без JS-ошибок', errors.length === 0, errors.join('; '));
    CHECKIN_STATE = {};
    await ctx.close();
  }
  {
    const { page, ctx, errors } = await openIce(browser, { usual: true, flags: UI_FLAGS, flagsCache: UI_FLAGS });
    await page.waitForTimeout(500);
    await shot(page, '14b-usual-off');
    check('14b: без s5 узлов .iv2-card__usual нет', await page.locator('.iv2-card__usual').count() === 0);
    check('14b: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }

  /* 13. s4 off → старая вкладка; s4 on + ?map=1 → старая вкладка. */
  {
    ICE_V2_SERVE = false;
    const { page, ctx, errors } = await openIce(browser, { flags: { ...UI_FLAGS, redesign_s4: false } });
    await shot(page, '13-s4-off');
    check('13: старый ice.html (#iceRoot)', await page.locator('#iceRoot').count() === 1);
    check('13: нет v2-разметки', await page.locator('#iv2Title').count() === 0);
    check('13: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();

    ICE_V2_SERVE = true;
    const r2 = await openIce(browser, { url: '/webapp/ice?map=1' });
    check('13b: ?map=1 → старая вкладка', await r2.page.locator('#iceRoot').count() === 1);
    check('13b: нет v2-разметки', await r2.page.locator('#iv2Title').count() === 0);
    await r2.ctx.close();
  }
  /* 14. TASK-450 (5.3): плашка «Твоя компания · идут N» в строке — тап → страница компании. */
  {
    const { page, ctx, errors } = await openIce(browser, { company: true, flags: { ...UI_FLAGS, redesign_s5: true }, flagsCache: { ...UI_FLAGS, redesign_s5: true } });
    const comp = page.locator('.iv2-card__comp');
    check('14: плашка компании есть', await comp.count() === 1);
    if (await comp.count()) {
      check('14: текст «Твоя компания · идут 3»', (await comp.textContent()).includes('идут 3'));
      await comp.scrollIntoViewIfNeeded();
      await page.waitForTimeout(200);
      check('14: плашка во вьюпорте', await comp.isVisible() && await comp.evaluate((el) => {
        const r = el.getBoundingClientRect();
        return r.top >= 0 && r.bottom <= window.innerHeight;
      }));
      await shot(page, '14-company-plaque');
    }
    check('14: без JS-ошибок', errors.length === 0, errors.join('; '));
    await ctx.close();
  }
} finally {
  await browser.close();
  server.close();
}
console.log(failures ? `\n${failures} failed` : '\nall checks pass');
process.exit(failures ? 1 : 0);
