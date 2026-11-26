#!/usr/bin/env node
/**
 * Лаба редизайна на стабах (PR #288 / release/redesign-v1).
 *
 *   node tools/redesign-lab.mjs
 *   → http://127.0.0.1:9810/
 *
 * Слева — сценарии (те же формы данных, что e2e). Справа — живой UI 390px.
 * Агент: открой /?scene=home-booking или скажи id сценария.
 *
 * Это не прод: API поддельные, Telegram — заглушка, «сейчас» зафиксировано.
 */
import http from 'node:http';
import { readFileSync, existsSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { exec } from 'node:child_process';
import { SCENES, sceneById, apiForScene, NOW_DEFAULT } from '../tests/e2e/lab/scenes.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(here, '..');
const staticDir = path.join(repoRoot, 'static');
const photosDir = path.join(repoRoot, 'data', 'arena-cards', 'photos');
const PORT = Number(process.env.LAB_PORT || 9810);

const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2',
  '.json': 'application/json',
};

const ICE_V2_PARAMS = new Set(['city_id', 'day', 'kind', 'when', 'intent', 'init_data', 'tgWebAppStartParam', 'lab']);

function parseCookies(req) {
  const out = {};
  const raw = req.headers.cookie || '';
  raw.split(';').forEach((p) => {
    const i = p.indexOf('=');
    if (i > 0) out[p.slice(0, i).trim()] = decodeURIComponent(p.slice(i + 1).trim());
  });
  return out;
}

function currentScene(req, url) {
  const q = url.searchParams.get('scene') || url.searchParams.get('lab');
  if (q) return sceneById(q);
  const c = parseCookies(req).lab_scene;
  if (c) return sceneById(c);
  return sceneById('home-newbie');
}

function tgMockJs(scene) {
  const scheme = scene.tgScheme || 'light';
  return `window.Telegram = { WebApp: {
    initData: 'user=%7B%22id%22%3A1%2C%22first_name%22%3A%22%D0%9C%D0%B0%D0%BA%D1%81%D0%B8%D0%BC%22%7D',
    initDataUnsafe: { user: { id: 1, first_name: 'Максим', allows_write_to_pm: true } },
    colorScheme: '${scheme}', themeParams: {},
    version: '8.0', platform: 'ios', isExpanded: true, viewportHeight: 844,
    isVersionAtLeast(v) {
      const cmp = (a, b) => a.split('.').map(Number).reduce((d, x, i) => d || x - (b[i] || 0), 0);
      return cmp(this.version, String(v)) >= 0;
    },
    ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
    onEvent() {}, offEvent() {}, enableClosingConfirmation() {}, disableVerticalSwipes() {},
    HapticFeedback: { selectionChanged() {}, impactOccurred() {}, notificationOccurred() {} },
    BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
    MainButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
    openTelegramLink(u) { console.info('[lab] openTelegramLink', u); },
    openLink(u) { console.info('[lab] openLink', u); window.open(u, '_blank'); },
    shareURL(u) { console.info('[lab] shareURL', u); },
  } };`;
}

function injectLab(html, scene) {
  const now = (scene.now || NOW_DEFAULT).getTime();
  const flags = JSON.stringify({ u: '1', ...(scene.flags || {}), at: Date.now() });
  const boot = `
<script>
/* redesign-lab inject */
try {
  /* При смене scene чистим кэши экрана и героя: старая сцена не должна
     «приоткрывать» новую своим кэшом (s3 кэширует целый экран и фото героя). */
  var labScene = ${JSON.stringify(scene.id)};
  if (localStorage.getItem('lab_scene') !== labScene) {
    localStorage.setItem('lab_scene', labScene);
    var rm = [];
    for (var li = 0; li < localStorage.length; li++) {
      var lk = localStorage.key(li);
      if (lk && /^(hv2_hero_|hv2_screen_v1:|iv2_screen_v1:)/.test(lk)) rm.push(lk);
    }
    rm.forEach(function (k) { localStorage.removeItem(k); });
    try { sessionStorage.removeItem('hv2_ice_pf'); } catch (e2) {}
  }
  localStorage.setItem('cw_ui_flags_v1', ${JSON.stringify(flags)});
} catch (e) {}
(function () {
  var fixed = ${now};
  var RealDate = Date;
  function LabDate() {
    if (arguments.length === 0) return new RealDate(fixed);
    return new (Function.prototype.bind.apply(RealDate, [null].concat([].slice.call(arguments))))();
  }
  LabDate.now = function () { return fixed; };
  LabDate.parse = RealDate.parse;
  LabDate.UTC = RealDate.UTC;
  LabDate.prototype = RealDate.prototype;
  window.Date = LabDate;
})();
</script>`;
  const tgTag = '<script src="/lab/tg.js"></' + 'script>';
  let out = html.replace(
    /<script src="https:\/\/telegram\.org\/js\/telegram-web-app\.js"><\/script>/,
    tgTag,
  );
  if (!out.includes('/lab/tg.js')) {
    out = out.replace('</head>', tgTag + '</head>');
  }
  out = out.replace('</head>', boot + '</head>');
  return out;
}

function resolveWebappFile(pathname, searchParams, scene) {
  const s4 = !!(scene.flags && scene.flags.redesign_s4);
  const s1 = !!(scene.flags && scene.flags.redesign_s1);

  if (pathname === '/webapp/client-home' || pathname === '/webapp/client-home/') {
    return s1 ? 'webapp/client-home-v2.html' : 'webapp/client-home.html';
  }
  if (pathname === '/webapp/client-home.html') return 'webapp/client-home.html';
  if (pathname === '/webapp/client-home-v2.html') return 'webapp/client-home-v2.html';

  if (pathname === '/webapp/ice' || pathname === '/webapp/ice/') {
    const legacy = searchParams.has('map') || [...searchParams.keys()].some((k) => !ICE_V2_PARAMS.has(k));
    return (s4 && !legacy) ? 'webapp/client-ice-v2.html' : 'webapp/ice.html';
  }
  if (pathname === '/webapp/client-ice-v2.html') return 'webapp/client-ice-v2.html';
  if (pathname === '/webapp/ice.html') return 'webapp/ice.html';

  if (pathname === '/webapp/client-me' || pathname === '/webapp/client-me/') {
    return s4 ? 'webapp/client-me-v2.html' : 'webapp/client-me.html';
  }
  if (pathname === '/webapp/client-me.html') return 'webapp/client-me.html';
  if (pathname === '/webapp/client-me-v2.html') return 'webapp/client-me-v2.html';

  return null;
}

function labIndexHtml(activeId) {
  const groups = {};
  for (const s of SCENES) {
    (groups[s.group] || (groups[s.group] = [])).push(s);
  }
  const nav = Object.entries(groups).map(([g, items]) => {
    const links = items.map((s) => {
      const on = s.id === activeId ? ' on' : '';
      const note = s.note ? ` title="${escapeHtml(s.note)}"` : '';
      return `<a class="sc${on}" href="/?scene=${encodeURIComponent(s.id)}"${note}>${escapeHtml(s.title)}</a>`;
    }).join('');
    return `<div class="g"><div class="gh">${escapeHtml(g)}</div>${links}</div>`;
  }).join('');

  const scene = sceneById(activeId);
  const frameSrc = scene.page + (scene.page.includes('?') ? '&' : '?') + 'lab=' + encodeURIComponent(scene.id);

  return `<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Glide redesign lab</title>
<style>
  :root { --ink:#0b1620; --muted:#6b7a86; --line:#e7ebee; --bg:#eef1f3; --teal:#0a6f73; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.4 "Golos Text", system-ui, sans-serif; color: var(--ink); background: var(--bg); height: 100vh; display: flex; }
  aside { width: 280px; flex-shrink: 0; background: #fff; border-right: 1px solid var(--line); overflow: auto; padding: 16px 12px 40px; }
  h1 { font-size: 15px; margin: 0 12px 4px; letter-spacing: -.02em; }
  .lead { color: var(--muted); font-size: 12px; margin: 0 12px 16px; }
  .g { margin-bottom: 14px; }
  .gh { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); padding: 4px 12px; }
  .sc { display: block; padding: 8px 12px; border-radius: 10px; color: var(--ink); text-decoration: none; font-weight: 500; }
  .sc:hover { background: #f3f6f7; }
  .sc.on { background: var(--ink); color: #fff; }
  main { flex: 1; display: flex; flex-direction: column; align-items: center; padding: 20px 16px 24px; min-width: 0; }
  .meta { width: 390px; max-width: 100%; margin-bottom: 10px; display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
  .meta b { font-size: 14px; }
  .meta span { font-size: 12px; color: var(--muted); }
  .phone { width: 390px; height: min(844px, calc(100vh - 80px)); border-radius: 28px; overflow: hidden;
    box-shadow: 0 24px 50px -24px rgba(11,22,32,.45), inset 0 0 0 1px rgba(11,22,32,.08); background: #fff; }
  iframe { width: 100%; height: 100%; border: 0; display: block; background: #f5f6f8; }
  .hint { margin-top: 10px; width: 390px; max-width: 100%; font-size: 12px; color: var(--muted); }
  code { font-size: 11px; background: #fff; padding: 1px 5px; border-radius: 4px; }
</style>
</head>
<body>
<aside>
  <h1>Redesign lab</h1>
  <p class="lead">Стабы API · живой UI из ветки. Не прод.</p>
  ${nav}
</aside>
<main>
  <div class="meta">
    <b>${escapeHtml(scene.group)} · ${escapeHtml(scene.title)}</b>
    <span><code>${escapeHtml(scene.id)}</code></span>
  </div>
  <div class="phone"><iframe src="${escapeHtml(frameSrc)}" title="scene"></iframe></div>
  <p class="hint">${scene.note ? escapeHtml(scene.note) + ' · ' : ''}Данные фиктивные. «Сейчас» = ${(scene.now || NOW_DEFAULT).toISOString()} (UTC).</p>
</main>
</body>
</html>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function send(res, code, type, body, extraHeaders) {
  res.writeHead(code, { 'content-type': type, ...(extraHeaders || {}) });
  res.end(body);
}

function safeJoin(root, rel) {
  const file = path.join(root, rel);
  if (!file.startsWith(root)) return null;
  if (!existsSync(file) || statSync(file).isDirectory()) return null;
  return file;
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', `http://127.0.0.1:${PORT}`);
  let pathname = decodeURIComponent(url.pathname);

  /* index / scene switch */
  if (pathname === '/' || pathname === '/lab' || pathname === '/lab/') {
    const scene = currentScene(req, url);
    const html = labIndexHtml(scene.id);
    send(res, 200, 'text/html; charset=utf-8', html, {
      'set-cookie': `lab_scene=${encodeURIComponent(scene.id)}; Path=/; SameSite=Lax`,
    });
    return;
  }

  if (pathname === '/lab/scenes.json') {
    send(res, 200, 'application/json', JSON.stringify(SCENES.map((s) => ({
      id: s.id, group: s.group, title: s.title, page: s.page, note: s.note || null,
    })), null, 2));
    return;
  }

  if (pathname === '/lab/tg.js') {
    const scene = currentScene(req, url);
    send(res, 200, 'text/javascript; charset=utf-8', tgMockJs(scene));
    return;
  }

  /* API stubs */
  if (pathname.startsWith('/api/')) {
    const scene = currentScene(req, url);
    if (pathname.startsWith('/api/public/photos')) {
      const photo = safeJoin(photosDir, 'arena-25/hero.jpg');
      if (photo) {
        send(res, 200, 'image/jpeg', readFileSync(photo));
        return;
      }
    }
    const body = apiForScene(scene, pathname, req.method || 'GET', url.searchParams);
    send(res, 200, 'application/json', JSON.stringify(body));
    return;
  }

  /* photos */
  if (pathname.startsWith('/photos/')) {
    const file = safeJoin(photosDir, pathname.slice('/photos/'.length));
    if (!file) { send(res, 404, 'text/plain', 'no photo'); return; }
    send(res, 200, MIME[path.extname(file)] || 'application/octet-stream', readFileSync(file));
    return;
  }

  const scene = currentScene(req, url);
  const mapped = resolveWebappFile(pathname, url.searchParams, scene);
  if (mapped) {
    const file = safeJoin(staticDir, mapped);
    if (!file) { send(res, 404, 'text/plain', 'no page'); return; }
    let html = readFileSync(file, 'utf-8');
    html = injectLab(html, scene);
    send(res, 200, 'text/html; charset=utf-8', html, {
      'set-cookie': `lab_scene=${encodeURIComponent(scene.id)}; Path=/; SameSite=Lax`,
    });
    return;
  }

  /* static */
  if (pathname.startsWith('/static/')) pathname = pathname.slice('/static'.length);
  if (pathname.startsWith('/webapp/')) {
    const file = safeJoin(staticDir, pathname.slice(1));
    if (file) {
      if (path.extname(file) === '.html') {
        send(res, 200, 'text/html; charset=utf-8', injectLab(readFileSync(file, 'utf-8'), scene));
      } else {
        send(res, 200, MIME[path.extname(file)] || 'application/octet-stream', readFileSync(file));
      }
      return;
    }
  }
  const asStatic = safeJoin(staticDir, pathname.replace(/^\//, ''));
  if (asStatic) {
    send(res, 200, MIME[path.extname(asStatic)] || 'application/octet-stream', readFileSync(asStatic));
    return;
  }

  send(res, 404, 'text/plain', 'not found: ' + pathname);
});

server.listen(PORT, '127.0.0.1', () => {
  const url = `http://127.0.0.1:${PORT}/`;
  console.log(`Redesign lab → ${url}`);
  console.log(`Сценариев: ${SCENES.length}. Список: ${url}lab/scenes.json`);
  console.log('Пример: ' + url + '?scene=home-booking');
  if (process.env.LAB_NO_OPEN !== '1') {
    const openCmd = process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'start' : 'xdg-open';
    exec(`${openCmd} ${JSON.stringify(url)}`);
  }
});
