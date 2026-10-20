/**
 * TASK-305 (AC-1, AC-2): hub bootstrap may start before /client/profiles when a profile is stored.
 * Run: node --test tests/js/hub-bootstrap-parallel.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');

const modelPath = path.resolve(__dirname, '../../static/webapp/hub-bootstrap-parallel-model.js');

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

describe('HubBootstrapParallel', () => {
  const m = loadModel();

  it('без сохранённого id — ждём профили, bootstrap после', () => {
    assert.equal(m.shouldStartBootstrapParallel(null), false);
    assert.equal(m.bootstrapFetchPlan(false, null, 42), 'after_profiles');
  });

  it('сохранённый id валиден — параллельный старт, один bootstrap', () => {
    assert.equal(m.shouldStartBootstrapParallel(7), true);
    assert.equal(m.bootstrapFetchPlan(true, 7, 7), 'use_early');
  });

  it('сохранённый id сброшен — параллельный старт, затем ровно один refetch', () => {
    assert.equal(m.bootstrapFetchPlan(true, 99, 12), 'refetch');
    assert.equal(m.bootstrapFetchPlan(true, 99, 12), 'refetch');
  });
});

describe('профиль по умолчанию с прошлого открытия', () => {
  const fs = require('fs');
  const webapp = path.resolve(__dirname, '../../static/webapp');
  const switcher = fs.readFileSync(path.join(webapp, 'client-profile-switcher.js'), 'utf8');
  const main = fs.readFileSync(path.join(webapp, 'client-home-main.js'), 'utf8');

  it('запоминается после профилей и только для того же Telegram-аккаунта', () => {
    assert.match(switcher, /writeCachedDefaultId\(state\.defaultProfileId\)/);
    assert.match(switcher, /v\.u === uid/);
  });

  it('главная шлёт ранний bootstrap с этой догадкой, если выбранного профиля нет', () => {
    assert.match(main, /storedProfileId == null && switcher && typeof switcher\.getCachedDefaultProfileId === 'function'/);
    assert.match(main, /fetchHubBootstrap\(guessDefault \? storedProfileId : null\)/);
    assert.match(main, /'X-Profile-Id': String\(guessProfileId\)/);
  });
});
