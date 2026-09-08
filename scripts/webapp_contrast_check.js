#!/usr/bin/env node
/**
 * TASK-087 (EPIC4 client-premium) — проверка контраста текста по WCAG AA.
 *
 * Зачем инструмент, а не таблица в документе. Токен знает свой цвет, но не знает,
 * на каком фоне окажется: `--glide-hint` на карточке и он же на подложке модалки —
 * это два разных контраста. Посчитать можно только по факту рендера, пройдя от
 * элемента вверх до первого непрозрачного фона. Именно так и находится класс ошибок,
 * ради которого задача и заведена: текст #1a1a1a на фоне #141618 формально «задан
 * токеном темы» и при этом невидим.
 *
 * Порог AA: 4.5:1 для основного текста, 3:1 для крупного (>=24px либо >=18.7px и >=700).
 *
 * Честность важнее зелёного отчёта: если под текстом градиент или картинка,
 * контраст не вычисляется и элемент попадает в раздел «не посчитано», а не в «прошло».
 *
 * Использование:
 *   node scripts/webapp_contrast_check.js --base http://127.0.0.1:8001
 *   node scripts/webapp_contrast_check.js --base … --only ice --theme dark
 */
'use strict';

const fs = require('node:fs');
const {
  CDP, launchChrome, buildMockScript, signInitData, readEnv, waitFor,
  SCREENS, THEMES, VIEWPORT, CLIENT_NAME,
} = require('./webapp_visual_baseline.js');

const PROBE = `(() => {
  const parse = (c) => {
    const m = String(c).match(/rgba?\\(([^)]+)\\)/);
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); const hi = Math.max(l1, l2), lo = Math.min(l1, l2); return (hi + 0.05) / (lo + 0.05); };
  const over = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });

  const name = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    if (el.classList.length) s += '.' + [...el.classList].slice(0, 3).join('.');
    return s;
  };

  /*
   * Градиент — не повод не считать. Контракт поверхностей (TASK-088) кладёт под
   * карточку linear-gradient из двух сплошных тонов, и пропускать такой фон значило бы
   * снять проверку ровно с тех элементов, которые только что переделали.
   * Берём все опорные цвета и считаем по ХУДШЕМУ: если текст читается на самой
   * невыгодной точке градиента, он читается на всём.
   */
  const gradientStops = (bgImage) => {
    if (!/^(linear|radial)-gradient\\(/.test(bgImage)) return null;
    const stops = bgImage.match(/rgba?\\([^)]+\\)/g);
    if (!stops || !stops.length) return null;
    const parsed = stops.map(parse).filter((c) => c && c.a > 0);
    return parsed.length ? parsed : null;
  };

  const out = { fail: [], skipped: [], checked: 0 };

  for (const el of document.querySelectorAll('body *')) {
    // Считаем только собственный текст элемента: иначе один и тот же абзац
    // проверялся бы столько раз, сколько над ним обёрток.
    const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join(' ').trim();
    if (!own) continue;

    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || !el.getClientRects().length) continue;
    if (parseFloat(cs.opacity) === 0) continue;

    const fg = parse(cs.color);
    if (!fg || fg.a === 0) continue;

    // Эффективный фон: вверх до первого непрозрачного. Картинка или градиент
    // означают, что посчитать нельзя — честно уходим в «не посчитано».
    let bg = null, painted = null, node = el, candidates = null;
    while (node && node !== document.documentElement.parentNode) {
      const ncs = getComputedStyle(node);
      if (ncs.backgroundImage && ncs.backgroundImage !== 'none') {
        const stops = gradientStops(ncs.backgroundImage);
        if (!stops) { painted = name(node); break; }
        candidates = stops;
        break;
      }
      const c = parse(ncs.backgroundColor);
      if (c && c.a > 0) {
        bg = bg ? over(bg, c) : c;
        if (bg.a >= 0.999) break;
      }
      node = node.parentElement;
    }
    if (painted) { out.skipped.push({ sel: name(el), reason: 'фон-изображение у ' + painted, text: own.slice(0, 40) }); continue; }
    if (!candidates && (!bg || bg.a < 0.999)) { out.skipped.push({ sel: name(el), reason: 'фон не определён', text: own.slice(0, 40) }); continue; }

    const size = parseFloat(cs.fontSize);
    const weight = parseInt(cs.fontWeight, 10) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const need = large ? 3 : 4.5;
    // Под градиентом проверяем каждую опорную точку и оставляем худшую.
    const grounds = candidates || [bg];
    let worst = null;
    for (const g of grounds) {
      const base = g.a >= 0.999 ? g : over(g, bg || { r: 255, g: 255, b: 255, a: 1 });
      const eff = fg.a < 1 ? over(fg, base) : fg;
      const r = ratio(eff, base);
      if (!worst || r < worst.r) worst = { r, base };
    }
    out.checked += 1;
    if (worst.r < need) {
      const b = worst.base;
      out.fail.push({ sel: name(el), text: own.slice(0, 40), ratio: Math.round(worst.r * 100) / 100, need,
                      size: size + 'px', weight, fg: cs.color,
                      bg: 'rgb(' + Math.round(b.r) + ',' + Math.round(b.g) + ',' + Math.round(b.b) + ')' + (candidates ? ' (худшая точка градиента)' : '') });
    }
  }
  return JSON.stringify(out);
})()`;

async function inspect(cdp, screen, theme, initData, baseUrl) {
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  await cdp.send('Page.enable', {}, sessionId);
  await cdp.send('Runtime.enable', {}, sessionId);
  await cdp.send('Network.enable', {}, sessionId);
  await cdp.send('Network.setBlockedURLs', { urls: ['*telegram.org/js/telegram-web-app.js*'] }, sessionId);
  await cdp.send('Emulation.setDeviceMetricsOverride', VIEWPORT, sessionId);
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: buildMockScript(initData, theme) }, sessionId);
  await cdp.send('Page.navigate', { url: baseUrl + screen.url }, sessionId);
  const settled = await waitFor(cdp, sessionId, screen.ready, 12000);
  await cdp.send('Runtime.evaluate', { expression: 'document.fonts.ready', awaitPromise: true }, sessionId);
  await new Promise((r) => setTimeout(r, settled ? 900 : 2500));
  const { result } = await cdp.send('Runtime.evaluate', { expression: PROBE, returnByValue: true }, sessionId);
  await cdp.send('Target.closeTarget', { targetId });
  return JSON.parse(result.value);
}

async function main() {
  const args = process.argv.slice(2);
  const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 && args[i + 1] ? args[i + 1] : d; };
  const baseUrl = opt('--base', 'http://127.0.0.1:8000').replace(/\/$/, '');
  const only = opt('--only', null);
  const oneTheme = opt('--theme', null);

  const env = readEnv();
  const token = process.env.TELEGRAM_BOT_TOKEN_CLIENT || env.TELEGRAM_BOT_TOKEN_CLIENT;
  if (!token) throw new Error('TELEGRAM_BOT_TOKEN_CLIENT не найден — без него API отдаст 401.');

  const initData = signInitData(token, CLIENT_NAME);
  const screens = only ? SCREENS.filter((s) => s.id.includes(only)) : SCREENS;
  const themes = oneTheme ? [oneTheme] : THEMES;

  const { proc, userDataDir, wsUrl } = await launchChrome();
  const cdp = await CDP.connect(wsUrl);

  let fails = 0, checked = 0, skipped = 0;
  try {
    for (const screen of screens) {
      for (const theme of themes) {
        const r = await inspect(cdp, screen, theme, initData, baseUrl);
        checked += r.checked; skipped += r.skipped.length; fails += r.fail.length;
        const tag = `${screen.id} / ${theme}`;
        console.log(`  ${tag}${' '.repeat(Math.max(0, 30 - tag.length))} проверено ${String(r.checked).padStart(3)} · не прошло ${r.fail.length} · не посчитано ${r.skipped.length}`);
        for (const f of r.fail) {
          console.log(`      ${f.ratio}:1 < ${f.need}  ${f.sel}  ${f.size}/${f.weight}\n          «${f.text}»  ${f.fg} на ${f.bg}`);
        }
      }
    }
  } finally {
    cdp.close();
    const exited = new Promise((r) => proc.once('exit', r));
    proc.kill();
    await Promise.race([exited, new Promise((r) => setTimeout(r, 3000))]);
    try { fs.rmSync(userDataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch { /* временный профиль */ }
  }

  console.log(`\nИтого: проверено ${checked} пар текст/фон, не прошло AA — ${fails}, не посчитано (градиент/картинка) — ${skipped}`);
  if (fails) process.exitCode = 1;
}

main().catch((e) => { console.error('Ошибка:', e.message); process.exit(1); });
