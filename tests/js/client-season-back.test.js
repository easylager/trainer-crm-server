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
const on = JSON.stringify({ u: '42', season_ui: true, at: Date.now() });

describe('readCachedSeasonUi / isSeasonUi: состояния кэша', () => {
  it('флаг включён у того же пользователя', () => assert.equal(B.isSeasonUi(env(on)), true));
  it('u числом тоже совпадает', () =>
    assert.equal(B.isSeasonUi(env(JSON.stringify({ u: 42, season_ui: true, at: Date.now() }))), true));
  /* TASK-437: по умолчанию включено (на проде season_ui у всех); выключает только свежий явный false. */
  it('кэша нет → включено', () => assert.equal(B.isSeasonUi(env(null)), true));
  it('битый JSON → включено', () => assert.equal(B.isSeasonUi(env('{oops')), true));
  it('чужой u → включено', () => assert.equal(B.isSeasonUi(env(JSON.stringify({ u: '7', season_ui: false, at: Date.now() }))), true));
  it('нет u в кэше → включено', () => assert.equal(B.isSeasonUi(env(JSON.stringify({ season_ui: false }))), true));
  it('"true" строкой', () =>
    assert.equal(B.isSeasonUi(env(JSON.stringify({ u: '42', season_ui: 'true', at: Date.now() }))), true));
  it('"false" строкой — не явный false, включено', () =>
    assert.equal(B.isSeasonUi(env(JSON.stringify({ u: '42', season_ui: 'false', at: Date.now() }))), true));
  it('season_ui false свежий — выключено', () =>
    assert.equal(B.isSeasonUi(env(JSON.stringify({ u: '42', season_ui: false, at: Date.now() }))), false));
  it('season_ui false старше суток или без at — включено', () => {
    assert.equal(B.isSeasonUi(env(JSON.stringify({ u: '42', season_ui: false, at: Date.now() - 86400000 - 60000 }))), true);
    assert.equal(B.isSeasonUi(env(JSON.stringify({ u: '42', season_ui: false }))), true);
  });
  it('JSON не объект', () => {
    assert.equal(B.isSeasonUi(env('null')), true);
    assert.equal(B.isSeasonUi(env('true')), true);
    assert.equal(B.isSeasonUi(env('"x"')), true);
  });
  it('storage бросает', () =>
    assert.equal(B.isSeasonUi({ localStorage: throwing, Telegram: { WebApp: tg(42) } }), true));
  it('доступ к localStorage бросает', () => {
    const e = { Telegram: { WebApp: tg(42) } };
    Object.defineProperty(e, 'localStorage', { get() { throw new Error('denied'); } });
    assert.equal(B.isSeasonUi(e), true);
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
