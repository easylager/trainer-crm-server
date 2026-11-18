/**
 * TASK-431: «Вечер» лиги — подписи дня, строка человека, жесты, месячная строка, правила кепки.
 *
 * Run: TZ=UTC node --test tests/js/kto-kogo-league-evening.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
require('../../static/webapp/kto-kogo-model.js');
const S = require('../../static/webapp/kto-kogo-screens-model.js');

const NBSP = ' ';
const M = (home, away, extra) => Object.assign({ home, away, status: 'final', home_score: 3, away_score: 2, started: true, starts_at: '2026-11-18T16:00:00Z' }, extra);
const EV = {
  day: '2026-11-18',
  complete: true,
  cap: { decided: true, in_play: true, need_moves: 2, min_players: 3 },
  matches: [M('Динамо-Минск', 'СКА'), M('Юность-Минск', 'Неман'), M('Гомель', 'Шахтер'), M('Металлург Жлобин', 'Лида')],
};

describe('шапка вечера', () => {
  it('«Вечер 18 ноября» и «Динамо — СКА 3:2 · ещё 3 матча»', () => {
    assert.equal(S.eveningTitle('2026-11-18'), 'Вечер 18' + NBSP + 'ноября');
    assert.equal(S.eveningSummary(EV), 'Динамо — СКА 3:2 · ещё 3' + NBSP + 'матча');
    assert.equal(S.eveningSummary({ matches: [M('Юность-Минск', 'Неман')] }), 'Юность-Минск — Неман 3:2');
    assert.equal(S.eveningSummary({ matches: [] }), '');
  });
  it('несыгранный матч — «идёт» или время, без счёта', () => {
    assert.equal(S.eveningScore(M('А', 'Б', { status: 'scheduled', started: true })), 'идёт');
    assert.equal(S.eveningScore(M('А', 'Б', { status: 'scheduled', started: false })), '19:00');
  });
});

describe('строка человека', () => {
  it('«K из N» и очки — только когда в дне есть сыгранный матч', () => {
    assert.equal(S.eveningMoves({ hits: 3 }, EV), '3 из 4');
    assert.equal(S.eveningPoints({ points: 100 }, EV), '+100');
    assert.equal(S.eveningPoints({ points: 0 }, EV), '+0');
    const ahead = { matches: [M('А', 'Б', { status: 'scheduled', started: false })] };
    assert.equal(S.eveningPoints({ points: 0 }, ahead), '');
  });
  it('жесты: несколько — глаголом во множественном, один — без глагола (пол неизвестен)', () => {
    const r = { gestures: [{ kind: 'pen', from: 'Саша', from_me: false }, { kind: 'pen', from: 'Макс', from_me: true }, { kind: 'stick', from: 'Аня', from_me: false }] };
    assert.equal(S.gestureNote(r), 'Аня — стук клюшкой · Ты и Саша дали 2' + NBSP + 'минуты');
    assert.equal(S.gestureNote({ gestures: [] }), '');
    const three = { gestures: ['Аня', 'Саша', 'Дима'].map((n) => ({ kind: 'stick', from: n, from_me: false })) };
    assert.equal(S.gestureNote(three), 'Аня, Саша и Дима постучали клюшкой');
  });
  it('почему без кепки: шарф дня, мало ходов; не разыгрывали — молчим', () => {
    assert.equal(S.eveningReason({ scarf: { club: 'Юность-Минск', picked: 'Неман' } }, EV), 'Болеет за Юность-Минск, ход — за Неман');
    assert.equal(S.eveningReason({ moves: 1, in_cap_race: false }, EV), 'Ход 1 из 4 — не в споре за кепку');
    assert.equal(S.eveningReason({ moves: 0, in_cap_race: false }, EV), 'Без ходов — не в споре за кепку');
    assert.equal(S.eveningReason({ moves: 3, in_cap_race: true }, EV), '');
    const few = Object.assign({}, EV, { cap: { decided: true, in_play: false, min_players: 3 } });
    assert.equal(S.eveningReason({ moves: 1, in_cap_race: false }, few), '');
    assert.equal(S.eveningFoot(few), 'Кепку в этот вечер не разыграли: в споре меньше троих.');
    assert.equal(S.eveningFoot(EV), 'Кепка дня — тому, кто хуже всех угадывал в этот вечер.');
  });
  it('тот же жест снимает, другой меняет', () => {
    assert.equal(S.gestureNext('pen', 'pen'), null);
    assert.equal(S.gestureNext('pen', 'stick'), 'stick');
    assert.equal(S.gestureNext(null, 'stick'), 'stick');
  });
});

describe('таблица месяца', () => {
  it('«12 мин штрафа · 3 кепки», нулевые части не показываем', () => {
    assert.equal(S.leagueMarks({ penalty_minutes: 12, caps: 3, sticks: 0 }), '12' + NBSP + 'мин штрафа · 3' + NBSP + 'кепки');
    assert.equal(S.leagueMarks({ penalty_minutes: 0, caps: 1, sticks: 9 }), '1' + NBSP + 'кепка · 9' + NBSP + 'стуков');
    assert.equal(S.leagueMarks({}), '');
  });
});

describe('правила и тексты', () => {
  it('раздел «Кепка» — текст макета Rules.dc.html', () => {
    const r = S.capRules();
    assert.equal(r.lead, 'Кепка дня достаётся тому, кто хуже всех угадывал в этот день');
    assert.equal(r.items.length, 5);
    const mock = fs.readFileSync(path.join(__dirname, '../../design/kto-kogo-league-evening/Rules.dc.html'), 'utf8');
    for (const x of r.items) assert.ok(mock.includes(x.t), x.t);
    assert.ok(mock.includes(r.foot));
  });
  it('в текстах вечера и правил нет азартных слов и «срок»', () => {
    const r = S.capRules();
    const g = S.gestureRules();
    const all = [r.lead, r.foot, g.lead].concat(r.items.map((x) => x.t), g.items.map((x) => x.t), S.GESTURES.map((x) => x[1])).join(' ');
    assert.doesNotMatch(all, /ставк|постав|срок|×|до \d/i);
  });
});

describe('шторка правил: разделы', () => {
  it('«Кепка» и «Жесты» рисуются по state.sheet.tab, вкладка выбора — role=tab', () => {
    const vm = require('node:vm');
    function h(tag, attrs, kids) {
      const e = { tag, attrs: {}, children: [], className: '', textContent: '', listeners: {} };
      Object.keys(attrs || {}).forEach((k) => {
        const v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') e.className = v;
        else if (k === 'text') e.textContent = v;
        else if (k.indexOf('on') === 0) e.listeners[k.slice(2)] = v;
        else e.attrs[k] = String(v);
      });
      (kids || []).forEach((c) => { if (c) e.children.push(typeof c === 'string' ? { tag: '#text', textContent: c, children: [] } : c); });
      return e;
    }
    const state = { sheet: { kind: 'points', tab: 'cap' } };
    const K = { h, M: {}, S, I: { down: [], chev: [] }, state, icon: () => h('svg'), render() {}, sheet: (title, sub, kids) => h('div', { class: 'sheet', 'aria-label': title }, kids) };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo-hub-cards.js'), 'utf8'), { window: { KK: K } });
    const text = (n) => (n.textContent || '') + (n.children || []).map(text).join('');
    let root = K.hubCards.pointsSheet();
    assert.equal(root.attrs['aria-label'], 'Как считаются очки?');
    const tabs = root.children[0];
    assert.equal(tabs.className, 'kk-rtabs');
    assert.deepEqual(tabs.children.map((t) => [t.textContent, t.attrs['aria-selected']]), [['Очки', 'false'], ['Кепка', 'true'], ['Жесты', 'false']]);
    assert.match(text(root), /Кепка дня достаётся тому, кто хуже всех угадывал в этот день/);
    assert.match(text(root), /3 за ход — кепка/);
    tabs.children[2].listeners.click();
    root = K.hubCards.pointsSheet();
    assert.match(text(root), /Стук клюшкой\./);
  });
});

describe('цвета вечера в обеих темах', () => {
  const css = fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo.css'), 'utf8');
  function tokens(selector) {
    const start = css.indexOf(selector + ' {');
    const body = css.slice(css.indexOf('{', start) + 1, css.indexOf('}', start));
    const out = {};
    for (const m of body.matchAll(/--(kk-[a-z-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim();
    return out;
  }
  function lum(hex) {
    const n = hex.replace('#', '');
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const light = tokens('.kk');
  const dark = Object.assign({}, light, tokens('body.kk-dark .kk'));
  it('ссылка «Как считаем», значок «кепка дня» и вкладка правил читаются (≥ 4.5:1); отметки различимы на карточке (цифры дублирует «K из N»)', () => {
    for (const [name, t] of [['light', light], ['dark', dark]]) {
      assert.ok(ratio(t['kk-link'], t['kk-bg']) >= 4.5, name + ' link/bg ' + ratio(t['kk-link'], t['kk-bg']).toFixed(2));
      assert.ok(ratio(t['kk-gold'], t['kk-badge']) >= 4.5, name + ' gold/badge');
      assert.ok(ratio(t['kk-dot-hit'], t['kk-card']) >= 1.5, name + ' hit/card');
    }
    assert.ok(ratio(dark['kk-dot'], dark['kk-card']) >= 1.5, 'dark miss/card ' + ratio(dark['kk-dot'], dark['kk-card']).toFixed(2));
  });
});

describe('вход «Вечер в лиге» из сводки', () => {
  const Mdl = require('../../static/webapp/kto-kogo-model.js');
  it('kkv_<лига>_<ГГГГММДД> и ?league=&day= открывают лигу на «Вечере» за день', () => {
    assert.deepEqual(Mdl.eveningEntry('kkv_12_20261118', null, null), { id: 12, tab: 'evening', day: '2026-11-18' });
    assert.deepEqual(Mdl.eveningEntry('', '12', '2026-11-18'), { id: 12, tab: 'evening', day: '2026-11-18' });
    assert.deepEqual(Mdl.eveningEntry('', '12', 'вчера'), { id: 12, tab: 'evening', day: '' });
    assert.equal(Mdl.eveningEntry('kks_insta', null, null), null);
    assert.equal(Mdl.eveningEntry('', 'x', '2026-11-18'), null);
  });
  it('boot кладёт лигу поверх hub только без другого экрана из ссылки', () => {
    const js = fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo.js'), 'utf8');
    assert.match(js, /var evening = entry \? null : M\.eveningEntry\(startParam\(\), params\.get\('league'\), params\.get\('day'\)\);\s*if \(evening\) go\('league', evening\);/);
  });
});
