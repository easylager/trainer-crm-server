/**
 * TASK-375: при выключенном флаге «назад»/«Главная» на страницах из «Ещё» ведут себя как до задачи.
 * LEGACY_HOME — побайтная копия mini-app-client-home.js из epic/your-season до TASK-375.
 * Run: node --test tests/js/client-season-back*.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const WEBAPP = path.join(__dirname, '../../static/webapp');
const read = (f) => fs.readFileSync(path.join(WEBAPP, f), 'utf8');
const LEGACY_HOME = String.raw`/**
 * Client mini apps: navigate to hub (client-home) preserving Telegram init_data in URL.
 * Wires #btnHome when present (DOM ready or immediately if DOM already loaded).
 */
(function () {
  function webappBasePath() {
    var p = window.location.pathname || '';
    return p.replace(/[^/]+$/, '') || '/webapp/';
  }

  function withInit(url) {
    var tg = window.Telegram && window.Telegram.WebApp;
    var initData = tg && tg.initData ? tg.initData : '';
    if (!initData) return url;
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'init_data=' + encodeURIComponent(initData);
  }

  function navigateClientHome() {
    /* Canonical app route is /webapp/client-home (no .html) — see src/api/app.py */
    window.location.href = withInit(webappBasePath() + 'client-home');
  }

  window.navigateClientHome = navigateClientHome;

  function canBrowserGoBack() {
    try {
      if (window.navigation && typeof window.navigation.canGoBack === 'function') {
        return window.navigation.canGoBack();
      }
    } catch (e) { /* older WebViews */ }
    return window.history && window.history.length > 1;
  }

  function wireBack() {
    var btn = document.getElementById('btnBack');
    if (!btn || btn.getAttribute('data-skip-history-back') === 'true') return;
    function sync() {
      btn.hidden = !canBrowserGoBack();
    }
    btn.onclick = function () {
      window.history.back();
    };
    sync();
    window.addEventListener('popstate', sync);
  }

  function wire() {
    var b = document.getElementById('btnHome');
    if (b) b.onclick = navigateClientHome;
    wireBack();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
`;
const CURRENT_HOME = read('mini-app-client-home.js');
const HELPER = read('client-season-back.js');

const KEY = 'cw_ui_flags_v1';

/** Прогон скрипта в песочнице; возвращает наблюдаемое поведение кнопок. */
function run(src, { flag, history = 3, withHelper = true, attrs = {}, cache, nav, storageThrows = false }) {
  const log = { back: 0, href: null, hrefs: [] };
  const mk = (a) => ({
    hidden: true, onclick: null,
    getAttribute: (n) => (n in a ? a[n] : null),
    hasAttribute: (n) => n in a,
  });
  const btnBack = mk(attrs);
  const btnHome = mk({});
  const listeners = [];
  const window = {
    location: { pathname: '/webapp/client-support', set href(v) { log.href = v; log.hrefs.push(v); }, get href() { return log.href; } },
    history: { length: history, back() { log.back++; } },
    navigation: nav,
    Telegram: { WebApp: { initData: 'a=1', initDataUnsafe: { user: { id: 42 } } } },
    addEventListener: (n, f) => listeners.push([n, f]),
  };
  const raw = cache !== undefined ? cache : flag ? JSON.stringify({ u: '42', season_ui: true }) : null;
  window.localStorage = storageThrows
    ? { getItem() { throw new Error('denied'); } }
    : { getItem: (k) => (k === KEY ? raw : null) };
  window.document = {
    readyState: 'complete',
    addEventListener() {},
    getElementById: (id) => (id === 'btnBack' ? btnBack : id === 'btnHome' ? btnHome : null),
  };
  const ctx = vm.createContext({ window, document: window.document, globalThis: window });
  window.window = window;
  if (withHelper) vm.runInContext(HELPER, ctx);
  vm.runInContext(src, ctx);
  const out = { hiddenAtStart: btnBack.hidden, homeSet: typeof btnHome.onclick, backSet: typeof btnBack.onclick };
  if (btnBack.onclick) btnBack.onclick();
  if (btnHome.onclick) btnHome.onclick();
  out.back = log.back;
  out.href = log.href;
  out.hrefs = log.hrefs;
  out.popstate = listeners.filter(([n]) => n === 'popstate').length;
  return out;
}

describe('mini-app-client-home.js: флаг выключен = прежнее поведение (6 страниц)', () => {
  const states = [
    ['нет кэша', { flag: false }],
    ['кэш season_ui false', { flag: false, cache: JSON.stringify({ u: '42', season_ui: false }) }],
    ['"true" строкой', { cache: JSON.stringify({ u: '42', season_ui: 'true' }) }],
    ['чужой u', { cache: JSON.stringify({ u: '7', season_ui: true }) }],
    ['битый JSON', { cache: '{oops' }],
    ['storage бросает', { storageThrows: true }],
    ['хелпер не загрузился', { flag: true, withHelper: false }],
  ];
  const buttons = [
    ['#btnBack без атрибутов (certificates, family-access, support — до правки)', {}],
    ['#btnBack с data-season-back (после правки разметки)', { 'data-season-back': '' }],
    ['#btnBack data-skip-history-back (stats, passes, passes-certificates)', { 'data-skip-history-back': 'true' }],
  ];
  for (const [sname, s] of states) {
    for (const [bname, attrs] of buttons) {
      for (const history of [1, 3]) {
        for (const nav of [undefined, { canGoBack: () => false }, { canGoBack: () => true }]) {
          it(`${sname} / ${bname} / history=${history} / nav=${nav ? nav.canGoBack() : '—'}`, () => {
            const legacyAttrs = 'data-season-back' in attrs ? {} : attrs;
            const a = run(LEGACY_HOME, { ...s, history, nav, attrs: legacyAttrs, withHelper: false });
            const b = run(CURRENT_HOME, { ...s, history, nav, attrs });
            assert.deepEqual(b, a);
          });
        }
      }
    }
  }
});

describe('mini-app-client-home.js: флаг включён', () => {
  const on = { flag: true };
  it('data-season-back: кнопка видна без истории, «назад» → client-me', () => {
    const r = run(CURRENT_HOME, { ...on, history: 1, attrs: { 'data-season-back': '' } });
    assert.equal(r.hiddenAtStart, false);
    assert.equal(r.back, 0);
    assert.deepEqual(r.hrefs, ['/webapp/client-me?init_data=a%3D1', '/webapp/client-home?init_data=a%3D1']);
  });
  it('data-season-back с историей → history.back(); «Главная» → client-home', () => {
    const r = run(CURRENT_HOME, { ...on, history: 3, attrs: { 'data-season-back': '' } });
    assert.equal(r.back, 1);
    assert.deepEqual(r.hrefs, ['/webapp/client-home?init_data=a%3D1']); // только «Главная»
  });
  it('без data-season-back (другие страницы с этим скриптом) — как раньше', () => {
    const legacy = run(LEGACY_HOME, { ...on, history: 1, withHelper: false });
    assert.deepEqual(run(CURRENT_HOME, { ...on, history: 1 }), legacy);
  });
  it('data-skip-history-back — скрипт не трогает кнопку', () => {
    const r = run(CURRENT_HOME, { ...on, attrs: { 'data-skip-history-back': 'true' } });
    assert.equal(r.backSet, 'object'); // null
    assert.equal(r.hiddenAtStart, true);
  });
});

describe('обработчики страниц: прежний код сохранён побайтно, новый — за флагом', () => {
  const must = (file, snippet) => assert.ok(read(file).includes(snippet), `${file}: нет прежнего фрагмента`);
  it('client-saved-trainers-main.js', () => {
    must('client-saved-trainers-main.js', `  } else if (btnBack && window.history.length > 1) {
    btnBack.hidden = false;
    btnBack.onclick = function () { window.history.back(); };
  }`);
    must('client-saved-trainers-main.js', `document.getElementById('btnHome').onclick = function () { goTo('client-home'); };`);
  });
  for (const [file, id, list] of [
    ['client-passes.html', 'screenDetail', `showScreen('screenList');`],
    ['client-passes-certificates.html', 'pass-screenDetail', `showPassScreen('pass-screenList');`],
  ]) {
    it(file, () => {
      const s = read(file);
      must(file, `navBack.hidden = id !== '${id}'`);
      must(file, `        ${list}\n      };`);
      assert.ok(s.includes(`seasonBackOn() && !document.getElementById('${id}').classList.contains('active')`));
      assert.ok(s.includes(`if (seasonBackOn()) document.getElementById('btnBack').hidden = false;`));
    });
  }
  it('client-stats-main.js: новая кнопка только за флагом', () => {
    const s = read('client-stats-main.js');
    assert.ok(s.includes('if (!S || !btn || !S.isSeasonUi(window)) return;'));
  });
  it('страницы подключают хелпер, оболочку — нет', () => {
    for (const f of ['client-saved-trainers', 'client-stats', 'client-passes-certificates', 'client-passes',
      'client-certificates', 'client-family-access', 'client-support']) {
      const s = read(f + '.html');
      assert.ok(s.includes('/static/webapp/client-season-back.js'), f);
      assert.ok(!s.includes('mini-app-client-shell'), f);
    }
  });
});
