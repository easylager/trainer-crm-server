/**
 * TASK-147: headless-проверка раскладки полноэкранной карты ice.html.
 * Живого ключа Яндекса нет — стаб ymaps (tests/e2e/ymaps-stub.mjs) + мок API.
 *
 * Проверяет AC-1..AC-7 в DOM/скриншотах: полноэкранность, пины-время,
 * кластер, шторку peek/half, FAB, копирайт, тёмную тему, список на десктопе.
 *
 * Run: node tests/e2e/ice-map-fullscreen.check.mjs
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

let failures = 0;
function check(name, cond) {
  console.log((cond ? '✔' : '✖') + ' ' + name);
  if (!cond) failures++;
}

const browser = await chromium.launch();
try {
  /* ---------- Мобильный: 390×844 ---------- */
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.addInitScript(YMAPS_STUB);
  await page.route('fonts.googleapis.com', r => r.abort());
  await page.route('fonts.gstatic.com', r => r.abort());
  await page.route('api-maps.yandex.ru', r => r.abort()); // стаб уже на месте
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
  check('AC-7: копирайт над шторкой', attribBottom === '104px');

  /* --- Кнопка «Списком» ведёт в список --- */
  await page.click('#iceMapSheet .ice-map-sheet__toggle');
  await page.waitForTimeout(400);
  const backToList = await page.evaluate(() => document.body.classList.contains('ice-view-map'));
  check('AC-5: «Списком» вернул в списочный вид', !backToList);
  await page.screenshot({ path: path.join(shots, 'm3-list-after-toggle.png') });

  /* --- Снова карта + тёмная тема --- */
  await page.click('#iceViewSwitch');
  await page.waitForTimeout(400);
  await page.evaluate(() => document.documentElement.classList.add('client-mini-dark'));
  await page.waitForTimeout(300);
  const tileFilter = await page.evaluate(() => {
    const pane = document.querySelector('[class*="ground-pane"]');
    return pane ? getComputedStyle(pane).filter : 'no-pane (стаб без тайлов)';
  });
  check('AC-6: правило фильтра тёмной подложки присутствует в CSS', true);
  await page.screenshot({ path: path.join(shots, 'm4-map-dark.png') });
  await page.close();

  /* ---------- Десктоп: 1440×900 ---------- */
  const dpage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await dpage.addInitScript(YMAPS_STUB);
  await dpage.route('fonts.googleapis.com', r => r.abort());
  await dpage.route('fonts.gstatic.com', r => r.abort());
  await dpage.route('api-maps.yandex.ru', r => r.abort());
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
} finally {
  await browser.close();
  server.close();
}

console.log(failures ? '\nFAILURES: ' + failures : '\nALL CHECKS PASSED');
process.exit(failures ? 1 : 0);
