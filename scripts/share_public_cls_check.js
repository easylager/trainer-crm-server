#!/usr/bin/env node
/**
 * CLS для публичных share-страниц (/, /c/{city}, /p/...).
 * Вьюпорт 390×844, эмуляция Slow 4G (CDP), PerformanceObserver layout-shift.
 *
 *   node scripts/share_public_cls_check.js --base http://127.0.0.1:8011
 */
'use strict';

const path = require('node:path');
const H = require(path.join(__dirname, 'webapp_visual_baseline.js'));
const { CDP, launchChrome, VIEWPORT } = H;

const PAGES = [
  { id: '/', path: '/' },
  { id: '/c/minsk', path: '/c/minsk' },
  { id: '/p/minsk/chizhovka', path: '/p/minsk/chizhovka' },
];

const OBSERVER = `(() => {
  window.__cls = { value: 0, shifts: [] };
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.hadRecentInput) continue;
        window.__cls.value += entry.value;
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch (e) {
    window.__cls.unsupported = String(e);
  }
})();`;

async function measure(cdp, baseUrl, pagePath) {
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  await cdp.send('Page.enable', {}, sessionId);
  await cdp.send('Runtime.enable', {}, sessionId);
  await cdp.send('Network.enable', {}, sessionId);
  await cdp.send('Emulation.setDeviceMetricsOverride', VIEWPORT, sessionId);
  await cdp.send(
    'Network.emulateNetworkConditions',
    {
      offline: false,
      downloadThroughput: (400 * 1024) / 8,
      uploadThroughput: (400 * 1024) / 8,
      latency: 400,
    },
    sessionId
  );
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: OBSERVER }, sessionId);
  await cdp.send('Page.navigate', { url: baseUrl + pagePath }, sessionId);
  await new Promise((r) => setTimeout(r, 8000));
  const { result } = await cdp.send(
    'Runtime.evaluate',
    { expression: 'JSON.stringify(window.__cls)', returnByValue: true },
    sessionId
  );
  await cdp.send('Target.closeTarget', { targetId });
  const cls = JSON.parse(result.value || '{"value":0}');
  return Math.round((cls.value || 0) * 1000) / 1000;
}

async function main() {
  const args = process.argv.slice(2);
  const i = args.indexOf('--base');
  const baseUrl = (i >= 0 && args[i + 1] ? args[i + 1] : 'http://127.0.0.1:8011').replace(/\/$/, '');
  const { proc, userDataDir, wsUrl } = await launchChrome();
  const cdp = await CDP.connect(wsUrl);
  try {
    console.log(`CLS (390×844, Slow 4G) base=${baseUrl}\n`);
    for (const page of PAGES) {
      const v = await measure(cdp, baseUrl, page.path);
      console.log(`${page.id}\t${v}`);
    }
  } finally {
    await cdp.close();
    proc.kill();
    require('node:fs').rmSync(userDataDir, { recursive: true, force: true });
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
