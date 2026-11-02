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

  it('спор отметок даёт знак «!» на пине, статус остаётся', () => {
    const v = W.stateView(pt({ state: 'flooded', dispute: true }));
    assert.equal(v.pin, 'dispute');
    assert.equal(v.label, 'Залит');
  });

  it('цена: бесплатно / платно / неизвестно — «бесплатно» по умолчанию не подставляем', () => {
    assert.equal(W.priceLabel(pt({ is_paid: false })), 'Бесплатно');
    assert.equal(W.priceLabel(pt({ is_paid: true })), 'Платно');
    assert.equal(W.priceLabel(pt({ is_paid: null })), 'Цена уточняется');
  });

  it('часы всегда с подписью сезона, без «открыто сейчас»; нет часов — честная строка', () => {
    const known = pt({ hours: { known: true, summary: 'Ежедневно 7:00–23:00', label: 'зимой 2025/26' } });
    assert.equal(W.hoursLabel(known), 'Ежедневно 7:00–23:00 · зимой 2025/26');
    assert.equal(W.hoursLabel(pt()), 'Часы уточняйте по телефону');
    assert.ok(!/открыт/i.test(W.cardMeta(known)));
    assert.ok(!/круглосуточ/i.test(W.hoursLabel(pt())));
  });

  it('расстояние: метры до километра, запятая, неточная точка без расстояния', () => {
    assert.equal(W.distanceLabel(1.24), '1,2 км');
    assert.equal(W.distanceLabel(0.34), '350 м');
    assert.equal(W.distanceLabel(null), '');
  });

  it('строка «когда отметили»: людской статус — давность, админский — дата, ожидание — пусто', () => {
    const now = new Date('2026-12-10T12:00:00Z');
    assert.equal(W.checkedLine(pt({ state: 'flooded', checked_by: 'people', state_at: '2026-12-10T11:20:00Z' }), now), 'Отметили 40 мин назад');
    assert.equal(W.checkedLine(pt({ state: 'flooded', checked_by: 'admin', state_at: '2026-12-09T22:30:00Z' }), now), 'Проверено 10.12');
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

  it('неточная точка в карточке честно говорит «точку уточняем»', () => {
    assert.match(W.cardMeta(pt({ locating: true })), /точку уточняем/);
  });
});

describe('заголовок и пустое состояние (U4)', () => {
  it('ноль залитых — «Сезон открывается», подписка поднята', () => {
    const h = W.headline(63, 0);
    assert.equal(h.title, 'Сезон открывается: ждём первые заливы');
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

  it('вопросов три, необязательные подписаны', () => {
    const q = W.questionsView(W.reportInit());
    assert.equal(q.length, 3);
    assert.equal(q[0].label, 'ЛЁД');
    assert.match(q[1].label, /необязательно/);
  });

  it('ответ: что уже на странице и правило; с сайта «залит» не обещает смену статуса', () => {
    let s = W.reportToggle(W.reportInit(), 'ice', 'on');
    s = W.reportToggle(s, 'crowd', 'few');
    const site = W.reportOutcome(s, { state: 'waiting' }, 'site');
    assert.equal(site.summary, 'Залит · мало людей · только что');
    assert.match(site.rule, /администратором/);
    const tg = W.reportOutcome(s, { state: 'flooded' }, 'miniapp');
    assert.match(tg.rule, /уже подтверждён/);
    const off = W.reportOutcome(W.reportToggle(W.reportInit(), 'ice', 'off'), { state: 'waiting' }, 'site');
    assert.match(off.rule, /две за сутки/);
    const bad = W.reportOutcome(W.reportToggle(W.reportInit(), 'ice', 'bad'), { state: 'flooded' }, 'site');
    assert.match(bad.rule, /не влияет/);
  });

  it('ошибки: лимит с ожиданием, устаревшая страница, снятая точка, сеть', () => {
    assert.match(W.reportErrorText(429, 7200), /через 2 часа/);
    assert.match(W.reportErrorText(429, 5400), /1 час 30 минут/);
    assert.match(W.reportErrorText(429, 30), /через 1 минуту/);
    assert.match(W.reportErrorText(403), /Обновите/);
    assert.match(W.reportErrorText(404), /не принимает/);
    assert.match(W.reportErrorText(0), /Не удалось отправить/);
  });

  it('быстрые отметки «Уже залит / Не зальют» — те же отметки про лёд', () => {
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

  it('источник/админ — «Проверено DD.MM»', () => {
    assert.equal(W.checkedLine(pt({ state: 'flooded', checked_by: 'source', state_at: '2026-12-09T22:30:00Z' }), new Date('2026-12-10T12:00:00Z')), 'Проверено 10.12');
  });
});
