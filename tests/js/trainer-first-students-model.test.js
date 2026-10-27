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
    /* TASK-313: без «1 из 3» — звучало как лимит на трёх учеников. */
    assert.equal(M.sheetTitle(state(0, [])), 'Новый ученик');
    assert.equal(M.sheetTitle(state(3, ['А', 'Б', 'В'])), 'Новый ученик');
    assert.equal(M.addedKicker({ count: 1 }), 'Уже 1 ученик');
    assert.equal(M.addedKicker({ count: 2 }), 'Уже 2 ученика');
    assert.deepEqual(
      [0, 1, 2, 3].map((n) => M.addButtonLabel({ count: n })),
      ['Добавить ученика', 'Добавить ещё', 'Добавить ещё', 'Добавить ещё']
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

describe('«Первые три ученика»: услуга, ошибки, обещания', () => {
  const state = {
    services: [{ service_id: 5, name: 'Индивидуально' }, { service_id: 9, name: 'Группа' }],
    options: [{ slot_id: 1, service_id: 9 }, { slot_id: 2, service_id: null }, { slot_id: 3, service_id: 77 }],
  };

  it('услуга окна, иначе первая очная', () => {
    assert.equal(M.defaultServiceId(state, 1), 9);
    assert.equal(M.defaultServiceId(state, 2), 5);
    assert.equal(M.defaultServiceId(state, 3), 5, 'услуги окна нет в профиле — не подставляем чужую');
    assert.equal(M.defaultServiceId({ services: [] }, 1), null);
  });

  it('422 по телефону — человеческим текстом, а не «Unprocessable Entity»', () => {
    const err = Object.assign(new Error('Unprocessable Entity'), {
      detail: [{ loc: ['body', 'phone'], msg: 'Value error, Номер должен начинаться с +375 или +7' }],
    });
    assert.equal(M.errorText(err), 'Номер должен начинаться с +375 или +7');
    assert.equal(M.errorText(new Error('Unprocessable Entity')), 'Не получилось сохранить. Попробуйте ещё раз.');
    assert.equal(M.errorText(new Error('Слот уже занят')), 'Слот уже занят');
  });

  it('утреннюю сводку обещаем только с записью; без подписки — не обещаем окна', () => {
    assert.ok(!M.doneWorks({ students: [{}] }).some((w) => /утром/i.test(w)));
    assert.ok(M.doneWorks({ students: [{ next_label: 'завтра 18:00' }] })[0].startsWith('Утром'));
    assert.ok(/подпиской/.test(M.cardLead({ can_book: false })));
    assert.ok(!/окна/.test(M.cardLead({ can_book: false })));
    assert.ok(/подпиской/.test(M.slotFieldLabel({ can_book: false })));
  });

  it('пример номера и подсказка ошибки зависят от страны тренера', () => {
    assert.equal(M.phoneExample('RUB'), '+7 912 345-67-89');
    assert.equal(M.phoneExample('BYN'), '+375 29 123-45-67');
    const err = { detail: [{ loc: ['body', 'phone'], msg: '' }] };
    assert.match(M.errorText(err, 'RUB'), /\+7 912/);
    assert.match(M.errorText(err), /\+375 29/);
  });

  it('телефон с готовым кодом страны: только код — номера нет, вставка целиком не дублирует код', () => {
    assert.equal(M.phonePrefix('RUB'), '+7 ');
    assert.equal(M.phonePrefix('BYN'), '+375 ');
    assert.equal(M.phoneForSave('+7 ', 'RUB'), null);
    assert.equal(M.phoneForSave('+7 912 345-67-89', 'RUB'), '+79123456789');
    assert.equal(M.phoneForSave('+7 8 912 345-67-89', 'RUB'), '+79123456789');
    assert.equal(M.phoneForSave('+7 9123456789', 'RUB'), '+79123456789');
    assert.equal(M.phoneForSave('+375 ', 'BYN'), null);
    assert.equal(M.phoneForSave('+375 29 123-45-67', 'BYN'), '+375291234567');
    assert.equal(M.phoneForSave('+375 375291234567', 'BYN'), '+375291234567');
  });

  it('маска телефона не пускает лишние цифры и не дублирует код', () => {
    assert.equal(M.phoneMask('+7 ', 'RUB'), '+7 ');
    assert.equal(M.phoneMask('+7 9123456789999999', 'RUB'), '+7 912 345-67-89');
    assert.equal(M.phoneMask('89123456789', 'RUB'), '+7 912 345-67-89');
    assert.equal(M.phoneMask('+7 91', 'RUB'), '+7 91');
    assert.equal(M.phoneMask('+375 291234567890', 'BYN'), '+375 29 123-45-67');
    assert.equal(M.phoneMask('+375 375291234567', 'BYN'), '+375 29 123-45-67');
    assert.equal(M.phoneForSave(M.phoneMask('+7 912 345-67-89', 'RUB'), 'RUB'), '+79123456789');
  });
});
