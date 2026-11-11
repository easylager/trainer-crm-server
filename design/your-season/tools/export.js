// Экспорт макетов холста в статичный HTML + PNG для репозитория.
// Из корня репозитория: node design/your-season/tools/export.js
// Рендерит исходники холста (source/*.dc.html) в статичный HTML и PNG рядом с этой папкой.
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const OUT = path.join(__dirname, '..');
const SRC = path.join(OUT, 'source');
const ASSETS = path.join(OUT, 'img');
const BLOBS = {
  c5a6f0736a829934d304a092c0b002cf: { file: 'kk-hub-top.png', out: 'img/kk-hub-top.png' },
  f2969364cbe872dc662d4ca423c13fa0: { file: 'kk-hub-bottom.png', out: 'img/kk-hub-bottom.png' },
};
const LINKS = {
  'Main.dc.html': 'me-season-light.html',
  'Newcomer.dc.html': 'me-new-light.html',
  'Picker.dc.html': 'club-picker.html',
  'MyRink.dc.html': 'rink-picker-step1.html',
  'NameSheet.dc.html': 'name-sheet.html',
  'TabBar.dc.html': 'tab-bar.html',
  'Passport.dc.html': '#',
};
const JOBS = [
  { name: 'tab-bar', file: 'TabBar.dc.html', w: 390, h: 820, title: 'Новый таб-бар' },
  { name: 'me-season-light', file: 'Main.dc.html', w: 390, h: 960, props: { variant: 'season', dark: false }, title: '«Я» — в сезоне, светлая' },
  { name: 'me-season-dark', file: 'Main.dc.html', w: 390, h: 960, props: { variant: 'season', dark: true }, title: '«Я» — в сезоне, тёмная' },
  { name: 'me-new-light', file: 'Main.dc.html', w: 390, h: 960, props: { variant: 'new', dark: false }, title: '«Я» — первый день, светлая' },
  { name: 'me-new-dark', file: 'Main.dc.html', w: 390, h: 960, props: { variant: 'new', dark: true }, title: '«Я» — первый день, тёмная' },
  { name: 'club-picker', file: 'Picker.dc.html', w: 390, h: 844, title: '«За кого болеешь?»' },
  { name: 'club-picker-none', file: 'Picker.dc.html', w: 390, h: 844, state: { picked: null }, title: '«За кого болеешь?» — ничего не выбрано' },
  { name: 'rink-picker-step1', file: 'MyRink.dc.html', w: 390, h: 844, state: { step2: false }, title: '«Мой каток» — шаг 1' },
  { name: 'rink-picker-step2', file: 'MyRink.dc.html', w: 390, h: 844, state: { step2: true }, title: '«Мой каток» — шаг 2, подписка' },
  { name: 'name-sheet', file: 'NameSheet.dc.html', w: 390, h: 844, state: { value: 'Макс' }, title: '«Как тебя зовут?» — изменено' },
  { name: 'name-sheet-empty', file: 'NameSheet.dc.html', w: 390, h: 844, state: { value: '' }, title: '«Как тебя зовут?» — пусто' },
  { name: 'kk-tab', file: 'KKTab.dc.html', w: 390, h: 1440, title: '«Кто кого» во вкладке' },
];

(async () => {
  fs.mkdirSync(path.join(OUT, 'img'), { recursive: true });
  fs.mkdirSync(path.join(OUT, 'png'), { recursive: true });
  const browser = await chromium.launch();
  for (const job of JOBS) {
    const ctx = await browser.newContext({ viewport: { width: job.w, height: job.h }, deviceScaleFactor: 2 });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.route('http://dc.local/**', (route) => {
      const u = new URL(route.request().url());
      const blob = /^\/_blob\/([0-9a-f]{32})$/.exec(u.pathname);
      if (blob && BLOBS[blob[1]]) return route.fulfill({ path: path.join(ASSETS, BLOBS[blob[1]].file), contentType: 'image/png' });
      const f = path.join(SRC, decodeURIComponent(u.pathname.slice(1)));
      if (!fs.existsSync(f)) return route.fulfill({ status: 404, body: 'nf' });
      const type = f.endsWith('.js') ? 'application/javascript' : 'text/html; charset=utf-8';
      return route.fulfill({ path: f, contentType: type });
    });
    const q = new URLSearchParams();
    if (job.props) q.set('props', JSON.stringify(job.props));
    if (job.state) q.set('state', JSON.stringify(job.state));
    await page.goto(`http://dc.local/${job.file}?${q}`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => window.__dcExport());
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => Promise.all(Array.from(document.images).map((i) => (i.complete ? 0 : new Promise((r) => { i.onload = i.onerror = r; })))));
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(OUT, 'png', job.name + '.png'), fullPage: false });
    let html = await page.evaluate(() => {
      document.querySelectorAll('script').forEach((s) => s.remove());
      document.querySelectorAll('[data-helmet]').forEach((n) => n.removeAttribute('data-helmet'));
      return '<!doctype html>\n' + document.documentElement.outerHTML;
    });
    for (const [id, b] of Object.entries(BLOBS)) html = html.split('/_blob/' + id).join(b.out);
    for (const [from, to] of Object.entries(LINKS)) html = html.split('href="' + from + '"').join('href="' + to + '"');
    html = html.replace(/<title>[^<]*<\/title>/, `<title>${job.title}</title>`);
    html = html.replace('<head>', '<head>\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<!-- Сгенерировано из source/' + job.file + ' — правки вносить в исходник на холсте и переэкспортировать. -->');
    fs.writeFileSync(path.join(OUT, job.name + '.html'), html);
    console.log(job.name, errors.length ? 'ERR ' + errors.join(' | ') : 'ok');
    await ctx.close();
  }
  await browser.close();
})();
