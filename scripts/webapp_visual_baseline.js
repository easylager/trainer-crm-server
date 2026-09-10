#!/usr/bin/env node
/**
 * TASK-085 — визуальный стенд клиентского Mini App (EPIC4 client-premium).
 *
 * Снимает все клиентские экраны в ОБЕИХ темах на одном вьюпорте и складывает PNG
 * в .ai/epics/client-premium/design/shots/<дата>/. Снимки «до» — доказательная база
 * эпика: без них спор «стало лучше» решается вкусом, а регресс светлой темы всплывает
 * на проде, а не в диффе (см. theme.css, ревизия 26.08.2026).
 *
 * Зависимостей нет. Chrome управляется по CDP через встроенный в Node WebSocket.
 *
 * Приложение живёт внутри Telegram, поэтому стенд:
 *   1) подписывает initData тем же HMAC, что проверяет src/shared/telegram_webapp.py,
 *      иначе API отдаёт 401 и мы снимаем экраны ошибок вместо продукта;
 *   2) подсовывает мок window.Telegram.WebApp до выполнения скриптов страницы;
 *   3) переключает тему через colorScheme мока — как в проде, не через prefers-color-scheme
 *      (theme.css: тема ОС ≠ тема Telegram).
 *
 * Использование:
 *   node scripts/webapp_visual_baseline.js                     снять в папку сегодняшней даты
 *   node scripts/webapp_visual_baseline.js --out before        снять в папку с именем before
 *   node scripts/webapp_visual_baseline.js --base http://…     другой сервер
 *   node scripts/webapp_visual_baseline.js --only ice          только экраны с этой подстрокой
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');

const ROOT = path.resolve(__dirname, '..');
const SHOTS_DIR = path.join(ROOT, '.ai/epics/client-premium/design/shots');

/**
 * Эталонный вьюпорт (TASK-085 Q-001): 390×844 — логические размеры iPhone 14/15,
 * самый частый класс устройств в СНГ. DPR 2, чтобы типографика читалась на снимке.
 */
const VIEWPORT = { width: 390, height: 844, deviceScaleFactor: 2, mobile: true };

/**
 * Локальный клиент из dev-БД. Это тот же аккаунт, с которого сняты скриншоты
 * владельца 2026-09-07, — снимки стенда сопоставимы с ними напрямую.
 */
const CLIENT_TELEGRAM_ID = Number(process.env.BASELINE_CLIENT_ID || 1304982166);
const CLIENT_NAME = { first_name: 'Максим', last_name: 'Василенко', username: 'maks' };

const SCREENS = [
  { id: 'client-home', url: '/webapp/client-home', ready: "document.body.classList.contains('hub-body--revealed')" },
  // TASK-090: список катков рисуется карточкой-табло (.ice-board); линза
  // «Тренеры» осталась на строке .ice-acard — готовность ждём по обеим.
  {
    id: 'ice-skate',
    url: '/webapp/ice',
    ready: "document.querySelectorAll('.ice-board, .ice-acard').length > 0",
  },
  { id: 'ice-coach', url: '/webapp/ice?intent=coach', ready: "document.querySelectorAll('.ice-acard').length > 0" },
  { id: 'arena-card', url: '/webapp/arena?arena_id=3', ready: "document.querySelector('#arenaRoot') !== null" },
  { id: 'client-bookings', url: '/webapp/client-bookings', ready: null },
  /*
   * TASK-098. Тренерские экраны в стенде — не расширение эпика, а его условие:
   * mini-app-components.css общий, и правка клиентских кнопок молча меняет
   * двенадцать тренерских страниц. TASK-097 уже показала, как правка общего
   * theme.css утащила их в системный шрифт — тогда заметили только потому, что
   * искали. Здесь искать будет нечему, если не снимать.
   */
  { id: 'trainer-home', url: '/webapp/trainer-home', audience: 'trainer', ready: null },
  { id: 'trainer-clients', url: '/webapp/trainer-clients', audience: 'trainer', ready: null },
  { id: 'trainer-profile', url: '/webapp/trainer-profile', audience: 'trainer', ready: null },
  { id: 'trainer-stats', url: '/webapp/trainer-stats', audience: 'trainer', ready: null },
  { id: 'trainer-subscription', url: '/webapp/trainer-subscription', audience: 'trainer', ready: null },
];

/*
 * Локальный тренер: тот же telegram_id, что у клиента в dev-БД, но initData
 * подписывается ДРУГИМ ботом — тренерские маршруты проверяют свой токен.
 */
const TRAINER_TELEGRAM_ID = Number(process.env.BASELINE_TRAINER_ID || 1304982166);
const TRAINER_NAME = { first_name: 'Максим', last_name: 'Василенко', username: 'maks' };

const THEMES = ['dark', 'light'];

// ── Telegram initData ────────────────────────────────────────────────────────

function readEnv() {
  const out = {};
  const file = path.join(ROOT, '.env');
  if (!fs.existsSync(file)) return out;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    const t = line.trim();
    if (!t || t.startsWith('#') || !t.includes('=')) continue;
    const i = t.indexOf('=');
    out[t.slice(0, i)] = t.slice(i + 1).trim().replace(/^["']|["']$/g, '');
  }
  return out;
}

/**
 * Подпись ровно как в src/shared/telegram_webapp.py:
 * secret = HMAC_SHA256(key="WebAppData", msg=bot_token); hash = HMAC_SHA256(secret, dcs).
 */
function signInitData(botToken, user, telegramId = CLIENT_TELEGRAM_ID) {
  const fields = {
    query_id: 'AAF' + crypto.randomBytes(8).toString('hex'),
    user: JSON.stringify({ id: telegramId, is_bot: false, language_code: 'ru', ...user }),
    auth_date: String(Math.floor(Date.now() / 1000)),
  };
  const dcs = Object.keys(fields)
    .sort()
    .map((k) => `${k}=${fields[k]}`)
    .join('\n');
  const secret = crypto.createHmac('sha256', 'WebAppData').update(botToken).digest();
  const hash = crypto.createHmac('sha256', secret).update(dcs).digest('hex');
  return new URLSearchParams({ ...fields, hash }).toString();
}

// ── Мок Telegram WebApp ──────────────────────────────────────────────────────

/**
 * Покрывает только то, что приложение реально вызывает (проверено grep'ом по
 * client-home-main.js, ice-tab.js, mini-app-client-shell.js, mini-app-telegram-chrome.js).
 * Отсутствующий метод = исключение на старте = пустой снимок, поэтому лучше шире.
 */
function buildMockScript(initData, theme, opts = {}) {
  // Плёнку перехода (TASK-094) снимают с ЖИВЫМИ анимациями — иначе снимать нечего.
  const freezeAnimations = opts.freezeAnimations !== false;
  const telegramId = opts.telegramId || CLIENT_TELEGRAM_ID;
  const person = opts.person || CLIENT_NAME;
  const dark = theme === 'dark';
  const themeParams = dark
    ? { bg_color: '#0B0C0E', text_color: '#E6E9EA', hint_color: '#868D93', link_color: '#57D0D2',
        button_color: '#45B9BB', button_text_color: '#04262A', secondary_bg_color: '#141618' }
    : { bg_color: '#F1F3F2', text_color: '#101617', hint_color: '#5E6B6B', link_color: '#0B6E70',
        button_color: '#45B9BB', button_text_color: '#04262A', secondary_bg_color: '#FFFFFF' };

  return `(() => {
  const noop = () => {};
  const btn = () => ({ show: noop, hide: noop, setText: noop, onClick: noop, offClick: noop,
                       enable: noop, disable: noop, showProgress: noop, hideProgress: noop, isVisible: false });
  window.Telegram = { WebApp: {
    initData: ${JSON.stringify(initData)},
    initDataUnsafe: { user: ${JSON.stringify({ id: telegramId, ...person })} },
    version: '7.10', platform: 'ios',
    colorScheme: ${JSON.stringify(theme)},
    themeParams: ${JSON.stringify(themeParams)},
    isExpanded: true,
    viewportHeight: ${VIEWPORT.height},
    viewportStableHeight: ${VIEWPORT.height},
    safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
    contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
    headerColor: ${JSON.stringify(themeParams.bg_color)},
    backgroundColor: ${JSON.stringify(themeParams.bg_color)},
    isVerticalSwipesEnabled: true,
    MainButton: btn(), SecondaryButton: btn(), BackButton: btn(), SettingsButton: btn(),
    HapticFeedback: { impactOccurred: noop, notificationOccurred: noop, selectionChanged: noop },
    CloudStorage: { getItem: noop, setItem: noop, removeItem: noop },
    ready: noop, expand: noop, close: noop,
    enableVerticalSwipes: noop, disableVerticalSwipes: noop,
    enableClosingConfirmation: noop, disableClosingConfirmation: noop,
    requestFullscreen: noop, exitFullscreen: noop,
    setHeaderColor: noop, setBackgroundColor: noop, setBottomBarColor: noop,
    onEvent: noop, offEvent: noop, sendData: noop,
    openLink: noop, openTelegramLink: noop, openInvoice: noop,
    showAlert: (m, cb) => cb && cb(), showConfirm: (m, cb) => cb && cb(false),
    showPopup: (p, cb) => cb && cb(''),
    switchInlineQuery: noop, shareToStory: noop,
  }};
  // Стенд снимает статичный кадр: анимации только смазывают снимок и делают дифф шумным.
  //
  // ВАЖНО (найдено в TASK-094): скрипт выполняется на document-start, когда
  // documentElement ещё null — прежняя версия падала здесь с TypeError, и
  // анимации на самом деле НЕ глушились ни на одном снимке эпика. Ждём корень.
  const freeze = () => {
    if (!${freezeAnimations}) return;
    const root = document.documentElement;
    if (!root) return;
    const style = document.createElement('style');
    style.textContent = '*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;transition-duration:0s!important;transition-delay:0s!important;}';
    root.appendChild(style);
  };
  if (document.documentElement) freeze();
  else document.addEventListener('readystatechange', freeze, { once: true });
})();`;
}

// ── Минимальный CDP-клиент ───────────────────────────────────────────────────

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
      }
    });
  }

  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => {
      ws.addEventListener('open', res, { once: true });
      ws.addEventListener('error', () => rej(new Error('CDP: не удалось подключиться')), { once: true });
    });
    return new CDP(ws);
  }

  send(method, params = {}, sessionId) {
    const id = ++this.id;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    this.ws.send(JSON.stringify(payload));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }

  close() {
    this.ws.close();
  }
}

function findChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
  ].filter(Boolean);
  for (const c of candidates) if (fs.existsSync(c)) return c;
  throw new Error('Chrome не найден. Укажите путь в CHROME_PATH.');
}

async function launchChrome() {
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'webapp-baseline-'));
  const proc = spawn(
    findChrome(),
    [
      '--headless=new',
      '--remote-debugging-port=0',
      `--user-data-dir=${userDataDir}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-gpu',
      '--hide-scrollbars',
      '--force-color-profile=srgb',
      '--disable-lcd-text',
      'about:blank',
    ],
    { stdio: ['ignore', 'ignore', 'pipe'] }
  );

  // Chrome пишет фактический порт в DevToolsActivePort — берём оттуда, а не гадаем.
  const portFile = path.join(userDataDir, 'DevToolsActivePort');
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (fs.existsSync(portFile)) {
      const [port] = fs.readFileSync(portFile, 'utf8').split('\n');
      if (port) {
        const res = await fetch(`http://127.0.0.1:${port}/json/version`);
        const info = await res.json();
        return { proc, userDataDir, wsUrl: info.webSocketDebuggerUrl };
      }
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  proc.kill();
  throw new Error('Chrome не поднял отладочный порт за 15 с');
}

/**
 * TASK-098. Учётки стенда. Тренерские экраны отличаются от клиентских ровно
 * одним: initData подписан другим ботом. Помощники живут здесь, чтобы все
 * четыре проверки (снимки, обрезания, контраст, CLS) ходили одним способом —
 * иначе тренерский экран молча снимется как «401» и пройдёт проверку.
 */
function buildCredentials(env) {
  const clientToken = process.env.TELEGRAM_BOT_TOKEN_CLIENT || env.TELEGRAM_BOT_TOKEN_CLIENT;
  if (!clientToken) throw new Error('TELEGRAM_BOT_TOKEN_CLIENT не найден — без него API отдаст 401.');
  const trainerToken = process.env.TELEGRAM_BOT_TOKEN_TRAINER || env.TELEGRAM_BOT_TOKEN_TRAINER;
  return {
    client: {
      initData: signInitData(clientToken, CLIENT_NAME, CLIENT_TELEGRAM_ID),
      telegramId: CLIENT_TELEGRAM_ID,
      person: CLIENT_NAME,
      available: true,
    },
    trainer: {
      initData: trainerToken ? signInitData(trainerToken, TRAINER_NAME, TRAINER_TELEGRAM_ID) : '',
      telegramId: TRAINER_TELEGRAM_ID,
      person: TRAINER_NAME,
      available: !!trainerToken,
    },
  };
}

/** Экраны, которые нечем открыть, из прогона выпадают — с явным предупреждением. */
function usableScreens(screens, creds) {
  if (creds.trainer.available) return screens;
  const skipped = screens.filter((s) => s.audience === 'trainer').length;
  if (skipped) console.log(`TELEGRAM_BOT_TOKEN_TRAINER не найден — ${skipped} тренерских экранов пропущено\n`);
  return screens.filter((s) => s.audience !== 'trainer');
}

/** Мок Telegram под аудиторию конкретного экрана. */
function mockForScreen(screen, theme, creds, opts = {}) {
  const who = creds[screen.audience === 'trainer' ? 'trainer' : 'client'];
  return buildMockScript(who.initData, theme, {
    ...opts,
    telegramId: who.telegramId,
    person: who.person,
  });
}

// ── Съёмка ───────────────────────────────────────────────────────────────────

async function waitFor(cdp, sessionId, expression, timeoutMs) {
  if (!expression) return false;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const { result } = await cdp.send('Runtime.evaluate', { expression, returnByValue: true }, sessionId);
      if (result && result.value === true) return true;
    } catch {
      /* страница ещё перестраивается — пробуем снова */
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  return false;
}

async function capture(cdp, screen, theme, creds, baseUrl, outDir) {
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });

  await cdp.send('Page.enable', {}, sessionId);
  await cdp.send('Runtime.enable', {}, sessionId);
  await cdp.send('Network.enable', {}, sessionId);
  /*
   * Настоящий SDK с telegram.org присваивает window.Telegram и затирает наш мок —
   * страница тогда думает, что тема светлая, и оба снимка выходят одинаковыми.
   * Блокируем только его. Google Fonts НЕ блокируем: типографика — предмет этого
   * эпика, и снимать её системным фолбэком значит снимать не тот продукт.
   */
  await cdp.send(
    'Network.setBlockedURLs',
    { urls: ['*telegram.org/js/telegram-web-app.js*'] },
    sessionId
  );
  await cdp.send('Emulation.setDeviceMetricsOverride', VIEWPORT, sessionId);
  await cdp.send(
    'Page.addScriptToEvaluateOnNewDocument',
    { source: mockForScreen(screen, theme, creds) },
    sessionId
  );

  await cdp.send('Page.navigate', { url: baseUrl + screen.url }, sessionId);

  const settled = await waitFor(cdp, sessionId, screen.ready, 12000);
  // Даже после готовности данных остаются картинки и шрифты — без паузы снимок «мигает».
  await new Promise((r) => setTimeout(r, settled ? 900 : 2500));

  const shots = [];
  const fold = await cdp.send('Page.captureScreenshot', { format: 'png' }, sessionId);
  const foldPath = path.join(outDir, `${screen.id}-${theme}.png`);
  fs.writeFileSync(foldPath, Buffer.from(fold.data, 'base64'));
  shots.push(foldPath);

  const full = await cdp.send(
    'Page.captureScreenshot',
    { format: 'png', captureBeyondViewport: true },
    sessionId
  );
  const fullPath = path.join(outDir, `${screen.id}-${theme}-full.png`);
  fs.writeFileSync(fullPath, Buffer.from(full.data, 'base64'));
  shots.push(fullPath);

  await cdp.send('Target.closeTarget', { targetId });
  return { settled, shots };
}

async function main() {
  const args = process.argv.slice(2);
  const opt = (name, def) => {
    const i = args.indexOf(name);
    return i >= 0 && args[i + 1] ? args[i + 1] : def;
  };

  const baseUrl = opt('--base', 'http://127.0.0.1:8000').replace(/\/$/, '');
  const outName = opt('--out', new Date().toISOString().slice(0, 10));
  const only = opt('--only', null);
  const outDir = path.join(SHOTS_DIR, outName);

  const env = readEnv();
  const creds = buildCredentials(env);

  try {
    const probe = await fetch(`${baseUrl}/webapp/client-home`, { signal: AbortSignal.timeout(4000) });
    if (!probe.ok) throw new Error(`статус ${probe.status}`);
  } catch (e) {
    throw new Error(`Сервер ${baseUrl} недоступен (${e.message}). Поднимите uvicorn.`);
  }

  fs.mkdirSync(outDir, { recursive: true });
  const screens = usableScreens(only ? SCREENS.filter((s) => s.id.includes(only)) : SCREENS, creds);

  const { proc, userDataDir, wsUrl } = await launchChrome();
  const cdp = await CDP.connect(wsUrl);

  const report = [];
  try {
    for (const screen of screens) {
      for (const theme of THEMES) {
        const { settled } = await capture(cdp, screen, theme, creds, baseUrl, outDir);
        const mark = settled || !screen.ready ? 'ok' : 'ПО ТАЙМАУТУ';
        console.log(`  ${pad(screen.id + ' / ' + theme, 32)} ${mark}`);
        report.push({ screen: screen.id, theme, settled: settled || !screen.ready });
      }
    }
  } finally {
    cdp.close();
    // Ждём фактического выхода Chrome: иначе он ещё пишет в профиль и rm падает с ENOTEMPTY.
    const exited = new Promise((r) => proc.once('exit', r));
    proc.kill();
    await Promise.race([exited, new Promise((r) => setTimeout(r, 3000))]);
    try {
      fs.rmSync(userDataDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    } catch {
      /* временный профиль — не повод ронять съёмку */
    }
  }

  const stale = report.filter((r) => !r.settled);
  console.log(`\nСнимки: ${path.relative(ROOT, outDir)}  (${report.length * 2} PNG)`);
  if (stale.length) {
    console.log(
      `\nВНИМАНИЕ: ${stale.length} экранов сняты по таймауту ожидания данных — ` +
        `на них могли остаться скелетоны:\n  ` +
        stale.map((s) => `${s.screen} / ${s.theme}`).join('\n  ')
    );
  }
}

function pad(s, n) {
  return String(s) + ' '.repeat(Math.max(0, n - String(s).length));
}

/*
 * Обвязка (CDP, запуск Chrome, подпись initData, мок Telegram, список экранов)
 * переиспользуется webapp_overflow_check.js. Разносить её по двум файлам нельзя:
 * два расходящихся мока Telegram — это два разных продукта под проверкой.
 */
module.exports = {
  CDP, launchChrome, buildMockScript, signInitData, readEnv, waitFor,
  buildCredentials, usableScreens, mockForScreen,
  SCREENS, THEMES, VIEWPORT, CLIENT_NAME, ROOT,
};

if (require.main === module) {
  main().catch((e) => {
    console.error('Ошибка:', e.message);
    process.exit(1);
  });
}
