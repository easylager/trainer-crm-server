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
  it('«Вечер 18 ноября» и «4 матча · все сыграны»; один матч — со счётом', () => {
    assert.equal(S.eveningTitle('2026-11-18'), 'Вечер 18' + NBSP + 'ноября');
    assert.equal(S.eveningSummary(EV), '4' + NBSP + 'матча · все сыграны');
    const half = { matches: [M('А', 'Б'), M('В', 'Г', { status: 'scheduled', started: true }), M('Д', 'Е', { status: 'scheduled', started: false })] };
    assert.equal(S.eveningSummary(half), '3' + NBSP + 'матча · сыграно 1');
    const ahead = { matches: [M('А', 'Б', { status: 'scheduled', started: false }), M('В', 'Г', { status: 'scheduled', started: false })] };
    assert.equal(S.eveningSummary(ahead), '2' + NBSP + 'матча · первый в 19:00');
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
  it('что прилетело мне — настоящим временем (пол неизвестен)', () => {
    const r = { gestures: [{ kind: 'pen', from: 'Мария', from_me: false }, { kind: 'stick', from: 'Андрей', from_me: false }] };
    assert.equal(S.gestureNote(r), 'Андрей стучит тебе клюшкой · Мария отправляет тебя на скамейку');
    assert.equal(S.gestureNote({ gestures: [] }), '');
    const three = { gestures: ['Аня', 'Саша', 'Дима'].map((n) => ({ kind: 'stick', from: n, from_me: false })) };
    assert.equal(S.gestureNote(three), 'Аня, Саша и Дима стучат тебе клюшкой');
    const two = { gestures: ['Аня', 'Саша'].map((n) => ({ kind: 'pen', from: n, from_me: false })) };
    assert.equal(S.gestureNote(two), 'Аня и Саша отправляют тебя на скамейку');
  });
  it('мой жест другу — что он значит; себе и без жеста — пусто', () => {
    assert.equal(S.myGestureNote({ my_gesture: 'pen' }, EV), 'На скамейке до следующего вечера · +2' + NBSP + 'мин в ноябре');
    assert.equal(S.myGestureNote({ my_gesture: 'stick' }, EV), 'Твой стук горит у друга до следующего вечера');
    assert.equal(S.myGestureNote({ my_gesture: null }, EV), '');
    assert.equal(S.myGestureNote({ is_me: true, my_gesture: 'pen' }, EV), '');
  });
  it('строки под именем: мне — что прилетело, другу — причина и мой жест с цветом', () => {
    const me = { is_me: true, moves: 4, in_cap_race: true, gestures: [{ kind: 'stick', from: 'Андрей', from_me: false }] };
    assert.deepEqual(S.eveningNotes(me, EV), [{ text: 'Андрей стучит тебе клюшкой', tone: '' }]);
    const friend = { moves: 4, in_cap_race: true, scarf: { club: 'Динамо-Минск', picked: 'Юность-Минск' }, my_gesture: 'pen', gestures: [{ kind: 'pen', from: 'Макс', from_me: true }] };
    assert.deepEqual(S.eveningNotes(friend, EV).map((n) => n.tone), ['', 'pen']);
  });
  it('след на аватаре: ×N стуков от двух, «2:00» за каждую скамейку', () => {
    const r = { gestures: [{ kind: 'stick' }, { kind: 'stick' }, { kind: 'pen' }, { kind: 'pen' }] };
    const st = S.gestureStamps(r);
    assert.equal(st.stickLabel, '×2');
    assert.equal(st.penLabel, '4:00');
    assert.equal(st.say, '2' + NBSP + 'стука, на скамейке 4' + NBSP + 'мин');
    assert.deepEqual(S.gestureStamps({ gestures: [{ kind: 'stick' }] }), { sticks: 1, stickLabel: '', pens: 0, penLabel: '', say: '1' + NBSP + 'стук' });
  });
  it('прилёт жестов анимируем один раз на набор: подпись не зависит от порядка и моих жестов', () => {
    const a = { gestures: [{ kind: 'pen', from: 'Б' }, { kind: 'stick', from: 'А' }, { kind: 'pen', from: 'Я', from_me: true }] };
    const b = { gestures: [{ kind: 'stick', from: 'А' }, { kind: 'pen', from: 'Б' }] };
    assert.equal(S.gestureSeenKey(a), S.gestureSeenKey(b));
    assert.equal(S.gestureSeenKey({ gestures: [] }), '');
  });
  it('облик жеста отдельно от смысла: неизвестный скин — базовый', () => {
    assert.equal(S.gestureSkin('stick', 'base').motion, 'knock');
    assert.equal(S.gestureSkin('pen', 'base').motion, 'drain');
    assert.deepEqual(S.gestureSkin('pen', 'gold-led'), S.GESTURE_SKINS.base.pen);
  });
  it('почему без кепки: шарф дня, мало ходов; не разыгрывали — молчим', () => {
    assert.equal(S.eveningReason({ scarf: { club: 'Юность-Минск', picked: 'Неман' } }, EV), 'Юность-Минск простит? Ход — за Неман');
    assert.equal(S.eveningReason({ moves: 1, in_cap_race: false }, EV), 'Ход 1 из 4 — не в споре за кепку');
    assert.equal(S.eveningReason({ moves: 0, in_cap_race: false }, EV), 'Без ходов — не в споре за кепку');
    assert.equal(S.eveningReason({ moves: 3, in_cap_race: true }, EV), '');
    const few = Object.assign({}, EV, { cap: { decided: true, in_play: false, min_players: 3 } });
    assert.equal(S.eveningReason({ moves: 1, in_cap_race: false }, few), '');
    assert.equal(S.eveningFoot(few), 'Кепку и капитана в этот вечер не разыграли: в споре меньше троих.');
    assert.equal(S.eveningFoot(EV), 'Капитан — лучший за вечер, в кепке дня — худший. Носят до следующего вечера.');
    assert.equal(S.eveningFoot(Object.assign({}, EV, { captain_on: true })), 'Капитан — лучший за вечер, в кепке дня — худший. Капитан выдаёт экипировку кому угодно, даже себе. Носят до следующего вечера.');
    assert.equal(S.eveningFoot(Object.assign({}, EV, { gestures_on: true })), 'Кепку даёт игра, стук и скамейку — друзья. Всё держится до следующего вечера.');
  });
  it('итог вечера: капитан и кепка от сервера, имена без склонения; вечер не сыгран — итога нет', () => {
    const items = [
      { display_name: 'Макс', is_me: true, hits: 0, moves: 4, points: 0, cap: true },
      { display_name: 'Андрей', hits: 4, moves: 4, points: 130, cap: false, captain: true },
      { display_name: 'Мария', hits: 3, moves: 4, points: 70, cap: false },
    ];
    const ev = Object.assign({}, EV, { items });
    assert.deepEqual(S.eveningVerdict(ev), {
      captain: { label: 'Капитан', name: 'Андрей', sub: '4 из 4 · +130' },
      cap: { label: 'Кепка дня', name: 'у тебя', sub: '0 из 4. Носишь до следующего вечера' },
    });
    const other = Object.assign({}, EV, { items: items.map((r) => Object.assign({}, r, { cap: r.display_name === 'Мария' })) });
    assert.equal(S.eveningVerdict(other).cap.name, 'Мария');
    assert.equal(S.eveningVerdict(other).cap.sub, '3 из 4 · носит до следующего вечера');
    const mine = Object.assign({}, EV, { items: [Object.assign({}, items[0], { captain: true, cap: false, hits: 4, points: 130 })] });
    assert.equal(S.eveningVerdict(mine).captain.name, 'ты');
    const tie = Object.assign({}, EV, { items: [Object.assign({}, items[1]), Object.assign({}, items[2], { captain: true }), Object.assign({}, items[0], { captain: true, cap: false })] });
    assert.deepEqual(S.eveningVerdict(tie).captain, { label: 'Капитаны', name: 'ты, Андрей и Мария', sub: 'Выдаёт тот, кто успеет первым' });
    const few = Object.assign({}, EV, { items: [Object.assign({}, items[1], { captain: false })], cap: { decided: true, in_play: false, min_players: 3 } });
    assert.equal(S.eveningVerdict(few).captain, null);
    assert.deepEqual(S.eveningVerdict(few).cap, { label: 'Кепка дня', name: 'не разыграна', sub: 'В споре меньше троих — и капитана нет' });
    assert.equal(S.eveningVerdict(Object.assign({}, ev, { complete: false })), null);
    const zero = Object.assign({}, EV, { items: [{ display_name: 'А', moves: 2, points: 0 }], cap: { decided: true, in_play: true } });
    assert.equal(S.eveningVerdict(zero), null);
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
    // Жесты выключены (KK_GESTURES_ENABLED) — раздела «Жесты» нет.
    assert.deepEqual(tabs.children.map((t) => [t.textContent, t.attrs['aria-selected']]), [['Очки', 'false'], ['Кепка', 'true']]);
    assert.match(text(root), /Кепка дня достаётся тому, кто хуже всех угадывал в этот день/);
    assert.match(text(root), /3 за ход — кепка/);
    state.gesturesOn = true;
    root = K.hubCards.pointsSheet();
    const on = root.children[0].children;
    assert.deepEqual(on.map((t) => t.textContent), ['Очки', 'Кепка', 'Жесты']);
    on[2].listeners.click();
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

describe('«Лига готова» (Ready.dc.html)', () => {
  const Mdl = require('../../static/webapp/kto-kogo-model.js');
  it('переключатель «Все · Динамо · Свои команды» и строка под названием', () => {
    assert.deepEqual(S.READY_SCOPES.map((x) => x[1]), ['Все', 'Динамо', 'Свои команды']);
    assert.equal(S.readyLine('all', []), 'Все матчи «КТО КОГО», до конца сезона. Название и картинку можно поменять потом.');
    assert.match(S.readyLine('dinamo', []), /^Матчи Динамо-Минск, до конца сезона\./);
    assert.match(S.readyLine('clubs', ['Неман', 'Шахтер']), /^Матчи: Неман, Шахтёр — до конца сезона\./);
    assert.equal(S.readyError({ scope: 'clubs', clubs: [] }), 'Выбери команду');
    assert.equal(S.readyError({ scope: 'all', clubs: [] }), '');
  });
  it('тело «Позвать друзей»: команды только для своих, «на что играем» и метка — если есть', () => {
    assert.deepEqual(S.readyBody({ scope: 'all', clubs: ['Неман'] }, '', ''), { scope: 'all', clubs: [] });
    assert.deepEqual(S.readyBody({ scope: 'clubs', clubs: ['Неман'] }, 'на пиво', 'lg1'), { scope: 'clubs', clubs: ['Неман'], stake_text: 'на пиво', src: 'lg1' });
  });
  it('вход kkg_<метка>: экран «Лига готова» и та же метка, что у kks_', () => {
    assert.equal(Mdl.readyEntry('kkg_lg1', null), true);
    assert.equal(Mdl.readyEntry('', '1'), true);
    assert.equal(Mdl.readyEntry('kks_lg1', null), false);
    assert.equal(Mdl.promoSrc('kkg_LG2', ''), 'lg2');
    assert.equal(Mdl.inviteCode('kkg_lg1'), '');
  });
  it('лига создаётся по кнопке, а не при открытии экрана; поле без подсказки внутри', () => {
    const src = fs.readFileSync(path.join(__dirname, '../../static/webapp/kto-kogo-leagues.js'), 'utf8');
    const ready = src.slice(src.indexOf("K.register('ready'"), src.indexOf('// ---------- Вход по ссылке'));
    const enter = ready.slice(0, ready.indexOf('render:'));
    assert.ok(!/POST/.test(enter), 'enter только спрашивает GET /quick');
    assert.match(src, /K\.api\('POST', '\/client\/hockey\/leagues\/quick'/);
    const input = ready.slice(ready.indexOf("id: 'kk-rstake'"), ready.indexOf("id: 'kk-rstake'") + 300);
    assert.ok(!/placeholder/.test(input));
  });
});
