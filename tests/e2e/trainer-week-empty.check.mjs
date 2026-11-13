/**
 * TASK-415: пустая неделя H единой карточки — раскладка по доске NoSlots на 320 и 390, светлая и тёмная.
 * Настоящие trainers.html, CSS и JS витрины; стабы /api/* и Telegram. Узкие ширины — iframe (headless не уже ~500px).
 *
 * Доска NoSlots: блок «Ближайшее время» r18, padding 16, текст на всю ширину блока; «Сообщить…» 48px с колокольчиком 18;
 * внизу «Написать тренеру» — акцентная 52px, 15px/800, r14, поля 16; «Оставить заявку» — вторичная 48px.
 *
 * Run: node tests/e2e/trainer-week-empty.check.mjs   (код выхода 1 — расхождение)
 * Скриншоты: tests/e2e/__shots__/trainer-week-empty/ (каталог в .gitignore)
 */
import { chromium } from 'playwright';
import http from 'node:http';
import { mkdirSync, rmSync, readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.join(here, '../../static');
const shots = path.join(here, '__shots__', 'trainer-week-empty');
rmSync(shots, { recursive: true, force: true });
mkdirSync(shots, { recursive: true });

const LONG = 'Александра-Виктория Константинопольская-Щедрина';
const base = {
  id: 7, name: 'Анна Соколова', first_name: 'Анна', photo_url: '', experience_years: 7, description: 'Учу кататься с нуля.',
  education: '', can_book: true, contact_url: '/r/tg/7', phone: '', telegram_url: '', session_duration_minutes: 60,
  primary_arena_name: '«Замок»', city_name: 'Минск', windows: [],
  services: [{ service_id: 3, service_name: 'Взрослое занятие', title: 'Взрослое занятие', is_public: true, is_online: false,
    currency_code: 'BYN', price_cents: 4500, price_tiers: [] }],
  arenas: [{ id: 3, name: 'Замок', address: 'ул. Притыцкого, 156' }],
};
/* Состояние: Telegram (initData) и данные тренера. */
const CASES = {
  tg_contact: { tg: true, t: {} },
  tg_nocontact: { tg: true, t: { contact_url: '' } },
  web_contact: { tg: false, t: {} },
  web_phone: { tg: false, t: { contact_url: '', phone: '+375291112233' } },
  web_tglink: { tg: false, t: { contact_url: '', telegram_url: 'https://t.me/glide_bot?startapp=trainer_7' } },
  cb_false: { tg: true, t: { can_book: false } },
  cb_false_web: { tg: false, t: { can_book: false, contact_url: '', phone: '+375291112233' } },
  long_name: { tg: true, t: { name: LONG, first_name: 'Александра' } },
};

const MIME = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };
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
      '" style="border:0;display:block;width:' + Number(u.searchParams.get('w')) + 'px;height:760px"></iframe></body>');
    return;
  }
  if (p === '/__tg.js') {
    const tg = u.searchParams.get('tg') === '1';
    const dark = u.searchParams.get('dark') === '1';
    res.writeHead(200, { 'content-type': 'text/javascript' });
    res.end('window.Telegram={WebApp:{initData:' + JSON.stringify(tg ? 'query_id=1&user=%7B%22id%22%3A1%7D&hash=x' : '') +
      ',initDataUnsafe:{},colorScheme:' + JSON.stringify(dark ? 'dark' : 'light') + ',themeParams:{},platform:"ios",version:"8.0",' +
      'isVersionAtLeast:function(){return true},ready:function(){},expand:function(){},onEvent:function(){},offEvent:function(){},' +
      'BackButton:{show:function(){},hide:function(){},onClick:function(){},offClick:function(){}},' +
      'HapticFeedback:{impactOccurred:function(){},notificationOccurred:function(){},selectionChanged:function(){}}}};');
    return;
  }
  if (p.startsWith('/api/')) {
    const ref = new URL(req.headers.referer || 'http://x/', 'http://x');
    const c = CASES[ref.searchParams.get('__case')] || CASES.tg_contact;
    const t = { ...base, ...c.t };
    if (p === '/api/public/trainer-showcase') return json(res, { items: [t] });
    if (/^\/api\/(public\/trainers|webapp\/client\/catalog-trainer)\/7$/.test(p)) return json(res, t);
    if (p === '/api/webapp/client/slots') return json(res, { slots: [] });
    if (p === '/api/webapp/client/trainer-edges') return json(res, { all: [], primary: null, saved: [], past: [] });
    if (p === '/api/webapp/client/profiles') return json(res, { items: [{ client_id: 1, first_name: 'Тест' }], default_profile_id: 1 });
    return json(res, {});
  }
  if (p === '/webapp/trainers') {
    const tg = CASES[u.searchParams.get('__case')]?.tg ? '1' : '0';
    let html = readFileSync(path.join(staticDir, 'webapp/trainers.html'), 'utf8')
      .replace('https://telegram.org/js/telegram-web-app.js', '/__tg.js?tg=' + tg + '&dark=' + (u.searchParams.get('__dark') === '1' ? '1' : '0'));
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
const page = await browser.newPage({ viewport: { width: 520, height: 800 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));

function measure() {
  const r = (el) => (el ? el.getBoundingClientRect() : null);
  const cs = (el) => (el ? getComputedStyle(el) : null);
  const lines = (el) => (el ? Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight)) : 0);
  const sec = document.querySelector('.tc-h-none');
  const title = document.querySelector('.tc-h .tc-empty-t');
  const hint = document.querySelector('.tc-h-none .tc-empty-p');
  const notify = document.querySelector('.tc-h-none [data-act="notify"]');
  const ft = document.querySelector('.tc-h ~ .ft.tc-ft');
  const cta = ft && ft.querySelector('.cta');
  const secs = ft ? [...ft.querySelectorAll('.sec2')] : [];
  const back = document.querySelector('[data-act="to-trainer"]');
  const hback = document.querySelector('.tc-h-head .tc-bback');
  const btns = [...document.querySelectorAll('.tc-h button, .tc-ft button')].filter((b) => b.offsetParent);
  const de = document.documentElement;
  return {
    W: de.clientWidth,
    overflow: de.scrollWidth - de.clientWidth,
    ask: !!document.querySelector('.tc-h-ask'),
    sec: sec && { w: r(sec).width, radius: cs(sec).borderTopLeftRadius, pad: cs(sec).paddingLeft, h2: cs(sec.querySelector('h2')).fontSize + '/' + cs(sec.querySelector('h2')).fontWeight + ' ' + sec.querySelector('h2').textContent },
    title: title && { w: Math.round(r(title).width), lines: lines(title), font: cs(title).fontSize + '/' + cs(title).fontWeight, text: title.textContent },
    hint: hint && { w: Math.round(r(hint).width), lines: lines(hint), font: cs(hint).fontSize + '/' + cs(hint).lineHeight, color: cs(hint).color },
    notify: notify && { h: r(notify).height, w: Math.round(r(notify).width), bell: notify.querySelector('svg') ? r(notify.querySelector('svg')).width : 0, text: notify.textContent },
    cta: cta && { h: r(cta).height, w: Math.round(r(cta).width), left: Math.round(r(cta).left), font: cs(cta).fontSize + '/' + cs(cta).fontWeight, radius: cs(cta).borderTopLeftRadius, bg: cs(cta).backgroundColor, color: cs(cta).color, text: cta.textContent },
    secs: secs.map((b) => ({ h: r(b).height, w: Math.round(r(b).width), radius: cs(b).borderTopLeftRadius, color: cs(b).color, text: b.textContent })),
    back: back && { h: r(back).height, w: Math.round(r(back).width) },
    hback: hback && { w: r(hback).width, h: r(hback).height },
    minBtn: Math.min(...btns.map((b) => r(b).height)),
    bodyBg: cs(document.body).backgroundColor,
    dark: document.body.classList.contains('tg-dark'),
  };
}

const fails = [];
const check = (cond, msg) => { if (!cond) fails.push(msg); };
const rows = [];
let shotsLeft = 2;
for (const [name, c] of Object.entries(CASES)) {
  for (const dark of [false, true]) {
    if (dark && !['tg_contact', 'web_phone', 'cb_false'].includes(name)) continue;
    for (const w of [320, 390]) {
      const src = '/webapp/trainers?trainer_id=7&action=book&service_id=3&from=hub&__case=' + name + (dark ? '&__dark=1' : '');
      await page.goto(origin + '/__frame?w=' + w + '&src=' + encodeURIComponent(src));
      const frame = page.frame({ url: /\/webapp\/trainers/ });
      await frame.waitForSelector('.tc-h .tc-empty-t', { timeout: 5000 });
      await frame.evaluate(() => document.fonts.ready);
      // Тема ставится по таймерам client-mini-app-theme.js (0…1500 мс) — ждём её, а не первый кадр.
      await frame.waitForFunction((d) => document.body.classList.contains('tg-dark') === d, dark, { timeout: 3000 });
      const m = await frame.evaluate(measure);
      const id = `${name} ${w}${dark ? ' dark' : ''}`;
      rows.push({ id, ...m });
      check(m.W === w, `${id}: ширина iframe ${m.W}`);
      check(m.overflow === 0, `${id}: горизонтальный скролл ${m.overflow}px`);
      check(m.dark === dark, `${id}: тема`);
      check(m.minBtn >= 44, `${id}: кнопка ниже 44px (${m.minBtn})`);
      // В Telegram «Назад» — нативная кнопка клиента, своей в шапке нет.
      if (c.tg) check(!m.hback, `${id}: своя «Назад» в Telegram`);
      else check(m.hback && m.hback.w >= 44 && m.hback.h >= 44, `${id}: «Назад» в шапке ${JSON.stringify(m.hback)}`);
      check(!!m.back && m.back.h >= 44, `${id}: нет «Назад к тренеру»`);
      check(!m.ask, `${id}: на пустой H блок «Не подходит время?» (доска Week), а не NoSlots`);
      if (c.t.can_book === false) continue;
      check(!!m.sec, `${id}: нет блока «Ближайшее время»`);
      if (m.sec) {
        check(m.sec.radius === '18px' && m.sec.pad === '16px', `${id}: блок r${m.sec.radius} p${m.sec.pad}, на доске 18/16`);
        check(m.sec.w === w - 32, `${id}: блок ${m.sec.w}px, ждём ${w - 32} (поля 16)`);
        const inner = w - 32 - 2 - 32;
        check(m.title.w === inner, `${id}: заголовок ${m.title.w}px, ждём ${inner} (на всю ширину)`);
        check(m.title.font === '16px/700' && m.title.lines <= 2, `${id}: заголовок ${m.title.font}, строк ${m.title.lines}`);
        check(m.hint.w === inner && m.hint.lines <= 3, `${id}: пояснение ${m.hint.w}px, строк ${m.hint.lines}`);
        check(m.hint.font.startsWith('13px'), `${id}: пояснение ${m.hint.font}`);
      }
      if (c.tg) check(m.notify && m.notify.h === 48 && m.notify.bell === 18 && m.notify.w === w - 66, `${id}: «Сообщить» ${JSON.stringify(m.notify)}`);
      else check(!m.notify, `${id}: «Сообщить» вне Telegram`);
      check(!!m.cta, `${id}: внизу нет главной кнопки`);
      if (m.cta) {
        check(m.cta.h === 52 && m.cta.font === '15px/800' && m.cta.radius === '14px', `${id}: главная ${m.cta.h}px ${m.cta.font} r${m.cta.radius}, на доске 52 15/800 r14`);
        check(m.cta.w === w - 32 && m.cta.left === 16, `${id}: главная ${m.cta.w}px с ${m.cta.left}, ждём ${w - 32} с 16`);
        const want = c.t.contact_url !== '' ? 'Написать тренеру' : c.tg ? 'Оставить заявку' : c.t.phone ? 'Скопировать телефон' : 'Открыть в Telegram';
        check(m.cta.text === want, `${id}: главная «${m.cta.text}», ждём «${want}»`);
      }
      for (const s of m.secs) check(s.h === 48 && s.radius === '14px', `${id}: вторичная «${s.text}» ${s.h}px r${s.radius}`);
      if (name === 'tg_contact') check(m.secs.length === 1 && m.secs[0].text === 'Оставить заявку', `${id}: вторичные ${m.secs.map((s) => s.text)}`);
      if (shotsLeft > 0 && name === 'tg_contact' && ((w === 320 && !dark) || (w === 390 && dark))) {
        await page.setViewportSize({ width: w, height: 760 });
        await page.locator('#f').screenshot({ path: path.join(shots, `${name}-${w}${dark ? '-dark' : ''}.png`) });
        await page.setViewportSize({ width: 520, height: 800 });
        shotsLeft -= 1;
      }
    }
  }
}
await browser.close();
server.close();

for (const m of rows) {
  const s = m.sec ? `блок ${m.sec.w} r${m.sec.radius} | ${m.sec.h2} | заголовок ${m.title.w}px×${m.title.lines}стр | пояснение ${m.hint.w}px×${m.hint.lines}стр ${m.hint.font}` : (m.title ? `заголовок ${m.title.w}px «${m.title.text}»` : '');
  const n = m.notify ? ` | сообщить ${m.notify.w}×${m.notify.h} колокольчик ${m.notify.bell}` : '';
  const ct = m.cta ? ` | главная «${m.cta.text}» ${m.cta.w}×${m.cta.h} ${m.cta.font} r${m.cta.radius} ${m.cta.bg}/${m.cta.color}` : ' | главной нет';
  const sc = m.secs.map((x) => ` | «${x.text}» ${x.w}×${x.h} ${x.color}`).join('');
  console.log(`${m.id}: overflow ${m.overflow} | min кнопка ${m.minBtn} | шапка «Назад» ${m.hback ? m.hback.w + '×' + m.hback.h : 'нативная'} | ${s}${n}${ct}${sc} | «Назад к тренеру» ${m.back ? m.back.w + '×' + m.back.h : 'нет'} | ask ${m.ask}`);
}
if (errors.length) console.log('JS-ошибки:', errors);
if (fails.length || errors.length) {
  console.error('\nРАСХОЖДЕНИЯ (' + fails.length + '):\n- ' + fails.join('\n- '));
  process.exit(1);
}
console.log('\nOK: ' + rows.length + ' состояний, расхождений с доской NoSlots нет');
