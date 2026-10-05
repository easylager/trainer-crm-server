/**
 * Каждый ассет, на который ссылается клиентская страница, обязан иметь маршрут
 * в src/api/app.py.
 *
 * Почему этот тест существует. TASK-160 добавил `hub-me-card.js`, страница его
 * подключила, все статические гварды были зелёные — а сервер отдавал 404.
 * `window.HubMeCard` не появлялся, `renderMeCard` по защитному условию молча
 * возвращал null, и хаб тихо откатывался на прежнюю раскладку. Ни один тест
 * этого не видел: они проверяли, что страница ССЫЛАЕТСЯ на модуль, но не что
 * его кто-то ОТДАЁТ. Нашлось только на живом приложении.
 *
 * Run: node --test tests/js/webapp-assets-served.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../..');
const WEBAPP = path.join(ROOT, 'static/webapp');
const appPy = fs.readFileSync(path.join(ROOT, 'src/api/app.py'), 'utf8');

/** Страницы, которые отдаются маршрутами /webapp/<name> и грузят модули. */
const PAGES = fs
  .readdirSync(WEBAPP)
  .filter((f) => f.endsWith('.html') && !f.startsWith('hub-priority-buttons'));

/**
 * Монтирование StaticFiles существует, но висит на /static/webapp, а страницы
 * грузят ассеты относительными путями, то есть из /webapp. Поэтому пофайловый
 * маршрут обязателен, и никакой лазейки «есть StaticFiles — значит отдастся»
 * здесь быть не должно: именно она в первой версии этого теста сделала его
 * незамечающим (мутационная проверка не краснела).
 */
const mountsWebappRoot = /app\.mount\(\s*["']\/webapp["']/.test(appPy);

function assetsOf(html) {
  const out = new Set();
  const re = /(?:src|href)="([a-z0-9][a-z0-9._-]*\.(?:js|css))(?:\?v=\d+)?"/gi;
  let m;
  while ((m = re.exec(html))) out.add(m[1]);
  return out;
}

describe('ассеты клиентских страниц реально отдаются сервером', () => {
  for (const page of PAGES) {
    it(page + ': каждый локальный <script>/<link> имеет маршрут', () => {
      const html = fs.readFileSync(path.join(WEBAPP, page), 'utf8');
      const missing = [];
      for (const asset of assetsOf(html)) {
        if (!fs.existsSync(path.join(WEBAPP, asset))) continue; // чужое/внешнее
        const routed = appPy.includes('"/webapp/' + asset + '"')
          || appPy.includes("'/webapp/" + asset + "'");
        if (!routed && !mountsWebappRoot) missing.push(asset);
      }
      assert.deepEqual(
        missing,
        [],
        page + ' ссылается на ассеты без маршрута в app.py — они отдадут 404: ' + missing.join(', ')
      );
    });
  }
});
