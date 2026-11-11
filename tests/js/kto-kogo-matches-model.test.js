/**
 * TASK-359: «Матчи и мои ходы» — чистая модель: фазы матча, десять состояний строки, секции, сводка, слияние страниц.
 *
 * Run: TZ=UTC node --test tests/js/kto-kogo-matches-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
require('../../static/webapp/kto-kogo-model.js');
const S = require('../../static/webapp/kto-kogo-screens-model.js');

const NBSP = ' ';
const NOW = new Date('2026-11-09T16:30:00Z'); // понедельник, 19:30 в Минске
const H = 3600 * 1000;

function at(offsetMs) {
  return new Date(NOW.getTime() + offsetMs).toISOString();
}

function mk(o) {
  return Object.assign(
    {
      id: 1,
      home_team: 'Юность',
      away_team: 'Шахтер',
      home: { name: 'Юность', short: 'ЮН' },
      away: { name: 'Шахтер', short: 'ША' },
      starts_at: at(H),
      status: 'scheduled',
      phase: 'upcoming',
      open: true,
      league: 'extraliga',
      city: null,
      moved_from: null,
      result: null,
      live: null,
      my_pick: null,
      my_points: null,
    },
    o
  );
}

const PICK = { side: 'home', home_score: 3, away_score: 1, points: null, doubled: false };
const SIDE_ONLY = { side: 'away', home_score: null, away_score: null, points: null, doubled: false };
const done = (o) => mk(Object.assign({ status: 'final', phase: 'done', open: false, starts_at: at(-30 * H), result: { home_score: 0, away_score: 4, decided_in: 'regulation' } }, o));

describe('фаза матча', () => {
  it('идёт три часа, дальше ждём итог; запомненный итог и ручная проверка — сразу', () => {
    assert.equal(S.matchPhase(mk({ starts_at: at(60000) }), NOW), 'upcoming');
    assert.equal(S.matchPhase(mk({ starts_at: at(-60000), phase: 'upcoming' }), NOW), 'live'); // экран открыт до старта: матч начался
    assert.equal(S.matchPhase(mk({ starts_at: at(-3 * H + 1000) }), NOW), 'live');
    assert.equal(S.matchPhase(mk({ starts_at: at(-3 * H) }), NOW), 'waiting');
    assert.equal(S.matchPhase(mk({ starts_at: at(-H), phase: 'waiting' }), NOW), 'waiting');
    assert.equal(S.matchPhase(mk({ starts_at: at(-H), status: 'review' }), NOW), 'waiting');
    assert.equal(S.matchPhase(done(), NOW), 'done');
    assert.equal(S.matchPhase(mk({ status: 'cancelled' }), NOW), 'cancelled');
  });

  it('без итога больше трёх суток — «зависший»: из «ждём итог» уходит', () => {
    assert.equal(S.isStale(mk({ starts_at: at(-3 * 86400000 + 1000), phase: 'waiting' }), NOW), false);
    assert.equal(S.isStale(mk({ starts_at: at(-3 * 86400000), phase: 'waiting' }), NOW), true);
    assert.equal(S.isStale(done({ starts_at: at(-5 * 86400000) }), NOW), false);
  });
});

describe('десять состояний строки (макет States)', () => {
  it('ход принят: впереди, ход есть, можно менять', () => {
    const r = S.rowModel(mk({ my_pick: PICK, starts_at: at(23.5 * H), city: 'Минск' }), NOW);
    assert.equal(r.label, 'ЗАВТРА 19:00 · ЭКСТРАЛИГА · МИНСК');
    assert.deepEqual(r.center, { big: '19:00', cap: 'ход' + NBSP + 'открыт' });
    assert.deepEqual(r.move, { label: 'ТВОЙ ХОД', text: 'Юность · 3:1', muted: false });
    assert.deepEqual(r.right, { kind: 'button', text: 'Изменить', gold: false });
    assert.equal(r.chip, null);
  });

  it('хода нет: золотая кнопка «Сделать ход»', () => {
    const r = S.rowModel(mk({ starts_at: at(24 * H) }), NOW);
    assert.equal(r.move.text, 'ещё' + NBSP + 'не' + NBSP + 'выбран');
    assert.equal(r.move.muted, true);
    assert.deepEqual(r.right, { kind: 'button', text: 'Сделать ход', gold: true });
  });

  it('ход без счёта показывает только команду', () => {
    assert.equal(S.rowModel(mk({ my_pick: SIDE_ONLY }), NOW).move.text, 'Шахтёр');
  });

  it('идёт: неофициальный счёт, очков нет', () => {
    const m = mk({ starts_at: at(-H), open: false, phase: 'live', my_pick: PICK, live: { home_score: 1, away_score: 0 } });
    const r = S.rowModel(m, NOW);
    assert.deepEqual(r.chip, { kind: 'live', text: 'ИДЁТ' });
    assert.deepEqual(r.center, { big: '1:0', cap: 'по' + NBSP + 'ходу игры' });
    assert.deepEqual(r.right, { kind: 'note', text: 'Очки' + NBSP + '— после' + NBSP + 'итога' });
    assert.equal(S.rowModel(Object.assign({}, m, { live: null }), NOW).center.big, '—:—');
  });

  it('ждём итог: без счёта и без срока, тот же вид для ручной проверки', () => {
    for (const m of [mk({ starts_at: at(-4 * H), open: false, phase: 'waiting', my_pick: PICK, live: { home_score: 2, away_score: 1 } }), mk({ starts_at: at(-H), open: false, status: 'review', my_pick: PICK })]) {
      const r = S.rowModel(m, NOW);
      assert.deepEqual(r.chip, { kind: 'wait', text: 'ЖДЁМ ИТОГ' });
      assert.deepEqual(r.center, { big: '—:—', cap: 'итог' + NBSP + 'уточняем' });
      assert.equal(r.right.kind, 'note');
    }
  });

  it('матч окончен, итог сверяем (m.checking с сервера) — своя подпись; идущий дольше трёх часов — прежняя', () => {
    const probed = S.rowModel(mk({ starts_at: at(-2 * H), open: false, phase: 'waiting', checking: true, my_pick: PICK }), NOW);
    assert.deepEqual(probed.chip, { kind: 'wait', text: 'ЖДЁМ ИТОГ' });
    assert.deepEqual(probed.center, { big: '—:—', cap: 'Матч' + NBSP + 'окончен · сверяем' + NBSP + 'счёт' });
    const review = S.rowModel(mk({ starts_at: at(-5 * H), open: false, status: 'review', phase: 'waiting', checking: true }), NOW);
    assert.equal(review.center.cap, 'Матч' + NBSP + 'окончен · сверяем' + NBSP + 'счёт');
    const longLive = S.rowModel(mk({ starts_at: at(-4 * H), open: false, phase: 'waiting', checking: false, my_pick: PICK }), NOW);
    assert.equal(longLive.center.cap, 'итог' + NBSP + 'уточняем');
    // Трое суток без итога — «не подтверждён», даже если сервер его видел.
    const stale = S.rowModel(mk({ starts_at: at(-4 * 86400000), open: false, phase: 'waiting', checking: true, my_pick: PICK }), NOW);
    assert.equal(stale.center.cap, 'итог' + NBSP + 'не' + NBSP + 'подтверждён');
  });

  it('итог не подтверждён больше трёх суток — честная подпись, всё ещё без счёта', () => {
    const r = S.rowModel(mk({ starts_at: at(-4 * 86400000), open: false, phase: 'waiting', my_pick: PICK }), NOW);
    assert.equal(r.stale, true);
    assert.deepEqual(r.chip, { kind: 'wait', text: 'БЕЗ ИТОГА' });
    assert.equal(r.center.big, '—:—');
    assert.ok(/не подтверждён/.test(r.center.cap));
  });

  it('угадал: очки с козырем; золото только за «в точку»', () => {
    const won = S.rowModel(done({ my_pick: { side: 'away', home_score: 0, away_score: 2, points: 30, doubled: false }, my_points: 30 }), NOW);
    assert.deepEqual(won.right, { kind: 'points', tone: 'pos', text: '+30', trump: false });
    assert.deepEqual(won.center, { big: '0:4', cap: 'итог' });
    assert.equal(won.label, 'ВС 8 НОЯБРЯ · 13:30 · ЭКСТРАЛИГА');
    const exact = S.rowModel(done({ my_pick: { side: 'away', home_score: 0, away_score: 4, points: 50, doubled: true }, my_points: 100 }), NOW);
    assert.deepEqual(exact.right, { kind: 'points', tone: 'exact', text: '+100 В' + NBSP + 'ТОЧКУ', trump: true });
    // Козырь удваивает и обычные очки, но не красит их золотом.
    const twice = S.rowModel(done({ my_pick: { side: 'away', home_score: null, away_score: null, points: 20, doubled: true }, my_points: 40 }), NOW);
    assert.equal(twice.right.tone, 'pos');
    assert.equal(twice.right.text, '+40');
  });

  it('не угадал: нейтральная плашка с нулём, без красного смысла', () => {
    const r = S.rowModel(done({ my_pick: { side: 'home', home_score: null, away_score: null, points: 0, doubled: false }, my_points: 0 }), NOW);
    assert.deepEqual(r.right, { kind: 'points', tone: 'zero', text: '0 · не' + NBSP + 'угадал', trump: false });
  });

  it('очки ещё не посчитаны — «Считаем очки», а не ноль', () => {
    const r = S.rowModel(done({ my_pick: PICK }), NOW);
    assert.deepEqual(r.right, { kind: 'note', text: 'Считаем очки' });
  });

  it('овертайм и буллиты подписаны под счётом', () => {
    assert.equal(S.rowModel(done({ result: { home_score: 2, away_score: 3, decided_in: 'ot' } }), NOW).center.cap, 'в' + NBSP + 'овертайме');
    assert.equal(S.rowModel(done({ result: { home_score: 2, away_score: 1, decided_in: 'so' } }), NOW).center.cap, 'по' + NBSP + 'буллитам');
  });

  it('не ходил: подпись без кнопки и без очков', () => {
    const r = S.rowModel(done(), NOW);
    assert.deepEqual(r.move, { label: 'ТВОЙ ХОД', text: 'ты' + NBSP + 'не' + NBSP + 'ходил', muted: true });
    assert.deepEqual(r.right, { kind: 'none' });
    assert.equal(S.rowModel(mk({ starts_at: at(-H), open: false, phase: 'live' }), NOW).move.text, 'ты' + NBSP + 'не' + NBSP + 'ходил');
  });

  it('перенесён: новое время, «было …», ход сохранён', () => {
    const r = S.rowModel(mk({ my_pick: { side: 'home', home_score: 2, away_score: 0, points: null, doubled: false }, starts_at: at(24 * H), moved_from: at(23 * H) }), NOW);
    assert.deepEqual(r.chip, { kind: 'moved', text: 'ПЕРЕНЕСЁН' });
    assert.equal(r.label, 'ВТ 10 НОЯБРЯ · ЭКСТРАЛИГА');
    assert.deepEqual(r.center, { big: '19:30', cap: 'было' + NBSP + '18:30' });
    assert.equal(r.move.text, 'Юность · 2:0');
    assert.equal(r.right.text, 'Изменить');
  });

  it('отменён: ход снят, в очки не входит', () => {
    const r = S.rowModel(mk({ status: 'cancelled', phase: 'cancelled', open: false, my_pick: SIDE_ONLY, starts_at: at(24 * H) }), NOW);
    assert.deepEqual(r.chip, { kind: 'cancelled', text: 'ОТМЕНЁН' });
    assert.deepEqual(r.center, { big: '—', cap: 'матч' + NBSP + 'отменён' });
    assert.equal(r.struck, true);
    assert.deepEqual(r.move, { label: 'ТВОЙ ХОД', text: 'ход' + NBSP + 'снят', muted: true });
    assert.equal(r.right.kind, 'note');
  });

  it('ходы закрылись за минуту до старта: кнопки нет', () => {
    const r = S.rowModel(mk({ starts_at: at(30000), open: false, my_pick: PICK }), NOW);
    assert.equal(r.center.cap, 'ходы' + NBSP + 'закрыты');
    assert.equal(r.right.kind, 'note');
  });
});

describe('слова строк', () => {
  const BANNED = /ставк|коэффициент|прогноз|пари\b|выигрыш|букмекер|банк\b|ставь|поставить|срок|%|\p{Extended_Pictographic}/iu;
  const WAIT_PROMISE = /обычно|за\s+полчаса|минут|через\s+\d/i;

  function strings(row) {
    const out = [row.label, row.center.big, row.center.cap, row.move.label, row.move.text, row.right.text, row.chip && row.chip.text];
    return out.filter(Boolean);
  }

  it('нигде нет азартных слов, процентов, эмодзи; «ждём итог» не обещает время', () => {
    const rows = [
      mk({ my_pick: PICK }),
      mk({ moved_from: at(H / 2) }),
      mk({ starts_at: at(-H), phase: 'live', open: false, my_pick: PICK, live: { home_score: 1, away_score: 0 } }),
      mk({ starts_at: at(-4 * H), phase: 'waiting', open: false, my_pick: PICK }),
      mk({ starts_at: at(-4 * 86400000), phase: 'waiting', open: false, my_pick: PICK }),
      done({ my_pick: Object.assign({}, PICK, { points: 50, doubled: true }), my_points: 100 }),
      done({ my_pick: Object.assign({}, PICK, { points: 0 }), my_points: 0 }),
      done(),
      mk({ status: 'cancelled', open: false, my_pick: PICK }),
    ].map((m) => S.rowModel(m, NOW));
    for (const r of rows) for (const s of strings(r)) assert.doesNotMatch(s, BANNED, s);
    for (const r of rows.filter((x) => x.phase === 'waiting')) for (const s of strings(r)) assert.doesNotMatch(s, WAIT_PROMISE, s);
    assert.doesNotMatch(S.waitNote(true), WAIT_PROMISE);
    assert.doesNotMatch(S.waitNote(false), WAIT_PROMISE);
    for (const s of [S.waitNote(true), S.waitNote(false), S.MATCHES_TITLE, S.ENTRY_TITLE, S.MATCHES_EMPTY.head, S.MATCHES_EMPTY.text, S.MATCHES_EMPTY.cta]) assert.doesNotMatch(s, BANNED, s);
  });

  it('про бота — только если игрок включил сообщения', () => {
    assert.ok(/в бота/.test(S.waitNote(true)));
    assert.ok(!/бот/.test(S.waitNote(false)));
  });

  it('файлы экрана не содержат азартных слов и множителя до матча', () => {
    const BAN = /ставк|коэффициент|прогноз|пари\b|выигрыш|букмекер|банк\b|ставь|поставить|срок/i;
    const file = path.join(__dirname, '../../static/webapp/kto-kogo-matches.js');
    if (!fs.existsSync(file)) return;
    const src = fs.readFileSync(file, 'utf8');
    const quoted = [...src.matchAll(/'((?:[^'\\\n]|\\.){2,})'/g)].map((m) => m[1]);
    assert.deepEqual(quoted.filter((s) => BAN.test(s) || /×/.test(s)), []);
  });
});

describe('секции списка', () => {
  const list = [
    mk({ id: 1, starts_at: at(-H), phase: 'live', open: false, my_pick: PICK }),
    mk({ id: 2, starts_at: at(-4 * H), phase: 'waiting', open: false, my_pick: PICK }),
    mk({ id: 3, starts_at: at(-3.5 * H), phase: 'waiting', open: false, my_pick: PICK }),
    mk({ id: 4, starts_at: at(24 * H) }),
    mk({ id: 5, starts_at: at(23.5 * H), my_pick: PICK }),
    mk({ id: 6, starts_at: at(50 * H) }),
    done({ id: 7, starts_at: at(-30 * H) }),
    done({ id: 8, starts_at: at(-31 * H), my_pick: PICK }),
    done({ id: 9, starts_at: at(-80 * H) }),
    mk({ id: 10, starts_at: at(-4 * 86400000), phase: 'waiting', open: false, my_pick: PICK }),
    mk({ id: 11, status: 'cancelled', phase: 'cancelled', open: false, starts_at: at(26 * H), my_pick: SIDE_ONLY }),
    mk({ id: 12, status: 'cancelled', phase: 'cancelled', open: false, starts_at: at(-60 * H), my_pick: SIDE_ONLY }),
    done({ id: 13, starts_at: at(-49 * H) }),
  ];
  const g = S.groupMatches(list, NOW);

  it('«Идёт и ждём итог»: идущие первыми, дальше ждущие по времени старта', () => {
    assert.deepEqual(g.active.map((m) => m.id), [1, 2, 3]);
  });

  it('«Впереди»: по дням, внутри дня по времени; отменённый с ходом остаётся строкой', () => {
    assert.deepEqual(g.upcoming.map((d) => d.head), ['ЗАВТРА, ВТ 10 НОЯБРЯ', 'СР 11 НОЯБРЯ']);
    assert.deepEqual(g.upcoming[0].items.map((m) => m.id), [5, 4, 11]);
    assert.deepEqual(g.upcoming[1].items.map((m) => m.id), [6]);
  });

  it('«Итог есть»: с итогом за двое суток, от новых к старым — над «Впереди», а не под ним', () => {
    assert.deepEqual(g.recent.map((m) => m.id), [7, 8]);
  });

  it('«Сыграли»: от новых к старым; без итога старше трёх суток и прошедшие отменённые тоже здесь', () => {
    assert.deepEqual(g.done.flatMap((d) => d.items.map((m) => m.id)), [13, 12, 9, 10]);
  });

  it('заголовки дней: сегодня, завтра, вчера, дальше — просто дата', () => {
    assert.equal(S.dayHeading(at(0), NOW), 'СЕГОДНЯ, ПН 9 НОЯБРЯ');
    assert.equal(S.dayHeading(at(24 * H), NOW), 'ЗАВТРА, ВТ 10 НОЯБРЯ');
    assert.equal(S.dayHeading(at(-24 * H), NOW), 'ВЧЕРА, ВС 8 НОЯБРЯ');
    assert.equal(S.dayHeading(at(72 * H), NOW), 'ЧТ 12 НОЯБРЯ');
  });
});

describe('сводка и вход', () => {
  it('две цифры: ждут итога и очки · место; склонения', () => {
    assert.deepEqual(S.matchesSummary({ points: 240, rank: 12, played: 14 }, 3), { awaiting: '3', awaitingLabel: 'ждут итога', points: '240', pointsLabel: 'очков · 12-е' + NBSP + 'место' });
    assert.equal(S.matchesSummary({ points: 1, rank: 1 }, 1).awaitingLabel, 'ждёт итога');
    assert.equal(S.matchesSummary({ points: 1, rank: 1 }, 1).pointsLabel, 'очко · 1-е' + NBSP + 'место');
    assert.equal(S.matchesSummary({ points: 22, rank: 5 }, 0).pointsLabel, 'очка · 5-е' + NBSP + 'место');
    // Игрок без начисленных очков: место не выдумываем.
    assert.deepEqual(S.matchesSummary(null, 2), { awaiting: '2', awaitingLabel: 'ждут итога', points: '0', pointsLabel: 'очков · пока без места' });
    assert.equal(S.matchesSummary({ points: 12345, rank: 3 }, 0).points, '12' + NBSP + '345');
  });

  it('«Сыграли · N ходов» — это me.played, а не число матчей', () => {
    assert.equal(S.playedCount({ played: 14 }), '14' + NBSP + 'ходов');
    assert.equal(S.playedCount({ played: 1 }), '1' + NBSP + 'ход');
    assert.equal(S.playedCount({ played: 3 }), '3' + NBSP + 'хода');
    assert.equal(S.playedCount(null), '');
  });

  it('строка входа из хаба: «3 ждут итога · 12-е место»', () => {
    assert.equal(S.entryLine(3, { rank: 12 }), '3' + NBSP + 'ждут итога · 12-е' + NBSP + 'место');
    assert.equal(S.entryLine(0, { rank: 12 }), '12-е' + NBSP + 'место');
    assert.equal(S.entryLine(1, null), '1' + NBSP + 'ждёт итога');
    assert.equal(S.entryLine(0, null), 'Статус каждого хода');
  });

  it('новый игрок: пустое состояние, пока нет ни одного хода и нечего подгружать', () => {
    assert.equal(S.matchesEmpty([mk({ id: 1 }), mk({ id: 2 })], false), true);
    assert.equal(S.matchesEmpty([mk({ id: 1, my_pick: PICK })], false), false);
    assert.equal(S.matchesEmpty([], true), false); // старые ходы могут лежать на следующих страницах
    assert.equal(S.nearestOpen([mk({ id: 2, starts_at: at(5 * H) }), mk({ id: 1, starts_at: at(2 * H) }), mk({ id: 3, open: false })]).id, 1);
    assert.equal(S.nearestOpen([mk({ open: false })]), null);
  });
});

describe('слияние страниц', () => {
  const t = (n) => at(-n * H);
  const hist = (id, hoursAgo) => done({ id, starts_at: t(hoursAgo) });
  // Курсор сервера: микросекунды от эпохи и id.
  const cursor = (m) => String(new Date(m.starts_at).getTime() * 1000) + '_' + m.id;

  it('«Показать раньше» дописывает страницу без дублей', () => {
    const prev = { items: [hist(3, 30), hist(2, 31)], hasMore: true, cursor: 'c1' };
    const next = S.appendMatchPage(prev, [hist(2, 31), hist(1, 32)], { has_more: false, next_before: null });
    assert.deepEqual(next.items.map((m) => m.id), [1, 2, 3]);
    assert.equal(next.hasMore, false);
    assert.equal(next.cursor, null);
  });

  it('обновление первой страницы не теряет подгруженное, но заменяет устаревшее', () => {
    const loaded = [hist(1, 60), hist(2, 50), hist(3, 40), hist(4, 30)]; // 1 и 2 — подгружены раньше
    const prev = { items: loaded.concat([mk({ id: 9, starts_at: at(-H), phase: 'live', open: false })]), hasMore: true, cursor: 'old' };
    const fresh = [hist(3, 40), hist(4, 30), hist(5, 20)];
    const merged = S.mergeMatchList(prev, fresh, { has_more: true, next_before: cursor(fresh[0]) }, NOW);
    assert.deepEqual(merged.items.map((m) => m.id), [1, 2, 3, 4, 5]); // 9 (был «идёт») свежий ответ уже не вернул — не оставляем
    assert.equal(merged.cursor, 'old');
    assert.equal(merged.hasMore, true);
  });

  it('если в свежей странице вся история — прежние страницы не нужны', () => {
    const prev = { items: [hist(1, 60)], hasMore: false, cursor: null };
    const merged = S.mergeMatchList(prev, [hist(3, 40)], { has_more: false, next_before: null }, NOW);
    assert.deepEqual(merged.items.map((m) => m.id), [3]);
    assert.equal(merged.hasMore, false);
  });

  it('первая загрузка без прежнего состояния', () => {
    const merged = S.mergeMatchList(null, [hist(3, 40)], { has_more: true, next_before: 'c' }, NOW);
    assert.deepEqual(merged, { items: merged.items, hasMore: true, cursor: 'c' });
  });
});

describe('хаб игры: ждём итог', () => {
  const list = [
    mk({ id: 1, starts_at: at(-H), phase: 'live', open: false, my_pick: PICK }),
    mk({ id: 2, starts_at: at(-4 * H), phase: 'waiting', open: false, my_pick: PICK }),
    mk({ id: 3, starts_at: at(-4 * H), phase: 'waiting', open: false }), // хода нет — в блок не идёт
    mk({ id: 4, starts_at: at(-4 * 86400000), phase: 'waiting', open: false, my_pick: PICK }), // зависший
    mk({ id: 5, starts_at: at(2 * H), my_pick: PICK }),
    done({ id: 6, my_pick: PICK }),
  ];

  it('начавшийся матч с моим ходом без итога остаётся в хабе', () => {
    assert.deepEqual(S.pendingMatches(list, NOW).map((m) => m.id), [1, 2]);
  });

  it('заголовок блока по составу', () => {
    assert.equal(S.pendingHead([list[1]], 'Юность', NOW), 'ТВОЯ КОМАНДА · ЖДЁМ ИТОГ');
    assert.equal(S.pendingHead([list[1]], null, NOW), 'ЖДЁМ ИТОГ');
    assert.equal(S.pendingHead([list[1]], 'Лида', NOW), 'ЖДЁМ ИТОГ');
    assert.equal(S.pendingHead([list[0]], null, NOW), 'ИДЁТ');
    assert.equal(S.pendingHead([list[0], list[1]], null, NOW), 'ИДЁТ И ЖДЁМ ИТОГ');
  });

  it('«Матчи дня» не дублирует матчи из блока «ждём итог»', () => {
    const day = [mk({ id: 20, starts_at: at(H), my_pick: PICK }), mk({ id: 21, starts_at: at(-H), phase: 'live', open: false, my_pick: PICK }), mk({ id: 22, starts_at: at(2 * H) })];
    const d = S.dayMatches(day, NOW, [21]);
    assert.deepEqual(d.items.map((m) => m.id), [20, 22]);
    // Прежний вызов с одним id продолжает работать.
    assert.deepEqual(S.dayMatches(day, NOW, 20).items.map((m) => m.id), [21, 22]);
  });
});
