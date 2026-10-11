/**
 * TASK-232: открытка «Пойдёшь со мной на каток?» — вопрос, склонение, вердикты.
 * Run: node --test tests/js/zovi-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const M = require(path.resolve(__dirname, '../../static/shared/zovi-model.js'));

describe('вопрос открытки', () => {
  it('каток с именем: имя отдельно, чтобы покрасить', () => {
    assert.equal(M.questionText('Лера', 'public_skate'), 'Лера, пойдёшь со мной на каток?');
    assert.equal(M.questionParts('Лера', 'open_ice').name, 'Лера');
    assert.equal(M.questionText('Лера', 'open_ice'), 'Лера, пойдёшь со мной на каток?');
  });

  it('ОХМ — на хоккей', () => {
    assert.equal(M.questionText('Аня', 'hockey_practice'), 'Аня, пойдёшь со мной на хоккей?');
  });

  it('без имени (групповой чат) — с большой буквы, без имени', () => {
    assert.equal(M.questionText(null, 'public_skate'), 'Пойдёшь со мной на каток?');
    assert.equal(M.questionText('  ', 'hockey_practice'), 'Пойдёшь со мной на хоккей?');
    assert.equal(M.questionParts(null, 'public_skate').name, '');
  });
});

describe('decline', () => {
  it('Макс → Макса / Максу', () => {
    assert.equal(M.decline('Макс', 'gen'), 'Макса');
    assert.equal(M.decline('Макс', 'dat'), 'Максу');
  });
  it('Лера → Леры / Лере', () => {
    assert.equal(M.decline('Лера', 'gen'), 'Леры');
    assert.equal(M.decline('Лера', 'dat'), 'Лере');
  });
  it('Андрей → Андрея / Андрею', () => {
    assert.equal(M.decline('Андрей', 'gen'), 'Андрея');
    assert.equal(M.decline('Андрей', 'dat'), 'Андрею');
  });
  it('Оля, Маша — «и» после я и шипящих', () => {
    assert.equal(M.decline('Оля', 'gen'), 'Оли');
    assert.equal(M.decline('Маша', 'gen'), 'Маши');
  });
  it('пусто — «друга / другу»; латиница не трогается', () => {
    assert.equal(M.decline('', 'gen'), 'друга');
    assert.equal(M.decline(null, 'dat'), 'другу');
    assert.equal(M.decline('Alex', 'gen'), 'Alex');
  });
});

describe('вердикт', () => {
  it('0 попыток', () => {
    assert.equal(M.verdict(0, 0, false), 'Ответ «да» — с первой секунды. Кнопка «Нет» даже не проснулась.');
  });
  it('1–2 попытки', () => {
    assert.equal(M.verdict(1, 0, false), 'Пара секунд на раздумья. Для приличия.');
    assert.equal(M.verdict(2, 0, false), 'Пара секунд на раздумья. Для приличия.');
  });
  it('довели до падения', () => {
    assert.equal(M.verdict(3, 1, false), 'Кнопку «Нет» довели до падения. Беспощадно.');
    assert.equal(M.verdict(4, 1, false), 'Кнопку «Нет» довели до падения. Беспощадно.');
  });
  it('5 — сдалась', () => {
    assert.equal(M.verdict(5, 1, false), 'Кнопка «Нет» сдалась первой.');
  });
  it('без падения на 3–4', () => {
    assert.equal(M.verdict(3, 0, false), 'Долго думали. Но правильно.');
  });
  it('tricked важнее числа попыток', () => {
    assert.equal(M.verdict(2, 0, true), 'Нажали «Нет». Это была «Да» в маскировке. Засчитано.');
  });
});

describe('билет и дата', () => {
  it('кто на билете', () => {
    assert.deepEqual(M.ticketWho('Лера', 'Макс'), ['Лера', 'Макс']);
    assert.deepEqual(M.ticketWho(null, 'Макс'), ['Макс', 'компания']);
  });
  it('дата по local_date без сдвига часового пояса', () => {
    assert.equal(M.dayLabel('2026-10-17', 'short'), 'Сб, 17 окт');
    assert.equal(M.dayLabel('2026-10-17', 'ticket'), 'Сб, 17 октября');
    assert.equal(M.dayLabel('2026-10-17', 'long'), 'Суббота, 17 октября');
    assert.equal(M.dayLabel('', 'short'), '');
  });
  it('секунды сопротивления: хоть одна, если трогали', () => {
    assert.equal(M.resistSeconds(0), 0);
    assert.equal(M.resistSeconds(200), 1);
    assert.equal(M.resistSeconds(12400), 12);
  });
  it('тело ответа и адрес билета зажаты в пределы API', () => {
    assert.deepEqual(M.answerBody('a'.repeat(32), 99, 9e9, 9, 1), {
      device_token: 'a'.repeat(32), tries: 10, resist_ms: 600000, falls: 5, tricked: true
    });
    assert.equal(M.ticketQuery(3, 14, 1, false), '?t=3&s=14&f=1&k=0');
    assert.equal(M.ticketQuery(999, 9999, -1, true), '?t=10&s=600&f=0&k=1');
  });
});

describe('воронка (TASK-237): тело маячка и ?src=', () => {
  const model = M;

  it('маячок несёт вид и токен, акт зажат в 0..10', () => {
    assert.deepEqual(model.eventBody('invite_send_answer', 'tok'), { kind: 'invite_send_answer', device_token: 'tok' });
    assert.deepEqual(model.eventBody('invite_no_attempt', 'tok', 4), {
      kind: 'invite_no_attempt',
      device_token: 'tok',
      act: 4,
    });
    assert.equal(model.eventBody('invite_no_attempt', 'tok', 99).act, 10);
  });

  it('src берётся из адреса страницы только как короткое слово', () => {
    assert.equal(model.srcQuery('?src=sys'), '?src=sys');
    assert.equal(model.srcQuery('?a=1&src=copy&b=2'), '?src=copy');
    assert.equal(model.srcQuery('?src=<script>'), '');
    assert.equal(model.srcQuery(''), '');
    assert.equal(model.srcQuery(undefined), '');
  });
});
