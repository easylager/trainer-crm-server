/**
 * TASK-416: «Отзывы» и «На занятиях» единой карточки — раскладка по доске A (и тёмной A) на 320 и 390.
 * Настоящие trainers.html, CSS и JS витрины; стабы /api/* и Telegram. Узкие ширины — iframe (headless не уже ~500px).
 *
 * Доска A: «Отзывы» — карточка r18, поля 16/0/16/16 (лента уходит в правый край), сводка «4,9» Dela 28px, звёзды
 * #B7791F (тёмная #f0c36d), «14 оценок» 13px; карточки отзыва 260px, поля 14, r14, фон --g-bg, дата 12px;
 * подпись 12px. «На занятиях» — без карточки, h2 с отступом 4/8, плитки 148×110 r14 через 8px.
 *
 * Run: node tests/e2e/trainer-card-reviews.check.mjs   (код выхода 1 — расхождение)
 * Скриншоты: tests/e2e/__shots__/trainer-card-reviews/ (каталог в .gitignore)
 */
import { chromium } from 'playwright';
import http from 'node:http';
import { mkdirSync, rmSync, readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.join(here, '../../static');
const shots = path.join(here, '__shots__', 'trainer-card-reviews');
rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });

const LONG = 'Ходим к Анне второй сезон. Первое занятие было спокойным: привыкали ко льду, учились падать и вставать. ' +
  'Сын боялся льда, через месяц катается сам и просится ещё. Анна объясняет просто и не торопит, на каждом занятии ' +
  'что-то новое: торможение, повороты, шаг назад. Рекомендуем всем, кто начинает с нуля.';
const trainer = {
  id: 7, name: 'Анна Соколова', first_name: 'Анна', photo_url: '/static/landing/assets/hero-ice-macro.webp', experience_years: 7,
  description: 'Учу кататься с нуля.', education: '', can_book: true, contact_url: '/r/tg/7', phone: '', telegram_url: '',
  rating_avg: 4.9, rating_count: 14, glide_since: '2026-09', session_duration_minutes: 60, primary_arena_name: '«Замок»',
  city_name: 'Минск', min_session_price_cents: 4500, windows: [],
  services: [{ service_id: 3, service_name: 'Взрослое занятие', title: 'Взрослое занятие', is_public: true, is_online: false,
    currency_code: 'BYN', price_cents: 4500, price_tiers: [] }],
  arenas: [{ id: 3, name: 'Замок', address: 'ул. Притыцкого, 156' }],
  reviews: [
    { name: 'Марк М.', rating: 5, text: LONG, date: '2026-11-02' },
    { name: 'Елена К.', rating: 5, text: 'Спокойно и понятно, дочь довольна. ' + LONG, date: '2026-10-28' },
    { name: 'Константин Длиннофамильный-Второй', rating: 4, text: 'Хорошо поставили торможение.', date: '2026-10-19' },
  ],
  class_photos: ['/static/landing/assets/bento-ice-grain.webp', '/static/landing/og-trainers.png', '/static/landing/assets/hero-ice-macro.webp?2'],
};

const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp', '.woff2': 'font/woff2' };
function sendFile(res, file) {
  if (!existsSync(file) || statSync(file).isDirectory()) { res.writeHead(404); res.end('no'); return; }
  res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
  res.end(readFileSync(file));
}
function json(res, data) { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(data)); }

const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://x');
  const p = decodeURIComponent(u.pathname);
  if (p === '/__frame') {
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end('<!doctype html><body style="margin:0"><iframe id="f" src="' + u.searchParams.get('src').replace(/"/g, '&quot;') +
      '" style="border:0;display:block;width:' + Number(u.searchParams.get('w')) + 'px;height:900px"></iframe></body>');
    return;
  }
  if (p === '/__tg.js') {
    const dark = u.searchParams.get('dark') === '1';
    res.writeHead(200, { 'content-type': 'text/javascript' });
    res.end('window.Telegram={WebApp:{initData:"query_id=1&user=%7B%22id%22%3A1%7D&hash=x",' +
      'initDataUnsafe:{},colorScheme:' + JSON.stringify(dark ? 'dark' : 'light') + ',themeParams:{},platform:"ios",version:"8.0",' +
      'isVersionAtLeast:function(){return true},ready:function(){},expand:function(){},onEvent:function(){},offEvent:function(){},' +
      'BackButton:{show:function(){},hide:function(){},onClick:function(){},offClick:function(){}},' +
      'HapticFeedback:{impactOccurred:function(){},notificationOccurred:function(){},selectionChanged:function(){}}}};');
    return;
  }
  if (p.startsWith('/api/')) {
    if (p === '/api/public/trainer-showcase') return json(res, { items: [trainer] });
    if (p === '/api/webapp/client/slots') return json(res, { slots: [{ id: 101, slot_date: '2026-11-21', start_time: '10:00', end_time: '11:00', capacity: 1, spots_left: 1, arena_id: 3 }] });
    if (p === '/api/webapp/client/trainer-edges') return json(res, { all: [], primary: null, saved: [], past: [] });
    if (p === '/api/webapp/client/profiles') return json(res, { items: [{ client_id: 1, first_name: 'Тест' }], default_profile_id: 1 });
    return json(res, {});
  }
  if (p === '/webapp/trainers') {
    let html = readFileSync(path.join(staticDir, 'webapp/trainers.html'), 'utf8')
      .replace('https://telegram.org/js/telegram-web-app.js', '/__tg.js?dark=' + (u.searchParams.get('__dark') === '1' ? '1' : '0'));
    html = html.replace('<head>', '<head>\n<script>window.__UNIFIED_TRAINER_CARD__=true;</script>');
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end(html);
    return;
  }
  if (p.startsWith('/webapp/')) return sendFile(res, path.join(staticDir, p));
  if (p.startsWith('/static/')) return sendFile(res, path.join(staticDir, p.slice('/static/'.length)));
  res.writeHead(404); res.end('no');
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const origin = 'http://127.0.0.1:' + server.address().port;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 520, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));

function measure() {
  const r = (el) => (el ? el.getBoundingClientRect() : null);
  const cs = (el) => (el ? getComputedStyle(el) : null);
  const rgb = (s) => (s.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
  const lum = (c) => { const [R, G, B] = c.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * R + 0.7152 * G + 0.0722 * B; };
  const ratio = (a, b) => { const [x, y] = [lum(rgb(a)), lum(rgb(b))].sort((p, q) => q - p); return Math.round(((x + 0.05) / (y + 0.05)) * 100) / 100; };
  const sec = document.querySelector('.tc-revs');
  const h2 = sec && sec.querySelector('h2');
  const score = sec && sec.querySelector('.tc-rev-sum > b');
  const sumStars = sec && sec.querySelector('.tc-rev-sum .tc-rev-stars');
  const count = sec && sec.querySelector('.tc-rev-sum span + span');
  const lane = sec && sec.querySelector('.tc-rev-lane');
  const arts = sec ? [...sec.querySelectorAll('.tc-rev')] : [];
  const a0 = arts[0];
  const more = sec && sec.querySelector('[data-act="rev-more"]');
  const note = sec && sec.querySelector('.tc-rev-note');
  const time = a0 && a0.querySelector('time');
  const gal = document.querySelector('.tc-gal');
  const imgs = gal ? [...gal.querySelectorAll('img')] : [];
  const glane = gal && gal.querySelector('.tc-gal-lane');
  const de = document.documentElement;
  const surface = cs(sec).backgroundColor;
  const artBg = cs(a0).backgroundColor;
  return {
    W: de.clientWidth,
    overflow: de.scrollWidth - de.clientWidth,
    dark: document.body.classList.contains('tg-dark'),
    sec: sec && { w: Math.round(r(sec).width), radius: cs(sec).borderTopLeftRadius, pad: [cs(sec).paddingTop, cs(sec).paddingRight, cs(sec).paddingBottom, cs(sec).paddingLeft].join(' '), bg: surface },
    h2: h2 && { font: cs(h2).fontSize + '/' + cs(h2).fontWeight, text: h2.textContent },
    score: score && { font: cs(score).fontSize + ' ' + cs(score).fontFamily.split(',')[0], text: score.textContent },
    sumStars: sumStars && { color: cs(sumStars).color, text: sumStars.textContent, label: sumStars.getAttribute('aria-label'), contrast: ratio(cs(sumStars).color, surface) },
    count: count && { font: cs(count).fontSize, text: count.textContent, contrast: ratio(cs(count).color, surface) },
    lane: lane && { client: lane.clientWidth, scroll: lane.scrollWidth, right: Math.round(r(lane).right), secRight: Math.round(r(sec).right) },
    arts: arts.map((a) => ({ w: Math.round(r(a).width), h: Math.round(r(a).height), pad: cs(a).paddingLeft, radius: cs(a).borderTopLeftRadius, bg: cs(a).backgroundColor })),
    artStarsContrast: a0 && ratio(cs(a0.querySelector('.tc-rev-stars')).color, artBg),
    nameOverflow: arts.map((a) => { const b = a.querySelector('header b'); const s = a.querySelector('header .tc-rev-stars'); return Math.round(r(b).right - r(s).left); }),
    time: time && { font: cs(time).fontSize, contrast: ratio(cs(time).color, artBg), text: time.textContent },
    textContrast: a0 && ratio(cs(a0.querySelector('p')).color, artBg),
    more: more && { h: Math.round(r(more).height), text: more.textContent, contrast: ratio(cs(more).color, artBg) },
    note: note && { font: cs(note).fontSize, contrast: ratio(cs(note).color, surface), text: note.textContent },
    galH2: gal && { mt: cs(gal.querySelector('h2')).marginTop, mb: cs(gal.querySelector('h2')).marginBottom },
    imgs: imgs.map((i) => ({ w: Math.round(r(i).width), h: Math.round(r(i).height), radius: cs(i).borderTopLeftRadius, ok: i.complete && i.naturalWidth > 0 })),
    gap: imgs.length > 1 ? Math.round(r(imgs[1]).left - r(imgs[0]).right) : null,
    glane: glane && { client: glane.clientWidth, scroll: glane.scrollWidth },
    order: ['Где проходят занятия', 'Отзывы', 'На занятиях'].map((t) => [...document.querySelectorAll('h2')].findIndex((h) => h.textContent === t)),
  };
}

const fails = [];
const check = (cond, msg) => { if (!cond) fails.push(msg); };
const rows = [];
let shotsLeft = 2;
for (const dark of [false, true]) {
  for (const w of [320, 390]) {
    const src = '/webapp/trainers?trainer_id=7' + (dark ? '&__dark=1' : '');
    await page.goto(origin + '/__frame?w=' + w + '&src=' + encodeURIComponent(src));
    const frame = page.frame({ url: /\/webapp\/trainers/ });
    await frame.waitForSelector('.tc-revs', { timeout: 5000 });
    await frame.evaluate(() => document.fonts.ready);
    await frame.waitForFunction((d) => document.body.classList.contains('tg-dark') === d, dark, { timeout: 3000 });
    await frame.waitForFunction(() => [...document.querySelectorAll('.tc-gal img')].every((i) => i.complete), null, { timeout: 5000 });
    const m = await frame.evaluate(measure);
    const id = `${w}${dark ? ' dark' : ''}`;
    rows.push({ id, ...m });
    check(m.W === w, `${id}: ширина ${m.W}`);
    check(m.overflow === 0, `${id}: горизонтальный скролл страницы ${m.overflow}px`);
    check(m.dark === dark, `${id}: тема`);
    check(m.sec && m.sec.radius === '18px' && m.sec.pad === '16px 0px 16px 16px', `${id}: карточка ${JSON.stringify(m.sec)}`);
    check(m.sec && m.sec.w === w - 32, `${id}: ширина карточки ${m.sec && m.sec.w}`);
    check(m.h2 && m.h2.font === '12px/700', `${id}: h2 ${JSON.stringify(m.h2)}`);
    check(m.score && m.score.font.startsWith('28px') && /Dela/.test(m.score.font) && m.score.text === '4,9', `${id}: сводка ${JSON.stringify(m.score)}`);
    const star = dark ? 'rgb(240, 195, 109)' : 'rgb(183, 121, 31)';
    check(m.sumStars && m.sumStars.color === star && m.sumStars.text === '★★★★★' && m.sumStars.label === 'Рейтинг 4,9 из 5', `${id}: звёзды ${JSON.stringify(m.sumStars)}`);
    check(m.sumStars && m.sumStars.contrast >= 3, `${id}: контраст звёзд сводки ${m.sumStars && m.sumStars.contrast}`);
    check(m.count && m.count.font === '13px' && m.count.text === '14 оценок' && m.count.contrast >= 4.5, `${id}: «14 оценок» ${JSON.stringify(m.count)}`);
    check(m.lane && m.lane.scroll > m.lane.client && m.lane.right === m.lane.secRight - 1, `${id}: лента ${JSON.stringify(m.lane)} (до правого края карточки)`);
    check(m.arts.length === 3 && m.arts.every((a) => a.w === 260 && a.pad === '14px' && a.radius === '14px'), `${id}: карточки ${JSON.stringify(m.arts)}`);
    check(m.artStarsContrast >= 3, `${id}: контраст звёзд в отзыве ${m.artStarsContrast}`);
    check(m.nameOverflow.every((d) => d <= -8), `${id}: имя наезжает на звёзды ${m.nameOverflow}`);
    check(m.textContrast >= 4.5, `${id}: контраст текста отзыва ${m.textContrast}`);
    check(m.time && m.time.font === '12px' && m.time.contrast >= 4.5 && m.time.text === '2 ноября 2026', `${id}: дата ${JSON.stringify(m.time)}`);
    check(m.more && m.more.h >= 44 && m.more.contrast >= 4.5, `${id}: «Читать полностью» ${JSON.stringify(m.more)}`);
    check(m.note && m.note.font === '12px' && m.note.contrast >= 4.5 && m.note.text === 'Тексты отзывов проверяем перед публикацией.', `${id}: подпись ${JSON.stringify(m.note)}`);
    check(m.galH2 && m.galH2.mt === '4px' && m.galH2.mb === '8px', `${id}: h2 «На занятиях» ${JSON.stringify(m.galH2)}`);
    check(m.imgs.length === 3 && m.imgs.every((i) => i.w === 148 && i.h === 110 && i.radius === '14px' && i.ok), `${id}: плитки ${JSON.stringify(m.imgs)}`);
    check(m.gap === 8, `${id}: зазор плиток ${m.gap}`);
    check(m.glane && m.glane.scroll > m.glane.client && m.glane.client === w - 32, `${id}: лента фото ${JSON.stringify(m.glane)}`);
    check(m.order[0] >= 0 && m.order[0] < m.order[1] && m.order[1] < m.order[2], `${id}: порядок h2 ${m.order}`);
    if (shotsLeft > 0 && w === 390) {
      await page.setViewportSize({ width: w, height: 900 });
      await frame.evaluate(() => { const s = document.querySelector('.tc-revs'); window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY - 12); });
      await page.locator('#f').screenshot({ path: path.join(shots, `reviews-${w}${dark ? '-dark' : ''}.png`) });
      await page.setViewportSize({ width: 520, height: 900 });
      shotsLeft -= 1;
    }
  }
}
// «Читать полностью» у второго отзыва (лента прокручена к нему) раскрывает его и не сбрасывает прокрутку ленты.
{
  await page.goto(origin + '/__frame?w=390&src=' + encodeURIComponent('/webapp/trainers?trainer_id=7'));
  const frame = page.frame({ url: /\/webapp\/trainers/ });
  await frame.waitForSelector('[data-act="rev-more"]');
  const r = await frame.evaluate(async () => {
    const lane = document.querySelector('.tc-rev-lane');
    const second = lane.querySelectorAll('.tc-rev')[1];
    lane.scrollLeft = second.offsetLeft - lane.offsetLeft;
    await new Promise((ok) => setTimeout(ok, 50));
    const x = lane.scrollLeft;
    second.querySelector('[data-act="rev-more"]').click();
    await new Promise((ok) => setTimeout(ok, 50));
    const lane2 = document.querySelector('.tc-rev-lane');
    return { x, after: lane2.scrollLeft, more: document.querySelectorAll('[data-act="rev-more"]').length, full: document.querySelector('#tcRev1').textContent.endsWith('нуля.'), focus: document.activeElement && document.activeElement.id };
  });
  rows.push({ id: 'раскрытие 390', ...r });
  check(r.x > 0 && r.more === 1 && r.full && r.focus === 'tcRev1', `раскрытие: ${JSON.stringify(r)}`);
  check(Math.abs(r.after - r.x) <= 1, `раскрытие: прокрутка ленты ${r.x} → ${r.after}`);
}
await browser.close();
server.close();

for (const m of rows) console.log(JSON.stringify(m));
check(!errors.length, 'ошибки страницы: ' + errors.join(' | '));
if (fails.length) {
  console.error('\nРАСХОЖДЕНИЯ:\n' + fails.join('\n'));
  process.exit(1);
}
console.log('\nOK: «Отзывы» и «На занятиях» по доске A на 320/390, светлая и тёмная; скриншоты: ' + shots);
