#!/usr/bin/env node
/**
 * TASK-095 (AC-002). Сдвиг макета меряется, а не оценивается на глаз.
 *
 * Считает настоящий Cumulative Layout Shift через PerformanceObserver
 * ('layout-shift'), на тех же условиях съёмки, что и остальные инструменты
 * эпика: вьюпорт 390×844 DPR2, мок Telegram, тот же клиент, обе темы.
 *
 * Для каждого сдвига сохраняются его источники — селектор узла и то, куда он
 * уехал. Без этого «CLS 0.08» — число, по которому нечего чинить.
 *
 *   node scripts/webapp_cls_check.js --base http://127.0.0.1:8011
 *   node scripts/webapp_cls_check.js --base http://127.0.0.1:8011 --only ice
 *
 * Порог: 0.005. Это не «примерно ноль», а признание того, что округление
 * субпикселей при смене шрифта даёт микросдвиги, неразличимые глазом.
 */
'use strict';

const path = require('node:path');

const H = require(path.join(__dirname, 'webapp_visual_baseline.js'));
const { CDP, launchChrome, readEnv, waitFor, buildCredentials, usableScreens, mockForScreen, SCREENS, THEMES, VIEWPORT } = H;

const THRESHOLD = 0.005;

/* Ставится до любого скрипта страницы: сдвиги начинаются раньше, чем грузится приложение. */
const OBSERVER = `(() => {
  window.__cls = { value: 0, shifts: [] };
  const sel = (node) => {
    if (!node || node.nodeType !== 1) return '(не элемент)';
    let s = node.tagName.toLowerCase();
    if (node.id) s += '#' + node.id;
    if (node.classList && node.classList.length) s += '.' + [...node.classList].slice(0, 2).join('.');
    return s;
  };
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        // Сдвиг после клика/тапа пользователь считает своим — он не в метрике.
        if (entry.hadRecentInput) continue;
        window.__cls.value += entry.value;
        window.__cls.shifts.push({
          value: Math.round(entry.value * 10000) / 10000,
          at: Math.round(entry.startTime),
          sources: (entry.sources || []).slice(0, 3).map((s) => ({
            node: sel(s.node),
            from: s.previousRect ? Math.round(s.previousRect.top) : null,
            to: s.currentRect ? Math.round(s.currentRect.top) : null,
          })),
        });
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch (e) {
    window.__cls.unsupported = String(e);
  }
})();`;

async function measure(cdp, screen, theme, creds, baseUrl) {
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  await cdp.send('Page.enable', {}, sessionId);
  await cdp.send('Runtime.enable', {}, sessionId);
  await cdp.send('Network.enable', {}, sessionId);
  await cdp.send('Network.setBlockedURLs', { urls: ['*telegram.org/js/telegram-web-app.js*'] }, sessionId);
  await cdp.send('Emulation.setDeviceMetricsOverride', VIEWPORT, sessionId);
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: OBSERVER }, sessionId);
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: mockForScreen(screen, theme, creds) }, sessionId);

  await cdp.send('Page.navigate', { url: baseUrl + screen.url }, sessionId);
  await waitFor(cdp, sessionId, screen.ready, 12000);
  // Данные пришли — но шрифт и картинки ещё догружаются, а сдвиг чаще всего там.
  await new Promise((r) => setTimeout(r, 2500));

  const { result } = await cdp.send(
    'Runtime.evaluate',
    { expression: 'JSON.stringify(window.__cls)', returnByValue: true },
    sessionId
  );
  await cdp.send('Target.closeTarget', { targetId });
  return JSON.parse(result.value || '{"value":0,"shifts":[]}');
}

function pad(s, n) {
  s = String(s);
  return s.length >= n ? s : s + ' '.repeat(n - s.length);
}

async function main() {
  const args = process.argv.slice(2);
  const opt = (name, def) => {
    const i = args.indexOf(name);
    return i >= 0 && args[i + 1] ? args[i + 1] : def;
  };
  const baseUrl = opt('--base', 'http://127.0.0.1:8000').replace(/\/$/, '');
  const only = opt('--only', null);
  const verbose = args.includes('--sources');

  const env = readEnv();
  const creds = buildCredentials(env);
  const screens = usableScreens(only ? SCREENS.filter((s) => s.id.includes(only)) : SCREENS, creds);

  const { proc, userDataDir, wsUrl } = await launchChrome();
  const cdp = await CDP.connect(wsUrl);
  let worst = 0;
  const failed = [];
  try {
    console.log('CLS на вьюпорте 390×844, порог ' + THRESHOLD + '\n');
    for (const screen of screens) {
      for (const theme of THEMES) {
        const cls = await measure(cdp, screen, theme, creds, baseUrl);
        const v = Math.round(cls.value * 10000) / 10000;
        worst = Math.max(worst, v);
        const ok = v <= THRESHOLD;
        if (!ok) failed.push({ screen: screen.id, theme, value: v });
        console.log(`  ${pad(screen.id + ' / ' + theme, 30)} CLS ${pad(v, 8)} ${ok ? 'ok' : 'СДВИГ'}`);
        if (!ok || verbose) {
          for (const s of cls.shifts.slice(0, 6)) {
            const src = s.sources
              .map((x) => `${x.node} ${x.from}→${x.to}px`)
              .join('; ');
            console.log(`      +${s.value} на ${s.at}мс  ${src || '(источник не определён)'}`);
          }
        }
      }
    }
  } finally {
    cdp.close();
    const exited = new Promise((r) => proc.once('exit', r));
    proc.kill();
    await Promise.race([exited, new Promise((r) => setTimeout(r, 3000))]);
    try {
      require('node:fs').rmSync(userDataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    } catch {
      /* временный профиль — не повод ронять прогон */
    }
  }

  console.log(`\nХудший CLS: ${worst}`);
  if (failed.length) {
    console.log(`НЕ ПРОШЛО: ${failed.length} из ${screens.length * THEMES.length}`);
    process.exitCode = 1;
  } else {
    console.log('Сдвига макета нет.');
  }
}

if (require.main === module) {
  main().catch((e) => {
    console.error(e.message);
    process.exit(1);
  });
}
