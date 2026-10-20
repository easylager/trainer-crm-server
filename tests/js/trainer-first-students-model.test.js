'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const M = require(path.resolve(__dirname, '../../static/webapp/trainer-first-students-model.js'));

describe('«Первые три ученика»: вставка списка из заметок', () => {
  it('отделяет имя от телефона в разных записях номера', () => {
    assert.deepEqual(M.parseStudentLine('Маша Ковалёва +375 29 111-22-33'), {
      first_name: 'Маша',
      last_name: 'Ковалёва',
      phone: '+375291112233',
    });
    assert.deepEqual(M.parseStudentLine('Лиза 29 444 55 66'), { first_name: 'Лиза', last_name: '', phone: '294445566' });
    assert.deepEqual(M.parseStudentLine('Даня'), { first_name: 'Даня', last_name: '', phone: '' });
  });

  it('снимает нумерацию и разделители заметок', () => {
    assert.deepEqual(M.parseStudentLine('1. Петя — 8 029 765 43 21'), {
      first_name: 'Петя',
      last_name: '',
      phone: '80297654321',
    });
    assert.deepEqual(M.parseStudentLine('• Оля, Сидорова'), { first_name: 'Оля', last_name: 'Сидорова', phone: '' });
  });

  it('время и день занятия не попадают ни в имя, ни в телефон', () => {
    assert.deepEqual(M.parseStudentLine('Лиза пн 19:00'), { first_name: 'Лиза', last_name: '', phone: '' });
    assert.deepEqual(M.parseStudentLine('Гриша Петров, ср 17.30'), { first_name: 'Гриша', last_name: 'Петров', phone: '' });
  });

  it('пустые строки, одни цифры и дубли пропускаются', () => {
    const rows = M.parseStudentList('Маша 291112233\n\n12345\nМаша 291112233\nДаня\n');
    assert.deepEqual(
      rows.map((r) => r.first_name),
      ['Маша', 'Даня']
    );
  });
});

describe('«Первые три ученика»: места и подписи', () => {
  const state = (count, names) => ({
    goal: 3,
    count,
    students: names.map((n) => ({ name: n, initials: n[0] })),
  });

  it('места: сначала ученики, потом пустые до трёх', () => {
    assert.deepEqual(M.seats(state(1, ['Маша'])), [
      { filled: true, initials: 'М', name: 'Маша' },
      { filled: false },
      { filled: false },
    ]);
    assert.equal(M.seats(state(5, ['А', 'Б', 'В'])).length, 3);
  });

  it('заголовок листа и кнопка считают учеников', () => {
    assert.equal(M.sheetTitle(state(0, [])), 'Ученик 1 из 3');
    assert.equal(M.sheetTitle(state(2, ['А', 'Б'])), 'Ученик 3 из 3');
    assert.equal(M.sheetTitle(state(3, ['А', 'Б', 'В'])), 'Ещё ученик');
    assert.deepEqual(
      [0, 1, 2, 3].map((n) => M.addButtonLabel({ count: n })),
      ['Добавить ученика', 'Добавить второго', 'Добавить третьего', 'Добавить ещё']
    );
    assert.equal(M.remaining(state(1, ['А'])), 2);
  });
});

describe('«Первые три ученика»: финал не обещает лишнего', () => {
  const st = (rows, count) => ({ goal: 3, count: count || rows.length, students: rows });

  it('«на неделе» — только когда записаны все', () => {
    assert.equal(M.doneKicker(st([{ next_label: 'завтра 18:00' }, { next_label: 'чт 17:00' }, { next_label: 'пн 17:00' }])), '3 ученика на неделе');
    assert.equal(M.doneKicker(st([{ next_label: 'завтра 18:00' }, {}, {}])), '3 ученика в приложении');
    assert.equal(M.doneKicker(st([{}, {}, {}], 5)), '5 учеников в приложении');
  });

  it('ссылка ученику без записи не говорит, что его записали', () => {
    const none = M.inviteMessage({ name: 'Лиза' });
    assert.ok(!/запис/i.test(none), none);
    const booked = M.inviteMessage({ name: 'Маша', next_label: 'завтра 18:00' });
    assert.ok(booked.includes('завтра 18:00'));
    assert.ok(!/записал/i.test(booked), 'без рода тренера');
  });
});
