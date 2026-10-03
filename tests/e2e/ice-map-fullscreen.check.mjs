/**
 * TASK-147: headless-проверка раскладки полноэкранной карты ice.html.
 * Живого ключа Яндекса нет — стаб ymaps (tests/e2e/ymaps-stub.mjs) + мок API.
 *
 * Проверяет AC-1..AC-7 в DOM/скриншотах: полноэкранность, пины-время,
 * кластер, шторку peek/half, FAB, копирайт, тёмную тему, список на десктопе.
 *
 * Хвост к макету 02 (TASK-147): цвет пина = тип места (токены --app-venue-*), легенда
 * типов под чипами окна (видна/скрыта по составу выдачи), копирайт Яндекса на месте
 * и не перекрыт, нет горизонтального скролла, читаемость на тёмной подложке.
 *
 * По умолчанию гоняется на ymaps-stub.mjs БЕЗ СЕТИ: всё внешнее блокируется, а активность
 * стаба проверяется жёстко (window.__ymapsStub). YMAPS_REAL=1 — тот же сценарий на настоящем
 * API Яндекса (нужна сеть; паритет стаба с реальностью).
 *
 * Run: node tests/e2e/ice-map-fullscreen.check.mjs        (стаб, офлайн)
 *      YMAPS_REAL=1 node tests/e2e/ice-map-fullscreen.check.mjs  (настоящий API)
 * Скриншоты: tests/e2e/__shots__/
 */
import { chromium } from 'playwright';
import http from 'node:http';
import { mkdirSync, rmSync, readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { YMAPS_STUB } from './ymaps-stub.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const webappDir = path.join(here, '../../static/webapp');
const shots = path.join(here, '__shots__');
rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });

/* Собственный статический сервер: под file:// относительные /api/* ломаются. */
const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/') p = '/ice.html';
  const file = path.join(webappDir, p);
  if (!file.startsWith(webappDir) || !existsSync(file) || statSync(file).isDirectory()) {
    res.writeHead(404); res.end('no'); return;
  }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
  res.end(readFileSync(file));
});
await new Promise(r => server.listen(0, r));
const port = server.address().port;
const base = 'http://localhost:' + port;

const REAL = process.env.YMAPS_REAL === '1';
const blocked = []; // внешние запросы, которые в офлайн-режиме отрезаны
/* Общая подготовка страницы: стаб + запрет сети (офлайн) либо только шрифты (реальный API). */
async function prepare(pg) {
  if (REAL) {
    await pg.route('**://fonts.googleapis.com/**', r => r.abort());
    await pg.route('**://fonts.gstatic.com/**', r => r.abort());
    return;
  }
  await pg.addInitScript(YMAPS_STUB);
  await pg.route(u => !/^(http:\/\/localhost|data:|blob:|about:)/.test(u.href), r => {
    blocked.push(r.request().url());
    return r.abort();
  });
}

/* Минск, как в прототипе: координаты/слои данных близки к живой карте. */
const ARENAS = [
  { id: 1, name: 'ТЦ Замок', slug: 'zamok', district: 'Центральный', venue_type: 'ice', tier: 'A', on_map: true, latitude: 53.9295, longitude: 27.5125, thumb: '', address: 'пр-т Победителей, 65', distance_km: null, live: { kind: 'session', text: 'Сегодня вечером 18:15 · взр. 10 · дет. 8', starts_at_local: '18:15' } },
  { id: 2, name: 'Минск-Арена', slug: 'minsk-arena', district: 'Центральный', venue_type: 'ice', tier: 'A', on_map: true, latitude: 53.9365, longitude: 27.4830, thumb: '', address: 'пр-т Победителей, 111', distance_km: null, live: { kind: 'session', text: 'Сегодня вечером 19:00', starts_at_local: '19:00' } },
  { id: 3, name: 'Конькобежный стадион', slug: 'konkobezhnyj', district: 'Центральный', venue_type: 'ice', tier: 'B', on_map: true, latitude: 53.9368, longitude: 27.4836, thumb: '', address: 'пр-т Победителей, 111/1', distance_km: null, live: { kind: 'session', text: 'Сегодня вечером 18:30', starts_at_local: '18:30' } },
  { id: 4, name: 'Ледовый дворец спорта Минской области', slug: 'lds-prityckogo', district: 'Фрунзенский', venue_type: 'ice', tier: 'A', on_map: true, latitude: 53.9076, longitude: 27.4863, thumb: '', address: 'ул. Притыцкого, 27', distance_km: null, live: { kind: 'session', text: 'Сегодня вечером 19:30', starts_at_local: '19:30' } },
  { id: 5, name: 'Чижовка-арена', slug: 'chizhovka', district: 'Заводской', venue_type: 'ice', tier: 'A', on_map: true, latitude: 53.8560, longitude: 27.6390, thumb: '', address: 'ул. Ташкентская, 19', distance_km: null, live: { kind: 'session', text: 'Сегодня вечером 18:45', starts_at_local: '18:45' } },
  { id: 6, name: 'ТЦ DiaMond city', slug: 'diamond-city', district: 'Щомыслица', venue_type: 'ice', tier: 'B', on_map: true, latitude: 53.8500, longitude: 27.4560, thumb: '', address: 'Щомыслица', distance_km: null, live: { kind: 'session', text: 'Сегодня вечером 20:00', starts_at_local: '20:00' } },
  { id: 7, name: 'Олимпик-арена', slug: 'olympic', district: 'Центральный', venue_type: 'ice', tier: 'C', on_map: true, latitude: 53.9445, longitude: 27.4520, thumb: '', address: 'ул. Ратомская, 2', distance_km: null, live: { kind: 'unknown', text: 'Есть в справочнике' } },
  { id: 8, name: 'Лыжероллерная трасса', slug: 'roller-track', district: 'Центральный', venue_type: 'outdoor', tier: 'B', on_map: true, latitude: 53.9185, longitude: 27.5300, thumb: '', address: 'Победителей, 20/3', distance_km: null, live: { kind: 'session', text: 'до 22:00', starts_at_local: 'до 22:00' } },
  { id: 9, name: 'Figuristshop', slug: 'figuristshop', district: 'Ленинский', venue_type: 'shop', tier: 'C', on_map: true, latitude: 53.8945, longitude: 27.5580, thumb: '', address: 'ул. Кирова, 18', distance_km: null, live: { kind: 'unknown', text: 'Заточка · коньки · до 20:00' } },
  { id: 10, name: 'Каток вне окна', slug: 'off-window', district: 'Партизанский', venue_type: 'ice', tier: 'A', on_map: true, latitude: 53.9070, longitude: 27.5880, thumb: '', address: 'ул. Первомайская, 3', distance_km: null, live: { kind: 'session', text: 'Завтра 11:00', starts_at_local: '11:00', outside_window: true } },
];


/* ---------- Хвост к макету 02: хелперы ---------- */
const CITIES = { items: [{ id: 2, name: 'Минск', country: 'BY', latitude: 53.902, longitude: 27.562, skate_count: 20, trainer_count: 0, map_rink_count: 9, bounds: { min_lat: 53.80, max_lat: 53.99, min_lon: 27.38, max_lon: 27.72 } }] };

function place(id, venue_type, tier, lat, lon, live, extra) {
  return Object.assign({ id, name: 'Место ' + id, slug: 'p' + id, district: 'Центральный', venue_type, tier, on_map: true, latitude: lat, longitude: lon, thumb: '', address: 'ул. Тестовая, ' + id, distance_km: null, live }, extra || {});
}
const SESSION = (t) => ({ kind: 'session', text: 'Сегодня вечером ' + t, starts_at_local: t });
const NOSESSION = { kind: 'unknown', text: 'Есть в справочнике' };

/* Места разнесены на ~0.1° — на десктопе 1440 это >100px, кластер их не склеивает. */
const SPREAD = [
  place(101, 'ice', 'A', 53.93, 27.42, SESSION('18:15'), { venue_chip: 'Лёд' }),
  place(102, 'outdoor', 'B', 53.93, 27.55, SESSION('19:00'), { venue_chip: 'Улица' }),
  place(103, 'gym', 'C', 53.86, 27.42, { kind: 'place', text: 'Сегодня 10:00–20:00' }, { venue_chip: 'Зал' }),
  place(104, 'shop', 'C', 53.86, 27.55, { kind: 'place', text: 'Сегодня 10:00–20:00' }, { venue_chip: 'Магазин' }),
  place(105, 'pool', 'C', 53.82, 27.65, NOSESSION, { venue_chip: 'Бассейн' }),
  place(106, 'ice', 'C', 53.96, 27.65, NOSESSION, { venue_chip: 'Лёд' }),
];
const ICE_ONLY = [
  place(201, 'ice', 'A', 53.93, 27.42, SESSION('18:15')),
  place(202, 'ice', 'B', 53.86, 27.55, SESSION('19:00')),
  place(203, 'ice', 'C', 53.82, 27.65, NOSESSION),
];

async function openMap(browser, viewport, arenas) {
  const pg = await browser.newPage({ viewport });
  await prepare(pg);
  await pg.route('**/api/public/ice/cities*', r => r.fulfill({ json: CITIES }));
  await pg.route('**/api/webapp/client/session*', r => r.fulfill({ json: { city_id: 2, city_name: 'Минск' } }));
  await pg.route('**/api/public/ice/arenas*', r => r.fulfill({ json: { items: arenas, total: arenas.length, window: { key: 'evening', label: 'сегодня вечером' } } }));
  await pg.route('**/api/public/ice/map-config*', r => r.fulfill({ json: { yandex_maps_js_api_key: 'stub-key' } }));
  await pg.goto(base + '/ice.html');
  await pg.waitForSelector('#iceViewSwitch', { timeout: 8000 });
  await pg.click('#iceViewSwitch');
  await pg.waitForSelector('#iceMapSheet .ice-map-rail .ice-acard', { timeout: 8000 });
  await pg.waitForTimeout(600);
  return pg;
}

/* Токен → rgb, как его видит браузер в текущей теме. */
function tokenColor(pg, name) {
  return pg.evaluate((n) => {
    const d = document.createElement('i');
    d.style.background = 'var(' + n + ')';
    document.body.appendChild(d);
    const c = getComputedStyle(d).backgroundColor;
    d.remove();
    return c;
  }, name);
}

const TOKEN_OF = { ice: '--app-venue-ice', outdoor: '--app-venue-ice', gym: '--app-venue-gym', choreo: '--app-venue-gym', pool: '--app-venue-pool', shop: '--app-venue-shop', other: '--app-venue-service' };

function legendState(pg) {
  return pg.evaluate(() => {
    const el = document.getElementById('iceMapLegend');
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return {
      display: cs.display,
      hidden: el.hidden,
      pe: cs.pointerEvents,
      rect: { l: r.left, t: r.top, r: r.right, b: r.bottom },
      items: Array.prototype.map.call(el.querySelectorAll('.ice-map-legend__item'), (i) => ({
        text: i.textContent.trim(),
        type: (i.className.match(/ice-map-legend__item--(\w+)/) || [])[1],
        dot: getComputedStyle(i.querySelector('.ice-map-legend__dot')).backgroundColor,
      })),
      overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
      vw: window.innerWidth,
    };
  });
}

/* Цвет пинов по типу: заливка точки (пилюля) или кольцо (полая точка). Выбранный пин — отдельно. */
function pinColors(pg) {
  return pg.evaluate(() => {
    return Array.prototype.map.call(document.querySelectorAll('.ice-ypin'), (p) => {
      const type = (p.className.match(/ice-ypin--(ice|outdoor|gym|choreo|pool|shop|other)\b/) || [])[1];
      const hollow = p.classList.contains('ice-ypin--dot');
      const sel = p.classList.contains('ice-ypin--sel');
      const color = hollow
        ? getComputedStyle(p, '::after').borderTopColor
        : getComputedStyle(p.querySelector('.ice-ypin__dot')).backgroundColor;
      const label = p.querySelector('.ice-ypin__label');
      return { type, hollow, sel, color, label: label ? label.textContent : '' };
    });
  });
}

/* Ожидаемый цвет пина: пилюля — токен типа; полая точка — всегда серый обод (макет 02, .pin-hollow). */
async function expectedPinColor(pg, p) {
  return p.hollow ? tokenColor(pg, '--glide-line-strong') : tokenColor(pg, TOKEN_OF[p.type]);
}

/* Копирайт Яндекса: геометрия + что реально лежит под пальцем в трёх точках текста. */
function attribState(pg) {
  return pg.evaluate(() => {
    const el = document.getElementById('iceMapAttrib');
    const sh = document.getElementById('iceMapSheet');
    const lg = document.getElementById('iceMapLegend');
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const sr = sh.getBoundingClientRect();
    const lr = lg.getBoundingClientRect();
    const on = (x, y) => { const e = document.elementFromPoint(x, y); return !!e && (e === el || el.contains(e)); };
    const link = el.querySelector('a');
    return {
      rect: { l: r.left, t: r.top, r: r.right, b: r.bottom },
      sheetTop: sr.top,
      sheetSnap: sh.dataset.snap,
      shown: cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0,
      inViewport: r.left >= 0 && r.right <= window.innerWidth && r.top >= 0 && r.bottom <= window.innerHeight,
      hit: [on(r.left + 3, (r.top + r.bottom) / 2), on((r.left + r.right) / 2, (r.top + r.bottom) / 2), on(r.right - 3, (r.top + r.bottom) / 2)],
      text: el.textContent.trim(),
      linkHref: link ? link.getAttribute('href') : '',
      legendOverlap: !lg.hidden && !(r.right <= lr.left || lr.right <= r.left || r.bottom <= lr.top || lr.bottom <= r.top),
    };
  });
}

async function checkAttrib(pg, label) {
  const a = await attribState(pg);
  check(label + ': копирайт виден, в экране', a.shown && a.inViewport);
  check(label + ': текст и ссылка на месте', /^© Яндекс · Условия/.test(a.text) && /yandex\.ru\/legal\/maps_termsofuse/.test(a.linkHref));
  check(label + ': ничто не лежит поверх (hit-test в 3 точках)', a.hit.every(Boolean));
  check(label + ': над шторкой (низ копирайта ≤ верх шторки), snap=' + a.sheetSnap, a.rect.b <= a.sheetTop + 0.5);
  check(label + ': не под легендой', !a.legendOverlap);
  return a;
}

function rectsOverlap(a, b) {
  return !(a.r <= b.l || b.r <= a.l || a.b <= b.t || b.b <= a.t);
}

/* Контраст текста легенды к её фону (WCAG). Фон непрозрачный — иначе честно «не посчитано». */
function legendContrast(pg) {
  return pg.evaluate(() => {
    const parse = (c) => { const m = String(c).match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(',').map(parseFloat); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
    const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
    const el = document.getElementById('iceMapLegend');
    const item = el.querySelector('.ice-map-legend__item');
    const fg = parse(getComputedStyle(item).color);
    const bg = parse(getComputedStyle(el).backgroundColor);
    if (!fg || !bg || bg.a < 1) return { ratio: null, bgAlpha: bg && bg.a };
    const a = lum(fg), b = lum(bg);
    return { ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05), bgAlpha: bg.a };
  });
}

let failures = 0;
function check(name, cond) {
  console.log((cond ? '✔' : '✖') + ' ' + name);
  if (!cond) failures++;
}

const browser = await chromium.launch();
try {
  /* ---------- Мобильный: 390×844 ---------- */
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await prepare(page);
  await page.route('**/api/public/ice/cities*', r => r.fulfill({
    json: { items: [{ id: 2, name: 'Минск', country: 'BY', latitude: 53.902, longitude: 27.562, skate_count: 20, trainer_count: 0, map_rink_count: 9, bounds: { min_lat: 53.80, max_lat: 53.99, min_lon: 27.38, max_lon: 27.72 } }] },
  }));
  await page.route('**/api/webapp/client/session*', r => r.fulfill({ json: { city_id: 2, city_name: 'Минск' } }));
  await page.route('**/api/public/ice/arenas*', r => r.fulfill({ json: { items: ARENAS, total: ARENAS.length, window: { key: 'evening', label: 'сегодня вечером' } } }));
  await page.route('**/api/public/ice/map-config*', r => r.fulfill({ json: { yandex_maps_js_api_key: 'stub-key' } }));

  await page.goto(base + '/ice.html');
  await page.waitForSelector('#iceViewSwitch', { timeout: 8000 });

  /* Список не пострадал: город у masthead, пилюля «Карта» на месте. */
  const heroCity = await page.$eval('.ice-hero-top .ice-citypill__name', el => el.textContent);
  check('список: город у masthead = «Минск»', heroCity === 'Минск');
  const listVisible = await page.$eval('#iceListSkate', el => el.children.length > 0);
  check('список: карточки на месте', listVisible);

  /* --- Переход в режим карты (карта монтируется при первом входе) --- */
  await page.click('#iceViewSwitch');
  await page.waitForSelector('#iceMapSheet .ice-map-rail .ice-acard', { timeout: 8000 });
  await page.waitForTimeout(400);

  const stageBox = await page.$eval('#iceMapStage', el => {
    const r = el.getBoundingClientRect();
    return { top: r.top, bottom: r.bottom, w: r.width, h: r.height, pos: getComputedStyle(el).position };
  });
  check('AC-1: карта fixed на весь экран', stageBox.pos === 'fixed' && stageBox.top <= 2 && stageBox.h > 700);

  const heroPos = await page.$eval('.ice-sec--hero', el => getComputedStyle(el).position);
  check('AC-1: hero плавает над картой (fixed)', heroPos === 'fixed');

  const mastheadHidden = await page.$eval('.ice-masthead', el => el.offsetParent === null);
  const kickerHidden = await page.$eval('.ice-kicker', el => el.offsetParent === null);
  const nearestHidden = await page.$eval('#iceNearestBtn', el => el.offsetParent === null);
  const cityInSearchVisible = await page.$eval('#iceCityChangeMap', el => getComputedStyle(el).display !== 'none');
  check('AC-1: masthead/kicker/Рядом скрыты', mastheadHidden && kickerHidden && nearestHidden);
  check('AC-1: город внутри строки поиска в режиме карты', cityInSearchVisible);

  /* --- Шторка half: каркас + карусель + сводка --- */
  const sheetInfo = await page.$eval('#iceMapSheet', el => ({
    pos: getComputedStyle(el).position,
    snap: el.dataset.snap,
    h: el.getBoundingClientRect().height,
    bottom: el.getBoundingClientRect().bottom,
    title: el.querySelector('.ice-map-sheet__title') && el.querySelector('.ice-map-sheet__title').textContent,
    sub: el.querySelector('.ice-map-sheet__sub') && el.querySelector('.ice-map-sheet__sub').textContent,
    cards: el.querySelectorAll('.ice-acard').length,
    railBound: !!el.querySelector('.ice-map-rail').__railBound,
  }));
  check('AC-5: шторка fixed overlay', sheetInfo.pos === 'fixed');
  check('AC-5: half по умолчанию (~222px)', sheetInfo.snap === 'half' && Math.abs(sheetInfo.h - 222) < 2);
  check('AC-5: сводка окна в шапке', /мест/.test(sheetInfo.title || '') && (sheetInfo.sub || '').length > 0);
  check('AC-5: карусель карточек собрана', sheetInfo.cards >= 7);
  check('скролл-слушатель рельсы живёт (не умирает на repaint)', sheetInfo.railBound);

  /* --- Пины: время в пилюле, вне окна — точка --- */
  const pinStats = await page.$$eval('.ice-acard--sheet', cards => cards.length);
  check('карточки в карусели', pinStats >= 7);

  await page.screenshot({ path: path.join(shots, 'm1-map-half.png') });

  /* --- Хвост к макету 02: легенда в режиме карты (в выдаче лёд + улица + магазин) --- */
  {
    const lg = await legendState(page);
    check('стаб ymaps активен (window.__ymapsStub)', REAL || await page.evaluate(() => window.__ymapsStub === true));
    check('легенда: видна в режиме карты', lg.display === 'flex' && !lg.hidden);
    check('легенда: лёд и улица сведены в «Лёд», остальное — Магазин', lg.items.map(i => i.type).join() === 'ice,shop' && lg.items[0].text === 'Лёд');
    check('легенда: нет типов, которых нет в выдаче (Зал/Бассейн/Улица)', !lg.items.some(i => ['gym', 'pool', 'outdoor'].includes(i.type)));
    let dotsOk = true;
    for (const i of lg.items) dotsOk = dotsOk && i.dot === await tokenColor(page, TOKEN_OF[i.type]);
    check('легенда: цвет точек = токены --app-venue-ice / --app-venue-shop', dotsOk);
    check('легенда: pointer-events none (карта под ней живая)', lg.pe === 'none');
    check('легенда: целиком в экране, нет горизонтального скролла (390)', lg.rect.l >= 0 && lg.rect.r <= lg.vw && !lg.overflowX);
    await checkAttrib(page, 'копирайт 390 half, светлая');
    const pins = await pinColors(page);
    const typed = pins.filter(p => !p.sel && p.type);
    let pinOk = typed.length > 0;
    for (const p of typed) pinOk = pinOk && p.color === await expectedPinColor(page, p);
    check('пины: пилюля — токен типа, полая точка — серый обод (' + typed.length + ' шт.)', pinOk);
    const outd = pins.find(p => p.type === 'outdoor' && !p.sel);
    check('пины: улица (outdoor) — цвета льда, как до хвоста', !outd || outd.color === await tokenColor(page, '--app-venue-ice'));
    const hollow = pins.filter(p => p.hollow && !p.sel);
    const grey = await tokenColor(page, '--glide-line-strong');
    check('пины: все полые точки — серый обод, независимо от типа (' + hollow.length + ' шт.)', hollow.length > 0 && hollow.every(p => p.color === grey));
  }

  /* --- Тап по хэндлу: peek --- */
  await page.click('#iceMapSheet .ice-map-sheet__handle');
  await page.waitForTimeout(400);
  const peekSnap = await page.$eval('#iceMapSheet', el => el.dataset.snap);
  const peekH = await page.$eval('#iceMapSheet', el => el.getBoundingClientRect().height);
  check('AC-5: тап по хэндлу → peek (~96px)', peekSnap === 'peek' && Math.abs(peekH - 96) < 3);
  const peekBodyHidden = await page.$eval('#iceMapSheet .ice-map-sheet__body', el => parseFloat(getComputedStyle(el).opacity) === 0);
  check('AC-5: в peek карусель скрыта', peekBodyHidden);
  await page.screenshot({ path: path.join(shots, 'm2-map-peek.png') });

  /* --- FAB «Где я» едет вместе со шторкой --- */
  const fabBottom = await page.$eval('#iceNearBtn', el => el.style.bottom);
  check('AC-7: FAB над шторкой (bottom синхронизирован)', fabBottom === '108px');
  const attribBottom = await page.$eval('#iceMapAttrib', el => el.style.bottom);
  check('AC-7: копирайт над шторкой (bottom = таб-бар + высота шторки + 8)', /^calc\(var\(--client-shell-tab-inset, 80px\) \+ 104px\)$/.test(attribBottom));
  await page.waitForTimeout(450); // transition bottom 0.32s
  await checkAttrib(page, 'копирайт 390 peek, светлая');

  /* --- Кнопка «Списком» ведёт в список --- */
  await page.click('#iceMapSheet .ice-map-sheet__toggle');
  await page.waitForTimeout(400);
  const backToList = await page.evaluate(() => document.body.classList.contains('ice-view-map'));
  check('AC-5: «Списком» вернул в списочный вид', !backToList);
  await page.screenshot({ path: path.join(shots, 'm3-list-after-toggle.png') });
  check('легенда: в списочном виде не показывается', (await legendState(page)).display === 'none');

  /* --- Снова карта + тёмная тема --- */
  await page.click('#iceViewSwitch');
  await page.waitForTimeout(400);
  await page.evaluate(() => document.documentElement.classList.add('client-mini-dark'));
  await page.waitForTimeout(300);
  const tileFilter = await page.evaluate(() => {
    const pane = document.querySelector('[class*="ground-pane"]');
    return pane ? getComputedStyle(pane).filter : '';
  });
  check('AC-6: на слое тайлов в тёмной теме реально применён invert-фильтр', /invert\(1\)/.test(tileFilter) && /hue-rotate\(180deg\)/.test(tileFilter));
  await page.screenshot({ path: path.join(shots, 'm4-map-dark.png') });
  {
    const lg = await legendState(page);
    const c = await legendContrast(page);
    check('тёмная тема: легенда на месте', lg.display === 'flex' && lg.items.length === 2);
    await page.waitForTimeout(450);
    await checkAttrib(page, 'копирайт 390 half, тёмная');
    check('тёмная тема: контраст текста легенды ≥ 4.5 (' + (c.ratio ? c.ratio.toFixed(2) : 'не посчитано') + ')', c.ratio != null && c.ratio >= 4.5);
    let dotsOk = true;
    for (const i of lg.items) dotsOk = dotsOk && i.dot === await tokenColor(page, TOKEN_OF[i.type]);
    check('тёмная тема: точки легенды = токены темы', dotsOk);
    console.log('  (тёмная: точки ' + lg.items.map(i => i.type + '=' + i.dot).join(' ') + ')');
  }
  await page.close();

  /* ---------- Десктоп: 1440×900 ---------- */
  const dpage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await prepare(dpage);
  await dpage.route('**/api/public/ice/cities*', r => r.fulfill({
    json: { items: [{ id: 2, name: 'Минск', country: 'BY', latitude: 53.902, longitude: 27.562, skate_count: 20, trainer_count: 0, map_rink_count: 9, bounds: { min_lat: 53.80, max_lat: 53.99, min_lon: 27.38, max_lon: 27.72 } }] },
  }));
  await dpage.route('**/api/webapp/client/session*', r => r.fulfill({ json: { city_id: 2, city_name: 'Минск' } }));
  await dpage.route('**/api/public/ice/arenas*', r => r.fulfill({ json: { items: ARENAS, total: ARENAS.length, window: { key: 'evening', label: 'сегодня вечером' } } }));
  await dpage.route('**/api/public/ice/map-config*', r => r.fulfill({ json: { yandex_maps_js_api_key: 'stub-key' } }));

  await dpage.goto(base + '/ice.html');
  await dpage.waitForSelector('#iceViewSwitch', { timeout: 8000 });
  const dListOk = await dpage.$eval('#iceListSkate', el => el.children.length > 0);
  check('десктоп: список собран', dListOk);
  await dpage.screenshot({ path: path.join(shots, 'd1-list.png') });

  await dpage.click('#iceViewSwitch');
  await dpage.waitForSelector('#iceMapSheet .ice-map-rail .ice-acard', { timeout: 8000 });
  await dpage.waitForTimeout(300);
  const dStage = await dpage.$eval('#iceMapStage', el => {
    const r = el.getBoundingClientRect();
    return { w: r.width, h: r.height };
  });
  check('десктоп: карта на всю ширину окна', dStage.w > 1400 && dStage.h > 700);
  const dSheet = await dpage.$eval('#iceMapSheet', el => ({
    w: el.getBoundingClientRect().width,
    h: el.getBoundingClientRect().height,
  }));
  check('десктоп: шторка на всю ширину', dSheet.w > 1400);
  await dpage.screenshot({ path: path.join(shots, 'd2-map.png') });
  await dpage.close();

  /* ---------- Легенда по составу выдачи: 390×844 ---------- */
  {
    const mp = await openMap(browser, { width: 390, height: 844 }, ICE_ONLY);
    const lg = await legendState(mp);
    check('легенда: только лёд в выдаче → блока нет (display none, пусто)', lg.display === 'none' && lg.hidden && lg.items.length === 0);
    const pins = await pinColors(mp);
    let same = pins.length > 0;
    for (const p of pins.filter(x => !x.sel)) same = same && p.color === await expectedPinColor(mp, p);
    check('пины при одном типе: пилюля — лёд-токен, полая — серый обод', same);
    await mp.screenshot({ path: path.join(shots, 'm5-map-ice-only-no-legend.png') });
    await mp.close();

    /* Лёд + улица — один цвет → одна запись, легенды нет вообще. */
    const iceOut = await openMap(browser, { width: 390, height: 844 }, [
      place(301, 'ice', 'A', 53.93, 27.42, SESSION('18:15'), { venue_chip: 'Лёд' }),
      place(302, 'outdoor', 'B', 53.86, 27.55, SESSION('19:00'), { venue_chip: 'Улица' }),
    ]);
    const lio = await legendState(iceOut);
    check('легенда: лёд + улица = один цвет → блока нет', lio.display === 'none' && lio.items.length === 0);
    await iceOut.close();

    const mm = await openMap(browser, { width: 390, height: 844 }, SPREAD);
    const l2 = await legendState(mm);
    check('легенда (SPREAD: лёд, улица, зал, магазин, бассейн): улица сведена со льдом, порядок фиксирован', l2.items.map(i => i.type).join() === 'ice,gym,pool,shop');
    check('легенда: подписи с сервера, «Лёд» без «Улица»', l2.items.map(i => i.text).join() === 'Лёд,Зал,Бассейн,Магазин');
    check('легенда (4 записи): целиком в экране, нет горизонтального скролла', l2.rect.l >= 0 && l2.rect.r <= l2.vw && !l2.overflowX);
    const a = await checkAttrib(mm, 'копирайт 390 half, светлая (4 типа)');
    console.log('  (390: легенда y=' + Math.round(l2.rect.t) + '–' + Math.round(l2.rect.b) + '; копирайт y=' + Math.round(a.rect.t) + '–' + Math.round(a.rect.b) + ', шторка y=' + Math.round(a.sheetTop) + ')');
    await mm.screenshot({ path: path.join(shots, 'm6-map-legend-4-types.png') });
    await mm.close();
  }

  /* ---------- Цвет пина = тип места, подписи без выдумок: 1440×900 ---------- */
  {
    const dp = await openMap(browser, { width: 1440, height: 900 }, SPREAD);
    const lg = await legendState(dp);
    check('десктоп: легенда видна, 4 записи', lg.display === 'flex' && lg.items.length === 4);
    let dotsOk = true;
    for (const i of lg.items) dotsOk = dotsOk && i.dot === await tokenColor(dp, TOKEN_OF[i.type]);
    check('десктоп: цвет точек легенды = токены --app-venue-*', dotsOk);
    check('десктоп: нет горизонтального скролла', !lg.overflowX);
    await checkAttrib(dp, 'копирайт 1440 half, светлая');
    await dp.click('#iceMapSheet .ice-map-sheet__handle');
    await dp.waitForTimeout(450);
    await checkAttrib(dp, 'копирайт 1440 peek, светлая');
    await dp.click('#iceMapSheet .ice-map-sheet__handle');
    await dp.waitForTimeout(450);

    const pins = await pinColors(dp);
    console.log('  (пины на десктопе: ' + pins.map(p => (p.type || '?') + (p.hollow ? ':полый' : ':пилюля') + (p.sel ? ':выбран' : '') + (p.label ? '«' + p.label + '»' : '')).join(', ') + ')');
    let allOk = pins.filter(x => !x.sel && x.type).length >= 4;
    for (const p of pins.filter(x => !x.sel && x.type)) allOk = allOk && p.color === await expectedPinColor(dp, p);
    check('десктоп: пилюли — токен типа, полые точки — серый обод', allOk);
    const grey = await tokenColor(dp, '--glide-line-strong');
    const nonIceHollow = pins.filter(p => ['gym', 'shop', 'pool'].includes(p.type));
    check('десктоп: зал/магазин/бассейн — полые серые точки без текста (нет сеанса — нет подписи)', nonIceHollow.length === 3 && nonIceHollow.every(p => p.hollow && p.label === '' && (p.sel || p.color === grey)));
    const ice = pins.filter(p => p.type === 'ice' && !p.hollow && p.label);
    check('подпись: у льда с сеансом — время сеанса, как прежде', ice.length > 0 && ice.every(p => /^\d{1,2}:\d{2}$/.test(p.label)));
    const outdoor = pins.find(p => p.type === 'outdoor' && !p.sel);
    check('улица с сеансом — пилюля цвета льда', !outdoor || (!outdoor.hollow && outdoor.color === await tokenColor(dp, '--app-venue-ice')));
    const hollowIce = pins.filter(p => p.type === 'ice' && p.hollow);
    check('полый лёд (tier C) остаётся полым, серым и без текста', hollowIce.length > 0 && hollowIce.every(p => p.label === '' && (p.sel || p.color === grey)));
    await dp.screenshot({ path: path.join(shots, 'd3-map-legend-pins.png') });

    await dp.evaluate(() => document.documentElement.classList.add('client-mini-dark'));
    await dp.waitForTimeout(300);
    const dl = await legendState(dp);
    const dc = await legendContrast(dp);
    check('десктоп тёмная: легенда читаема, контраст ≥ 4.5 (' + (dc.ratio ? dc.ratio.toFixed(2) : 'не посчитано') + ')', dl.display === 'flex' && dc.ratio != null && dc.ratio >= 4.5);
    let dd = true;
    for (const i of dl.items) dd = dd && i.dot === await tokenColor(dp, TOKEN_OF[i.type]);
    check('десктоп тёмная: точки легенды = токены темы', dd);
    await checkAttrib(dp, 'копирайт 1440 half, тёмная');
    await dp.screenshot({ path: path.join(shots, 'd4-map-legend-dark.png') });
    await dp.close();
  }

  /* ---------- Офлайн-гарантия ---------- */
  if (!REAL) {
    console.log('  (заблокировано внешних запросов: ' + blocked.length + (blocked.length ? ' — ' + [...new Set(blocked.map(u => new URL(u).host))].join(', ') : '') + ')');
    check('офлайн: страница не просила api-maps.yandex.ru (стаб подменил SDK)', !blocked.some(u => /api-maps\.yandex\.ru/.test(u)));
  }
} finally {
  await browser.close();
  server.close();
}

console.log(failures ? '\nFAILURES: ' + failures : '\nALL CHECKS PASSED');
process.exit(failures ? 1 : 0);
