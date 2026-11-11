/**
 * Вкладка «Я» (TASK-370): модель экрана — какие блоки и строки видны при каком ответе GET /client/me.
 * Run: node --test tests/js/client-me-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');
global.RuText = require(path.join(webapp, 'ru-text.js'));
const me = require(path.join(webapp, 'client-me.js'));
const kk = require(path.join(webapp, 'kto-kogo-model.js'));

const NB = '\u00a0';
// Среда, 11 ноября 2026, 12:00 по Минску.
const NOW = new Date('2026-11-11T12:00:00+03:00');

/** Каталожный человек — AC-2 TASK-368. */
function newcomer() {
  return {
    name: 'Максим',
    initial: 'М',
    city: 'Минск',
    club: null,
    home_arena: null,
    stats: { trainings: null, streak_weeks: null, kk_points: null, kk_place: null },
    rows: {
      bookings: null,
      passes: null,
      saved: null,
      family: { people: [{ profile_id: null, name: 'Максим', is_you: true, active: true }] },
      requests: null,
    },
    profile_name: null,
  };
}

/** Полный ответ из контракта TASK-368. */
function full() {
  return {
    name: 'Максим 🌱',
    initial: 'М',
    city: 'Минск',
    club: {
      name: 'Динамо-Минск',
      short: 'ДМ',
      color: '#003DA5',
      logo: '/static/webapp/hockey-logos/dinamo-minsk.png',
      label_ink: '#FFFFFF',
      next_match: { starts_at: '2026-11-13T19:30:00+03:00', opponent: 'СКА', href: '/webapp/kto-kogo' },
    },
    home_arena: { id: 12, name: '«Чижовка-арена»', href: '/webapp/arena?id=12', sessions_left_today: 2, tomorrow_first: null, subscribed: true },
    stats: { trainings: 14, streak_weeks: 3, kk_points: 340, kk_place: 12 },
    rows: {
      bookings: { next_starts_at: '2026-11-12T18:30:00+03:00' },
      passes: { lessons_left: 4 },
      saved: { count: 5 },
      family: {
        people: [
          { profile_id: 15, name: 'Максим 🌱', is_you: true, active: false },
          { profile_id: 16, name: 'Аня', is_you: false, active: true },
        ],
      },
      requests: { count: 1 },
    },
    profile_name: 'Аня',
  };
}

const model = (data, opts) => me.screenModel(data, Object.assign({ now: NOW }, opts));
const rowKeys = (m) => m.ice.rows.map((r) => r.key);
const row = (m, key) => m.ice.rows.find((r) => r.key === key);

/** Всё видимое на экране, одной строкой: в ней не должно быть пустот, «null» и нулей. */
function visibleTexts(m) {
  const out = [m.header.name, m.header.initial, m.ice.title, m.app.title];
  if (m.header.city) out.push(m.header.city);
  if (m.header.cover) out.push(m.header.cover.label);
  (m.stats || []).forEach((c) => out.push(c.value, c.label));
  if (m.club.kind === 'club') out.push(m.club.name, m.club.note || 'x');
  if (m.rink.kind === 'rink') out.push(m.rink.name, m.rink.note);
  m.ice.rows.concat(m.app.rows).forEach((r) => out.push(r.label, r.value === '' ? 'x' : r.value));
  return out;
}

describe('шапка', () => {
  it('нет клуба → нет обложки', () => {
    assert.equal(model(newcomer()).header.cover, null);
  });

  it('клуб есть → обложка цветом клуба, подпись — имя клуба цветом label_ink', () => {
    assert.deepEqual(model(full()).header.cover, { color: '#003DA5', label: 'Динамо-Минск', ink: '#FFFFFF' });
  });

  it('имя клуба с «ё» на обложке и в плитке, хотя в базе без неё', () => {
    const d = full();
    d.club.name = 'Шахтер';
    const m = model(d);
    assert.equal(m.header.cover.label, 'Шахтёр');
    assert.equal(m.club.name, 'Шахтёр');
  });

  it('city null → строки подписи нет', () => {
    const d = newcomer();
    d.city = null;
    assert.equal(model(d).header.city, null);
    assert.equal(model(newcomer()).header.city, 'Минск');
  });

  it('эмодзи в имени — как есть', () => {
    assert.equal(model(full()).header.name, 'Максим 🌱');
  });

  it('пустое имя → «Вы», не пустота; буква — «?», если её нет', () => {
    for (const name of ['', '   ']) {
      const d = newcomer();
      d.name = name;
      d.initial = '';
      const h = model(d).header;
      assert.equal(h.name, 'Вы');
      assert.equal(h.initial, '?');
    }
  });

  it('шапка не меняется от активного профиля ребёнка', () => {
    const a = full();
    const b = full();
    b.profile_name = null;
    b.rows.family.people[0].active = true;
    b.rows.family.people[1].active = false;
    assert.deepEqual(model(a).header, model(b).header);
    assert.deepEqual(model(a).stats, model(b).stats);
  });
});

describe('цифры сезона', () => {
  it('все null → блока нет', () => {
    assert.equal(model(newcomer()).stats, null);
  });

  it('четыре ячейки в порядке тренировки, недели, очки, место; ссылки', () => {
    const cells = model(full()).stats;
    assert.deepEqual(cells.map((c) => c.key), ['trainings', 'streak_weeks', 'kk_points', 'kk_place']);
    assert.deepEqual(cells.map((c) => c.value + ' ' + c.label), ['14 тренировок', '3 недели подряд', '340 очков', '12 место']);
    assert.deepEqual(cells.map((c) => c.href), ['client-stats', 'client-stats', 'kto-kogo', 'kto-kogo']);
  });

  it('от одной до четырёх ячеек — только не-null', () => {
    const cases = [
      [{ trainings: 1, streak_weeks: null, kk_points: null, kk_place: null }, ['trainings']],
      [{ trainings: null, streak_weeks: 2, kk_points: null, kk_place: 5 }, ['streak_weeks', 'kk_place']],
      [{ trainings: 21, streak_weeks: null, kk_points: 1, kk_place: 1 }, ['trainings', 'kk_points', 'kk_place']],
    ];
    for (const [stats, keys] of cases) {
      const d = newcomer();
      d.stats = stats;
      assert.deepEqual(model(d).stats.map((c) => c.key), keys);
    }
  });

  it('склонения: тренировка/тренировки, неделя/недели/недель подряд, очко/очка/очков', () => {
    const d = newcomer();
    const label = (k, n) => {
      d.stats = { trainings: null, streak_weeks: null, kk_points: null, kk_place: null, [k]: n };
      return model(d).stats[0].label;
    };
    assert.equal(label('trainings', 1), 'тренировка');
    assert.equal(label('trainings', 22), 'тренировки');
    assert.equal(label('trainings', 11), 'тренировок');
    assert.equal(label('streak_weeks', 1), 'неделя подряд');
    assert.equal(label('streak_weeks', 3), 'недели подряд');
    assert.equal(label('streak_weeks', 5), 'недель подряд');
    assert.equal(label('kk_points', 21), 'очко');
    assert.equal(label('kk_points', 34), 'очка');
    assert.equal(label('kk_points', 340), 'очков');
  });

  it('ноль очков при сыгранных матчах — ячейки нет (ни одного нуля на экране)', () => {
    const d = newcomer();
    d.stats = { trainings: null, streak_weeks: null, kk_points: 0, kk_place: 30 };
    assert.deepEqual(model(d).stats.map((c) => c.key), ['kk_place']);
  });
});

describe('плитка «Болею за»', () => {
  it('нет клуба → пунктирная «Выбрать команду»', () => {
    assert.deepEqual(model(newcomer()).club, { kind: 'empty' });
  });

  it('клуб с логотипом и матчем в пятницу', () => {
    const c = model(full()).club;
    assert.equal(c.kind, 'club');
    assert.equal(c.logo, '/static/webapp/hockey-logos/dinamo-minsk.png');
    assert.equal(c.note, 'Матч в' + NB + 'пятницу, 19:30');
  });

  it('нет логотипа → круг цвета клуба с коротким именем', () => {
    const d = full();
    d.club.logo = null;
    const c = model(d).club;
    assert.equal(c.logo, null);
    assert.equal(c.short, 'ДМ');
    assert.equal(c.color, '#003DA5');
  });

  it('next_match null → нижней строки нет', () => {
    const d = full();
    d.club.next_match = null;
    assert.equal(model(d).club.note, null);
  });

  it('день матча: сегодня, завтра, день недели, дальше — число', () => {
    const at = (iso) => {
      const d = full();
      d.club.next_match.starts_at = iso;
      return model(d).club.note;
    };
    assert.equal(at('2026-11-11T19:30:00+03:00'), 'Матч сегодня, 19:30');
    assert.equal(at('2026-11-12T09:00:00+03:00'), 'Матч завтра, 9:00');
    assert.equal(at('2026-11-17T19:00:00+03:00'), 'Матч во' + NB + 'вторник, 19:00');
    assert.equal(at('2026-11-18T19:00:00+03:00'), 'Матч 18' + NB + 'ноября, 19:00');
  });

  it('формат дня совпадает с «Кто кого» (kto-kogo-model.whenLabel)', () => {
    const start = Date.parse('2026-11-11T00:15:00+03:00');
    for (let h = 0; h < 24 * 9; h += 5) {
      const iso = new Date(start + h * 3600000).toISOString();
      assert.equal(me.whenLabel(iso, NOW), kk.whenLabel(iso, NOW).replace(/^(во?) /, '$1' + NB));
    }
  });
});

describe('плитка «Мой каток»', () => {
  it('нет катка → пунктирная «Выбрать каток»', () => {
    assert.deepEqual(model(newcomer()).rink, { kind: 'empty' });
  });

  it('каток есть → имя, ссылка на страницу катка, id для шторки', () => {
    const r = model(full()).rink;
    assert.equal(r.kind, 'rink');
    assert.equal(r.name, '«Чижовка-арена»');
    assert.equal(r.href, '/webapp/arena?id=12');
    assert.equal(r.id, 12);
  });

  it('sessions_left_today > 0 → «Сегодня ещё N сеанс/сеанса/сеансов»', () => {
    const note = (n) => me.sessionsNote({ sessions_left_today: n, tomorrow_first: null });
    assert.equal(note(1), 'Сегодня ещё' + NB + '1' + NB + 'сеанс');
    assert.equal(note(2), 'Сегодня ещё' + NB + '2' + NB + 'сеанса');
    assert.equal(note(5), 'Сегодня ещё' + NB + '5' + NB + 'сеансов');
    assert.equal(note(21), 'Сегодня ещё' + NB + '21' + NB + 'сеанс');
  });

  it('0 и tomorrow_first → «Сегодня сеансов нет, завтра — с 9:00»', () => {
    assert.equal(
      me.sessionsNote({ sessions_left_today: 0, tomorrow_first: '9:00' }),
      'Сегодня сеансов нет, завтра' + NB + '— с' + NB + '9:00'
    );
  });

  it('0 и завтра пусто → «Сегодня сеансов нет»', () => {
    assert.equal(me.sessionsNote({ sessions_left_today: 0, tomorrow_first: null }), 'Сегодня сеансов нет');
  });
});

describe('«Лёд и занятия»', () => {
  it('каталожный человек: одна строка «Семья — Добавить близкого»', () => {
    const m = model(newcomer());
    assert.equal(m.ice.title, 'Лёд и занятия');
    assert.deepEqual(m.ice.rows, [{ key: 'family', label: 'Семья', value: 'Добавить близкого', href: 'client-family-access' }]);
  });

  it('полный ответ: все строки по порядку, со своими страницами', () => {
    const m = model(full());
    assert.deepEqual(rowKeys(m), ['bookings', 'passes', 'saved', 'requests', 'family']);
    assert.deepEqual(
      m.ice.rows.map((r) => r.href),
      ['client-bookings', 'client-passes-certificates', 'client-saved-trainers', 'client-requests', 'client-family-access']
    );
    assert.equal(row(m, 'bookings').value, 'завтра, 18:30');
    assert.equal(row(m, 'passes').value, '4' + NB + 'занятия');
    assert.equal(row(m, 'saved').value, '5');
    assert.equal(row(m, 'requests').value, '1');
  });

  it('строки только при не-null', () => {
    const d = full();
    d.rows.passes = null;
    d.rows.saved = null;
    d.rows.requests = null;
    assert.deepEqual(rowKeys(model(d)), ['bookings', 'family']);
  });

  it('«Мои записи» скрыта, если в баре вкладка «Записи»', () => {
    assert.deepEqual(rowKeys(model(full(), { bookingsTab: true })), ['passes', 'saved', 'requests', 'family']);
  });

  it('«Мои записи» без будущей записи — строка есть, значения нет', () => {
    const d = full();
    d.rows.bookings.next_starts_at = null;
    assert.equal(row(model(d), 'bookings').value, '');
  });

  it('абонемент без остатка — строка есть, нуля нет', () => {
    const d = full();
    d.rows.passes.lessons_left = 0;
    assert.equal(row(model(d), 'passes').value, '');
    d.rows.passes.lessons_left = 1;
    assert.equal(row(model(d), 'passes').value, '1' + NB + 'занятие');
    d.rows.passes.lessons_left = 5;
    assert.equal(row(model(d), 'passes').value, '5' + NB + 'занятий');
  });

  it('profile_name → «Лёд и занятия · Аня»', () => {
    assert.equal(model(full()).ice.title, 'Лёд и занятия' + NB + '· Аня');
  });

  it('«Приложение» — одна строка «Написать нам»', () => {
    assert.deepEqual(model(newcomer()).app.rows, [{ key: 'support', label: 'Написать нам', value: '', href: 'client-support' }]);
  });
});

describe('«Семья»', () => {
  const you = { profile_id: 15, name: 'Максим', is_you: true, active: true };
  const kid = (name, id) => ({ profile_id: id, name, is_you: false, active: false });

  it('только «вы» → «Добавить близкого»', () => {
    assert.equal(me.familyValue([you]), 'Добавить близкого');
    assert.equal(me.familyValue([{ profile_id: null, name: '', is_you: true, active: true }]), 'Добавить близкого');
  });

  it('один, двое — имена через запятую', () => {
    assert.equal(me.familyValue([you, kid('Аня', 16)]), 'Аня');
    assert.equal(me.familyValue([you, kid('Аня', 16), kid('Миша', 17)]), 'Аня, Миша');
  });

  it('трое и больше — «Аня, Миша и ещё 1»', () => {
    assert.equal(me.familyValue([you, kid('Аня', 16), kid('Миша', 17), kid('Соня', 18)]), 'Аня, Миша и' + NB + 'ещё' + NB + '1');
    assert.equal(
      me.familyValue([you, kid('Аня', 16), kid('Миша', 17), kid('Соня', 18), kid('Лёва', 19)]),
      'Аня, Миша и' + NB + 'ещё' + NB + '2'
    );
  });

  it('безымянный (null или "") не печатается пустотой — уходит в «и ещё N»', () => {
    assert.equal(me.familyValue([you, kid(null, 16), kid('Миша', 17)]), 'Миша и' + NB + 'ещё' + NB + '1');
    assert.equal(me.familyValue([you, kid('', 16), kid('  ', 17), kid('Миша', 18)]), 'Миша и' + NB + 'ещё' + NB + '2');
  });

  it('безымянные все — «1 близкий» / «2 близких»', () => {
    assert.equal(me.familyValue([you, kid(null, 16)]), '1' + NB + 'близкий');
    assert.equal(me.familyValue([you, kid('', 16), kid(null, 17)]), '2' + NB + 'близких');
  });

  it('«вы» в значение не попадает, где бы ни стоял; слова «профиль» нет', () => {
    assert.equal(me.familyValue([kid('Аня', 16), you]), 'Аня');
    assert.doesNotMatch(me.familyValue([you, kid(null, 16)]), /профил/i);
  });
});

describe('ни одной пустой строки и ни одного нуля', () => {
  for (const [title, data] of [['новичок', newcomer()], ['полный ответ', full()]]) {
    it(title, () => {
      for (const s of visibleTexts(model(data))) {
        assert.ok(typeof s === 'string' && s.trim() !== '', 'пустая строка');
        assert.doesNotMatch(s, /\bnull\b|\bundefined\b|NaN/);
        assert.doesNotMatch(s, /(^|\D)0(\D|$)/, 'ноль на экране: ' + s);
      }
    });
  }
});

describe('тёплый кэш cw_me_warm_v1', () => {
  const T = 1_800_000_000_000;
  const wrap = (data, age) => JSON.stringify({ ts: T - age, data });

  it('свежий 60 с: 59 с — берём, 60 с — нет', () => {
    assert.ok(me.readWarm(wrap(newcomer(), 59_000), T, null));
    assert.equal(me.readWarm(wrap(newcomer(), 60_000), T, null), null);
  });

  it('битый, пустой, без ts — null, без исключения', () => {
    for (const raw of [null, '', '{', 'null', '[]', JSON.stringify({ data: newcomer() }), JSON.stringify({ ts: 'x', data: newcomer() })]) {
      assert.equal(me.readWarm(raw, T, null), null);
    }
  });

  it('старая схема rows.family = {profiles: N} — null, страница не падает', () => {
    const d = newcomer();
    d.rows.family = { profiles: 2 };
    assert.equal(me.readWarm(wrap(d, 1000), T, null), null);
    assert.doesNotThrow(() => me.screenModel(d, { now: NOW }));
    assert.equal(me.screenModel(d, { now: NOW }).ice.rows.at(-1).value, 'Добавить близкого');
  });

  it('кэш про другого человека (активен ребёнок, а спрашиваем «вас») — null', () => {
    assert.equal(me.readWarm(wrap(full(), 1000), T, null), null);
    assert.equal(me.readWarm(wrap(full(), 1000), T, 15), null);
    assert.ok(me.readWarm(wrap(full(), 1000), T, 16));
  });

  it('screenModel не падает на мусоре', () => {
    for (const junk of [null, undefined, 1, 'x', [], {}, { rows: [], stats: 'x', club: 1, home_arena: [] }]) {
      const m = me.screenModel(junk, { now: NOW });
      assert.equal(m.header.name, 'Вы');
      assert.equal(m.stats, null);
      assert.deepEqual(rowKeys(m), ['family']);
    }
  });
});
