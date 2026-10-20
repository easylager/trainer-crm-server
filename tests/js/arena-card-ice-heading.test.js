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
    assert.match(fnBody('renderShowtimes'), /showGroupHtml\(g, sectionTitle, dayLabel\)/);
    const body = fnBody('showGroupHtml');
    assert.ok(body.includes('g.title !== sectionTitle'));
    assert.ok(!body.includes("'<b>' + esc(g.title) + '</b>'"));
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
