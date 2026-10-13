import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';

const base = process.env.TASK256_BASE_URL || 'http://127.0.0.1:8011';
const placePath = process.env.TASK256_PLACE_PATH;
const outDir =
  process.env.TASK256_SHOTS_DIR ||
  path.resolve(process.env.HOME, 'Projects/.trainer-crm-state/tasks/TASK-256-screenshots');

if (!placePath) {
  console.error('TASK256_PLACE_PATH required');
  process.exit(2);
}

const tgStub = () => {
  window.Telegram = {
    WebApp: {
      initData: 'user=%7B%22id%22%3A1%7D&hash=stub',
      colorScheme: 'dark',
      themeParams: {},
      ready() {},
      expand() {},
      disableVerticalSwipes() {},
      enableVerticalSwipes() {},
      onEvent() {},
      BackButton: { show() {}, hide() {}, onClick() {} },
      HapticFeedback: { selectionChanged() {}, notificationOccurred() {} },
    },
  };
};

await mkdir(outDir, { recursive: true });

const browser = await chromium.launch();

const plain = await browser.newContext({ viewport: { width: 390, height: 844 } });
const plainPage = await plain.newPage();
await plainPage.goto(`${base}${placePath}`, { waitUntil: 'networkidle' });
const plainMeta = await plainPage.evaluate(() => ({
  tab: !!document.getElementById('clientTabBar'),
  tgDark: document.body.classList.contains('tg-dark'),
  bodyBg: getComputedStyle(document.body).backgroundColor,
}));
await plainPage.screenshot({ path: path.join(outDir, 'browser.png'), fullPage: false });
console.log('browser meta', JSON.stringify(plainMeta));
await plain.close();

const tg = await browser.newContext({ viewport: { width: 390, height: 844 } });
await tg.addInitScript(tgStub);
const tgPage = await tg.newPage();
await tgPage.goto(`${base}${placePath}`, { waitUntil: 'networkidle' });
await tgPage.waitForSelector('#clientTabBar', { timeout: 20000 });
await tgPage.waitForTimeout(1000);
const errText = 'Что-то пошло не так';
const tgMeta = await tgPage.evaluate((err) => {
  const body = document.body;
  const el = document.elementFromPoint(195, 400);
  const cs = el ? getComputedStyle(el) : null;
  const dock = document.getElementById('placeShareBtn');
  const bar = document.getElementById('clientTabBar');
  const dockBox = dock ? dock.getBoundingClientRect() : null;
  const barBox = bar ? bar.getBoundingClientRect() : null;
  return {
    tgDark: body.classList.contains('tg-dark'),
    bodyBg: getComputedStyle(body).backgroundColor,
    at400: cs ? cs.backgroundColor : '',
    dockY: dockBox ? [Math.round(dockBox.top), Math.round(dockBox.bottom)] : null,
    barY: barBox ? Math.round(barBox.top) : null,
    hasErr: document.body.innerText.includes(err),
    title: document.querySelector('.b-hero__title')?.textContent?.trim() || '',
    hasTabBar: !!document.getElementById('clientTabBar'),
    hasPozvat: !!document.getElementById('placeShareBtn'),
  };
}, errText);
if (tgMeta.hasErr) {
  console.error('telegram screenshot still shows recoverable error overlay');
  process.exit(1);
}
await tgPage.screenshot({ path: path.join(outDir, 'telegram.png'), fullPage: false });
console.log('telegram meta', JSON.stringify(tgMeta));
await tg.close();

await browser.close();
console.log('saved', outDir);
