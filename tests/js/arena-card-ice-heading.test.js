/**
 * Карточка катка: блок сеансов называется «Массовое катание», как на сайте,
 * а слот не повторяет это имя — остаётся только своё (площадка, «Свободный лёд»).
 * Run: node --test tests/js/arena-card-ice-heading.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');
const arenaSource = fs.readFileSync(path.join(webapp, 'arena-card.js'), 'utf8');
const M = require(path.join(webapp, 'arena-card-model.js'));

function fnBody(name) {
  const start = arenaSource.indexOf('function ' + name + '(');
  assert.ok(start >= 0, name + ' exists');
  const next = arenaSource.indexOf('\n  function ', start + 10);
  return arenaSource.slice(start, next > 0 ? next : undefined);
}

describe('arena card ice section heading', () => {
  it('never titles the skating block «Расписание»', () => {
    assert.ok(!/arena-h">Расписание</.test(arenaSource));
    const body = fnBody('renderIceSection');
    assert.ok(body.includes('iceSectionTitle()'));
  });

  it('falls back to «Массовое катание» without the copy dictionary', () => {
    assert.ok(fnBody('iceSectionTitle').includes("return 'Массовое катание'"));
  });

  it('drops the slot title when it only repeats the section name', () => {
    // TASK-306: группа сеансов рисуется общей showGroupHtml для массового катания и ОХМ.
    assert.match(fnBody('renderShowtimes'), /showGroupHtml\(g, sectionTitle, dayLabel, pricesAbove\)/);
    const body = fnBody('showGroupHtml');
    assert.ok(body.includes('g.title !== sectionTitle'));
    assert.ok(!body.includes("'<b>' + esc(g.title) + '</b>'"));
  });

  it('does not repeat the price tiles as a line under the day strip', () => {
    // Плитки «Вход · Детский · Прокат» уже над расписанием — строка под датами их дублировала.
    assert.ok(fnBody('renderShowtimes').includes('pricesAboveSchedule()'));
    assert.ok(fnBody('pricesAboveSchedule').includes('priceFloors()'));
    assert.ok(fnBody('showGroupHtml').includes('!pricesAbove && g.prices.length'));
  });

  it('merges one day of the same kind into one group when prices sit above (12:00 + 21:00)', () => {
    const mk = (id, t0, t1, adult) => ({ id, kind: 'public_skate', local_date: '2099-01-01', starts_at_local: t0, ends_at_local: t1, price_adult_minor: adult, session_label: 'Трен.', age_note: 'детский до 16 лет' });
    const sessions = [mk(1, '12:00', '12:45', 1000), mk(2, '21:00', '21:45', 1100)];
    const now = new Date('2098-12-31T00:00:00Z');
    const merged = M.showtimesForDay({ sessions, now, mergePrices: true });
    assert.equal(merged.groups.length, 1);
    assert.deepEqual(merged.groups[0].times.map((t) => t.time), ['12:00', '21:00']);
    assert.equal(merged.groups[0].title, 'Массовое катание');
    assert.ok(merged.groups[0].times[1].prices.length);
    assert.equal(M.showtimesForDay({ sessions, now }).groups.length, 2);
  });

  it('names figure_free and family_skate by kind, not by the hall', () => {
    const base = { local_date: '2099-01-01', starts_at_local: '10:00', ends_at_local: '11:00', session_label: 'Трен.' };
    const view = M.showtimesForDay({
      sessions: [Object.assign({ id: 1, kind: 'figure_free' }, base), Object.assign({ id: 2, kind: 'family_skate' }, base)],
      now: new Date('2098-12-31T00:00:00Z'),
    });
    assert.deepEqual(view.groups.map((g) => g.title).sort(), ['Свободное фигурное катание', 'Семейное массовое катание']);
  });

  it('carries the hall in full form on each time, from hall or a legacy label', () => {
    const base = { kind: 'public_skate', local_date: '2099-01-01', starts_at_local: '10:00', ends_at_local: '10:45' };
    const view = M.showtimesForDay({
      sessions: [
        Object.assign({ id: 1, session_label: 'Трен.' }, base),
        Object.assign({ id: 2, hall: 'Главная арена' }, base, { starts_at_local: '12:00', ends_at_local: '12:45' }),
      ],
      now: new Date('2098-12-31T00:00:00Z'),
      mergePrices: true,
    });
    assert.equal(view.groups.length, 1);
    assert.deepEqual(view.groups[0].times.map((t) => t.hall), ['Тренировочная арена', 'Главная арена']);
    assert.ok(fnBody('showGroupHtml').includes('arena-ticket__hall'));
  });

  it('model still names plain sessions «Массовое катание» and keeps own labels', () => {
    const day = { local_date: '2099-01-01' };
    const base = { local_date: day.local_date, starts_at_local: '10:00', ends_at_local: '11:00', price_adult_minor: 1000 };
    const view = M.showtimesForDay({
      sessions: [
        Object.assign({ id: 1, kind: 'public_skate' }, base),
        Object.assign({ id: 2, kind: 'public_skate', session_label: 'Малая арена' }, base),
        Object.assign({ id: 3, kind: 'open_ice' }, base),
      ],
      now: new Date('2098-12-31T00:00:00Z'),
    });
    const titles = view.groups.map((g) => g.title).sort();
    assert.deepEqual(titles, ['Малая арена', 'Массовое катание', 'Свободный лёд']);
  });
});

describe('price tiles for figure and family', () => {
  it('family combos become their own tiles', () => {
    const chips = M.priceChips({
      currency_code: 'BYN',
      price_tiers: [
        { label: '1 взрослый + 1 ребёнок', minor: 1400 },
        { label: '2 взрослых + 2 детей', minor: 2300 },
      ],
    });
    assert.deepEqual(chips.map((c) => c.label), ['1 взрослый + 1 ребёнок', '2 взрослых + 2 детей']);
    assert.match(chips[1].value, /23/);
  });
  it('figure per-person price is a single ticket tile', () => {
    const chips = M.priceChips({ currency_code: 'BYN', price_adult_minor: 1800 });
    assert.equal(chips[0].label, 'Билет');
    assert.match(chips[0].value, /18/);
  });
});
