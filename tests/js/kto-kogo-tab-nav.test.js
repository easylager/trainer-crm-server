/**
 * TASK-374 S1: «Кто кого» во вкладке таб-бара — стек игры.
 * Решения «назад», «показывать ли стрелку Telegram», повторный тап и вход по ссылке — чистые функции
 * kto-kogo-model.js; проводка в kto-kogo.js проверяется по исходнику.
 *
 * Run: node --test tests/js/kto-kogo-tab-nav.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const M = require('../../static/webapp/kto-kogo-model.js');

const js = fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo.js'), 'utf8');
const NESTED = ['table', 'profile', 'league', 'join', 'joined', 'month', 'matches', 'match', 'created'];
const hub = { name: 'hub', args: {} };

describe('без вкладки (флаг выключен) — как раньше', () => {
  it('с корня «назад» уходит на главную приложения', () => {
    assert.equal(M.backAction(1, false, false), 'home');
  });
  it('стрелка Telegram видна и на корне', () => {
    assert.equal(M.nativeBackShown(1, false), true);
    assert.equal(M.nativeBackShown(2, false), true);
  });
  it('шторка и вложенные экраны — как раньше', () => {
    assert.equal(M.backAction(1, true, false), 'sheet');
    assert.equal(M.backAction(3, false, false), 'pop');
  });
});

describe('во вкладке: корень', () => {
  it('стрелки Telegram нет', () => {
    assert.equal(M.nativeBackShown(1, true), false);
  });
  it('открытая шторка на корне — стрелка есть и закрывает шторку', () => {
    assert.equal(M.nativeBackShown(1, true, true), true);
    assert.equal(M.backAction(1, true, true), 'sheet');
    assert.equal(M.nativeBackShown(1, true, false), false);
    assert.equal(M.nativeBackShown(1, true, undefined), false);
  });
  it('флаг выключен: шторка ничего не меняет, стрелка и так видна', () => {
    assert.equal(M.nativeBackShown(1, false, true), true);
    assert.equal(M.nativeBackShown(1, false, false), true);
  });
  it('«назад» на корне ничего не делает', () => {
    assert.equal(M.backAction(1, false, true), 'stay');
  });
  it('своя круглая «назад» на главной игры не рисуется', () => {
    const board = fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo-board.js'), 'utf8');
    const hubSrc = board.slice(board.indexOf("K.register('hub'"), board.indexOf("K.register('table'"));
    assert.doesNotMatch(hubSrc, /'Назад'|K\.back|K\.topbar/);
  });
});

describe('во вкладке: вложенные экраны', () => {
  for (const name of NESTED) {
    it(`${name}: стрелка есть и снимает один экран, с корня дальше не уходит`, () => {
      const stack = [hub, { name, args: {} }];
      assert.equal(M.nativeBackShown(stack.length, true), true);
      assert.equal(M.backAction(stack.length, false, true), 'pop');
      const after = stack.slice(0, -1);
      assert.equal(M.nativeBackShown(after.length, true), false);
      assert.equal(M.backAction(after.length, false, true), 'stay');
    });
  }
});

describe('повторный тап по вкладке', () => {
  it('с вложенного экрана — сброс на hub', () => {
    for (const name of NESTED) assert.deepEqual(M.retapAction([hub, { name, args: {} }], false), { closeSheet: false, reset: true });
  });
  it('со шторкой на вложенном экране — шторка закрыта и сброс', () => {
    assert.deepEqual(M.retapAction([hub, { name: 'table', args: {} }], true), { closeSheet: true, reset: true });
  });
  it('на корне без шторки — без перерисовки (только прокрутка)', () => {
    assert.deepEqual(M.retapAction([hub], false), { closeSheet: false, reset: false });
  });
  it('на корне со шторкой — шторка закрыта, без сброса', () => {
    assert.deepEqual(M.retapAction([hub], true), { closeSheet: true, reset: false });
  });
  it('kto-kogo.js слушает client-shell:retap только для вкладки kk и только во вкладке', () => {
    assert.match(js, /addEventListener\('client-shell:retap', function \(e\) \{\s*if \(e && e\.detail && e\.detail\.tab === 'kk' && inTab\(\)\) retap\(\);/);
    assert.match(js, /function retap\(\) \{[\s\S]*?if \(act\.reset\) return reset\('hub'\);[\s\S]*?window\.scrollTo\(0, 0\);/);
  });
});

describe('входы по ссылкам кладут экран поверх hub', () => {
  // boot: стек = [hub], затем go(entry) — «назад» с экрана из ссылки ведёт на hub.
  function landing(code, openId, tab) {
    const e = M.entryScreen(code, openId, tab);
    return e ? [hub, e] : [hub];
  }
  it('?join= → join поверх hub', () => {
    assert.deepEqual(landing('ABC123', null, null), [hub, { name: 'join', args: { code: 'ABC123' } }]);
  });
  it('?pick=…&side=… → match поверх hub', () => {
    assert.deepEqual(landing('', 77, null), [hub, { name: 'match', args: { id: 77 } }]);
  });
  it('?tab=table → table поверх hub', () => {
    assert.deepEqual(landing('', null, 'table'), [hub, { name: 'table', args: {} }]);
  });
  it('?from=result и ?src= → остаются на hub', () => {
    assert.deepEqual(landing('', null, null), [hub]);
  });
  it('?tab=matches из кнопки «Следующие матчи» → матчи поверх hub', () => {
    assert.deepEqual(landing('', null, 'matches'), [hub, { name: 'matches', args: {} }]);
  });
  it('приглашение важнее матча', () => {
    assert.equal(M.entryScreen('ABC', 5, 'table').name, 'join');
  });
  it('«назад» с каждого экрана из ссылки во вкладке ведёт на hub', () => {
    for (const st of [landing('A', null, null), landing('', 9, null), landing('', null, 'table')]) {
      assert.equal(M.backAction(st.length, false, true), 'pop');
      assert.equal(st.slice(0, -1)[0].name, 'hub');
    }
  });
  it('boot: hub в стеке до экрана из ссылки, ?month= — go поверх текущего', () => {
    const boot = js.slice(js.indexOf('function boot()'));
    assert.ok(boot.indexOf("state.stack = [{ name: 'hub', args: {} }]") < boot.indexOf('M.entryScreen('));
    assert.match(boot, /var entry = M\.entryScreen\(code, openId, params\.get\('tab'\)\);\s*if \(entry\) go\(entry\.name, entry\.args\);/);
    assert.match(boot, /go\('month', \{\}\);/);
  });
});

describe('проводка в kto-kogo.js', () => {
  it('режим вкладки — флаг season_ui оболочки', () => {
    assert.match(js, /shell\.uiFlags\(\)\.season_ui/);
  });
  it('стрелка Telegram ставится через MiniAppBack по nativeBackShown, на корне вкладки — clear()', () => {
    assert.match(js, /if \(M\.nativeBackShown\(state\.stack\.length, inTab\(\), !!state\.sheet\)\) window\.MiniAppBack\.set\(back\);\s*else window\.MiniAppBack\.clear\(\);/);
  });
  it('«назад» решает backAction; без вкладки корень по-прежнему уходит на client-home', () => {
    assert.match(js, /M\.backAction\(state\.stack\.length, !!state\.sheet, inTab\(\)\)/);
    assert.match(js, /if \(act === 'stay'\) return;\s*location\.href = '\/webapp\/client-home'/);
  });
});

describe('S2: бар оболочки на странице игры', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo.html'), 'utf8');
  const css = fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo.css'), 'utf8');
  const tokens = fs.readFileSync(path.join(__dirname, '../../static/shared/glide-tokens.css'), 'utf8');

  it('TASK-391: инлайн opt-in view-transition — иначе уход с Главной/Я обрывает первый тап', () => {
    assert.match(html, /id="kk-vt-opt-in"/);
    const style = /<style id="kk-vt-opt-in">([\s\S]*?)<\/style>/.exec(html);
    assert.ok(style, 'opt-in в <head> до внешних CSS');
    assert.match(style[1], /@view-transition\s*\{\s*navigation:\s*auto/);
    assert.ok(html.indexOf('id="kk-vt-opt-in"') < html.indexOf('telegram-web-app.js'));
  });

  it('тег оболочки подключается только за проверкой кэша флага', () => {
    const head = html.slice(0, html.indexOf('</head>'));
    const outside = html.replace(/<script id="kk-shell-gate">[\s\S]*?<\/script>/, '');
    assert.doesNotMatch(outside, /mini-app-client-shell/);
    assert.doesNotMatch(html, /^\s*<link rel="stylesheet" href="\/static\/webapp\/mini-app-client-shell\.css/m);
    const gate = head.indexOf('id="kk-shell-gate"');
    assert.ok(gate > 0, 'inline-гейт в <head>');
    assert.ok(gate > head.indexOf('telegram-web-app.js'), 'после SDK Telegram (нужен id пользователя)');
    assert.ok(gate > head.indexOf('glide-tokens.css') && gate < head.indexOf('kto-kogo.css'), 'css оболочки между токенами и css игры');
  });
  describe('гейт оболочки (inline-скрипт kto-kogo.html)', () => {
    const vm = require('node:vm');
    const src = /<script id="kk-shell-gate">([\s\S]*?)<\/script>/.exec(html)[1];
    function run({ user = { id: 42 }, stored, storageThrows = false } = {}) {
      const writes = [];
      const requests = [];
      const ls = { getItem(k) { if (storageThrows) throw new Error('denied'); return k === 'cw_ui_flags_v1' ? (stored === undefined ? null : stored) : null; } };
      const win = {
        Telegram: { WebApp: { initDataUnsafe: user ? { user } : {} } },
        fetch(u) { requests.push(String(u)); return Promise.resolve({}); },
        XMLHttpRequest: function () { this.open = (m, u) => requests.push(String(u)); this.send = () => {}; },
      };
      Object.defineProperty(win, 'localStorage', { get() { return ls; } });
      win.window = win;
      win.document = { write(h) { writes.push(h); } };
      vm.runInNewContext(src, win);
      return { writes, requests };
    }
    /* TASK-437: по умолчанию оболочка есть; нет её только при свежем явном false или вне Telegram. */
    const off = {
      'season_ui false': { stored: JSON.stringify({ u: '42', season_ui: false, bookings_tab: false, at: Date.now() }) },
      'нет пользователя Telegram': { user: null, stored: JSON.stringify({ u: '42', season_ui: true, at: Date.now() }) },
    };
    const unknown = {
      'нет кэша': {},
      'битый JSON': { stored: '{season_ui:false' },
      'чужой u с false': { stored: JSON.stringify({ u: '7', season_ui: false, at: Date.now() }) },
      'season_ui строкой': { stored: JSON.stringify({ u: '42', season_ui: 'false', at: Date.now() }) },
      'storage недоступен': { storageThrows: true },
    };
    for (const [name, opts] of Object.entries(unknown)) {
      it(`${name} → оболочка грузится (текущий бар), запросов из гейта нет`, () => {
        const r = run(opts);
        assert.equal(r.writes.length, 1);
        assert.deepEqual(r.requests, []);
      });
    }
    for (const [name, opts] of Object.entries(off)) {
      it(`${name} → оболочка не грузится, запросов к client/session и ui-flags нет`, () => {
        const r = run(opts);
        assert.deepEqual(r.writes, []);
        assert.deepEqual(r.requests, []);
      });
    }
    it('season_ui true со своим u → оболочка и её css пишутся синхронно (document.write), без запросов из гейта', () => {
      const r = run({ stored: JSON.stringify({ u: '42', season_ui: true, bookings_tab: false, at: Date.now() }) });
      assert.equal(r.writes.length, 1);
      assert.match(r.writes[0], /<script src="\/static\/webapp\/mini-app-client-shell\.js\?v=[^"]+"><\/script>$/);
      assert.match(r.writes[0], /^<link rel="stylesheet" href="\/static\/webapp\/mini-app-client-shell\.css\?v=[^"]+">/);
      assert.doesNotMatch(r.writes[0], /async|defer/);
      assert.deepEqual(r.requests, []);
    });
    it('версии ассетов в гейте совпадают с остальными тегами страницы', () => {
      const v = /kto-kogo\.css\?v=(\d+)/.exec(html)[1];
      for (const m of src.matchAll(/\?v=(\d+)/g)) assert.equal(m[1], v);
    });
  });
  it('без оболочки режима вкладки нет: inTab() требует window.ClientShell', () => {
    assert.match(js, /function inTab\(\) \{\s*var shell = window\.ClientShell;[\s\S]*?shell && typeof shell\.uiFlags === 'function' && shell\.uiFlags\(\)\.season_ui/);
  });
  it('без флага бар не монтируется: body без data-client-shell, тема клиента не подключена', () => {
    assert.doesNotMatch(html, /data-client-shell/);
    assert.doesNotMatch(html, /client-mini-app-theme\.js/);
  });
  it('классы вкладки ставятся только при флаге и пересчитываются при смене флага', () => {
    assert.match(js, /classList\.toggle\('kk-in-tab', on\)/);
    assert.match(js, /classList\.toggle\('tg-dark', on && b\.classList\.contains\('kk-dark'\)\)/);
    assert.match(js, /'client-shell:ui-flags', function \(\) \{ syncTabMode\(\); syncBack\(\); \}/);
  });
  it('правила вкладки в css — только за body.kk-in-tab; шторки выше бара (9000)', () => {
    const tail = css.slice(css.indexOf('/* ─── TASK-374: игра во вкладке')).replace(/\/\*[\s\S]*?\*\//g, '');
    for (const m of tail.matchAll(/^([^\s/*}][^{}]*)\{/gm)) assert.match(m[1], /^body\.kk-in-tab/, m[1]);
    const z = /body\.kk-in-tab \.kk-scrim \{ z-index: (\d+);/.exec(tail);
    assert.ok(z && Number(z[1]) > 9000);
    assert.match(css, /104px \+ env\(safe-area-inset-bottom, 0px\)/);
  });
  it('подпись неактивной вкладки на плашке бара — контраст ≥ 4.5 в обеих темах', () => {
    const pick = (block, name) => new RegExp('--' + name + ':\\s*(#[0-9a-fA-F]{6})').exec(block)[1];
    const darkStart = tokens.indexOf('body.tg-dark {');
    const light = tokens.slice(0, darkStart);
    const dark = tokens.slice(darkStart, tokens.indexOf('}', darkStart));
    const lum = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
      .reduce((s, c, i) => s + c * [0.2126, 0.7152, 0.0722][i], 0);
    const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
    assert.ok(ratio(pick(light, 'g-muted'), pick(light, 'g-surface')) >= 4.5, 'светлая');
    assert.ok(ratio(pick(dark, 'g-muted'), pick(dark, 'g-surface')) >= 4.5, 'тёмная');
  });
});
