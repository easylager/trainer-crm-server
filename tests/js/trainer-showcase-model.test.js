/**
 * TASK-357: витрина тренеров и запись в Mini App — правила дизайна PDEC-033.
 * Run: node --test tests/js/trainer-showcase-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
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

  it('оценка — только при 3+; «В Glide с …» без числа занятий; стаж', () => {
    assert.equal(M.ratingLine(5, 2), '');
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

  it('один — тариф прошлой записи, двое — тариф на двоих, третий неактивен', () => {
    assert.equal(M.regularTier(s, [me], { lastVariantId: 100, lastProfileId: 3 }).tier_kind, 'child');
    assert.equal(M.regularTier(s, [sonya]).tier_kind, 'child');
    assert.equal(M.regularTier(s, [sonya, misha]).tier_kind, 'two_children');
    assert.equal(M.regularTier(s, [sonya, me]).tier_kind, 'adult_and_child');
    assert.equal(M.canAddProfile(s, [sonya, misha], me), false);
    assert.equal(M.canAddProfile(s, [me], { client_id: 4, role: 'self' }), false); // нет «двое взрослых»
  });

  it('абонемент: «спишем 1, останется N»; у одного из двоих — тренер может списать', () => {
    const pass = { trainer_id: 9, status: 'active', sessions_remaining: 4, service_ids: [], product_name: '8 занятий' };
    assert.equal(M.usablePass([pass], 9, 1), pass);
    assert.equal(M.usablePass([{ ...pass, service_ids: [2] }], 9, 1), null);
    assert.match(M.payLine({ tier: M.tierByKind(s, 'child'), pass }), /Абонемент «8 занятий»<\/b>: спишем 1, останется 3\./);
    const duo = M.payLine({ tier: M.tierByKind(s, 'two_children'), pass, duo: true });
    assert.match(duo, /Двое детей — 75 BYN<\/b> за двоих тренеру на месте\. Вместо оплаты тренер может списать занятие с абонемента\./);
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
    assert.equal(M.selfBookingLine('Мария', RuName), 'Мария записывает сама — напишите и договоритесь о времени и цене.');
    assert.match(M.selfBookingLine('Katusha', RuName), /^Онлайн-записи у Katusha нет/);
  });

  it('номер из requestContact', () => {
    assert.equal(M.phoneFromContact({ responseUnsafe: { contact: { phone_number: '375291234567' } } }), '+375291234567');
    assert.equal(M.phoneFromContact({ response: 'contact=' + encodeURIComponent(JSON.stringify({ phone_number: '+79123456789' })) }), '+79123456789');
    assert.equal(M.phoneFromContact(null), '');
  });
});
