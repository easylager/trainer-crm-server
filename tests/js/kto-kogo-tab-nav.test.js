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
    assert.match(js, /if \(M\.nativeBackShown\(state\.stack\.length, inTab\(\)\)\) window\.MiniAppBack\.set\(back\);\s*else window\.MiniAppBack\.clear\(\);/);
  });
  it('«назад» решает backAction; без вкладки корень по-прежнему уходит на client-home', () => {
    assert.match(js, /M\.backAction\(state\.stack\.length, !!state\.sheet, inTab\(\)\)/);
    assert.match(js, /if \(act === 'stay'\) return;\s*location\.href = '\/webapp\/client-home'/);
  });
});
