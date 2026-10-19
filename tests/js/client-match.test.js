/**
 * TASK-304: домашний матч — ивент. Модель текстов и проводка страницы и слота главной.
 * Run: node --test tests/js/client-match.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');
const M = require(path.join(webapp, 'client-match-model.js'));
const HubHome = require(path.join(webapp, 'hub-home.js'));
const pageHtml = fs.readFileSync(path.join(webapp, 'client-match.html'), 'utf8');
const pageJs = fs.readFileSync(path.join(webapp, 'client-match.js'), 'utf8');
const hubJs = fs.readFileSync(path.join(webapp, 'hub-home.js'), 'utf8');
const hubCss = fs.readFileSync(path.join(webapp, 'hub-home.css'), 'utf8');
const NBSP = ' ';

function ev(kk, extra) {
  return Object.assign(
    {
      match: { id: 7, home: { name: 'Динамо-Минск' }, away: { name: 'СКА' }, starts_at: '2026-10-23T16:30:00Z', status: 'scheduled', result: null },
      kk,
    },
    extra || {}
  );
}

describe('строка «КТО КОГО?»', () => {
  it('до хода: без компании — без имён; с компанией — без падежей и рода', () => {
    assert.deepEqual(M.kkRow(ev({ phase: 'open', company_names: [] })), { title: 'Угадай счёт', sub: 'Точный счёт — 50 очков', href: 'kto-kogo' });
    assert.equal(M.kkRow(ev({ phase: 'open', company_names: ['Аня', 'Петя'] })).sub, 'Уже с' + NBSP + 'ходом: Аня и' + NBSP + 'Петя · точный — 50');
  });

  it('ход сделан → «Твой счёт 3:2 · можно изменить до 19:30» (время Минска)', () => {
    const row = M.kkRow(ev({ phase: 'picked', my_pick: { side: 'home', home_score: 3, away_score: 2 } }));
    assert.deepEqual(row, { title: 'Твой счёт 3:2', sub: 'Можно изменить до 19:30', href: 'kto-kogo' });
    assert.equal(M.kkRow(ev({ phase: 'picked', my_pick: { side: 'away' } })).title, 'Ты за' + NBSP + 'СКА');
  });

  it('идёт и итог: ходы закрыты, очки FIFA, разбор итога ведёт в игру', () => {
    assert.equal(M.kkRow(ev({ phase: 'live', my_pick: null, company_names: [] })).title, 'Ходы закрыты');
    const done = ev({ phase: 'final', my_pick: { side: 'home', home_score: 3, away_score: 2 }, points: 50 });
    done.match.result = { home_score: 3, away_score: 2 };
    assert.deepEqual(M.kkRow(done), { title: 'В точку! +50', sub: 'Похвастаться в чате', href: 'kto-kogo?reveal=7' });
    const none = ev({ phase: 'final', my_pick: null });
    none.match.result = { home_score: 3, away_score: 2 };
    assert.equal(M.kkRow(none).title, 'Итог 3:2');
  });

  it('в текстах игры нет «прогноз» и «ставка» (PDEC-022)', () => {
    const model = fs.readFileSync(path.join(webapp, 'client-match-model.js'), 'utf8');
    assert.ok(!/прогноз|ставк/i.test(model + pageJs + pageHtml));
  });
});

describe('«Кто из ваших»', () => {
  it('пусто — блока нет; «Ты» первым и в строке, и в кружках', () => {
    assert.equal(M.who([]), null);
    const w = M.who([
      { name: 'Аня', status: 'going' },
      { name: 'Макс', status: 'going', is_me: true },
      { name: 'Дима', status: 'maybe' },
      { name: 'Оля', status: 'cant' },
    ]);
    assert.equal(w.line, 'Ты и' + NBSP + 'Аня идут · Дима смотрит дома');
    assert.equal(w.count, '2' + NBSP + 'идут');
    assert.deepEqual(w.initials.map((f) => f.letter), ['Я', 'А', 'Д']);
  });

  it('согласование: один — «идёт», ты один дома — «смотришь дома»', () => {
    assert.equal(M.who([{ name: 'Аня', status: 'going' }, { name: 'Я', status: 'maybe', is_me: true }]).line, 'Аня идёт · Ты смотришь дома');
  });
});

describe('шапка', () => {
  it('время матча и плашка по дням', () => {
    assert.equal(M.heroWhen('2026-10-23T16:30:00Z'), 'пт, 23' + NBSP + 'октября · 19:30');
    const m = { starts_at: '2026-10-23T16:30:00Z' };
    assert.equal(M.status(m, new Date('2026-10-20T10:00:00Z')).text, 'через 3' + NBSP + 'дня');
    assert.equal(M.status(m, new Date('2026-10-22T10:00:00Z')).text, 'завтра');
    assert.equal(M.status(m, new Date('2026-10-23T10:00:00Z')).text, 'сегодня');
    assert.equal(M.status(m, new Date('2026-10-23T17:00:00Z')).live, true);
    assert.equal(M.status(Object.assign({ result: { home_score: 3, away_score: 2 } }, m)).text, 'финал');
  });
});

describe('страница', () => {
  it('рисует только через createElement/textContent', () => {
    assert.ok(!/innerHTML|insertAdjacentHTML|outerHTML/.test(pageJs));
  });

  it('порядок как утвердил владелец: ответ → кто из ваших → игра → билеты → лёд', () => {
    const ids = ['cmRsvp', 'cmWho', 'cmKk', 'cmTickets', 'cmIce'].map((id) => pageHtml.indexOf('id="' + id + '"'));
    ids.forEach((p) => assert.ok(p > 0));
    assert.deepEqual([...ids].sort((a, b) => a - b), ids);
  });

  it('крестик игры только спрашивает; скрытие — после «Скрыть»', () => {
    assert.match(pageJs, /x\.addEventListener\('click', function \(\) \{ state\.kk = 'confirm'; paintKk\(state\.ev\); \}\)/);
    assert.match(pageJs, /hide\.addEventListener\('click', hideGame\)/);
    assert.match(pageJs, /api\('PUT', '\/client\/hockey\/prefs', \{ kk_hidden: true \}\)/);
  });

  it('шрифт заголовка — свой, preload совпадает с адресом из CSS', () => {
    assert.ok(!pageHtml.includes('fonts.googleapis.com'));
    assert.match(pageHtml, /dela-gothic-one-cyr-lat\.woff2\?v=__FONT_V__/);
  });

  it('у своих ассетов одна версия', () => {
    const versions = new Set([...pageHtml.matchAll(/\.(?:js|css)\?v=(\d+)/g)].map((m) => m[1]));
    assert.equal(versions.size, 1, [...versions].join(','));
  });
});

describe('слот главной — домашний матч', () => {
  const card = (mode, starts, result) => ({ mode, match: { starts_at: starts, result: result || null } });

  it('метка: МАТЧ · ПТ → СЕГОДНЯ → ИДЁТ → ИТОГ', () => {
    assert.deepEqual(HubHome._eventTag(card('before', '2026-10-23T16:30:00Z'), new Date('2026-10-21T10:00:00Z')), { text: 'МАТЧ · ПТ', dot: false, live: false });
    assert.equal(HubHome._eventTag(card('before', '2026-10-23T16:30:00Z'), new Date('2026-10-23T08:00:00Z')).text, 'СЕГОДНЯ');
    assert.deepEqual(HubHome._eventTag(card('live', '2026-10-23T16:30:00Z')), { text: 'ИДЁТ', dot: true, live: true });
    assert.equal(HubHome._eventTag(card('result', '2026-10-23T16:30:00Z', { home_score: 3, away_score: 2 })).text, 'ИТОГ 3:2');
  });

  it('домашний с event_href — карточка ивента, выездной — прежняя игра', () => {
    assert.match(hubJs, /now\.hockey && now\.hockey\.event_href\) eventCard\(now\.hockey, host\)/);
    assert.match(hubJs, /else if \(kind === 'kk_before'\) kkBefore\(now\.hockey, host\)/);
  });

  it('анимация метки выключается при reduced motion', () => {
    assert.match(hubCss, /prefers-reduced-motion: reduce\) \{\s+\.hn__tag, \.hn__tag::after, \.hn__tag-dot \{ animation: none; \}/);
  });
});
