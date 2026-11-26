/**
 * TASK-448 (этап 3): замер скорости главной — таблица, не gate.
 * Печатает для каждого кейса: число JS/CSS-файлов, байты в gzip, время до первого
 * кадра с контентом, время до данных, сумму layout shifts.
 *
 * Кейсы:  a-old    — старая client-home.html (флаги выкл);
 *         b-s1s2   — v2, redesign_s1+s2;
 *         c-s3cold — v2 с redesign_s3, холодный (пустой HTTP-кэш и localStorage);
 *         d-s3warm — второе открытие того же контекста (HTTP-кэш + кэш экрана).
 * Run: node tests/e2e/home-perf.mjs [a|b|c|d ...]
 *
 * Условия: CPU ×4, «4G» (latency 150ms, down 1.6Mbit/s, up 750kbit/s) через CDP,
 * gzip на статике, bootstrap с задержкой 400 мс. Фикстура — «запись сегодня»
 * (та же, что в home-v2.check.mjs).
 */
import { chromium } from 'playwright';
import http from 'node:http';
import zlib from 'node:zlib';
import { readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(here, '../..');
const staticDir = path.join(repoRoot, 'static');
const photosDir = path.join(repoRoot, 'data', 'arena-cards', 'photos');

const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2',
};

/* ── s3: серверные бандлы (то же склеивание, что в app.py — держать списки синхронно) ── */
const S3_HEAD_JS = ['glide-deeplink.js', 'write-access.js', 'client-mini-app-theme.js', 'mini-app-client-shell.js', 'ru-person-name.js'];
const S3_APP_JS = ['mini-app-telegram-chrome.js', 'mini-app-empty-state.js', 'mini-app-more-icons.js', 'client-profile-switcher.js', 'ga-press.js', 'home-v2.js', 'ga-touch.js'];
const S3_CSS = ['shared/glide-public-fonts.css', 'shared/glide-tokens.css', 'webapp/mini-app-client-theme.css', 'webapp/mini-app-client-shell.css', 'webapp/home-v2.css'];
const bundle = (files, sep) => files.map((f) => {
  const rel = f.includes('/') ? f : 'webapp/' + f;
  return '/* file: ' + rel + ' */\n' + readFileSync(path.join(staticDir, rel), 'utf-8');
}).join(sep);
const S3_BUNDLES = {
  '/webapp/home-v2.head.js': { body: bundle(S3_HEAD_JS, ';\n'), type: 'text/javascript' },
  '/webapp/home-v2.app.js': { body: bundle(S3_APP_JS, ';\n'), type: 'text/javascript' },
  '/webapp/home-v2.bundle.css': { body: bundle(S3_CSS, '\n'), type: 'text/css' },
};
function v2HtmlBundled() {
  /* Та же семантика, что home_v2_bundles.apply_bundles: первый регион → 3 тега,
     остальные регионы → пусто. */
  const html = readFileSync(path.join(staticDir, 'webapp/client-home-v2.html'), 'utf-8');
  const regions = [...html.matchAll(/<!-- s3:assets -->[\s\S]*?<!-- \/s3:assets -->/g)];
  if (!regions.length) return null;
  const tags = '  <script src="/webapp/home-v2.head.js?v=s3"></script>\n' +
    '  <link rel="stylesheet" href="/webapp/home-v2.bundle.css?v=s3" />\n' +
    '  <script defer src="/webapp/home-v2.app.js?v=s3"></script>\n';
  let out = html;
  for (let i = regions.length - 1; i >= 0; i--) {
    const m = regions[i];
    out = out.slice(0, m.index) + (i === 0 ? tags : '') + out.slice(m.index + m[0].length);
  }
  return out;
}

let CFG = { old: false, s3: false, bootDelay: 400, flags: {} };
const METER = [];

const server = http.createServer((req, res) => {
  const send = (type, body) => {
    const buf = Buffer.isBuffer(body) ? body : Buffer.from(body);
    const acceptGzip = /gzip/.test(String(req.headers['accept-encoding'] || ''));
    const out = acceptGzip ? zlib.gzipSync(buf) : buf;
    METER.push({ path: req.url.split('?')[0], bytes: out.length, type, t: Date.now() });
    res.writeHead(200, {
      'content-type': type,
      ...(acceptGzip ? { 'content-encoding': 'gzip' } : {}),
      'content-length': out.length,
      ...(S3_BUNDLES[req.url.split('?')[0]] ? { 'cache-control': 'public, max-age=31536000, immutable' } : {}),
    });
    res.end(out);
  };
  let p = decodeURIComponent(req.url.split('?')[0]);
  /* API-стабы живут в этом же сервере — page.route() отключает HTTP-кэш
     Chromium и ломает замер «тёплого» кейса. */
  if (p.startsWith('/api/')) {
    const json = (body) => send('application/json', JSON.stringify(body));
    if (p === '/api/webapp/client/ui-flags') return json(CFG.flags);
    if (p === '/api/webapp/client/hub/bootstrap') {
      return setTimeout(() => json(BOOT), CFG.bootDelay); // «серверное» время
    }
    if (p === '/api/webapp/client/profiles') return json({ items: [], default_profile_id: null });
    if (p === '/api/webapp/client/session/catalog-filters') return json({ success: true });
    if (p === '/api/public/ice/cities') return json({ items: [{ id: 1, name: 'Минск', skate_count: 3, trainer_count: 14, latitude: 53.9, longitude: 27.56 }] });
    if (p === '/api/webapp/client/slots') return json({ slots: [] });
    if (p.startsWith('/api/public/photos')) {
      return send('image/jpeg', readFileSync(path.join(photosDir, 'arena-25', 'hero.jpg')));
    }
    return json({});
  }
  if (p === '/webapp/telegram-stub.js') return send('text/javascript', tgMock());
  const pageHtml = (file) =>
    readFileSync(path.join(staticDir, 'webapp', file), 'utf-8')
      .replace('https://telegram.org/js/telegram-web-app.js', '/webapp/telegram-stub.js');
  if (p === '/webapp/client-home' || p === '/') {
    if (CFG.old) {
      send('text/html', pageHtml('client-home.html'));
    } else {
      const bundled = CFG.s3 ? v2HtmlBundled() : null;
      send('text/html', (bundled || pageHtml('client-home-v2.html'))
        .replace('https://telegram.org/js/telegram-web-app.js', '/webapp/telegram-stub.js'));
    }
    return;
  }
  if (S3_BUNDLES[p]) { const b = S3_BUNDLES[p]; send(b.type, b.body); return; }
  if (p === '/webapp/client-home-v2.html' || p === '/webapp/client-home.html') {
    send('text/html', readFileSync(path.join(staticDir, 'webapp' + path.basename(p)), 'utf-8'));
    return;
  }
  let file;
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
  send(MIME[path.extname(file)] || 'application/octet-stream', readFileSync(file));
});
await new Promise((r) => server.listen(0, r));
const base = 'http://localhost:' + server.address().port;

/* ── фикстуры (booking today) — привязаны к реальному «сейчас», без page.clock:
     фейковые часы искажают performance.now() и прячут resource-записи. ───────── */
const NOW = new Date();
const TODAY = NOW.toLocaleDateString('sv-SE'); // YYYY-MM-DD в локали Europe/Minsk из контекста ниже не нужна — sv-SE даёт ISO
const _in = (min) => new Date(NOW.getTime() + min * 60000);
const HM = (d) => String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
const BOOK_START = HM(_in(70));
const BOOK_END = HM(_in(120));
const P = (n) => '/photos/' + n;
const PHOTO = { nemiga: P('arena-38/hero.webp'), ledoviy: P('arena-25/hero.jpg'), gorky: P('arena-11/hero.webp'), chizh: P('arena-115/hockey-rink-interior.jpg') };
const CITY = {
  id: 1, name: 'Минск', name_in: 'Минске', kicker: '4 катка сегодня', counts_line: '4 катка',
  hero_photo: { thumb: PHOTO.gorky, card: PHOTO.gorky, hero: PHOTO.gorky },
  hero_photos: [{ thumb: PHOTO.gorky, card: PHOTO.gorky, hero: PHOTO.gorky }],
  upcoming: [], upcoming_href: 'ice?city_id=1', upcoming_more: 'Весь день',
  needs: [{ key: 'skate', title: 'Покататься', line: '10 катков', href: 'ice?city_id=1', windows: [] }],
};
const RAIL = {
  windows: [
    { key: 'today', label: 'Сегодня', count: 22, href: 'ice?city_id=1', arenas: [
      { arena_id: 11, name: 'Каток на Немиге', photo: { thumb: PHOTO.nemiga, card: PHOTO.nemiga }, href: 'arena?ref=11&s=101', price: '12 BYN', times: [{ time: '18:00', end: '19:15', session_id: 101, minutes_until: 25 }] },
      { arena_id: 12, name: 'Ледовый дворец', photo: { thumb: PHOTO.ledoviy, card: PHOTO.ledoviy }, href: 'arena?ref=12&s=102', price: '10 BYN', times: [{ time: '18:00', end: '19:30', session_id: 102, minutes_until: 25 }] },
    ] },
    { key: 'tomorrow', label: 'Завтра', count: 34, href: 'ice?city_id=1&when=tomorrow', arenas: [] },
    { key: 'weekend', label: 'Выходные', count: 28, href: 'ice?city_id=1&when=weekend', arenas: [] },
  ],
};
const BOOT = {
  bookings: { days: [{ date: TODAY, day_label: 'вс', bookings: [{
    id: 501, status: 'confirmed', start_time: BOOK_START, end_time: BOOK_END, duration_minutes: 50,
    trainer_id: 7, trainer_name: 'Максим', trainer_telegram_username: 'maxim_coach', trainer_list_photo_key: null,
    service_name: 'Индивидуальное занятие', arena_name: 'Ледовый дворец', arena_id: 12,
    place_display: 'Ледовый дворец', map_link: 'https://yandex.ru/maps/?pt=27.5,53.9&z=16', slot_date: TODAY,
  }] }] },
  requests: { items: [] },
  client_session: { city_id: 1, primary_trainer_id: 7, primary_trainer_name: 'Максим', primary_trainer_list_photo_key: null, saved_trainers: [], has_past_sessions: true },
  activity: { streak_weeks: 0, completed_total: 0 },
  passes: [], certificates: [], ice_teaser: null, pending_referral: null,
  home: { city: CITY, matches: { week_count: 6, all_href: 'client-matches', matches: [] }, now: { kind: 'feed', items: [] }, ice_rail: RAIL, place_photos: { 11: { thumb: PHOTO.nemiga, card: PHOTO.nemiga } } },
  platform: { vertical_key: 'ice', ui: {} },
};

const FLAGS = {
  off: { season_ui: false, bookings_tab: false, fast_tabs: false, search_board: false, redesign_s1: false },
  s1s2: { season_ui: false, bookings_tab: true, fast_tabs: false, search_board: false, redesign_s1: true, redesign_s2: true },
  s3: { season_ui: false, bookings_tab: true, fast_tabs: false, search_board: false, redesign_s1: true, redesign_s2: true, redesign_s3: true },
};

function tgMock() {
  return `window.Telegram = { WebApp: {
    initData: 'mock', initDataUnsafe: { user: { id: 1, first_name: 'Максим', allows_write_to_pm: true } }, colorScheme: 'light', themeParams: {},
    version: '8.0', platform: 'ios', isExpanded: true, viewportHeight: 844,
    isVersionAtLeast(v) { return true; },
    ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}, onEvent() {}, offEvent() {},
    HapticFeedback: { selectionChanged() {}, impactOccurred() {}, notificationOccurred() {} },
    BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} }, MainButton: { show() {}, hide() {} },
    openTelegramLink() {}, openLink() {}, shareURL() {},
  } };`;
}

/* Маркеры: первый кадр с контентом и «данные показаны». */
const SELS = {
  v2: {
    content: '#hv2Top > *, #hv2CityPickList .hv2-cprow',
    data: '#hv2Top .hv2-card, #hv2Top .hv2-pcard, #hv2Top .hv2-cpick, #hv2Top .hv2-error',
  },
  old: {
    content: '#hubNow > *:not(#hubInitialSkel), #nextBookingBlock > *, #hubMine:not([hidden])',
    data: '#hubNow > *:not(#hubInitialSkel), #nextBookingBlock > *, #stateMessage:not(.loading)',
  },
};

async function measure(browser, selKey, label, opts) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Minsk', locale: 'ru-RU' });
  if (opts && opts.warm) {
    /* Прогрев: HTTP-кэш + localStorage (кэш экрана) живут в контексте. */
    const p0 = await ctx.newPage();
    await p0.addInitScript((fl) => {
      try { localStorage.setItem('cw_ui_flags_v1', JSON.stringify({ u: '1', ...fl, at: Date.now() })); } catch (e) {}
    }, CFG.flags);
    await p0.goto(base + '/webapp/client-home', { waitUntil: 'load' });
    await p0.waitForTimeout(1500);
    await p0.close();
    METER.length = 0;
  }
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', {
    offline: false, latency: 150,
    downloadThroughput: (1.6 * 1024 * 1024) / 8,
    uploadThroughput: (750 * 1024) / 8,
  });
  METER.length = 0;
  await page.addInitScript((fl) => {
    try { localStorage.setItem('cw_ui_flags_v1', JSON.stringify({ u: '1', ...fl, at: Date.now() })); } catch (e) {}
  }, CFG.flags);
  await page.addInitScript((selJson) => {
    window.__perf = { marks: {}, cls: 0 };
    const sels = JSON.parse(selJson);
    const seen = window.__perf.marks;
    const hit = (key, sel) => {
      if (seen[key] != null) return;
      const els = document.querySelectorAll(sel);
      for (const el of els) {
        if (el.offsetHeight > 0 && (el.textContent || '').trim().length > 0) { seen[key] = performance.now(); return; }
      }
    };
    const scan = () => { for (const k of Object.keys(sels)) hit(k, sels[k]); };
    const install = () => {
      if (!document.documentElement) return setTimeout(install, 0);
      new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true, attributes: true, characterData: true });
      scan();
    };
    install();
    try {
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) if (!e.hadRecentInput) window.__perf.cls += e.value;
      }).observe({ type: 'layout-shift', buffered: true });
    } catch (e) {}
  }, JSON.stringify(SELS[selKey]));

  const t0 = Date.now();
  const nav = page.goto(base + '/webapp/client-home', { waitUntil: 'load' });
  await nav;
  await page.waitForSelector(SELS[selKey].data.split(',')[0].trim(), { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(1200); // догрузить «хвост»
  const marks = await page.evaluate(() => window.__perf);
  /* Только запросы до первого кадра с контентом (+ запас на таймеры) —
     фоновый префетч «Льда» и ленивые картинки в счёт первого кадра не входят. */
  const contentCut = marks.marks.content != null ? t0 + marks.marks.content + 50 : Infinity;
  const meter = METER.filter((m) => m.t <= contentCut);
  const js = meter.filter((m) => /\.js$/.test(m.path) || m.type === 'text/javascript');
  const css = meter.filter((m) => /\.css$/.test(m.path) || m.type === 'text/css');
  const idle = METER.filter((m) => m.t > contentCut);
  await ctx.close();
  return {
    label,
    files: js.length + css.length,
    jsFiles: js.length, jsKb: Math.round(js.reduce((a, m) => a + m.bytes, 0) / 1024),
    cssKb: Math.round(css.reduce((a, m) => a + m.bytes, 0) / 1024),
    contentMs: marks.marks.content != null ? Math.round(marks.marks.content) : null,
    idleFiles: idle.filter((m) => /\.js$|\.css$/.test(m.path)).length,
    dataMs: marks.marks.data != null ? Math.round(marks.marks.data) : null,
    cls: +marks.cls.toFixed(4),
    wallMs: Date.now() - t0,
  };
}

const browser = await chromium.launch();
const wanted = process.argv.slice(2).length ? process.argv.slice(2) : ['a', 'b', 'c', 'd'];
const rows = [];
try {
  for (const c of wanted) {
    if (c === 'a') { CFG = { old: true, s3: false, bootDelay: 400, flags: FLAGS.off }; rows.push(await measure(browser, 'old', 'a-old (старая)')); }
    if (c === 'b') { CFG = { old: false, s3: false, bootDelay: 400, flags: FLAGS.s1s2 }; rows.push(await measure(browser, 'v2', 'b-v2 s1+s2')); }
    if (c === 'c') { CFG = { old: false, s3: true, bootDelay: 400, flags: FLAGS.s3 }; rows.push(await measure(browser, 'v2', 'c-v2 s3 cold')); }
    if (c === 'd') {
      CFG = { old: false, s3: true, bootDelay: 400, flags: FLAGS.s3 };
      rows.push(await measure(browser, 'v2', 'd-v2 s3 warm', { warm: true }));
    }
  }
} finally {
  await browser.close();
  server.close();
}

console.log('\n| case | JS/CSS files | JS gzip | CSS gzip | first content | data shown | CLS |');
console.log('|---|---|---|---|---|---|---|');
for (const r of rows) {
  console.log(`| ${r.label} | ${r.files} (${r.jsFiles} js) | ${r.jsKb} КБ | ${r.cssKb} КБ | ${r.contentMs} мс | ${r.dataMs} мс | ${r.cls} |${r.idleFiles ? `  (+${r.idleFiles} idle)` : ''}`);
}
