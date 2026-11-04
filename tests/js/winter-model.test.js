/**
 * TASK-343: модель зимних точек (сайт и Mini App).
 * Run: TZ=UTC node --test tests/js/winter-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const W = require(path.resolve(__dirname, '../../static/shared/winter-model.js'));

function pt(over) {
  return Object.assign(
    {
      id: 1, name: 'Каток', kind: 'rink', state: 'waiting', district: 'Центр', pin: null,
      map_allowed: true, lat: 53.9, lon: 27.56, locating: false, distance_km: null,
      is_paid: false, price_note: null, dispute: false, doubtful: false, quality: null,
      crowd: null, hockey: null, state_at: null, checked_by: null,
      hours: { known: false, fallback: 'Часы уточняйте по телефону', label: 'зимой 2025/26' },
    },
    over || {}
  );
}

describe('статус и подписи', () => {
  it('каждый статус — слово и значок, не только цвет', () => {
    for (const s of ['flooded', 'waiting', 'stale', 'closed']) {
      const v = W.stateView(pt({ state: s }));
      assert.ok(v.label && v.icon && v.pin);
    }
    assert.equal(W.stateView(pt({ state: 'flooded' })).label, 'Залит');
    assert.equal(W.stateView(pt({ state: 'waiting' })).label, 'Ждём заливку');
  });

  it('спор отметок у залитой: знак «!» на пине, статус остаётся, текст нейтральный', () => {
    const p = pt({ state: 'flooded', dispute: true });
    const v = W.stateView(p);
    assert.equal(v.pin, 'dispute');
    assert.equal(v.label, 'Залит');
    assert.equal(W.disputeNote(p), 'Есть отметки «не залит» · проверяем');
    assert.ok(!/расходятся/.test(W.disputeNote(p)));
  });

  it('спор у не залитой точки ничего не показывает', () => {
    const p = pt({ state: 'waiting', dispute: true });
    assert.equal(W.disputeNote(p), '');
    assert.equal(W.stateView(p).pin, 'wait');
  });

  it('цена: бесплатно / платно / неизвестно — «бесплатно» по умолчанию не подставляем', () => {
    assert.equal(W.priceLabel(pt({ is_paid: false })), 'Бесплатно');
    assert.equal(W.priceLabel(pt({ is_paid: true })), 'Платно');
    assert.equal(W.priceLabel(pt({ is_paid: null })), '');
  });

  it('карточка: часы и цена прошлой зимы с префиксом, без «открыто сейчас»', () => {
    const known = pt({ hours: { known: true, summary: 'Ежедневно 07:00–23:00', label: 'зимой 2025/26', season: '2025/26' } });
    assert.equal(W.cardMeta(known), 'Прошлой зимой: ежедневно 07:00–23:00 · бесплатно');
    assert.equal(W.hoursLabel(known), 'Ежедневно 07:00–23:00');
    assert.ok(!/открыт/i.test(W.cardMeta(known)));
    assert.equal(W.dataSeason(known), '2025/26');
  });

  it('карточка: часов нет — подсказка про телефон только при телефоне; цены нет — молчим', () => {
    assert.equal(W.cardMeta(pt({ is_paid: null })), '');
    assert.equal(W.cardMeta(pt({ is_paid: null, phone: '+375 17 000-00-00' })), 'Часы уточняйте по телефону');
    assert.equal(W.hoursLabel(pt()), '');
    assert.ok(!/Цена уточняется/.test(W.cardMeta(pt({ is_paid: null }))));
  });

  it('заголовок карточки без дубля слова «Каток, » / «Коробка, »', () => {
    assert.equal(W.cardTitle(pt({ name: 'Каток, ул. Плеханова, 70' })), 'ул. Плеханова, 70');
    assert.equal(W.cardTitle(pt({ name: 'Коробка, пр. Рокоссовского, 128' })), 'пр. Рокоссовского, 128');
    assert.equal(W.cardTitle(pt({ name: 'Каток Юность' })), 'Каток Юность');
  });

  it('расстояние: метры до километра, запятая, неточная точка без расстояния', () => {
    assert.equal(W.distanceLabel(1.24), '1,2 км');
    assert.equal(W.distanceLabel(0.34), '350 м');
    assert.equal(W.distanceLabel(null), '');
  });

  it('строка «когда отметили»: людской статус — давность, админский — дата, ожидание — пусто', () => {
    const now = new Date('2026-12-10T12:00:00Z');
    assert.equal(W.checkedLine(pt({ state: 'flooded', checked_by: 'people', state_at: '2026-12-10T11:20:00Z' }), now), 'Отметили 40 мин назад');
    assert.equal(W.checkedLine(pt({ state: 'flooded', checked_by: 'admin', state_at: '2026-12-09T22:30:00Z' }), now), 'Заливку подтвердили 10 декабря');
    assert.equal(W.checkedLine(pt({ state: 'waiting', checked_by: null, state_at: '2026-12-01T00:00:00Z' }), now), '');
  });

  it('теги «сейчас»: людей, хоккей и плохой лёд', () => {
    assert.deepEqual(W.liveTags(pt({ crowd: 'few', hockey: 'playing', quality: 'bad' })), ['Мало людей', 'Идёт хоккей', 'Лёд плохой']);
    assert.deepEqual(W.liveTags(pt()), []);
  });

  it('теги «сейчас» со временем отметки: «Мало людей · 40 мин назад», старше 2 ч — нет', () => {
    const now = new Date('2026-12-10T12:00:00Z');
    const tags = W.liveTags(pt({ crowd: 'few', crowd_at: '2026-12-10T11:20:00Z', hockey: 'free', hockey_at: '2026-12-10T09:00:00Z' }), now);
    assert.deepEqual(tags, ['Мало людей · 40 мин назад']);
    assert.deepEqual(W.liveTags(pt({ hockey: 'playing', hockey_at: '2026-12-10T11:59:40Z' }), now), ['Идёт хоккей · только что']);
  });

  it('неточная точка в карточке честно говорит «адрес примерный»', () => {
    assert.match(W.cardMeta(pt({ locating: true })), /^Адрес примерный · /);
  });
});

describe('заголовок и пустое состояние (U4)', () => {
  it('ноль залитых — «Сезон открывается», подписка поднята', () => {
    const h = W.headline(63, 0);
    assert.equal(h.title, 'Сезон открывается: ждём первую заливку');
    assert.equal(h.hint, 'Как только где-то зальют, напишем в Telegram. Если вы рядом со льдом, отметьте его.');
    assert.equal(h.bellFirst, true);
    assert.equal(W.summaryLine(63, 0).includes('залиты 0'), false);
  });
  it('есть залитые — обычная сводка', () => {
    assert.equal(W.headline(63, 7).title, '');
    assert.equal(W.summaryLine(63, 7), '63 уличные точки · залиты 7 · ждём 56');
  });
});

describe('фильтры и сортировка', () => {
  const list = [
    pt({ id: 1, name: 'Ждём близко', lat: 53.9, lon: 27.5601 }),
    pt({ id: 2, name: 'Залит далеко', state: 'flooded', lat: 53.95, lon: 27.7 }),
    pt({ id: 3, name: 'Залит близко', state: 'flooded', lat: 53.9, lon: 27.56 }),
    pt({ id: 4, name: 'Немига', pin: 1, lat: 53.8, lon: 27.4 }),
    pt({ id: 5, name: 'Коробка', kind: 'hockey_box', district: 'Ленинский' }),
    pt({ id: 6, name: 'Неточная', map_allowed: false, lat: null, lon: null, locating: true, state: 'flooded' }),
  ];
  const origin = { lat: 53.9, lon: 27.56 };

  it('закреп → залитые → ближе → район → имя; неточные в конце своей группы без расстояния', () => {
    const names = W.applyFilters(list, { origin }).map((p) => p.name);
    assert.deepEqual(names, ['Немига', 'Залит близко', 'Залит далеко', 'Неточная', 'Коробка', 'Ждём близко']);
    const bad = W.applyFilters(list, { origin }).filter((p) => p.name === 'Неточная')[0];
    assert.equal(bad.distance_km, null);
  });

  it('без геолокации порядок тот же, расстояний нет', () => {
    const out = W.applyFilters(list, {});
    assert.ok(out.every((p) => p.distance_km == null));
    assert.equal(out[0].name, 'Немига');
  });

  it('чипы: залиты, катки, коробки, район', () => {
    assert.equal(W.applyFilters(list, { flooded: true }).length, 3);
    assert.deepEqual(W.applyFilters(list, { kind: 'hockey_box' }).map((p) => p.name), ['Коробка']);
    assert.equal(W.applyFilters(list, { kind: 'rink' }).length, 5);
    assert.deepEqual(W.applyFilters(list, { district: 'Ленинский' }).map((p) => p.name), ['Коробка']);
  });

  it('район показываем только где две точки и больше (U6)', () => {
    assert.deepEqual(W.districtList(list), [{ name: 'Центр', count: 5 }]);
    assert.deepEqual(W.districtList([pt({ district: '' }), pt({ district: 'Один' })]), []);
  });

  it('карта: только точные точки', () => {
    assert.equal(W.mapPoints(list).length, 5);
  });

  it('исходный список не меняется', () => {
    const copy = JSON.stringify(list);
    W.applyFilters(list, { origin });
    assert.equal(JSON.stringify(list), copy);
  });
});

describe('шторка «Как там сейчас?»', () => {
  it('«Отметить» недоступна, пока не выбран лёд', () => {
    let s = W.reportInit();
    assert.equal(W.reportCanSend(s), false);
    assert.equal(W.reportSendLabel(s), 'Сначала про лёд');
    assert.equal(W.reportPayload(s), null);
    s = W.reportToggle(s, 'crowd', 'few');
    assert.equal(W.reportCanSend(s), false);
    s = W.reportToggle(s, 'ice', 'on');
    assert.equal(W.reportCanSend(s), true);
    assert.equal(W.reportSendLabel(s), 'Отметить');
  });

  it('повторный тап снимает выбор', () => {
    let s = W.reportToggle(W.reportInit(), 'ice', 'bad');
    s = W.reportToggle(s, 'ice', 'bad');
    assert.equal(s.ice, null);
  });

  it('значения уходят в API: лёд главной отметкой, людей и хоккей попутно', () => {
    let s = W.reportInit();
    s = W.reportToggle(s, 'ice', 'off');
    s = W.reportToggle(s, 'crowd', 'mid');
    s = W.reportToggle(s, 'hockey', 'yes');
    assert.deepEqual(W.reportPayload(s, { token: 't', idem_key: 'k' }), {
      kind: 'ice', value: 'not_flooded', token: 't', idem_key: 'k',
      companions: [{ kind: 'crowd', value: 'normal' }, { kind: 'hockey', value: 'playing' }],
    });
  });

  it('у залитой точки три вопроса с короткими подписями', () => {
    const q = W.questionsView(W.reportInit(), { flooded: true });
    assert.deepEqual(q.map((x) => x.label), ['Лёд', 'Людей', 'Хоккей']);
  });

  it('у не залитой точки спрашиваем только про лёд', () => {
    assert.deepEqual(W.questionsView(W.reportInit(), { flooded: false }).map((x) => x.key), ['ice']);
    assert.deepEqual(W.questionsView(W.reportInit()).map((x) => x.key), ['ice']);
  });

  it('ответ после отметки: тексты по состояниям', () => {
    let s = W.reportToggle(W.reportInit(), 'ice', 'on');
    s = W.reportToggle(s, 'crowd', 'few');
    const pending = W.reportOutcome(s, { state: 'waiting' }, 'site');
    assert.equal(pending.summary, 'Залит · мало людей · только что');
    assert.equal(pending.rule, 'Спасибо! Передали на проверку. Пока проверяем, на странице остаётся «Ждём заливку».');
    assert.equal(W.reportOutcome(s, { state: 'waiting' }, 'miniapp').rule, pending.rule);
    assert.equal(W.reportOutcome(s, { state: 'flooded' }, 'miniapp').rule, 'Спасибо! Увидят все, кто выбирает, куда пойти.');
    const off = W.reportOutcome(W.reportToggle(W.reportInit(), 'ice', 'off'), { state: 'waiting' }, 'site');
    assert.equal(off.rule, 'Спасибо! Проверим и обновим статус.');
    const bad = W.reportOutcome(W.reportToggle(W.reportInit(), 'ice', 'bad'), { state: 'flooded' }, 'site');
    assert.equal(bad.rule, 'Спасибо! Отметку «плохой лёд» увидят все в ближайшие сутки.');
    assert.ok(!/вес|порог|две за сутки/.test(off.rule + bad.rule));
  });

  it('ошибки: лимит с ожиданием, устаревшая страница, снятая точка, сеть', () => {
    assert.match(W.reportErrorText(429, 7200), /через 2 часа/);
    assert.match(W.reportErrorText(429, 5400), /1 час 30 минут/);
    assert.match(W.reportErrorText(429, 30), /через 1 минуту/);
    assert.match(W.reportErrorText(403), /Обновите/);
    assert.match(W.reportErrorText(404), /не принимает/);
    assert.match(W.reportErrorText(0), /Не удалось отправить/);
  });

  it('быстрые отметки «Уже залит / Ещё не залит» — те же отметки про лёд', () => {
    assert.equal(W.quickPayload('on').value, 'flooded');
    assert.equal(W.quickPayload('off').value, 'not_flooded');
    assert.equal(W.quickPayload('x'), null);
  });

  it('ключ идемпотентности: 32 символа hex, разный', () => {
    const a = W.newIdemKey();
    assert.match(a, /^[0-9a-f]{16,32}$/);
    assert.notEqual(a, W.newIdemKey());
  });
});

describe('pending: люди отметили «залит», админ не подтвердил', () => {
  it('нейтральная строка вместо «отметили N мин назад», статус «Ждём заливку»', () => {
    const p = pt({ state: 'waiting', pending: true, pending_people: 3, checked_by: 'people', state_at: '2026-12-10T11:20:00Z' });
    assert.equal(W.checkedLine(p, new Date('2026-12-10T12:00:00Z')), '3 человека отметили, что залит · проверяем');
    assert.equal(W.pendingLine(pt({ pending: true, pending_people: 1 })), '1 человек отметил, что залит · проверяем');
    assert.equal(W.pendingLine(pt({ pending: true, pending_people: 11 })), '11 человек отметили, что залит · проверяем');
    assert.equal(W.pendingLine(pt({ pending: false, pending_people: 3 })), '');
    assert.equal(W.stateView(p).label, 'Ждём заливку');
  });

  it('источник/админ: у залитой «Заливку подтвердили 2 ноября», у остальных «Проверено 2 ноября»', () => {
    const now = new Date('2026-12-10T12:00:00Z');
    assert.equal(W.checkedLine(pt({ state: 'flooded', checked_by: 'source', state_at: '2026-11-02T10:00:00Z' }), now), 'Заливку подтвердили 2 ноября');
    assert.equal(W.checkedLine(pt({ state: 'stale', checked_by: 'admin', state_at: '2026-11-02T10:00:00Z' }), now), 'Проверено 2 ноября');
    assert.equal(W.checkedLine(pt({ state: 'closed', checked_by: 'admin', state_at: '2025-11-02T10:00:00Z' }), now), 'Проверено 2 ноября 2025');
  });
});

describe('свайп вниз по шторке', () => {
  it('дальше 80 px закрывает', () => {
    assert.equal(W.swipeDecision(81, 2000), 'close');
    assert.equal(W.swipeDecision(80, 2000), 'snap');
  });
  it('быстрый бросок (> 0.5 px/ms) закрывает, медленный короткий — возвращает', () => {
    assert.equal(W.swipeDecision(40, 60), 'close');
    assert.equal(W.swipeDecision(40, 100), 'snap');
  });
  it('случайный дёрг на пару пикселей не закрывает; движение вверх — никогда', () => {
    assert.equal(W.swipeDecision(8, 4), 'snap');
    assert.equal(W.swipeDecision(0, 10), 'snap');
    assert.equal(W.swipeDecision(-120, 50), 'snap');
  });
});

describe('группы списка и место подписки', () => {
  it('залитые → ждём → закрытые/давно без отметок; пустых групп нет; порядок внутри сохраняется', () => {
    const g = W.listGroups([pt({ id: 1, state: 'flooded' }), pt({ id: 2 }), pt({ id: 3, state: 'closed' }), pt({ id: 4, state: 'flooded' }), pt({ id: 5, state: 'stale' })]);
    assert.deepEqual(g.map((x) => x.key), ['now', 'wait', 'off']);
    assert.deepEqual(g[0].items.map((p) => p.id), [1, 4]);
    assert.deepEqual(g[2].items.map((p) => p.id), [3, 5]);
    assert.deepEqual(W.listGroups([pt()]).map((x) => x.key), ['wait']);
  });
  it('подписка — после залитых, а без них — над списком', () => {
    assert.equal(W.bellSlot(W.listGroups([pt({ state: 'flooded' }), pt()])), 'now');
    assert.equal(W.bellSlot(W.listGroups([pt(), pt({ state: 'closed' })])), 'top');
    assert.equal(W.bellSlot([]), 'top');
  });
  it('подписка «рядом» узнаётся по kind, подписка на точку — нет', () => {
    assert.equal(W.hasNearSub([{ kind: 'point', arena_id: 1 }]), false);
    assert.equal(W.hasNearSub([{ kind: 'point' }, { kind: 'near' }]), true);
    assert.equal(W.hasNearSub(null), false);
  });
});

it('markView: пока ждём заливку — «Залили / Ещё не залит» одним нажатием, без оценки качества', () => {
  const v = W.markView({ state: 'waiting' });
  assert.equal(v.oneTap, true);
  assert.deepEqual(v.ice.map((o) => o.label), ['Залили', 'Ещё не залит']);
  assert.equal(v.extras.length, 0);
  assert.equal(v.canSend, false);
});

it('markView: у залитой точки людей и хоккей спрашиваем только после выбора льда', () => {
  const before = W.markView({ state: 'flooded' });
  assert.equal(before.oneTap, false);
  assert.deepEqual(before.ice.map((o) => o.id), ['on', 'bad', 'off']);
  assert.equal(before.extras.length, 0);
  assert.equal(before.canSend, false);
  const after = W.markView({ state: 'flooded' }, { ice: 'bad', crowd: 'many', hockey: null });
  assert.equal(after.ice.find((o) => o.id === 'bad').selected, true);
  assert.deepEqual(after.extras.map((q) => q.key), ['crowd', 'hockey']);
  assert.equal(after.extras[0].opts.find((o) => o.id === 'many').selected, true);
  assert.equal(after.canSend, true);
});

it('hasPointSub: подписка именно на эту точку', () => {
  const items = [{ kind: 'near', radius_m: 3000 }, { kind: 'point', arena_id: 7 }];
  assert.equal(W.hasPointSub(items, 7), true);
  assert.equal(W.hasPointSub(items, '7'), true);
  assert.equal(W.hasPointSub(items, 8), false);
  assert.equal(W.hasPointSub(null, 7), false);
});

it('drawerTitle: счёт залитых и ждущих, «рядом» только с геолокацией', () => {
  const g = (key, n) => ({ key, items: Array.from({ length: n }, (_, i) => ({ id: i })) });
  assert.equal(W.drawerTitle([g('now', 3), g('wait', 5)], false), '3 залито · 5 ждут заливку');
  assert.equal(W.drawerTitle([g('now', 1), g('wait', 1)], true), 'Рядом с вами: 1 залит · 1 ждёт заливку');
  assert.equal(W.drawerTitle([g('off', 2)], false), '2 без свежих отметок');
  assert.equal(W.drawerTitle([], false), 'По этому фильтру ничего нет');
});

describe('navRowHtml — выход с зимней карты', () => {
  const W = require(require('node:path').resolve(__dirname, '../../static/shared/winter-model.js'));
  const assert = require('node:assert/strict');
  const { it } = require('node:test');
  it('даёт «Назад» и «Что ищем», когда экран умеет и то и другое', () => {
    const html = W.navRowHtml({ exit: true, categories: true, categoryIcon: '<path d="M1 1"/>' });
    assert.ok(html.includes('data-w-exit'));
    assert.ok(html.includes('data-w-cats'));
    assert.ok(html.includes('<path d="M1 1"/>'), 'значок текущего раздела — как в шапке');
    assert.ok(html.includes('ice-intent-chip'), 'тот же чип, что в шапке каталога');
  });
  it('без колбэков ряда нет вовсе', () => {
    assert.equal(W.navRowHtml({}), '');
    assert.equal(W.navRowHtml(), '');
  });
  it('только то, что экран умеет', () => {
    const html = W.navRowHtml({ exit: true });
    assert.ok(html.includes('data-w-exit'));
    assert.ok(!html.includes('data-w-cats'));
  });
});
