'use strict';
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const F = require('../../static/webapp/trainer-format.js');

const NB = ' ';

describe('TrainerFormat', () => {
  it('телефон: Беларусь и Россия по маске, остальное как есть', () => {
    assert.equal(F.phone('375293334455'), '+375 29 333-44-55');
    assert.equal(F.phone('+375 (29) 333 44 55'), '+375 29 333-44-55');
    assert.equal(F.phone('89991234567'), '+7 999 123-45-67');
    assert.equal(F.phone('+44 20 7946 0958'), '+44 20 7946 0958');
    assert.equal(F.phone(null), '');
  });

  it('деньги: копейки только когда есть, рубль знаком', () => {
    assert.equal(F.money(45, 'BYN'), '45' + NB + 'BYN');
    assert.equal(F.money(40.5, 'BYN'), '40,50' + NB + 'BYN');
    assert.equal(F.money(1500, 'RUB'), '1' + NB + '500' + NB + 'руб.');
    assert.equal(F.money('abc'), '');
  });

  it('дата: сегодня, завтра, вчера, иначе «пт, 23 окт»', () => {
    const now = new Date(2026, 9, 22);
    assert.equal(F.date('2026-10-22', { now }), 'сегодня');
    assert.equal(F.date('2026-10-23', { now }), 'завтра');
    assert.equal(F.date('2026-10-21', { now }), 'вчера');
    assert.equal(F.date('2026-10-30', { now }), 'пт, 30' + NB + 'окт');
  });

  it('срок и время', () => {
    assert.equal(F.dateLong('2027-11-26'), '26' + NB + 'ноября 2027');
    assert.equal(F.time('09:00:00'), '9:00');
    assert.equal(F.time('18:15'), '18:15');
  });

  it('склонение', () => {
    assert.equal(F.plural(1, 'запись', 'записи', 'записей'), 'запись');
    assert.equal(F.plural(3, 'запись', 'записи', 'записей'), 'записи');
    assert.equal(F.plural(12, 'запись', 'записи', 'записей'), 'записей');
    assert.equal(F.plural(21, 'запись', 'записи', 'записей'), 'запись');
  });
});
