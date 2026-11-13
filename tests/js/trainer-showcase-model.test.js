/**
 * TASK-357: витрина тренеров и запись в Mini App — правила дизайна PDEC-033.
 * Run: node --test tests/js/trainer-showcase-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const M = require(path.resolve(__dirname, '../../static/webapp/trainer-showcase-model.js'));
const RuName = require(path.resolve(__dirname, '../../static/webapp/ru-person-name.js'));

const tiers = (pairs) => pairs.map(([kind, cents], i) => ({ id: 100 + i, tier_kind: kind, price_cents: cents, currency_code: 'BYN' }));
const svc = (id, t, extra = {}) => ({ service_id: id, is_public: true, currency_code: 'BYN', price_cents: null, price_tiers: t, ...extra });

const gaevsky = {
  id: 9, name: 'Александр Гаевский', first_name: 'Александр', can_book: true,
  services: [svc(1, tiers([['child', 5000], ['adult', 5500], ['two_children', 7500], ['adult_and_child', 8000]])), svc(2, tiers([['adult', 5500]]))],
  arenas: [{ id: 3, name: 'ТЦ «Замок»', rental_cents: 900 }],
  windows: [{ slot_id: 1, starts_at: '2026-11-07T17:15:00+03:00', ends_at: '2026-11-07T18:00:00+03:00', arena_id: 3 }],
  session_duration_minutes: 45,
};
const vlad = { ...gaevsky, id: 11, windows: [{ slot_id: 2, starts_at: '2026-11-08T10:00:00+03:00' }] };
const katusha = { id: 74, can_book: false, services: [svc(1, []), svc(3, [])], arenas: [{ id: 3, name: 'ТЦ «Замок»' }], windows: [] };
const custom = { id: 80, can_book: true, services: [svc(99, tiers([['adult', 4000]]), { is_public: false })], arenas: [{ id: 3, name: 'X' }], windows: [] };
const rollersOnly = { id: 81, can_book: true, services: [svc(5, tiers([['adult', 4000]]))], arenas: [], windows: [] };

describe('вкладки и правило показа', () => {
  it('«С клюшкой» = хоккейное катание и ОХМ; своя услуга и ролики во вкладки не идут', () => {
    const hockey = { ...gaevsky, services: [svc(6, tiers([['adult', 5000]]))] };
    assert.equal(M.trainerInDirection(hockey, 's-klyushkoy'), true);
    assert.equal(M.trainerInDirection(custom, 'all'), false);
    assert.equal(M.trainerInDirection(rollersOnly, 'all'), false);
  });

  it('показ: услуга направления и (цена или каток)', () => {
    assert.equal(M.trainerInDirection(katusha, 'figurnoe'), true); // каток есть, цены нет
    assert.equal(M.trainerInDirection({ ...katusha, arenas: [] }, 'figurnoe'), false);
  });

  it('сверху — с онлайн-записью по ближайшему окну, без записи — в конце', () => {
    const list = M.visibleTrainers([katusha, vlad, gaevsky], 's-nulya', null);
    assert.deepEqual(list.map((t) => t.id), [9, 11, 74]);
  });

  it('фильтр катка и числа на вкладках', () => {
    const counts = M.tabCounts([gaevsky, katusha], 3);
    assert.equal(counts['s-nulya'], 2);
    assert.equal(counts.figurnoe, 1);
    assert.equal(M.tabCounts([gaevsky], 999)['s-nulya'], 0);
    assert.deepEqual(M.arenaOptions([gaevsky, katusha], 's-nulya'), [{ id: 3, name: 'ТЦ «Замок»', count: 2 }]);
  });
});

describe('карточка', () => {
  it('цена по тарифам направления', () => {
    assert.equal(M.cardPriceHtml(gaevsky.services[0]), 'Ребёнок — <b>50 BYN</b> · взрослый — <b>55 BYN</b>');
    assert.equal(M.cardPriceHtml(svc(1, tiers([['child', 5000], ['adult', 5000]]))), 'Дети и взрослые — <b>50 BYN</b>');
    assert.equal(M.cardPriceHtml(svc(1, [], { price_cents: 5500 })), '<b>55 BYN</b> за занятие');
    assert.equal(M.cardPriceHtml(svc(1, [])), 'Цену уточните у тренера');
  });

  it('оценка — с первой и с числом; «В Glide с …» без числа занятий; стаж', () => {
    assert.equal(M.ratingLine(5, 0), '');
    assert.equal(M.ratingLine(null, 2), '');
    assert.equal(M.ratingLine(5, 1), '★ 5,0 · 1 оценка');
    assert.equal(M.ratingLine(5, 2), '★ 5,0 · 2 оценки');
    assert.equal(M.ratingLine(5, 7), '★ 5,0 · 7 оценок');
    assert.equal(M.glideSince('2026-04'), 'В Glide с апреля 2026');
    assert.equal(M.glideSince(null), '');
    assert.equal(M.experienceBadge(6), 'Тренирует 6 лет');
    assert.equal(M.experienceBadge(1), 'Тренирует 1 год');
    assert.equal(M.experienceBadge(null), '');
  });

  it('каркас: пустые строки не показываем', () => {
    assert.deepEqual(M.cardFacts(gaevsky, 's-nulya'), [
      ['Кого учит', 'детей и взрослых'], ['Занятие', '45 мин, индивидуально'], ['Где', 'ТЦ «Замок»'],
    ]);
    // Без тарифов и онлайн-записи — «О себе» и «Где», как Katusha в прототипе.
    assert.deepEqual(M.cardFacts({ ...katusha, description: 'Мастер спорта', session_duration_minutes: 45 }, 'figurnoe'), [
      ['О себе', '«Мастер спорта»'], ['Где', 'ТЦ «Замок»'],
    ]);
  });
});

describe('«Кто будет заниматься?»', () => {
  it('строки — тарифы тренера; «двое» — отдельно и только если есть', () => {
    const o = M.whoOptions(gaevsky.services[0]);
    assert.deepEqual(o.single.map((r) => [r.title, r.price]), [['Ребёнок', '50 BYN'], ['Взрослый', '55 BYN']]);
    assert.deepEqual(o.duo.map((r) => r.title), ['Двое детей', 'Взрослый и ребёнок']);
    assert.equal(M.whoOptions(gaevsky.services[1]).duo.length, 0);
    assert.deepEqual(M.whoOptions(gaevsky.services[1]).single.map((r) => r.kind), ['adult']);
  });

  it('цены равны — без цены справа', () => {
    const o = M.whoOptions(svc(1, tiers([['child', 5000], ['adult', 5000]])));
    assert.deepEqual(o.single.map((r) => r.price), ['', '']);
  });

  it('у каждого участника своё поле; взрослому — имя из Telegram', () => {
    assert.deepEqual(M.nameFields('adult_and_child', 'Анна').map((f) => [f.label, f.value]), [['Ваше имя', 'Анна'], ['Имя ребёнка', '']]);
    assert.equal(M.nameFields('two_children', 'Анна').length, 2);
  });

  it('двое — одна запись на первого участника, второй — в комментарии тренеру', () => {
    const plan = M.newClientBookingPlan('two_children', { child: 'Соня', child2: 'Миша' });
    assert.equal(plan.profile, 'child');
    assert.equal(plan.childName, 'Соня');
    assert.equal(M.bookingComment(plan.secondName, 'Первый раз'), 'Второй участник: Миша\nПервый раз');
    assert.equal(M.newClientBookingPlan('adult', { self: 'Анна' }).profile, 'self');
    assert.equal(M.bookingComment('', ''), '');
  });
});

describe('постоянный ученик', () => {
  const s = gaevsky.services[0];
  const sonya = { client_id: 1, role: 'guardian', first_name: 'Соня' };
  const misha = { client_id: 2, role: 'guardian', first_name: 'Миша' };
  const me = { client_id: 3, role: 'self', first_name: 'Анна' };
  const granny = { client_id: 4, role: 'family_access', first_name: 'Бабушка' };
  const kids = { knownChildIds: { 1: true, 2: true } };

  it('вид профиля: взрослый — свой; детский — только известный ребёнок; семья — не угадываем', () => {
    assert.equal(M.profileKind(me), 'adult');
    assert.equal(M.profileKind(sonya), null);
    assert.equal(M.profileKind(granny), null);
    assert.equal(M.profileKind(sonya, kids), 'child');
  });

  it('один — тариф прошлой записи ЭТОГО профиля; чужая подсказка не применяется', () => {
    // Подсказка про Соню (детский, id 100) не переносится на Анну.
    assert.equal(M.regularTier(s, [me], { hints: { 1: 100 } }).tier_kind, 'adult');
    assert.equal(M.regularTier(s, [sonya], { hints: { 1: 100 } }).tier_kind, 'child');
    assert.equal(M.hintTier(s, me, { hints: { 1: 100 } }), null);
    // Взрослый профиль семьи без истории — тариф не угадываем.
    assert.equal(M.regularTier(s, [granny]), null);
    assert.equal(M.regularTier(s, [granny], { override: 101 }).tier_kind, 'adult');
  });

  it('единственный тариф не достаётся профилю другого вида', () => {
    const onlyChild = svc(1, tiers([['child', 4000]]));
    assert.equal(M.regularTier(onlyChild, [me]), null);
    assert.equal(M.regularTier(onlyChild, [sonya], kids).tier_kind, 'child');
  });

  it('двое — тариф пары при известных видах, иначе явный выбор; третий неактивен', () => {
    assert.equal(M.regularTier(s, [sonya, misha], kids).tier_kind, 'two_children');
    assert.equal(M.regularTier(s, [sonya, me], kids).tier_kind, 'adult_and_child');
    assert.equal(M.regularTier(s, [granny, me]), null);
    assert.deepEqual(M.tierChoices(s, 2).map((t) => t.tier_kind), ['two_children', 'adult_and_child']);
    assert.equal(M.canAddProfile(s, [sonya, misha], me, kids), false);
  });

  it('двое нельзя, если у услуги нет тарифов на двоих (или нет тарифов вовсе)', () => {
    assert.equal(M.canAddProfile(gaevsky.services[1], [me], sonya, kids), false);
    assert.equal(M.canAddProfile(svc(1, [], { price_cents: 5000 }), [me], sonya, kids), false);
    const noTwoAdults = svc(1, tiers([['adult', 5000], ['adult_and_child', 8000]]));
    assert.equal(M.canAddProfile(noTwoAdults, [me], { client_id: 9, role: 'self' }), false);
  });

  it('групповой слот: одно место на запись — второго не отметить, даже если у услуги есть тариф на двоих', () => {
    assert.equal(M.canAddProfile(s, [sonya], misha, { ...kids, group: true }), false);
    assert.equal(M.canAddProfile(s, [], sonya, { ...kids, group: true }), true);
    assert.equal(M.canAddProfile(s, [sonya], misha, kids), true);
    assert.equal(M.whoOptions(s, { group: true }).duo.length, 0);
  });

  it('«спишем 1» — только если абонемент точно покрывает тариф', () => {
    const base = { trainer_id: 9, status: 'active', sessions_remaining: 4, service_ids: [], product_name: '8 занятий' };
    const any = { ...base, tier_kinds: [] };
    const childOnly = { ...base, tier_kinds: ['child'] };
    const unknown = { ...base };
    assert.equal(M.usablePass([any], 9, 1, 'adult').certain, true);
    assert.equal(M.usablePass([childOnly], 9, 1, 'adult').certain, false);
    assert.equal(M.usablePass([unknown], 9, 1, 'child').certain, false);
    assert.equal(M.usablePass([{ ...any, service_ids: [2] }], 9, 1, 'child'), null);
    const child = M.tierByKind(s, 'child');
    assert.match(M.payLine({ tier: child, pass: M.usablePass([any], 9, 1, 'child') }), /Абонемент «8 занятий»<\/b>: спишем 1, останется 3\./);
    const careful = M.payLine({ tier: M.tierByKind(s, 'adult'), pass: M.usablePass([childOnly], 9, 1, 'adult') });
    assert.doesNotMatch(careful, /спишем/);
    assert.match(careful, /^<b>55 BYN<\/b> — тренеру на месте\. Если есть абонемент — тренер может списать занятие с него\./);
    const duo = M.payLine({ tier: M.tierByKind(s, 'two_children'), pass: M.usablePass([any], 9, 1, 'two_children'), duo: true });
    assert.match(duo, /Двое детей — 75 BYN<\/b> за двоих тренеру на месте\. Вместо оплаты тренер может списать занятие с абонемента\./);
  });

  it('групповой слот: цена — та, что запишет сервер (group_price_cents)', () => {
    assert.equal(M.payLine({ tier: null, fallbackCents: 2500 }), '<b>25 BYN</b> — тренеру на месте. Билет на сеанс — в кассе катка.');
  });

  it('оплата нового: занятие, билет и прокат, если есть', () => {
    assert.equal(
      M.payLine({ tier: M.tierByKind(s, 'child'), rentalCents: 900 }),
      '<b>50 BYN</b> — тренеру на месте. Билет на сеанс — в кассе катка, прокат коньков — 9 BYN, если нужен.'
    );
  });
});

describe('даты и имена', () => {
  it('сводка: «Сегодня, 17:15–18:00», «Вт, 10 ноября»; неделя', () => {
    assert.equal(M.slotWhen({ slot_date: '2026-11-07', start_time: '17:15', end_time: '18:00' }, '2026-11-07'), 'Сегодня, 17:15–18:00');
    assert.equal(M.dayLabel('2026-11-10', '2026-11-07'), 'Вт, 10 ноября');
    assert.equal(M.weekRange('2026-11-07'), '7–13 ноября');
    assert.equal(M.ctaDay('2026-11-07', '2026-11-07'), 'сегодня');
    assert.equal(M.ctaDay('2026-11-10', '2026-11-07'), '10 ноября');
    assert.equal(M.weekRange('2026-11-28'), '28 ноября – 4 декабря');
    const days = M.weekDays('2026-11-07', [{ slot_date: '2026-11-08' }]);
    assert.deepEqual(days.slice(0, 2).map((d) => [d.wd, d.day, d.off]), [['сб', 7, true], ['вс', 8, false]]);
  });

  it('окно витрины → слот', () => {
    assert.deepEqual(M.windowToSlot(gaevsky.windows[0]), { id: 1, slot_date: '2026-11-07', start_time: '17:15', end_time: '18:00', arena_id: 3, capacity: 1 });
  });

  it('«Запись отправлена Александру»; латиница — как есть', () => {
    assert.equal(M.dativeFirst('Александр', RuName), 'Александру');
    assert.equal(M.dativeFirst('Katusha', RuName), 'Katusha');
    assert.equal(M.selfBookingLine('Мария', RuName, { canWrite: true }), 'Мария записывает сама — напишите и договоритесь о времени и цене.');
    assert.equal(M.selfBookingLine('Мария', RuName, { canRequest: true }), 'Мария записывает сама — оставьте заявку и договоритесь о времени и цене.');
    assert.match(M.selfBookingLine('Katusha', RuName, {}), /^Онлайн-записи нет\. откройте Telegram/);
  });

  it('номер из requestContact', () => {
    assert.equal(M.phoneFromContact({ responseUnsafe: { contact: { phone_number: '375291234567' } } }), '+375291234567');
    assert.equal(M.phoneFromContact({ response: 'contact=' + encodeURIComponent(JSON.stringify({ phone_number: '+79123456789' })) }), '+79123456789');
    assert.equal(M.phoneFromContact(null), '');
  });
});

describe('своя услуга тренера во вкладке (TASK-353)', () => {
  const Mo = require('../../static/webapp/trainer-showcase-model.js');
  const own = (dir) => ({ service_id: 11, is_public: false, direction_service_id: dir, price_cents: 6000, price_tiers: [] });

  it('привязанная к «Фигурному» — во вкладке «Фигурное», без привязки — нигде', () => {
    const linked = { id: 1, services: [own(3)], arenas: [{ id: 3 }] };
    const loose = { id: 2, services: [own(null)], arenas: [{ id: 3 }] };
    const fig = Mo.DIRECTIONS.find((d) => d.ids && d.ids.indexOf(3) >= 0).key;
    assert.equal(Mo.servicesInDirection(linked, fig).length, 1);
    assert.equal(Mo.servicesInDirection(loose, fig).length, 0);
    assert.equal(Mo.servicesInDirection(loose, 'all').length, 0);
    // Привязка к роликам/ОФП — не вкладка.
    assert.equal(Mo.servicesInDirection({ id: 3, services: [own(7)] }, 'all').length, 0);
  });
});

describe('«от» вкладки — с сервера (min_price_by_direction)', () => {
  const Mo = require('../../static/webapp/trainer-showcase-model.js');
  const t = (id, mins) => ({ id, services: [], arenas: [], min_price_by_direction: mins });
  const p = (cents) => ({ cents, currency: 'BYN' });

  it('минимум по показанным тренерам для ключа вкладки; дробная цена абонемента — как есть', () => {
    const list = [t(1, { all: p(4187), 's-nulya': p(5000), 's-klyushkoy': p(4187) }), t(2, { all: p(2500), 's-nulya': p(2500) })];
    assert.deepEqual(Mo.minPriceOf(list, 'all'), p(2500));
    assert.deepEqual(Mo.minPriceOf(list, 's-klyushkoy'), p(4187));
    assert.equal(Mo.formatMoney(4187, 'BYN'), '41,87 BYN');
    assert.equal(Mo.minPriceOf([list[0]], 's-nulya').cents, 5000);
  });

  it('нет цены во вкладке — null; без ключа — «Все»', () => {
    assert.equal(Mo.minPriceOf([t(1, { all: p(4500) })], 'figurnoe'), null);
    assert.equal(Mo.minPriceOf([t(1, undefined)], 'all'), null);
    assert.deepEqual(Mo.minPriceOf([t(1, { all: p(4500) })]), p(4500));
  });
});

describe('услуга подходит к слоту — как проверяет сервер (422)', () => {
  it('онлайн-слот — онлайн-услуга, очный — очная; онлайн-флаг при катке = очный', () => {
    const live = { service_id: 1, is_online: false };
    const web = { service_id: 9, is_online: true };
    assert.equal(M.serviceFitsSlot(live, { is_online: false, arena_id: 3 }), true);
    assert.equal(M.serviceFitsSlot(web, { is_online: false, arena_id: 3 }), false);
    assert.equal(M.serviceFitsSlot(web, { is_online: true, arena_id: null }), true);
    assert.equal(M.serviceFitsSlot(live, { is_online: true, arena_id: null }), false);
    assert.equal(M.serviceFitsSlot(web, { is_online: true, arena_id: 3 }), false);
    assert.deepEqual(M.servicesForSlot([live, web], { is_online: false, arena_id: 3 }).map((s) => s.service_id), [1]);
  });
});

describe('карточка каталога → тренер витрины (личная ссылка)', () => {
  it('переносит групповую цену и привязку своей услуги', () => {
    const t = M.trainerFromCatalogCard({
      id: 7, can_book: true, profile: { first_name: 'Ольга', last_name: 'К' }, arena_ids: [3], arena_names: ['Каток'],
      services: [{ service_id: 1, service_name: 'С нуля', price_cents: 5000, group_price_cents: 2500, price_tiers: [] },
        { service_id: 42, service_name: 'Своя', price_cents: 3000, direction_service_id: 2, price_tiers: [] }],
    });
    assert.equal(t.name, 'Ольга К');
    assert.equal(t.initial, 'О');
    assert.equal(t.services[0].group_price_cents, 2500);
    assert.equal(t.services[1].group_price_cents, null);
    assert.equal(t.services[1].direction_service_id, 2);
    assert.deepEqual([...t.arenas.map((a) => a.id)], [3]);
  });
});

describe('TASK-399 плашка фактов', () => {
  const fixture = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../fixtures/trainer_card_facts.json'), 'utf8'));
  const cases = fixture.cases;

  it('та же таблица, что у Python', () => {
    for (const c of cases) assert.deepEqual(M.factStrip(c), c.facts, c.id);
  });

  it('сырые тарифы: нулевая цена не считается, как в Python', () => {
    globalThis.__UNIFIED_TRAINER_CARD__ = true;
    try {
      for (const c of fixture.raw_services) assert.equal(M.whoTeaches(c.services), c.audience, c.id);
    } finally {
      delete globalThis.__UNIFIED_TRAINER_CARD__;
    }
  });

  it('без флага whoTeaches как раньше; с флагом — подпись плашки', () => {
    const adult = [{ price_tiers: [{ tier_kind: 'adult', price_cents: 5000 }] }];
    const kids = [{ price_tiers: [{ tier_kind: 'child', price_cents: 5000 }] }];
    const both = [{ price_tiers: [{ tier_kind: 'child', price_cents: 5000 }, { tier_kind: 'adult', price_cents: 5500 }] }];
    assert.equal(M.whoTeaches(adult), 'взрослых');
    assert.equal(M.whoTeaches(kids), 'детей');
    assert.equal(M.whoTeaches(both), 'детей и взрослых');
    assert.equal(M.whoTeaches([]), '');
    globalThis.__UNIFIED_TRAINER_CARD__ = true;
    try {
      assert.equal(M.whoTeaches(adult), 'Любой возраст');
      assert.equal(M.whoTeaches(kids), 'Дети');
      assert.equal(M.whoTeaches(both), 'Любой возраст');
      assert.equal(M.whoTeaches([]), 'Любой возраст');
      assert.equal(M.whoTeaches([{ price_tiers: [{ tier_kind: 'adult_and_child', price_cents: 8000 }] }]), 'Любой возраст');
    } finally {
      delete globalThis.__UNIFIED_TRAINER_CARD__;
    }
    assert.equal(M.whoTeaches(adult), 'взрослых');
  });
});
