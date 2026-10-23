/**
 * Вкладка «Профиль» и экран «Услуги и цены» (TASK-313).
 *
 * Run: node --test "tests/js/*.test.js"
 *
 * Тренер не находил профиль в шторке «Ещё» и не понимал, где ставить цены. Проверяем то, на чём
 * держится новая навигация: пятая вкладка ведёт на экран-оглавление, каждый раздел открывается
 * отдельным экраном и возвращается обратно, а цены сохраняются, не теряя остального у услуги.
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');
const read = (name) => fs.readFileSync(path.join(webapp, name), 'utf8');

describe('бар: пятая вкладка — «Профиль»', () => {
  const shell = read('mini-app-trainer-shell.js');

  it('ведёт на trainer-account, а не открывает шторку', () => {
    assert.match(shell, /id: 'more',\s+label: 'Профиль',\s+path: 'trainer-account'/);
    assert.doesNotMatch(shell, /if \(tab\.id === 'more'\) \{\s*toggleMoreSheet\(\);/);
  });

  it('экраны профиля и цен подсвечивают эту вкладку', () => {
    assert.match(shell, /MORE_ROUTE_KEYS = \[\s*'trainer-account',\s*'trainer-prices',/);
  });

  it('отдаёт экрану бейджи разделов и пункт «Студия»', () => {
    assert.match(shell, /getMenuState: getMenuState/);
    assert.match(shell, /'trainer-shell:menu'/);
  });
});

describe('экран «Профиль»', () => {
  const js = read('trainer-account-main.js');
  const html = read('trainer-account.html');

  it('живёт под баром', () => {
    assert.match(html, /<body[^>]*data-trainer-shell="tabs"/);
  });

  it('все пункты бывшей шторки «Ещё» достижимы', () => {
    for (const route of ['trainer-pass-products', 'trainer-subscription', 'trainer-requests',
      'trainer-stats', 'trainer-groups', 'trainer-referral', 'trainer-faq']) {
      assert.ok(js.includes(`'${route}'`), `нет пути ${route}`);
    }
    assert.ok(js.includes("go('trainer-profile')"), 'вся анкета — запасной путь');
  });

  it('разделы анкеты возвращаются в профиль', () => {
    for (const task of ['basics', 'about', 'experience', 'contacts', 'booking', 'notifications']) {
      assert.match(js, new RegExp(`trainer-profile\\?task=${task}' \\+ BACK`));
    }
    assert.match(js, /arenas: 'trainer-arenas'/);
    assert.match(js, /var BACK = '&return=trainer-account'/);
  });

  it('«Странице не хватает» — только реально пустое', () => {
    assert.match(js, /anyServiceUnpriced\(\)/);
    assert.match(js, /descriptionFilled\(\)/);
    assert.match(js, /box\.hidden = !items\.length/);
  });
});

describe('анкета: разделы профиля — экраны с одной задачей', () => {
  const js = read('trainer-profile-main.js');

  it('у каждого раздела свой фокус-экран', () => {
    for (const task of ['basics', 'about', 'arenas', 'experience', 'contacts', 'booking', 'notifications']) {
      assert.match(js, new RegExp(`\\b${task}: \\{ rail: \\[`), `нет задачи ${task}`);
    }
  });

  it('экран может собрать два блока анкеты', () => {
    assert.match(js, /containerIds: \['obSessionDurationWrap', 'obMinHoursWrap', 'groupClassesField'\]/);
    assert.match(js, /containerIds: \['pushNotifyField', 'digestSettingsField'\]/);
    assert.ok(read('trainer-profile.html').includes('id="pushNotifyField"'));
  });

  it('возврат в профиль без обещания «откроется главная»', () => {
    assert.match(js, /returnTo === 'trainer-catalog' \|\| returnTo === 'trainer-account'/);
    assert.match(js, /return webappPageUrl\('trainer-account'\)/);
  });

  it('старые ссылки ?task=prices ведут на новый экран цен', () => {
    assert.match(js, /sp0\.get\('task'\) !== 'prices'/);
    assert.match(js, /webappPageUrl\('trainer-prices' \+ q0\)/);
  });
});

describe('экран «Услуги и цены»', () => {
  const js = read('trainer-prices-main.js');

  it('сохраняет только услуги, не трогая остальную анкету', () => {
    assert.match(js, /request\('PATCH', '\/trainer\/profile', \{ services: payload\(\) \}\)/);
  });

  it('услуга уходит со всем, что у неё было', () => {
    for (const k of ['description', 'client_notice', 'group_price_byn', 'ui_accent', 'is_online']) {
      assert.ok(js.includes(k), `теряется ${k}`);
    }
  });

  it('тариф уходит, только если у него есть цена', () => {
    assert.match(js, /if \(p != null && !isNaN\(p\)\) tiers\.push/);
  });

  it('«Взрослый» и «Детский» сразу, остальные — под «Ещё тарифы»', () => {
    assert.match(js, /MAIN_TIERS = \[\s*\{ code: 'adult'[^\]]*\{ code: 'child'/);
    assert.match(js, /EXTRA_TIERS = \[\s*\{ code: 'two_children'/);
  });

  it('онбординг ведёт сюда и ждёт тренера назад', () => {
    assert.ok(read('trainer-onboarding-main.js').includes("pageUrl('trainer-prices?from=onboarding')"));
    assert.match(js, /trainer-onboarding\?done=1/);
  });
});

describe('экран «Где занимаюсь»', () => {
  const js = read('trainer-arenas-main.js');
  const html = read('trainer-arenas.html');

  it('тип места — только «Каток» или «Зал»', () => {
    assert.match(js, /venue_type: state\.newVenue/);
    assert.ok(html.includes('data-venue="ice"') && html.includes('data-venue="gym"'));
    assert.doesNotMatch(html, /Бассейн|Хореограф|на улице/);
  });

  it('новый каток — шторка с двумя полями, дубль — предложение выбрать существующий', () => {
    assert.ok(html.includes('id="arNewName"') && html.includes('id="arNewAddress"'));
    assert.match(js, /mode: 'create'/);
    assert.match(js, /res\.status === 'duplicate_warning'/);
    assert.match(js, /submitNew\(true\)/);
  });

  it('сохраняет катки, основной и город одним PATCH', () => {
    assert.match(js, /var body = \{ arena_ids: state\.picked\.slice\(\) \}/);
    assert.match(js, /body\.primary_arena_id = /);
    assert.match(js, /body\.profile = \{ city_id: state\.cityId \}/);
  });

  it('каток с записями убрать нельзя — объясняем почему', () => {
    assert.match(js, /if \(state\.locked\[id\]\)/);
  });

  it('вкладка «Профиль» подсвечена и на этом экране', () => {
    assert.match(read('mini-app-trainer-shell.js'), /'trainer-arenas',/);
  });

  it('город переехал сюда: в «Фото и имя» его нет', () => {
    assert.match(read('trainer-profile-main.js'), /if \(task === 'basics'\) \{[\s\S]{0,160}cityWrap\.hidden = true/);
  });
});
