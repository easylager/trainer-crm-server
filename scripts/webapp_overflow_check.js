#!/usr/bin/env node
/**
 * TASK-086 (EPIC4 client-premium) — проверка переполнений на клиентских экранах.
 *
 * Зачем отдельный инструмент. Смена ступеней типа двигает метрики текста, а линтер
 * этого не видит: он читает CSS, а обрезанная на полслова строка появляется только
 * в браузере. Сравнивать снимки глазами тоже не выход — на 20 PNG перенос, уехавший
 * на один пиксель, не заметен, а в проде заметен сразу.
 *
 * Что ловим:
 *   page-scroll   горизонтальная прокрутка страницы — вёрстка шире вьюпорта
 *   clipped-x     текст обрезан по ширине (overflow: hidden / ellipsis)
 *   clipped-y     текст обрезан по высоте (line-clamp сработал не там, где задумано)
 *   overflow-box  элемент вылезает за границы своего контейнера
 *
 * Зависимостей нет: обвязка (Chrome по CDP, подпись initData, мок Telegram)
 * переиспользуется из webapp_visual_baseline.js — тот же продукт под проверкой.
 *
 * Использование:
 *   node scripts/webapp_overflow_check.js --base http://127.0.0.1:8001
 *   node scripts/webapp_overflow_check.js --only ice        только экраны «Льда»
 *   node scripts/webapp_overflow_check.js --json out.json   выгрузить находки
 */
'use strict';

const fs = require('node:fs');
const {
  CDP, launchChrome, readEnv, waitFor,
  buildCredentials, usableScreens, mockForScreen,
  SCREENS, THEMES, VIEWPORT,
} = require('./webapp_visual_baseline.js');

/**
 * Проба выполняется в странице. Возвращает находки, а не «да/нет»: без селектора
 * и текста находка бесполезна — непонятно, что чинить.
 */
const PROBE = `(() => {
  const out = { page: null, items: [] };
  const de = document.documentElement;

  if (de.scrollWidth > de.clientWidth + 1) {
    out.page = { scrollWidth: de.scrollWidth, clientWidth: de.clientWidth };
  }

  const name = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    if (el.classList.length) s += '.' + [...el.classList].slice(0, 3).join('.');
    return s;
  };

  const seen = new Set();
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || !el.getClientRects().length) continue;

    const text = (el.textContent || '').trim().slice(0, 60);
    const leaf = !el.querySelector('*');

    // 1. Обрезание по ширине: контент шире бокса и спрятан
    const hiddenX = cs.overflowX === 'hidden' || cs.overflowX === 'clip' || cs.textOverflow === 'ellipsis';
    if (hiddenX && el.scrollWidth > el.clientWidth + 1 && text) {
      out.items.push({ kind: 'clipped-x', sel: name(el), by: el.scrollWidth - el.clientWidth, text });
    }

    // 2. Обрезание по высоте. line-clamp — осознанный приём, поэтому он не находка;
    //    находка — обрезание там, где его не просили.
    const hiddenY = cs.overflowY === 'hidden' || cs.overflowY === 'clip';
    const clamped = cs.webkitLineClamp && cs.webkitLineClamp !== 'none';
    if (hiddenY && !clamped && el.scrollHeight > el.clientHeight + 1 && text && leaf) {
      out.items.push({ kind: 'clipped-y', sel: name(el), by: el.scrollHeight - el.clientHeight, text });
    }

    // 3. Вылет за границы родителя, который сам ничего не прячет и не скроллит
    const p = el.parentElement;
    if (p && leaf && text) {
      const pcs = getComputedStyle(p);
      const contained = ['hidden', 'clip', 'auto', 'scroll'].includes(pcs.overflowX)
        || pcs.position === 'relative' && cs.position === 'absolute';
      if (!contained && cs.position === 'static') {
        const r = el.getBoundingClientRect(), pr = p.getBoundingClientRect();
        const over = Math.max(r.right - pr.right, pr.left - r.left);
        if (over > 2 && pr.width > 0) {
          const key = 'ob:' + name(el);
          if (!seen.has(key)) { seen.add(key); out.items.push({ kind: 'overflow-box', sel: name(el), by: Math.round(over), text }); }
        }
      }
    }
  }
  return JSON.stringify(out);
})()`;

async function inspect(cdp, screen, theme, creds, baseUrl) {
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });

  await cdp.send('Page.enable', {}, sessionId);
  await cdp.send('Runtime.enable', {}, sessionId);
  await cdp.send('Network.enable', {}, sessionId);
  // Тот же блок, что в стенде снимков: настоящий SDK затирает мок и ломает тему.
  await cdp.send('Network.setBlockedURLs', { urls: ['*telegram.org/js/telegram-web-app.js*'] }, sessionId);
  await cdp.send('Emulation.setDeviceMetricsOverride', VIEWPORT, sessionId);
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: mockForScreen(screen, theme, creds) }, sessionId);
  await cdp.send('Page.navigate', { url: baseUrl + screen.url }, sessionId);

  const settled = await waitFor(cdp, sessionId, screen.ready, 12000);
  // Шрифт доезжает после данных, а метрики текста считаются уже по нему.
  await cdp.send('Runtime.evaluate', { expression: 'document.fonts.ready', awaitPromise: true }, sessionId);
  await new Promise((r) => setTimeout(r, settled ? 900 : 2500));

  const { result } = await cdp.send('Runtime.evaluate', { expression: PROBE, returnByValue: true }, sessionId);
  await cdp.send('Target.closeTarget', { targetId });
  return { settled: settled || !screen.ready, ...JSON.parse(result.value) };
}

async function main() {
  const args = process.argv.slice(2);
  const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 && args[i + 1] ? args[i + 1] : d; };
  const baseUrl = opt('--base', 'http://127.0.0.1:8000').replace(/\/$/, '');
  const only = opt('--only', null);
  const jsonOut = opt('--json', null);

  const env = readEnv();
  const creds = buildCredentials(env);
  const screens = usableScreens(only ? SCREENS.filter((s) => s.id.includes(only)) : SCREENS, creds);

  const { proc, userDataDir, wsUrl } = await launchChrome();
  const cdp = await CDP.connect(wsUrl);

  const all = [];
  try {
    for (const screen of screens) {
      for (const theme of THEMES) {
        const r = await inspect(cdp, screen, theme, creds, baseUrl);
        const n = r.items.length + (r.page ? 1 : 0);
        const tag = `${screen.id} / ${theme}`;
        console.log(`  ${tag}${' '.repeat(Math.max(0, 32 - tag.length))} ${n === 0 ? 'чисто' : n + ' находок'}${r.settled ? '' : '  (ПО ТАЙМАУТУ)'}`);
        if (r.page) {
          console.log(`      page-scroll: вёрстка ${r.page.scrollWidth}px при вьюпорте ${r.page.clientWidth}px`);
          all.push({ screen: screen.id, theme, kind: 'page-scroll', ...r.page });
        }
        for (const it of r.items) {
          console.log(`      ${it.kind}  +${it.by}px  ${it.sel}\n          «${it.text}»`);
          all.push({ screen: screen.id, theme, ...it });
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

  if (jsonOut) fs.writeFileSync(jsonOut, JSON.stringify(all, null, 2) + '\n');
  console.log(`\nВсего находок: ${all.length}`);
  if (all.length) process.exitCode = 1;
}

main().catch((e) => { console.error('Ошибка:', e.message); process.exit(1); });
