/**
 * TASK-432: право капитана — коллекция, цифры вещей, подписи в вечере и снаружи лиги.
 *
 * Run: TZ=UTC node --test tests/js/kto-kogo-kit.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Kit = require('../../static/webapp/kto-kogo-kit.js');

const NBSP = '\u00a0';
const M = (home_score, away_score) => ({ status: 'final', home_score, away_score });
const EV = { day: '2026-11-18', matches: [M(3, 1), M(2, 2), M(1, 4), M(0, 1)] };
const marks = (...states) => states.map((state) => ({ state }));

describe('коллекция', () => {
  it('10 вещей — те же ключи и порядок, что у сервера; у каждой есть рисунок', () => {
    const py = fs.readFileSync(path.join(__dirname, '../../src/application/hockey_league_captain.py'), 'utf8');
    const server = /OUTFITS = \(([^)]*)\)/.exec(py)[1].match(/"(\w+)"/g).map((x) => x.slice(1, -1));
    assert.deepEqual(Kit.OUTFITS.map((o) => o.id), server);
    for (const o of Kit.OUTFITS) {
      assert.ok(Kit.SHAPES[o.id] && Kit.SHAPES[o.id].length, o.id);
      assert.ok(o.name && o.full && o.joke, o.id);
    }
    assert.ok(Kit.SHAPES.cap, 'кепка дня рисуется как вещь');
    assert.equal(Kit.outfit('scarf'), null, 'шарф соперника не выдаётся');
  });
  it('слова: капитан, экипировка; без «наряда», «звезды», «скина» и азартных слов', () => {
    const src = fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo-kit.js'), 'utf8');
    const strings = [...src.matchAll(/'((?:[^'\\\n]|\\.){3,})'/g)].map((m) => m[1]);
    assert.deepEqual(strings.filter((s) => /наряд|звезд|скин|прогноз|ставк/i.test(s)), []);
  });
});

describe('цифры на вещах', () => {
  it('плакат — угаданные из всех матчей вечера; табло — счёт первого промаха, иначе первого матча без хода', () => {
    assert.deepEqual(Kit.numbers({ hits: 0, marks: marks('none', 'miss', 'miss', 'none') }, EV), { stat: 'ЗА 0 ИЗ 4', score: '2:2' });
    assert.deepEqual(Kit.numbers({ hits: 3, marks: marks('hit', 'hit', 'none', 'hit') }, EV), { stat: 'ЗА 3 ИЗ 4', score: '1:4' });
    assert.deepEqual(Kit.numbers({ hits: 4, marks: marks('hit', 'hit', 'hit', 'hit') }, EV), { stat: 'ЗА 4 ИЗ 4', score: '0:1' });
    assert.equal(Kit.fill('{stat}', { stat: 'ЗА 1 ИЗ 2' }), 'ЗА 1 ИЗ 2');
    assert.equal(Kit.fill('{score}', null), '');
    assert.equal(Kit.fill('РЕМОНТ', null), 'РЕМОНТ');
  });
});

describe('право капитана в вечере', () => {
  const items = [
    { pid: 'me', display_name: 'Макс', is_me: true, hits: 4, captain: true },
    { pid: 'an', display_name: 'Андрей', hits: 2 },
    { pid: 'ol', display_name: 'Олег', hits: 0, cap: true },
  ];
  it('по умолчанию — тот, кто в кепке; подписи «себе», «в кепке», «2 из 4»', () => {
    assert.equal(Kit.defaultTarget(items), 'ol');
    assert.equal(Kit.defaultTarget([items[0], items[1]]), 'an');
    assert.equal(Kit.defaultTarget([items[0]]), 'me');
    assert.deepEqual(items.map((r) => Kit.targetSub(r, EV)), ['себе', '2 из 4', 'в кепке']);
    assert.equal(Kit.targetLine(items[2], EV), '0 из 4 · кепка дня');
    assert.equal(Kit.targetLine(items[0], EV), '4 из 4 · капитан');
  });
  it('после выдачи: «Олег в экипировке» / «Ты в экипировке»', () => {
    assert.deepEqual(Kit.givenLine(items[2], 'bucket'), { title: 'Олег в экипировке', text: 'Ведро вместо шлема — до следующего вечера. Видят все в «КТО КОГО».' });
    assert.equal(Kit.givenLine(items[0], 'foil').title, 'Ты в экипировке');
  });
  it('подпись под строкой: моя выдача, выдача другого капитана, прошлый вечер; мне — плашка, без строки', () => {
    const mine = { captain: { award: { to: 'ol', item: 'bucket', from: 'Макс', from_me: true, current: true } } };
    assert.equal(Kit.headNote({ pid: 'ol', head: { item: 'bucket' } }, mine), 'Экипировка от тебя — до следующего вечера');
    const self = { captain: { award: { to: 'me', item: 'foil', from_me: true, current: true } } };
    assert.equal(Kit.headNote({ pid: 'me', is_me: true, head: { item: 'foil' } }, self), 'Твой выбор — до следующего вечера');
    const theirs = { captain: { award: { to: 'ol', item: 'wanted', from: 'Андрей', from_me: false, current: true } } };
    assert.equal(Kit.headNote({ pid: 'ol', head: { item: 'wanted' } }, theirs), 'Плакат «Разыскивается» — выдаёт Андрей');
    assert.equal(Kit.headNote({ pid: 'ol', is_me: true, head: { item: 'wanted' } }, theirs), '');
    const old = { captain: { award: Object.assign({}, theirs.captain.award, { current: false }) } };
    assert.equal(Kit.headNote({ pid: 'ol', head: { item: 'wanted' } }, old), 'Плакат «Разыскивается» · от капитана вечера');
    assert.equal(Kit.headNote({ pid: 'an', head: { item: 'cap' } }, theirs), '', 'кепка — без подписи');
  });
  it('плашка получателю — только мне, только от другого капитана и пока вечер действует', () => {
    const ev = { items: [{ pid: 'me', is_me: true }], captain: { award: { to: 'me', item: 'wanted', from: 'Андрей', from_me: false, current: true } } };
    assert.deepEqual(Kit.receivedBanner(ev), {
      title: 'Андрей выдаёт тебе экипировку',
      text: 'Плакат «Разыскивается» — до следующего вечера. Видят все в «КТО КОГО», и в общей таблице тоже.',
      tail: 'Стань капитаном — и выдавать будешь ты.',
    });
    assert.equal(Kit.receivedBanner(Object.assign({}, ev, { captain: { award: Object.assign({}, ev.captain.award, { current: false }) } })), null);
    assert.equal(Kit.receivedBanner(Object.assign({}, ev, { captain: { award: Object.assign({}, ev.captain.award, { to: 'an' }) } })), null);
    assert.equal(Kit.receivedBanner({ items: [], captain: { award: null } }), null);
  });
});

describe('снаружи лиги', () => {
  it('строка общей таблицы: последняя выданная и сколько ещё; имени лиги нет', () => {
    assert.equal(Kit.outsideNote({ item: 'bucket', items: [{ item: 'bucket', n: 1 }] }), 'Ведро вместо шлема · от капитана лиги');
    assert.equal(Kit.outsideNote({ item: 'wanted', items: [{ item: 'wanted', n: 1 }, { item: 'bucket', n: 1 }] }), 'Плакат «Разыскивается» и ещё 1 · от капитанов лиг');
    assert.equal(Kit.outsideNote(null), '');
  });
  it('список по тапу: одна вещь из двух лиг — «от двух капитанов лиг», без множителей', () => {
    const list = Kit.outsideList({ items: [{ item: 'bucket', n: 2, stat: 'ЗА 0 ИЗ 4', score: '1:2' }, { item: 'foil', n: 1 }] });
    assert.deepEqual(list.map((x) => [x.full, x.from]), [['Ведро вместо шлема', 'от двух' + NBSP + 'капитанов лиг'], ['Корона из фольги', 'от капитана лиги']]);
    assert.equal(list[0].stat, 'ЗА 0 ИЗ 4');
    assert.ok(!JSON.stringify(list).includes('×'));
  });
  it('диктору: что на голове', () => {
    assert.equal(Kit.headSay({ item: 'cap' }), 'в кепке дня');
    assert.equal(Kit.headSay({ item: 'bag' }), 'экипировка: пакет на голову');
    assert.equal(Kit.headSay(null), '');
  });
});

describe('правила «Капитан»', () => {
  it('пять пунктов и вся коллекция бесплатно', () => {
    const r = Kit.captainRules();
    assert.equal(r.items.length, 5);
    assert.match(r.collectionNote, /^Все 10 вещей — у каждого капитана, бесплатно/);
  });
});

describe('рисунки вещей — одни на Mini App и карточку для чата', () => {
  it('src/application/kk_kit_shapes.json совпадает с SHAPES из kto-kogo-kit.js', () => {
    const json = JSON.parse(fs.readFileSync(path.join(__dirname, '../../src/application/kk_kit_shapes.json'), 'utf8'));
    assert.deepEqual(json, JSON.parse(JSON.stringify(Kit.SHAPES)));
  });
});
