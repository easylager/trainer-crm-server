/**
 * TASK-173: экран дня ноль на главной тренера — статические гварды обвязки.
 *
 * Главное, что здесь защищается, — узость состояния. Блок показывается строго тогда,
 * когда после онбординга не создано ни одного слота; у тренера, который расписание уже
 * заводил, главная обязана остаться прежней. Второе — одиночество вопроса: пока он на
 * экране, инбокс, чипы, Day Canvas, FAB и кнопка «поделиться» молчат, иначе экран снова
 * предлагает отправить ссылку, которая сейчас ведёт ученика в тупик.
 *
 * Run: node --test tests/js/hub-day-zero-wiring.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');

function read(name) {
  return fs.readFileSync(path.join(webapp, name), 'utf8');
}

const hubHtml = read('trainer-home.html');
const hubMain = read('trainer-home-main.js');
const hubCss = read('mini-app-trainer-hub.css');

function at(id) {
  const idx = hubHtml.indexOf('id="' + id + '"');
  assert.ok(idx > -1, 'в trainer-home.html нет id="' + id + '"');
  return idx;
}

/** Тело функции по имени: от `function name(` до следующей function того же отступа. */
function fnBody(name) {
  const start = hubMain.indexOf('function ' + name + '(');
  assert.ok(start > -1, 'в trainer-home-main.js нет function ' + name);
  const next = hubMain.indexOf('\n      function ', start + 1);
  return hubMain.slice(start, next > -1 ? next : hubMain.length);
}

describe('день ноль: разметка', () => {
  it('секция есть и стоит между пульсом недели и инбоксом', () => {
    const pulse = at('hubWeekPulse');
    const dayZero = at('hubDayZero');
    const inbox = at('hubActionInbox');
    assert.ok(pulse < dayZero, 'вопрос должен идти после полоски дней');
    assert.ok(dayZero < inbox, 'вопрос должен быть выше инбокса');
  });

  it('есть и состояние вопроса, и состояние ответа', () => {
    at('hubDayZeroAsk');
    at('hubDayZeroPresets');
    at('hubDayZeroDone');
    at('hubDayZeroDoneTitle');
    at('hubDayZeroShareBtn');
  });

  it('секция скрыта по умолчанию — иначе мелькнёт у всех при загрузке', () => {
    const section = hubHtml.slice(at('hubDayZero'), at('hubDayZero') + 220);
    assert.match(section, /hidden/);
  });
});

describe('день ноль: условие показа узкое', () => {
  const body = fnBody('shouldShowHubDayZero');

  it('только после завершённого онбординга', () => {
    assert.match(body, /onboarding_completed/);
  });

  it('молчит, если шаблон недели уже заведён', () => {
    assert.match(body, /weekly_template_count/);
  });

  it('молчит, если впереди есть слоты', () => {
    assert.match(body, /has_future_slots/);
    assert.match(body, /has_future_available_slots/);
  });

  it('молчит у тренера, у которого уже были записи', () => {
    assert.match(body, /has_real_booking/);
    assert.match(body, /has_any_booking/);
  });
});

describe('день ноль: один вопрос на экране', () => {
  it('Day Canvas молчит', () => {
    assert.match(fnBody('shouldShowHubDayCanvas'), /shouldShowHubDayZero\(\)/);
  });

  it('FAB «Записать» снят', () => {
    assert.match(fnBody('shouldShowHubBookFab'), /shouldShowHubDayZero\(\)/);
  });

  it('инбокс молчит — его строка «отправьте ссылку» сейчас навредит', () => {
    assert.match(fnBody('renderHubActionInbox'), /shouldShowHubDayZero\(\)/);
  });

  it('нижние чипы молчат', () => {
    assert.match(fnBody('renderHubStatusMarkers'), /shouldShowHubDayZero\(\)/);
  });

  it('CSS снимает конкурирующие блоки по классу на body', () => {
    const idx = hubCss.indexOf('body.hub-day-zero-active');
    assert.ok(idx > -1, 'нет правила body.hub-day-zero-active');
    const rule = hubCss.slice(idx, idx + 600);
    for (const sel of [
      '#hubStatusMarkers',
      '#hubSummaryHints',
      '#hubActionInbox',
      '#hubDayCanvas',
      '.hub-book-fab',
      '#hubShareBookingLinkBtn',
    ]) {
      assert.ok(rule.includes(sel), 'body.hub-day-zero-active не снимает ' + sel);
    }
  });
});

describe('день ноль: ответ принимается на месте', () => {
  it('пресет уходит на свою ручку, а не в онбординг', () => {
    const body = fnBody('applyHubDayZeroPreset');
    assert.match(body, /postJsonTrainer\('\/trainer\/hub\/first-hours'/);
    assert.ok(
      !body.includes('quick-setup'),
      'день ноль не должен переигрывать онбординг — он спрашивает только про время'
    );
  });

  it('«своё время» ведёт в расписание, а не на ручку', () => {
    const body = fnBody('applyHubDayZeroPreset');
    assert.match(body, /if \(!presetKey\)/);
    assert.match(body, /schedule-editor/);
  });

  it('после ответа чеклист перечитывается — остальной хаб узнаёт о слотах сразу', () => {
    assert.match(fnBody('applyHubDayZeroPreset'), /loadOnboardingChecklist\(\)/);
  });

  it('ошибка пресета уводит в расписание, а не повторяет ту же кнопку', () => {
    const body = fnBody('applyHubDayZeroPreset');
    const tail = body.slice(body.indexOf('.catch('));
    assert.match(tail, /schedule-editor/);
  });

  it('отрисовка вызывается из общего пайплайна хаба', () => {
    assert.match(fnBody('syncHubDayCanvas'), /syncHubDayZero\(\)/);
  });
});
