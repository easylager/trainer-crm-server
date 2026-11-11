/**
 * TASK-375: хелпер «назад» при season_ui.
 * Run: node --test tests/js/client-season-back*.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const B = require('../../static/webapp/client-season-back.js');

const KEY = 'cw_ui_flags_v1';
const store = (v) => ({ getItem: (k) => (k === KEY ? v : null) });
const throwing = { getItem() { throw new Error('denied'); } };
const tg = (id) => ({ initDataUnsafe: { user: { id } } });
const env = (value, uid = 42) => ({ localStorage: store(value), Telegram: { WebApp: tg(uid) } });
const on = JSON.stringify({ u: '42', season_ui: true });

describe('readCachedSeasonUi / isSeasonUi: состояния кэша', () => {
  it('флаг включён у того же пользователя', () => assert.equal(B.isSeasonUi(env(on)), true));
  it('u числом тоже совпадает', () =>
    assert.equal(B.isSeasonUi(env(JSON.stringify({ u: 42, season_ui: true }))), true));
  it('кэша нет', () => assert.equal(B.isSeasonUi(env(null)), false));
  it('битый JSON', () => assert.equal(B.isSeasonUi(env('{oops')), false));
  it('чужой u', () => assert.equal(B.isSeasonUi(env(JSON.stringify({ u: '7', season_ui: true }))), false));
  it('нет u в кэше', () => assert.equal(B.isSeasonUi(env(JSON.stringify({ season_ui: true }))), false));
  it('"true" строкой', () =>
    assert.equal(B.isSeasonUi(env(JSON.stringify({ u: '42', season_ui: 'true' }))), false));
  it('1 вместо true', () =>
    assert.equal(B.isSeasonUi(env(JSON.stringify({ u: '42', season_ui: 1 }))), false));
  it('season_ui false', () =>
    assert.equal(B.isSeasonUi(env(JSON.stringify({ u: '42', season_ui: false }))), false));
  it('JSON не объект', () => {
    assert.equal(B.isSeasonUi(env('null')), false);
    assert.equal(B.isSeasonUi(env('true')), false);
    assert.equal(B.isSeasonUi(env('"x"')), false);
  });
  it('storage бросает', () =>
    assert.equal(B.isSeasonUi({ localStorage: throwing, Telegram: { WebApp: tg(42) } }), false));
  it('доступ к localStorage бросает', () => {
    const e = { Telegram: { WebApp: tg(42) } };
    Object.defineProperty(e, 'localStorage', { get() { throw new Error('denied'); } });
    assert.equal(B.isSeasonUi(e), false);
  });
  it('нет Telegram / нет id пользователя', () => {
    assert.equal(B.isSeasonUi({ localStorage: store(on) }), false);
    assert.equal(B.isSeasonUi({ localStorage: store(on), Telegram: { WebApp: {} } }), false);
    assert.equal(B.isSeasonUi({ localStorage: store(on), Telegram: { WebApp: tg(null) } }), false);
  });
  it('пустое окружение', () => {
    assert.equal(B.isSeasonUi(undefined), false);
    assert.equal(B.isSeasonUi({}), false);
  });
});

describe('isSeasonUi: оболочка приоритетнее кэша', () => {
  const shell = (flags) => ({ uiFlags: () => flags });
  it('оболочка говорит true, кэша нет', () =>
    assert.equal(B.isSeasonUi({ ClientShell: shell({ season_ui: true }) }), true));
  it('оболочка говорит false, кэш true — верим оболочке', () =>
    assert.equal(B.isSeasonUi({ ...env(on), ClientShell: shell({ season_ui: false }) }), false));
  it('оболочка отдаёт "true" строкой — не включено', () =>
    assert.equal(B.isSeasonUi({ ClientShell: shell({ season_ui: 'true' }) }), false));
  it('оболочка бросает — падаем на кэш', () =>
    assert.equal(B.isSeasonUi({ ...env(on), ClientShell: { uiFlags() { throw new Error('x'); } } }), true));
});

describe('backAction: флаг × история', () => {
  it('флаг выкл, есть история → legacy', () => assert.equal(B.backAction(false, true), 'legacy'));
  it('флаг выкл, нет истории → legacy', () => assert.equal(B.backAction(false, false), 'legacy'));
  it('флаг вкл, есть история → history', () => assert.equal(B.backAction(true, true), 'history'));
  it('флаг вкл, нет истории → me', () => assert.equal(B.backAction(true, false), 'me'));
  it('не-true значения флага → legacy', () => {
    for (const v of [undefined, null, 'true', 1, {}]) assert.equal(B.backAction(v, true), 'legacy');
  });
});
