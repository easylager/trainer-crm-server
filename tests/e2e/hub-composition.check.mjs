/**
 * TASK-149: headless-проверка композиции клиентского хаба (экраны 05/06 макета).
 * Статика client-home.html + стабы /api/* (Telegram и сеть не нужны).
 *
 * Сценарии (390×844, таймзона Europe/Minsk, «сейчас» зафиксировано на 19:30):
 *   а) гость: тизер + сеансы + фасеты → приветствие, ОДИН блок льда, поиск, «Куда катимся»;
 *   б) клиент с ближайшей записью: запись выше льда, рынок ниже;
 *   в) пустой рынок: ни плиток, ни сетки, ни карусели, ни блока льда — только поиск;
 *   в2) пустой рынок, но на платформе есть тренеры: карусель-фолбэк, плиток нет;
 *   г) льда нет, рынок есть: поиск виден, блока льда нет;
 *   д) клиент с основным тренером: лёд под панелью тренера, рынок ниже;
 *   е) страновой фолбэк «далёкого» льда: строки сеансов и подпись приветствия не выдумываются.
 * Везде: «Подборки»/«Сервис»/погоды нет, горизонтального скролла нет, JS-ошибок нет.
 *
 * Run: node tests/e2e/hub-composition.check.mjs
 * Скриншоты: tests/e2e/__shots__/hub-composition/ (каталог в .gitignore)
 */
import { chromium } from 'playwright';
import http from 'node:http';
import { mkdirSync, rmSync, readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const webappDir = path.join(here, '../../static/webapp');
// Чистим только свою папку: соседние проверки (карта) держат свои снимки в __shots__/.
const shots = path.join(here, '__shots__', 'hub-composition');
rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });

const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/' || p === '/client-home') p = '/client-home.html';
  const file = path.join(webappDir, p);
  if (!file.startsWith(webappDir) || !existsSync(file) || statSync(file).isDirectory()) {
    res.writeHead(404); res.end('no'); return;
  }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, r));
const base = 'http://localhost:' + server.address().port;

/* «Сейчас»: 3 октября 2026, 19:30 по Минску (16:30Z) — вечер, лёд ещё впереди. */
const NOW = new Date('2026-10-03T16:30:00Z');

function minskParts(date) {
  const f = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Minsk', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).reduce((a, p) => ({ ...a, [p.type]: p.value }), {});
  return { date: `${f.year}-${f.month}-${f.day}`, time: `${f.hour}:${f.minute}` };
}

function session(id, arenaId, name, venueType, minutesAhead, priceMinor) {
  const at = new Date(NOW.getTime() + minutesAhead * 60000);
  const m = minskParts(at);
  return {
    session_id: id, arena_id: arenaId, arena_slug: 'a' + arenaId, arena_name: name, venue_type: venueType,
    kind: 'public_skate', starts_at_utc: at.toISOString(), local_date: m.date, starts_at_local: m.time,
    price_adult_minor: priceMinor, currency_code: 'BYN',
  };
}

function teaser(overrides) {
  const sessions = [
    session(101, 11, 'Чижовка-арена', 'ice', 50, 1200),
    session(102, 12, 'Парк Горького', 'outdoor', 95, 500),
    session(103, 13, 'Ледовый дворец', 'ice', 140, 800),
    session(104, 11, 'Чижовка-арена', 'ice', 200, 1200),
  ];
  return {
    ...sessions[0], arena_district: 'Заводской', city_id: 2, city_name: 'Минск', thumb: null, card: null, distance_km: null,
    sessions, is_country_fallback: false, far_confirmed: false, ...(overrides || {}),
  };
}

const RICH_MARKET = {
  facets: [{ key: 'ice', chip: 'Лёд', count: 5 }, { key: 'outdoor', chip: 'Открытые', count: 3 }, { key: 'shop', chip: 'Магазин', count: 2 }],
  eveningHits: 4, outdoorLive: true, trainersTotal: 14,
};
const EMPTY_MARKET = { facets: [], eveningHits: 0, outdoorLive: false, trainersTotal: 0 };

const tomorrow = minskParts(new Date(NOW.getTime() + 24 * 3600 * 1000)).date;
const BOOKING_DAYS = [{
  date: tomorrow, day_label: 'вс',
  bookings: [{ id: 501, status: 'confirmed', start_time: '18:15', duration_minutes: 45, trainer_id: 7, trainer_name: 'Анна Коваль', arena_name: 'Ледовый дворец', service_id: 3 }],
}];

const TELEGRAM_MOCK = `window.Telegram = { WebApp: {
  initData: 'mock', initDataUnsafe: { user: { id: 1, first_name: 'Максим' } }, colorScheme: 'light', themeParams: {},
  version: '7.0', platform: 'ios', isExpanded: true, viewportHeight: 844,
  ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {}, onEvent() {}, offEvent() {},
  enableClosingConfirmation() {}, disableVerticalSwipes() {}, HapticFeedback: { selectionChanged() {}, impactOccurred() {}, notificationOccurred() {} },
  BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} }, MainButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
} };`;

let failures = 0;
function check(name, cond, extra) {
  console.log((cond ? '✔' : '✖') + ' ' + name + (cond || !extra ? '' : '  → ' + extra));
  if (!cond) failures++;
}

/** Открывает хаб со стабами. cfg: { bootstrap, market, platformTrainers }. */
async function openHub(browser, cfg) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Minsk', locale: 'ru-RU' });
  const page = await ctx.newPage();
  const errors = [];
  const navigations = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|ERR_FAILED|net::/.test(m.text())) errors.push(m.text()); });
  await page.clock.setFixedTime(NOW);
  await page.route('https://telegram.org/**', (r) => r.fulfill({ contentType: 'text/javascript', body: TELEGRAM_MOCK }));
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  // Переходы из хаба (тап по плитке): запоминаем адрес и не грузим чужие страницы.
  await page.route((u) => /\/(ice|arena|catalog|client-bookings)$/.test(u.pathname), (r) => {
    navigations.push(r.request().url());
    return r.fulfill({ contentType: 'text/html', body: '<html><body>stub</body></html>' });
  });
  const market = cfg.market || EMPTY_MARKET;
  await page.route('**/api/**', (r) => {
    const url = new URL(r.request().url());
    const p = url.pathname;
    const q = url.search;
    const json = (body) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (p === '/api/webapp/client/hub/bootstrap') return json(cfg.bootstrap);
    if (p === '/api/webapp/client/profiles') return json({ items: [], default_profile_id: null });
    if (p === '/api/webapp/client/slots') return json({ slots: [] });
    if (p === '/api/public/ice/arenas') {
      if (q.includes('when=today_evening')) return json({ items: [], window: { key: 'today_evening', hits: market.eveningHits } });
      if (q.includes('venue_type=outdoor')) return json({ items: market.outdoorLive ? [{ id: 12, live: { kind: 'session' } }] : [] });
      if (q.includes('limit=4')) return json({ items: [] });
      return json({ items: [], venue_type_facets: market.facets, total: 0 });
    }
    if (p === '/api/public/trainers') {
      if (q.includes('limit=1&')) return json({ items: [], total: market.trainersTotal });
      return json({ items: cfg.platformTrainers || [], total: (cfg.platformTrainers || []).length });
    }
    if (p.startsWith('/api/public/photos')) return r.fulfill({ status: 404, body: '' });
    return json({});
  });
  await page.goto(base + '/client-home.html');
  await page.waitForSelector('body.hub-body--revealed', { timeout: 10000 });
  await page.waitForTimeout(700); // дожидаемся конца fade-up и поздних запросов рынка
  return { page, ctx, errors, navigations };
}

/** Снимок структуры: что видно и где (верхняя граница в px документа). */
async function snapshot(page) {
  return page.evaluate(() => {
    const top = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const cs = getComputedStyle(el);
      if (el.hidden || cs.display === 'none' || cs.visibility === 'hidden') return null;
      const r = el.getBoundingClientRect();
      if (!r.width && !r.height) return null;
      return Math.round(r.top + window.scrollY);
    };
    const visibleAll = (sel) => [...document.querySelectorAll(sel)].filter((el) => {
      const cs = getComputedStyle(el);
      return !el.hidden && cs.display !== 'none' && el.getBoundingClientRect().height > 0;
    });
    const bodyText = document.body.innerText;
    return {
      greeting: top('#hubGreeting'),
      greetingText: (document.getElementById('hubGreetingHello') || {}).textContent || '',
      subText: (document.getElementById('hubGreetingSub') || {}).hidden ? '' : ((document.getElementById('hubGreetingSub') || {}).textContent || ''),
      heroHeight: Math.round(document.getElementById('hubHero').getBoundingClientRect().height),
      iceZone: top('#hubIceZone'),
      kicker: top('#hubIceKicker'),
      kickerText: (document.getElementById('hubIceKicker') || {}).textContent || '',
      teaser: top('a.hub-ice-card'),
      teaserFar: !!document.querySelector('a.hub-ice-card--far'),
      sessions: top('#hubIceSessions'),
      sessionBlocks: visibleAll('.hub-ice-today__card').length,
      sessionRows: visibleAll('.hub-ice-today__row').length,
      search: top('#hubSearchRow'),
      explore: top('#hubExplore'),
      exploreTitle: (document.querySelector('.hub-explore__title') || {}).textContent || '',
      tiles: visibleAll('.hub-cg__tile').map((el) => ({
        key: el.dataset.tile, href: el.getAttribute('href'), text: el.innerText.replace(/\s+/g, ' ').trim(),
        wide: el.classList.contains('hub-cg__tile--wide'), left: Math.round(el.getBoundingClientRect().left), width: Math.round(el.getBoundingClientRect().width),
      })),
      discovery: top('#hubDiscovery'),
      discoveryTitle: (document.querySelector('.hub-discovery__title') || {}).textContent || '',
      nextCard: top('#nextCard'),
      myTrainer: top('#trainerCard'),
      upcoming: top('#upcomingSection'),
      footer: top('#hubFooterAside'),
      bodyText,
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
      bodyScrollW: document.body.scrollWidth,
    };
  });
}

function commonChecks(label, s, errors) {
  check(`${label}: нет слова «Подборки»`, !/Подборки/i.test(s.bodyText));
  check(`${label}: нет плитки/слова «Сервис», «Заточка», «Бесплатно», «Каток недели»`, !/Сервис|Заточк|Бесплатно|Каток недели/i.test(s.bodyText));
  check(`${label}: нет погоды (°, «лёд держит», «идеальный вечер»)`, !/°|погод|лёд держит|идеальн/i.test(s.bodyText));
  check(`${label}: нет горизонтального скролла`, s.scrollW <= s.clientW && s.bodyScrollW <= s.clientW, `scrollW=${s.scrollW} clientW=${s.clientW} bodyScrollW=${s.bodyScrollW}`);
  check(`${label}: нет JS-ошибок`, errors.length === 0, errors.join(' | '));
  check(`${label}: ровно один блок сеансов льда (не больше)`, s.sessionBlocks <= 1, 'блоков: ' + s.sessionBlocks);
}

const increasing = (...vals) => vals.every((v, i) => v != null && (i === 0 || v > vals[i - 1]));

const browser = await chromium.launch();
try {
  const heroHeights = {};

  /* ---------- а) гость ---------- */
  {
    const { page, ctx, errors, navigations } = await openHub(browser, {
      bootstrap: { bookings: { days: [] }, requests: { items: [] }, client_session: { city_id: 2 }, ice_teaser: teaser(), passes: [] },
      market: RICH_MARKET,
      platformTrainers: [{ id: 1, profile: { first_name: 'Анна', last_name: 'К' }, photos: [], services: [] }],
    });
    const s = await snapshot(page);
    heroHeights.guest = s.heroHeight;
    check('а) приветствие «{время суток}, Максим» (вечер, 19:30)', s.greetingText === 'Вечер, Максим', s.greetingText);
    check('а) подпись — только факты: «Минск · 4 катка вечером»', s.subText === 'Минск · 4 катка вечером', s.subText);
    check('а) порядок: приветствие → кикер → герой → сеансы → поиск → «Куда катимся»',
      increasing(s.greeting, s.kicker, s.teaser, s.sessions, s.search, s.explore), JSON.stringify({ g: s.greeting, k: s.kicker, t: s.teaser, s: s.sessions, q: s.search, e: s.explore }));
    check('а) кикер блока льда честный: «На льду · Минск», без «сейчас»', s.kickerText === 'На льду · Минск' && !/сейчас/i.test(s.kickerText), s.kickerText);
    check('а) строки сеансов: 3 (4 сеанса минус тизерный)', s.sessionRows === 3 && s.sessionBlocks === 1, `rows=${s.sessionRows} blocks=${s.sessionBlocks}`);
    check('а) заголовок секции рынка — «Куда катимся»', s.exploreTitle === 'Куда катимся', s.exploreTitle);
    check('а) три плитки: Катки, Тренеры, Магазины — по порядку', s.tiles.map((t) => t.key).join() === 'rinks,trainers,shops', s.tiles.map((t) => t.key).join());
    check('а) счётчики честные: Катки 8 (5 крытых + 3 открытых), Тренеры 14, Магазины 2',
      /Катки 8\b/.test(s.tiles[0].text) && /Тренеры 14\b/.test(s.tiles[1].text) && /Магазины 2\b/.test(s.tiles[2].text), s.tiles.map((t) => t.text).join(' | '));
    check('а) «Катки»: подпись «4 катка вечером» и ссылка с when=today_evening',
      /4 катка вечером/.test(s.tiles[0].text) && /^ice\?city_id=2&when=today_evening$/.test(s.tiles[0].href), s.tiles[0].href);
    check('а) нечётные три плитки: первая на всю ширину, две другие рядом',
      s.tiles[0].wide && s.tiles[0].width > 300 && s.tiles[1].width < 200 && s.tiles[2].width < 200 && s.tiles[2].left > s.tiles[1].left);
    check('а) карусель #hubDiscovery скрыта: рынок не дублируется', s.discovery == null && !/Места и тренеры|Тренеры на платформе/.test(s.bodyText));
    check('а) нет отдельной секции «Сегодня на льду» внизу', !/Сегодня на льду/.test(s.bodyText));
    commonChecks('а)', s, errors);
    await page.screenshot({ path: path.join(shots, '01-guest-full.png'), fullPage: true });
    await page.screenshot({ path: path.join(shots, '01-guest-viewport.png') });

    // Тап по «Катки» ведёт в Поиск с окном; тап по «Тренерам» — с intent=coach.
    await page.click('[data-tile="rinks"]');
    await page.waitForTimeout(300);
    check('а) тап «Катки» → ice?city_id=2&when=today_evening', navigations.some((u) => /\/ice\?city_id=2&when=today_evening/.test(u)), navigations.join(' | '));
    await ctx.close();
  }
  {
    const { page, ctx, navigations } = await openHub(browser, {
      bootstrap: { bookings: { days: [] }, requests: { items: [] }, client_session: { city_id: 2 }, ice_teaser: teaser(), passes: [] },
      market: RICH_MARKET,
    });
    await page.click('[data-tile="trainers"]');
    await page.waitForTimeout(300);
    check('а) тап «Тренеры» → ice?city_id=2&intent=coach', navigations.some((u) => /\/ice\?city_id=2&intent=coach/.test(u)), navigations.join(' | '));
    await ctx.close();
  }

  /* ---------- б) клиент с ближайшей записью ---------- */
  {
    const { page, ctx, errors } = await openHub(browser, {
      bootstrap: { bookings: { days: BOOKING_DAYS }, requests: { items: [] }, client_session: { city_id: 2 }, ice_teaser: teaser(), passes: [] },
      market: RICH_MARKET,
    });
    const s = await snapshot(page);
    check('б) приветствие остаётся: «Вечер, Максим»', s.greetingText === 'Вечер, Максим', s.greetingText);
    check('б) порядок: приветствие → запись → блок льда (не выкинут) → поиск → рынок',
      increasing(s.greeting, s.nextCard, s.iceZone, s.search, s.explore), JSON.stringify({ g: s.greeting, n: s.nextCard, z: s.iceZone, q: s.search, e: s.explore }));
    check('б) лёд клиента с записью на месте: герой + строки сеансов (как сегодня)', s.teaser != null && s.sessionRows === 3);
    check('б) «Куда катимся» ниже записи и льда, до футера', increasing(s.nextCard, s.explore, s.footer));
    check('б) плитки на месте', s.tiles.length === 3);
    commonChecks('б)', s, errors);
    await page.screenshot({ path: path.join(shots, '02-client-booking-full.png'), fullPage: true });
    await ctx.close();
  }

  /* ---------- в) пустой рынок ---------- */
  {
    const { page, ctx, errors } = await openHub(browser, {
      bootstrap: { bookings: { days: [] }, requests: { items: [] }, client_session: { city_id: 2 }, ice_teaser: null, passes: [] },
      market: EMPTY_MARKET,
    });
    const s = await snapshot(page);
    heroHeights.noCity = s.heroHeight;
    check('в) пустой рынок: секции «Куда катимся» нет', s.explore == null && s.tiles.length === 0 && !/Куда катимся/.test(s.bodyText));
    check('в) пустой рынок: нет блока льда, героя, строк сеансов', s.teaser == null && s.sessions == null && s.sessionRows === 0 && s.kicker == null);
    check('в) пустой рынок: нет карусели (на платформе тренеров нет)', s.discovery == null);
    check('в) пустой рынок: подписи под приветствием нет (города нет)', s.subText === '');
    check('в) пустой рынок: поиск виден', s.search != null);
    commonChecks('в)', s, errors);
    await page.screenshot({ path: path.join(shots, '03-empty-market.png'), fullPage: true });
    await ctx.close();
  }
  {
    const { page, ctx, errors } = await openHub(browser, {
      bootstrap: { bookings: { days: [] }, requests: { items: [] }, client_session: {}, ice_teaser: null, passes: [] },
      market: EMPTY_MARKET,
      platformTrainers: [
        { id: 1, profile: { first_name: 'Анна', last_name: 'Коваль' }, photos: [], services: [] },
        { id: 2, profile: { first_name: 'Пётр', last_name: 'Лис' }, photos: [], services: [] },
      ],
    });
    const s = await snapshot(page);
    check('в2) рынок пуст, тренеры на платформе есть: карусель-фолбэк показана', s.discovery != null && s.discoveryTitle === 'Тренеры на платформе', s.discoveryTitle);
    check('в2) плиток нет, секции «Куда катимся» нет', s.explore == null && s.tiles.length === 0);
    commonChecks('в2)', s, errors);
    await page.screenshot({ path: path.join(shots, '04-empty-market-fallback-carousel.png'), fullPage: true });
    await ctx.close();
  }

  /* ---------- г) льда нет, рынок есть, поиск виден ---------- */
  {
    const { page, ctx, errors } = await openHub(browser, {
      bootstrap: { bookings: { days: [] }, requests: { items: [] }, client_session: { city_id: 2 }, ice_teaser: null, passes: [] },
      market: { ...RICH_MARKET, eveningHits: 0 },
    });
    const s = await snapshot(page);
    check('г) нет льда: поиск виден', s.search != null);
    check('г) нет льда: нет героя, кикера и строк сеансов', s.teaser == null && s.kicker == null && s.sessions == null && s.sessionRows === 0);
    check('г) нет льда: плитки рынка при этом есть, порядок поиск → «Куда катимся»', s.tiles.length === 3 && increasing(s.search, s.explore));
    check('г) нет вечерних катков: «Катки» без «вечером» и без when в ссылке', !/вечером/.test(s.tiles[0].text) && s.tiles[0].href === 'ice?city_id=2', s.tiles[0].text + ' ' + s.tiles[0].href);
    check('г) без teaser города для подписи нет — подписи под приветствием нет', s.subText === '');
    commonChecks('г)', s, errors);
    await page.screenshot({ path: path.join(shots, '05-no-ice-search-visible.png'), fullPage: true });
    await ctx.close();
  }

  /* ---------- д) клиент с основным тренером ---------- */
  {
    const { page, ctx, errors } = await openHub(browser, {
      bootstrap: {
        bookings: { days: [] }, requests: { items: [] }, ice_teaser: teaser(), passes: [],
        client_session: { city_id: 2, primary_trainer_id: 7, primary_trainer_name: 'Анна Коваль', primary_trainer_can_book: true },
      },
      market: RICH_MARKET,
    });
    const s = await snapshot(page);
    check('д) тренер выше льда (placeIceZone below-trainer), лёд выше рынка',
      increasing(s.greeting, s.myTrainer, s.iceZone, s.search, s.explore), JSON.stringify({ g: s.greeting, t: s.myTrainer, z: s.iceZone, q: s.search, e: s.explore }));
    check('д) рынок после льда, до футера', increasing(s.explore, s.footer));
    commonChecks('д)', s, errors);
    await page.screenshot({ path: path.join(shots, '06-client-trainer-full.png'), fullPage: true });
    await ctx.close();
  }

  /* ---------- е) страновой фолбэк «далёкого» льда ---------- */
  {
    const { page, ctx, errors } = await openHub(browser, {
      bootstrap: {
        bookings: { days: [] }, requests: { items: [] }, client_session: {}, passes: [],
        ice_teaser: teaser({ is_country_fallback: true, far_confirmed: true, city_id: 2, distance_km: null }),
      },
      market: RICH_MARKET,
    });
    const s = await snapshot(page);
    check('е) далёкий лёд: карточка «Скоро и у вас» вместо героя', s.teaserFar);
    check('е) далёкий лёд: строки сеансов чужого города не показываются', s.sessionRows === 0 && s.sessions == null);
    check('е) страновой фолбэк: подписи под приветствием нет (это не город клиента)', s.subText === '');
    check('е) страновой фолбэк без города: рынка и плиток нет, поиск виден', s.tiles.length === 0 && s.search != null);
    commonChecks('е)', s, errors);
    await page.screenshot({ path: path.join(shots, '07-country-fallback.png'), fullPage: true });
    await ctx.close();
  }

  check('CLS: строка приветствия не меняет высоту от подписи (с подписью = без подписи)',
    heroHeights.guest != null && heroHeights.guest === heroHeights.noCity, JSON.stringify(heroHeights));
} finally {
  await browser.close();
  server.close();
}

console.log(failures ? `\n✖ провалено проверок: ${failures}` : '\n✔ все проверки композиции хаба пройдены');
console.log('Скриншоты: ' + shots);
process.exit(failures ? 1 : 0);
