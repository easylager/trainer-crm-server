/**
 * TASK-160 (S1): «Моя карточка» — модель и рендер единственного героя хаба.
 *
 * Покрытые правила (приёмочные критерии слайса):
 *   1. крупное время `me__when` разрешено при 'booking' и 'city-ice' (моё
 *      обязательство и факт мира), запрещено при 'trainer' и 'dormant';
 *   2. ячейка кошелька — только при положительном остатке, нет ячеек — нет полосы;
 *   3. остаток показывается только под своим лицом; без лица подпись называет тренера;
 *   4. чипы окон: максимум 4 + обязательные «Все окна»; нет слотов — нет полосы;
 *   5. корень `me` не интерактивен (ни onclick, ни role="button", ни tabindex);
 *   6. нет поля — нет строки (ни «ваш тренер», ни выдуманных имён);
 *   7. весь текст из данных экранируется;
 *   8. модуль чистый: ни document, ни window.location, ни fetch, ни Date.now().
 * Плюс happy-path на каждую из шести заливок и пустые/битые входы.
 *
 * Run: node --test tests/js/hub-me-card-model.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/hub-me-card.js');

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

/** Фиксированное «сейчас»: 4 октября 2026, 18:00 местного времени. */
const NOW = new Date(2026, 9, 4, 18, 0, 0);

function html(input, now = NOW) {
  const { buildView, renderHtml } = loadModel();
  return renderHtml(buildView(input, now));
}

/* ── фикстуры ─────────────────────────────────────────────────────────── */

function booking(overrides) {
  return Object.assign(
    {
      start_time: '12:15:00',
      date_label: 'Завтра',
      duration_minutes: 45,
      status: 'confirmed',
      hub_in_session: false,
      trainer_name: 'Александр Гаевский',
      trainer_list_photo_key: 'photos/ag.jpg',
      trainer_id: 7,
      arena_name: 'ТЦ Замок',
      trainer_telegram_username: '@gaevsky',
      trainer_telegram_id: 100500,
    },
    overrides || {}
  );
}

function trainer(overrides) {
  return Object.assign(
    {
      id: 7,
      name: 'Александр Гаевский',
      photo: 'photos/ag.jpg',
      canBook: true,
      username: 'gaevsky',
      telegramId: 100500,
      arena_name: 'ТЦ Замок',
      city_name: 'Минск',
    },
    overrides || {}
  );
}

function slots(n) {
  const out = [];
  for (let i = 0; i < n; i++) {
    out.push({
      id: 100 + i,
      start_time: `1${i}:00:00`,
      slot_date: '2026-10-05',
      service_id: 3,
      arena_id: 9,
      arena_name: 'ТЦ Замок',
    });
  }
  return out;
}

/** Абонемент тренера 7: 1 из 4, срок далеко. */
function pass(overrides) {
  return Object.assign(
    {
      id: 1,
      status: 'active',
      sessions_remaining: 1,
      sessions_total: 4,
      expires_at: '2026-11-30',
      product_name: 'Взрослый 4 занятия',
      trainer_id: 7,
      trainer_name: 'Александр Гаевский',
    },
    overrides || {}
  );
}

function certificate(overrides) {
  return Object.assign(
    {
      id: 2,
      status: 'activated',
      amount_remaining_cents: 4800,
      trainer_id: 7,
      trainer_name: 'Александр Гаевский',
    },
    overrides || {}
  );
}

/* ── 1. Крупное время — только у моей записи ──────────────────────────── */

describe('правило 1: крупное время — обязательство или факт мира, но не чужое окно', () => {
  it('у записи крупное время есть: это обязательство тренера передо мной', () => {
    const out = html({ kind: 'booking', booking: booking() });
    assert.ok(out.includes('class="me__when"'));
    assert.ok(out.includes('<b>12:15</b>'));
    assert.ok(out.includes('Завтра · 45 мин'));
  });

  it('у сеанса площадки крупное время есть: это факт мира, как сеанс в кино', () => {
    const out = html({
      kind: 'city-ice',
      arena: { name: 'Чижовка-Арена', city_name: 'Минск', start_time: '19:00:00', kind_label: 'Массовое катание', price_label: '12 BYN' },
    });
    assert.ok(out.includes('class="me__when"'));
    assert.ok(out.includes('<b>19:00</b>'));
    assert.ok(out.includes('<span>Массовое катание · 12 BYN</span>'));
    assert.ok(!out.includes('me__head'), 'заголовок больше не дублирует крупное время');
    // Спутать с моей записью нечем: кикер про город, в who арена, штампа нет.
    assert.ok(out.includes('class="k">На льду сегодня · Минск<'));
    assert.ok(!out.includes('подтверждена'));
    assert.ok(!out.includes('class="pill'));
  });

  it('у тренера крупного времени нет ни при каких данных', () => {
    const { buildView } = loadModel();
    const view = buildView({ kind: 'trainer', trainer: trainer(), slots: slots(3) }, NOW);
    assert.equal(view.when, null, 'модель не заводит when для тренера');
    const out = html({ kind: 'trainer', trainer: trainer(), slots: slots(3) });
    assert.ok(!out.includes('me__when'));
    // Время тренера живёт только чипами.
    assert.ok(out.includes('class="me__chip"'));
    assert.ok(out.includes('<b>10:00</b>'));
  });

  it('у возврата крупного времени нет ни при каких данных', () => {
    const { buildView } = loadModel();
    const input = {
      kind: 'dormant',
      trainer: trainer(),
      slots: slots(3),
      passes: [pass()],
      history: { completed_count: 7, last_completed_at: '2026-05-18' },
    };
    assert.equal(buildView(input, NOW).when, null);
    assert.ok(!html(input).includes('me__when'));
  });

  it('заливки без крупного времени его не рендерят ни при каких данных', () => {
    const inputs = [
      { kind: 'trainer', trainer: trainer(), slots: slots(2) },
      { kind: 'dormant', trainer: trainer(), slots: slots(2), history: { completed_count: 3 } },
      { kind: 'city-pick', cities: [{ id: 1, name: 'Минск' }] },
      { kind: 'far', arena: { name: 'Брест-Арена', city_name: 'Брест' } },
    ];
    for (const input of inputs) {
      assert.ok(!html(input).includes('me__when'), `${input.kind} не рендерит крупное время`);
    }
  });

  // Правило держится и на уровне рендера: подложенный руками when игнорируется.
  it('рендер игнорирует when у тренера и возврата, но пропускает у разрешённых', () => {
    const { renderHtml } = loadModel();
    const faked = (kind) => ({ kind: kind, mod: '', status: { label: 'x', pill: null },
      when: { time: '12:15', meta: 'Завтра' }, head: '', who: null, line: '', pick: null,
      actions: [], cities: null, moreCities: false, geo: false, wallet: [], foot: null });
    assert.ok(!renderHtml(faked('trainer')).includes('me__when'));
    assert.ok(!renderHtml(faked('dormant')).includes('me__when'));
    assert.ok(renderHtml(faked('booking')).includes('me__when'));
    assert.ok(renderHtml(faked('city-ice')).includes('me__when'));
  });
});

/* ── 2. Кошелёк честный ───────────────────────────────────────────────── */

describe('правило 2: ячейка кошелька только при положительном остатке', () => {
  it('активный абонемент с остатком рендерится ячейкой с полосой', () => {
    const out = html({ kind: 'trainer', trainer: trainer(), slots: slots(1), passes: [pass({ sessions_remaining: 2 })] });
    assert.ok(out.includes('class="me__wallet"'));
    assert.ok(out.includes('me__w-k">Абонемент<'));
    assert.ok(out.includes('me__w-v">2<i>из 4</i>'));
    assert.ok(out.includes('me__w-bar'));
    assert.ok(out.includes('до 30 ноя'));
  });

  it('активированный сертификат с остатком рендерится ячейкой', () => {
    const out = html({ kind: 'trainer', trainer: trainer(), slots: slots(1), certificates: [certificate()] });
    assert.ok(out.includes('me__w-k">Сертификат<'));
    assert.ok(out.includes('me__w-v">48<i>BYN</i>'));
  });

  it('нулевой остаток, чужой статус и мусор ячейку не создают', () => {
    const { buildView } = loadModel();
    const badPasses = [
      pass({ sessions_remaining: 0 }),
      pass({ sessions_remaining: null }),
      pass({ sessions_remaining: -2 }),
      pass({ sessions_remaining: 'нет' }),
      pass({ status: 'used_up' }),
      pass({ status: 'expired' }),
    ];
    for (const p of badPasses) {
      const view = buildView({ kind: 'trainer', trainer: trainer(), slots: slots(1), passes: [p] }, NOW);
      assert.deepEqual(view.wallet, [], `абонемент ${JSON.stringify(p.status)}/${p.sessions_remaining}`);
    }
    const badCerts = [
      certificate({ amount_remaining_cents: 0 }),
      certificate({ amount_remaining_cents: null }),
      certificate({ status: 'issued' }), // выдан, но этим клиентом не активирован
      certificate({ status: 'redeemed' }),
    ];
    for (const c of badCerts) {
      const view = buildView({ kind: 'trainer', trainer: trainer(), slots: slots(1), certificates: [c] }, NOW);
      assert.deepEqual(view.wallet, [], `сертификат ${c.status}/${c.amount_remaining_cents}`);
    }
  });

  it('нет ни одной ячейки — нет и всей полосы', () => {
    const out = html({
      kind: 'trainer',
      trainer: trainer(),
      slots: slots(1),
      passes: [pass({ sessions_remaining: 0 })],
      certificates: [certificate({ amount_remaining_cents: 0 })],
    });
    assert.ok(!out.includes('me__wallet'));
    assert.ok(!out.includes('me__w-k'));
    assert.ok(!html({ kind: 'trainer', trainer: trainer(), slots: slots(1) }).includes('me__wallet'));
  });
});

describe('валюта сертификата приходит снаружи, а не зашита', () => {
  it('по умолчанию BYN', () => {
    const { buildView } = loadModel();
    const view = buildView({ kind: 'trainer', trainer: trainer(), slots: slots(1), certificates: [certificate()] }, NOW);
    assert.equal(view.wallet[0].unit, 'BYN');
  });

  it('альтернативная валюта выводится как есть (Москва — рубль)', () => {
    const { buildView } = loadModel();
    for (const currency of ['RUB', '₽', 'руб.']) {
      const view = buildView(
        { kind: 'trainer', trainer: trainer(), slots: slots(1), certificates: [certificate()], currency: currency },
        NOW
      );
      assert.equal(view.wallet[0].unit, currency);
      const out = html({ kind: 'trainer', trainer: trainer(), slots: slots(1), certificates: [certificate()], currency: currency });
      assert.ok(out.includes('me__w-v">48<i>' + currency + '</i>'), out);
      assert.ok(!out.includes('BYN'), out);
    }
  });

  it('пустая и мусорная валюта не оставляет ячейку без единицы', () => {
    const { buildView } = loadModel();
    for (const bad of ['', '   ', null, undefined]) {
      const view = buildView(
        { kind: 'trainer', trainer: trainer(), slots: slots(1), certificates: [certificate()], currency: bad },
        NOW
      );
      assert.equal(view.wallet[0].unit, 'BYN', `currency=${String(bad)}`);
    }
  });
});

/* ── 3. Кошелёк и чужой тренер ────────────────────────────────────────── */

describe('правило 3: остаток только под своим лицом', () => {
  it('в карточке тренера показывается только его остаток', () => {
    const { buildView } = loadModel();
    const view = buildView(
      {
        kind: 'trainer',
        trainer: trainer({ id: 7 }),
        slots: slots(1),
        passes: [
          pass({ id: 11, trainer_id: 42, trainer_name: 'Марина Ковалёва', sessions_remaining: 5, sessions_total: 8 }),
          pass({ id: 12, trainer_id: 7, sessions_remaining: 2 }),
        ],
      },
      NOW
    );
    assert.equal(view.wallet.length, 1);
    assert.equal(view.wallet[0].value, '2');
    assert.equal(view.wallet[0].trainerId, '7');
  });

  it('остаток чужого тренера под чужим лицом не показывается вообще', () => {
    const { buildView } = loadModel();
    const foreign = {
      passes: [pass({ trainer_id: 42, trainer_name: 'Марина Ковалёва', sessions_remaining: 5 })],
      certificates: [certificate({ trainer_id: 42, trainer_name: 'Марина Ковалёва' })],
    };
    for (const input of [
      Object.assign({ kind: 'trainer', trainer: trainer({ id: 7 }), slots: slots(1) }, foreign),
      Object.assign({ kind: 'booking', booking: booking({ trainer_id: 7 }) }, foreign),
      Object.assign({ kind: 'dormant', trainer: trainer({ id: 7 }), history: { completed_count: 3 } }, foreign),
    ]) {
      const view = buildView(input, NOW);
      assert.deepEqual(view.wallet, [], `${input.kind}: остаток Марины под лицом Александра`);
      assert.ok(!html(input).includes('Марина'));
    }
  });

  it('в карточке записи ячейка говорит, что именно спишется', () => {
    const out = html({ kind: 'booking', booking: booking(), passes: [pass({ sessions_remaining: 1 })] });
    assert.ok(out.includes('me__w-k">Спишется с абонемента<'));
    assert.ok(out.includes('это последнее занятие'));
    assert.ok(out.includes('me__w--warn'));
  });

  it('тренера в карточке нет (city-ice) — берётся любой активный, подпись называет тренера', () => {
    const { buildView } = loadModel();
    const input = {
      kind: 'city-ice',
      arena: { id: 5, name: 'Чижовка-Арена', start_time: '19:00', city_name: 'Минск' },
      passes: [pass({ trainer_id: 42, trainer_name: 'Марина Ковалёва', sessions_remaining: 2, sessions_total: 8 })],
    };
    const view = buildView(input, NOW);
    assert.equal(view.trainerId, null);
    assert.equal(view.wallet.length, 1);
    assert.ok(view.wallet[0].label.includes('Марина'), view.wallet[0].label);
    assert.ok(html(input).includes('Марина'));
  });

  it('возврат без тренера — любой активный остаток, подпись называет тренера', () => {
    const { buildView } = loadModel();
    const view = buildView(
      {
        kind: 'dormant',
        passes: [pass({ trainer_id: 42, trainer_name: 'Марина Ковалёва', sessions_remaining: 2, sessions_total: 8 })],
        history: { completed_count: 7, last_completed_at: '2026-05-18' },
      },
      NOW
    );
    assert.equal(view.who, null, 'лица нет — блока who нет');
    assert.ok(view.wallet[0].label.includes('Марина'), view.wallet[0].label);
  });

  it('серверная заглушка имени («Тренер») именем не считается', () => {
    const { buildView } = loadModel();
    const view = buildView(
      {
        kind: 'city-ice',
        arena: { name: 'Чижовка-Арена', start_time: '19:00' },
        passes: [pass({ trainer_id: 42, trainer_name: 'Тренер', sessions_remaining: 2 })],
      },
      NOW
    );
    assert.equal(view.wallet[0].label, 'Абонемент');
  });
});

/* ── 4. Чипы окон ─────────────────────────────────────────────────────── */

describe('правило 4: максимум 4 окна плюс обязательные «Все окна»', () => {
  it('десять слотов дают 4 чипа и один «Все окна» последним', () => {
    const { buildView, renderHtml } = loadModel();
    const view = buildView({ kind: 'trainer', trainer: trainer(), slots: slots(10) }, NOW);
    assert.equal(view.pick.chips.length, 4);
    const out = renderHtml(view);
    const all = out.match(/me__chip me__chip--all/g) || [];
    assert.equal(all.length, 1);
    // «Все окна» — последний элемент полосы.
    assert.ok(/me__chip--all[^>]*>[^<]*<\/button><\/div><\/div>/.test(out), out);
  });

  it('одно окно — всё равно есть вход во все окна', () => {
    const out = html({ kind: 'trainer', trainer: trainer(), slots: slots(1) });
    assert.equal((out.match(/class="me__chip"/g) || []).length, 1);
    assert.ok(out.includes('me__chip--all'));
  });

  it('нет слотов — нет всей полосы me__pick, но карточка тренера цела', () => {
    const { buildView } = loadModel();
    for (const slotsValue of [undefined, null, [], [{}], [{ start_time: '' }], 'мусор']) {
      const view = buildView({ kind: 'trainer', trainer: trainer(), slots: slotsValue }, NOW);
      assert.ok(view, `slots=${JSON.stringify(slotsValue)} не должен ломать карточку`);
      assert.equal(view.pick, null);
      const out = html({ kind: 'trainer', trainer: trainer(), slots: slotsValue });
      assert.ok(!out.includes('me__pick'));
      assert.ok(!out.includes('me__chip'));
      assert.ok(out.includes('class="me__who'), 'лицо тренера на месте');
      assert.ok(out.includes('Александр Гаевский'));
    }
  });

  it('canBook === false снимает полосу окон целиком', () => {
    const { buildView } = loadModel();
    const view = buildView({ kind: 'trainer', trainer: trainer({ canBook: false }), slots: slots(4) }, NOW);
    assert.equal(view.pick, null);
  });

  it('чип несёт день, время и идентификаторы слота', () => {
    const out = html({ kind: 'trainer', trainer: trainer(), slots: slots(1) });
    assert.ok(out.includes('<em>Завтра</em><b>10:00</b>'));
    assert.ok(out.includes('data-me-slot-id="100"'));
    assert.ok(out.includes('data-me-service-id="3"'));
    assert.ok(out.includes('data-me-arena-id="9"'));
  });
});

/* ── 5. Корень карточки не интерактивен ───────────────────────────────── */

describe('правило 5: корень .me не кликабелен', () => {
  const cases = () => [
    { kind: 'booking', booking: booking(), passes: [pass()] },
    { kind: 'booking', booking: booking({ status: 'pending' }) },
    { kind: 'trainer', trainer: trainer(), slots: slots(4), passes: [pass()] },
    { kind: 'trainer', trainer: trainer(), slots: [] },
    { kind: 'dormant', trainer: trainer(), slots: slots(2), passes: [pass({ expires_at: '2026-10-12' })], history: { completed_count: 7, last_completed_at: '2026-05-18' } },
    { kind: 'city-ice', arena: { id: 5, name: 'Чижовка-Арена', address: 'ул. Ташкентская, 19', city_name: 'Минск', start_time: '19:00', kind_label: 'Массовое катание', price_label: '12 BYN' }, slots: slots(3) },
    { kind: 'city-pick', cities: [{ id: 1, name: 'Минск' }, { id: 2, name: 'Брест' }] },
    { kind: 'far', arena: { name: 'Брест-Арена', city_name: 'Брест' } },
  ];

  it('у элемента .me нет onclick, role="button" и tabindex', () => {
    for (const input of cases()) {
      const out = html(input);
      const root = out.slice(0, out.indexOf('>') + 1);
      assert.ok(/^<div class="me/.test(root), root);
      assert.ok(!/onclick/i.test(root), root);
      assert.ok(!/role\s*=/i.test(root), root);
      assert.ok(!/tabindex/i.test(root), root);
    }
  });

  it('нигде в карточке нет onclick, role="button" и tabindex', () => {
    for (const input of cases()) {
      const out = html(input);
      assert.ok(!/onclick/i.test(out), out);
      assert.ok(!/role="button"/i.test(out), out);
      assert.ok(!/tabindex/i.test(out), out);
    }
  });

  it('кликабельны только вложенные button, и все они type="button"', () => {
    for (const input of cases()) {
      const out = html(input);
      const opens = out.match(/<button/g) || [];
      const typed = out.match(/<button type="button"/g) || [];
      assert.equal(opens.length, typed.length, out);
      // Действия адресуются через data-me-action, а не через обработчики в разметке.
      assert.equal(opens.length, (out.match(/data-me-action="/g) || []).length, out);
    }
  });
});

describe('лицо тренера — вложенная кнопка, открывающая его карточку', () => {
  it('аватар и имя внутри кнопки open-trainer с id тренера', () => {
    const out = html({ kind: 'trainer', trainer: trainer(), slots: slots(2) });
    assert.ok(out.includes('<button type="button" class="me__who-link" data-me-action="open-trainer" data-me-trainer-id="7"'), out);
    assert.ok(/me__who-link[^>]*>.*?avatar.*?me__who-t.*?<\/button>/.test(out), 'аватар и имя внутри кнопки');
    assert.ok(out.includes('aria-label="Карточка тренера, Александр Гаевский"'));
  });

  it('конверт — кнопка-сестра, а не вложенная (кнопка в кнопке невалидна)', () => {
    const out = html({ kind: 'booking', booking: booking() });
    assert.ok(out.includes('class="me__who-link"'));
    assert.ok(out.includes('class="me__dm"'));
    const link = out.slice(out.indexOf('me__who-link'), out.indexOf('me__dm'));
    assert.ok(link.includes('</button>'), 'кнопка лица закрыта до конверта');
  });

  it('на неинтерактивном контейнере me__who id тренера не висит', () => {
    const out = html({ kind: 'trainer', trainer: trainer(), slots: slots(2) });
    // Сам контейнер — просто flex-обёртка: атрибут действия живёт на кнопке.
    assert.ok(!/class="me__who( me__who--hero)?"[^>]*data-me-trainer-id/.test(out), out);
    assert.ok(out.includes('<div class="me__who me__who--hero"><button'), out);
    assert.equal((out.match(/data-me-trainer-id/g) || []).length, 2, 'лицо и кнопка «Все окна»');
  });

  it('нет id тренера — лицо остаётся неинтерактивным (арена, тренер без id)', () => {
    const iceOut = html({ kind: 'city-ice', arena: { name: 'Чижовка-Арена', start_time: '19:00' } });
    assert.ok(iceOut.includes('Чижовка-Арена'));
    assert.ok(!iceOut.includes('me__who-link'), 'арена — не карточка тренера');
    const noId = html({ kind: 'trainer', trainer: trainer({ id: null }), slots: slots(2) });
    assert.ok(!noId.includes('me__who-link'));
    assert.ok(noId.includes('Александр Гаевский'));
  });
});

/* ── 6. Никаких выдуманных данных ─────────────────────────────────────── */

describe('правило 6: нет поля — нет строки', () => {
  it('нет арены — строки места нет (и уж точно нет «ваш тренер»)', () => {
    const { buildView } = loadModel();
    const view = buildView({ kind: 'booking', booking: booking({ arena_name: null }) }, NOW);
    assert.equal(view.who.place, '');
    const out = html({ kind: 'booking', booking: booking({ arena_name: null }) });
    assert.ok(!out.includes('ваш тренер'));
    assert.ok(!out.includes('<span>⌖'));
    // Имя при этом на месте.
    assert.ok(out.includes('Александр Гаевский'));
  });

  it('у тренера без арены и города строки места нет', () => {
    const { buildView } = loadModel();
    const view = buildView(
      { kind: 'trainer', trainer: trainer({ arena_name: null, city_name: '' }), slots: slots(2) },
      NOW
    );
    assert.equal(view.who.place, '');
    assert.ok(!html({ kind: 'trainer', trainer: trainer({ arena_name: null, city_name: '' }), slots: slots(2) }).includes('⌖'));
  });

  it('нет имени тренера — блока с лицом нет, имя не выдумывается', () => {
    const { buildView } = loadModel();
    const out = html({ kind: 'booking', booking: booking({ trainer_name: '' }) });
    assert.ok(!out.includes('me__who'));
    assert.ok(!/Тренер|тренер Александр|Имя/.test(out.replace(/Написать тренеру|не ответит/g, '')));
    // Запись без имени тренера существует — время и штамп на месте.
    assert.ok(out.includes('<b>12:15</b>'));
    assert.equal(buildView({ kind: 'trainer', trainer: trainer({ name: '' }), slots: slots(2) }, NOW), null,
      'тренер без имени — не карточка тренера');
  });

  it('у города без данных карточка не подставляет ни адрес, ни цену, ни вид', () => {
    const out = html({ kind: 'city-ice', arena: { name: 'Чижовка-Арена', start_time: '19:00' } });
    assert.ok(out.includes('<div class="me__when"><b>19:00</b></div>'), out);
    assert.ok(!out.includes('BYN'));
    assert.ok(!out.includes('Массовое'));
  });

  it('нет срока абонемента — подписи о сроке нет', () => {
    const { buildView } = loadModel();
    const view = buildView(
      { kind: 'trainer', trainer: trainer(), slots: slots(1), passes: [pass({ expires_at: null, sessions_remaining: 2 })] },
      NOW
    );
    assert.equal(view.wallet[0].sub, '');
    assert.equal(view.wallet[0].warn, false);
  });

  it('нет sessions_total — нет ни «из N», ни полосы прогресса', () => {
    const { buildView } = loadModel();
    const view = buildView(
      { kind: 'trainer', trainer: trainer(), slots: slots(1), passes: [pass({ sessions_total: 0, sessions_remaining: 3 })] },
      NOW
    );
    assert.equal(view.wallet[0].unit, '');
    assert.equal(view.wallet[0].bar, null);
    assert.ok(!html({ kind: 'trainer', trainer: trainer(), slots: slots(1), passes: [pass({ sessions_total: 0, sessions_remaining: 3 })] }).includes('me__w-bar'));
  });

  it('нет контакта тренера — залитой кнопки «написать» нет', () => {
    const noContact = trainer({ username: '', telegramId: null, canBook: false });
    const out = html({ kind: 'trainer', trainer: noContact, slots: [] });
    assert.ok(!out.includes('btn-fill'));
    assert.ok(!out.includes('me__dm'));
    assert.ok(out.includes('btn-ghost'));
  });

  it('заливка far не обещает рассылки, которой нет', () => {
    const out = html({ kind: 'far', arena: { name: 'Брест-Арена', city_name: 'Брест' } });
    assert.ok(!/напишем|сообщим|уведомим|подписаться/i.test(out), out);
  });
});

/* ── 7. Экранирование ─────────────────────────────────────────────────── */

describe('правило 7: весь текст из данных экранируется', () => {
  it('<script> в имени тренера и названии арены не попадает в разметку', () => {
    const evil = '<script>alert(1)</script>';
    const out = html({
      kind: 'booking',
      booking: booking({ trainer_name: evil, arena_name: '"Арена" & <b>co</b>' }),
    });
    assert.ok(!out.includes('<script'), out);
    assert.ok(out.includes('&lt;script&gt;'));
    assert.ok(out.includes('&quot;Арена&quot; &amp; &lt;b&gt;co&lt;/b&gt;'));
  });

  it('<script> экранируется во всех текстовых узлах всех заливок', () => {
    const evil = '<script>x</script>';
    const inputs = [
      { kind: 'booking', booking: booking({ trainer_name: evil, arena_name: evil, date_label: evil }) },
      { kind: 'trainer', trainer: trainer({ name: evil, arena_name: evil, city_name: evil }), slots: [{ id: evil, start_time: '10:00', slot_date: '2026-10-05', arena_id: evil, service_id: evil }] },
      { kind: 'dormant', trainer: trainer({ name: evil }), history: { completed_count: 3 }, passes: [pass({ trainer_name: evil, sessions_remaining: 2 })] },
      { kind: 'city-ice', arena: { name: evil, address: evil, city_name: evil, start_time: '19:00', kind_label: evil, price_label: evil } },
      { kind: 'city-pick', cities: [{ id: evil, name: evil }] },
      { kind: 'far', arena: { name: evil, city_name: evil } },
    ];
    for (const input of inputs) {
      const out = html(input);
      assert.ok(!out.includes('<script'), `${input.kind}: ${out}`);
      assert.ok(out.includes('&lt;script&gt;'), `${input.kind}: ${out}`);
    }
  });

  it('кавычки в данных не ломают атрибуты', () => {
    const out = html({
      kind: 'booking',
      booking: booking({ trainer_telegram_username: 'a" onload="x', trainer_list_photo_key: 'a"b' }),
    });
    // Кавычка закрыта как &quot;, поэтому «onload=» остаётся текстом внутри
    // значения, а не становится новым атрибутом.
    assert.ok(!/\son[a-z]+\s*=\s*"/i.test(out), out);
    assert.ok(out.includes('data-me-dm-un="a&quot; onload=&quot;x"'), out);
    assert.ok(out.includes('src="/api/public/photos/a%22b"'), out);
  });
});

/* ── 8. Чистота модуля ───────────────────────────────────────────────── */

describe('правило 8: модуль чистый', () => {
  it('в исходнике нет document, window.location, fetch и Date.now()', () => {
    const src = fs.readFileSync(modelPath, 'utf8');
    // Комментарии перечисляют запреты — проверяем сам код.
    const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    for (const banned of ['document', 'window.location', 'fetch(', 'Date.now(', 'localStorage', 'XMLHttpRequest']) {
      assert.ok(!code.includes(banned), `запрещённое обращение «${banned}» в коде модуля`);
    }
  });

  it('работает без document и window: загрузка в node ничего не требует', () => {
    const { buildView, renderHtml } = loadModel();
    assert.equal(typeof buildView, 'function');
    assert.equal(typeof renderHtml, 'function');
    assert.equal(typeof globalThis.document, 'undefined');
    assert.ok(globalThis.HubMeCard, 'UMD вешает api на globalThis');
  });

  it('относительные подписи считаются от аргумента now, а не от часов машины', () => {
    const { buildView } = loadModel();
    const input = { kind: 'trainer', trainer: trainer(), slots: [{ id: 1, start_time: '10:00', slot_date: '2026-10-05' }] };
    assert.equal(buildView(input, new Date(2026, 9, 5, 9, 0)).pick.chips[0].day, 'Сегодня');
    assert.equal(buildView(input, new Date(2026, 9, 4, 9, 0)).pick.chips[0].day, 'Завтра');
    assert.equal(buildView(input, new Date(2026, 9, 1, 9, 0)).pick.chips[0].day, 'Пн, 5 окт');
  });

  it('невалидный now не выдумывает относительных подписей', () => {
    const { buildView } = loadModel();
    const input = { kind: 'trainer', trainer: trainer(), slots: [{ id: 1, start_time: '10:00', slot_date: '2026-10-05' }] };
    for (const bad of [undefined, null, 'сегодня', new Date('x'), 0]) {
      const view = buildView(input, bad);
      assert.equal(view.pick.chips[0].day, 'Пн, 5 окт', `now=${String(bad)}`);
    }
  });

  it('повторный вызов на тех же данных даёт тот же результат', () => {
    const input = { kind: 'dormant', trainer: trainer(), slots: slots(2), passes: [pass()], history: { completed_count: 7, last_completed_at: '2026-05-18' } };
    assert.equal(html(input), html(input));
  });
});

/* ── Happy path по каждой заливке ─────────────────────────────────────── */

describe('happy path: booking', () => {
  it('подтверждённая запись: время, штамп, лицо, место, подвал', () => {
    const out = html({ kind: 'booking', booking: booking(), passes: [pass({ sessions_remaining: 3 })] });
    assert.ok(out.includes('me--accent'));
    assert.ok(out.includes('me__status'));
    assert.ok(out.includes('class="k">Ваша запись<'));
    assert.ok(out.includes('pill pill--ok'));
    assert.ok(out.includes('подтверждена'));
    assert.ok(out.includes('<b>12:15</b>'));
    assert.ok(out.includes('avatar--photo'));
    assert.ok(out.includes('/api/public/photos/photos%2Fag.jpg'));
    assert.ok(out.includes('⌖ ТЦ Замок'));
    assert.ok(out.includes('class="me__dm"'));
    assert.ok(out.includes('me__foot'));
    assert.ok(out.includes('Детали, перенос, отмена'));
  });

  it('«Сегодня» вместо даты в статусе, день не дублируется в подписи времени', () => {
    const { buildView } = loadModel();
    const view = buildView({ kind: 'booking', booking: booking({ date_label: 'Сегодня' }) }, NOW);
    assert.equal(view.status.label, 'Сегодня');
    assert.equal(view.when.meta, '45 мин');
  });

  it('идёт сейчас: штамп «сейчас», действия нет', () => {
    const { buildView } = loadModel();
    const view = buildView({ kind: 'booking', booking: booking({ hub_in_session: true, date_label: 'Сегодня' }) }, NOW);
    assert.deepEqual(view.status.pill, { kind: 'soon', label: 'сейчас' });
    assert.deepEqual(view.actions, []);
  });

  it('ждёт подтверждения: warn-рамка, единственный глагол — написать, конверта в шапке нет', () => {
    const { buildView } = loadModel();
    const input = { kind: 'booking', booking: booking({ status: 'pending' }) };
    const view = buildView(input, NOW);
    assert.equal(view.mod, 'warn');
    assert.deepEqual(view.status.pill, { kind: 'wait', label: 'ждёт тренера' });
    assert.equal(view.who.dm, null);
    assert.equal(view.foot, null, 'нечего открывать, пока запись не подтверждена');
    assert.equal(view.actions.length, 1);
    assert.equal(view.actions[0].style, 'fill');
    const out = html(input);
    assert.ok(!out.includes('me__dm'));
    assert.ok(out.includes('Время держится за вами, пока Александр не ответит.'));
    assert.ok(out.includes('data-me-dm-un="gaevsky"'));
    assert.ok(out.includes('data-me-dm-tid="100500"'));
  });
});

/* ── Штамп записи и конец занятия (booking.start) ─────────────────────── */

describe('штамп записи: та же логика, что у nextCardStamp в хабе', () => {
  const pill = (b, now = NOW) => loadModel().buildView({ kind: 'booking', booking: booking(b) }, now).status.pill;

  it('ожидание важнее всего: ответ тренера — действие', () => {
    assert.deepEqual(
      pill({ status: 'pending', hub_in_session: true, start: new Date(2026, 9, 4, 19, 0) }),
      { kind: 'wait', label: 'ждёт тренера' }
    );
  });

  it('идёт сейчас — «сейчас», даже если по времени это «через час»', () => {
    assert.deepEqual(
      pill({ hub_in_session: true, start: new Date(2026, 9, 4, 19, 0) }),
      { kind: 'soon', label: 'сейчас' }
    );
  });

  it('до начала не больше трёх часов — «через N» с правильным склонением', () => {
    const at = (h, m) => pill({ start: new Date(2026, 9, 4, h, m) }).label;
    assert.equal(at(18, 20), 'через 20 минут');
    assert.equal(at(18, 1), 'через 1 минуту');
    assert.equal(at(18, 22), 'через 22 минуты');
    assert.equal(at(18, 45), 'через 45 минут');
    assert.equal(at(19, 0), 'через час');
    assert.equal(at(20, 0), 'через 2 часа');
    assert.equal(at(20, 55), 'через 3 часа');
    for (const h of [18, 19, 20]) assert.equal(pill({ start: new Date(2026, 9, 4, h, 30) }).kind, 'soon');
  });

  it('дальше трёх часов и всё, что уже прошло — обычное «подтверждена»', () => {
    assert.deepEqual(pill({ start: new Date(2026, 9, 4, 21, 30) }), { kind: 'ok', label: 'подтверждена' });
    assert.deepEqual(pill({ start: new Date(2026, 9, 5, 12, 15) }), { kind: 'ok', label: 'подтверждена' });
    assert.deepEqual(pill({ start: new Date(2026, 9, 4, 17, 0) }), { kind: 'ok', label: 'подтверждена' });
  });

  it('start принимается и ISO-строкой, и Date', () => {
    assert.equal(pill({ start: '2026-10-04T20:00:00' }).label, 'через 2 часа');
    assert.equal(pill({ start: new Date(2026, 9, 4, 20, 0) }).label, 'через 2 часа');
  });

  it('нет start, мусорный start или нет now — о близости штамп молчит', () => {
    for (const bad of [undefined, null, '', 'скоро', new Date('x'), {}]) {
      assert.deepEqual(pill({ start: bad }), { kind: 'ok', label: 'подтверждена' }, `start=${String(bad)}`);
    }
    assert.deepEqual(pill({ start: new Date(2026, 9, 4, 20, 0) }, null), { kind: 'ok', label: 'подтверждена' });
  });

  it('«до 13:00» — только у сегодняшнего занятия, и только когда есть start и duration', () => {
    const { buildView } = loadModel();
    const meta = (b) => buildView({ kind: 'booking', booking: booking(b) }, NOW).when.meta;
    assert.equal(meta({ date_label: 'Сегодня', start: new Date(2026, 9, 4, 12, 15), duration_minutes: 45 }), '45 мин · до 13:00');
    // Не сегодня — конца нет: им планируют текущий день, на послезавтра это шум.
    assert.equal(meta({ start: new Date(2026, 9, 5, 12, 15), duration_minutes: 45 }), 'Завтра · 45 мин');
    // Через полночь часы не врут.
    assert.equal(meta({ date_label: 'Сегодня', start: new Date(2026, 9, 4, 23, 40), duration_minutes: 45 }), '45 мин · до 00:25');
    // Нет одного из двух — строки конца нет.
    assert.equal(meta({ date_label: 'Сегодня', duration_minutes: 45 }), '45 мин');
    assert.equal(meta({ date_label: 'Сегодня', start: new Date(2026, 9, 4, 12, 15), duration_minutes: 0 }), '');
    assert.equal(meta({ date_label: 'Сегодня', start: new Date(2026, 9, 4, 12, 15), duration_minutes: null }), '');
  });
});

/* ── Падежи имени ─────────────────────────────────────────────────────── */

describe('падежи: готовые формы от вызывающего, иначе безпадежный фолбэк', () => {
  it('есть nameDative — «Написать Александру»', () => {
    const { buildView } = loadModel();
    const view = buildView(
      { kind: 'trainer', trainer: trainer({ nameDative: 'Александру Гаевскому' }), slots: [] },
      NOW
    );
    assert.equal(view.actions[0].label, 'Написать Александру');
    const out = html({ kind: 'trainer', trainer: trainer({ nameDative: 'Александру' }), slots: [] });
    assert.ok(out.includes('>Написать Александру</button>'));
  });

  it('есть nameGenitive — «Все окна Александра»', () => {
    const { buildView } = loadModel();
    const view = buildView(
      { kind: 'trainer', trainer: trainer({ nameGenitive: 'Александра Гаевского' }), slots: slots(2) },
      NOW
    );
    assert.equal(view.actions[0].label, 'Все окна Александра');
  });

  it('падежи работают и в записи, и в возврате', () => {
    const { buildView } = loadModel();
    const pendingView = buildView(
      { kind: 'booking', booking: booking({ status: 'pending' }), trainer: { nameDative: 'Александру' } },
      NOW
    );
    assert.equal(pendingView.actions[0].label, 'Написать Александру');
    const dormantView = buildView(
      {
        kind: 'dormant',
        trainer: trainer({ nameGenitive: 'Александра' }),
        slots: slots(2),
        history: { completed_count: 7 },
      },
      NOW
    );
    assert.equal(dormantView.actions[0].label, 'Все окна Александра');
  });

  it('нет форм — безпадежный фолбэк, а не кривой падеж', () => {
    const { buildView } = loadModel();
    assert.equal(
      buildView({ kind: 'trainer', trainer: trainer(), slots: [] }, NOW).actions[0].label,
      'Написать тренеру'
    );
    assert.equal(
      buildView({ kind: 'trainer', trainer: trainer(), slots: slots(2) }, NOW).actions[0].label,
      'Все окна'
    );
    // Пустые и мусорные формы к падежу не приводят.
    for (const bad of ['', '   ', null, undefined, 'Тренер']) {
      const view = buildView({ kind: 'trainer', trainer: trainer({ nameDative: bad }), slots: [] }, NOW);
      assert.equal(view.actions[0].label, 'Написать тренеру', `nameDative=${String(bad)}`);
    }
  });

  it('остаток чужого тренера подписан родительным падежом, когда он дан', () => {
    const { buildView } = loadModel();
    const cell = (extra) => buildView(
      {
        kind: 'city-ice',
        arena: { name: 'Чижовка-Арена', start_time: '19:00' },
        passes: [pass(Object.assign({ trainer_id: 42, trainer_name: 'Марина Ковалёва', sessions_remaining: 2 }, extra))],
      },
      NOW
    ).wallet[0].label;
    assert.equal(cell({ trainer_name_genitive: 'Марины Ковалёвой' }), 'Абонемент у Марины');
    assert.equal(cell({}), 'Абонемент · Марина', 'без падежа имя всё равно названо');
  });
});

describe('happy path: trainer', () => {
  it('тренер с окнами: лицо-герой, чипы, вход во все окна, кошелёк', () => {
    const out = html({ kind: 'trainer', trainer: trainer(), slots: slots(4), passes: [pass({ sessions_remaining: 2 })] });
    assert.ok(out.includes('me--accent'));
    assert.ok(out.includes('class="k">Ваш тренер<'));
    assert.ok(out.includes('me__who--hero'));
    assert.ok(out.includes('data-me-trainer-id="7"'));
    assert.ok(out.includes('⌖ ТЦ Замок · Минск'));
    assert.ok(out.includes('class="k">Когда вам удобно<'));
    assert.equal((out.match(/class="me__chip"/g) || []).length, 4);
    assert.ok(out.includes('Все окна →'));
    assert.ok(out.includes('me__wallet'));
    assert.ok(!out.includes('btn-fill'), 'выбор времени и есть действие — заливки тут нет');
  });

  it('окон нет: честный текст и единственный глагол «написать»', () => {
    const out = html({ kind: 'trainer', trainer: trainer(), slots: [] });
    assert.ok(!out.includes('me--accent'));
    assert.ok(out.includes('Свободных окон в расписании нет.'));
    assert.ok(out.includes('btn-fill'));
    assert.ok(out.includes('Написать тренеру'));
    assert.ok(out.includes('Все тренеры'));
  });
});

describe('happy path: dormant', () => {
  it('остался абонемент с горящим сроком: warn, срок назван один раз — в кошельке', () => {
    const out = html({
      kind: 'dormant',
      trainer: trainer(),
      slots: slots(3),
      passes: [pass({ expires_at: '2026-10-12', sessions_remaining: 1 })],
      history: { completed_count: 7, last_completed_at: '2026-05-18' },
    });
    assert.ok(out.includes('me--warn'));
    assert.ok(out.includes('class="k">У вас остался абонемент<'));
    assert.ok(out.includes('последнее занятие — 18 мая'));
    assert.ok(!out.includes('⌖ последнее занятие'), 'дата — не место, пина нет');
    assert.ok(out.includes('сгорит 12 окт · через 8 дней'));
    assert.equal((out.match(/12 окт/g) || []).length, 1, 'срок назван ровно один раз');
    assert.ok(out.includes('class="k">Ближайшие окна<'));
  });

  it('остатка нет, но история есть: статус из истории, кошелька нет', () => {
    const out = html({ kind: 'dormant', trainer: trainer(), history: { completed_count: 7, last_completed_at: '2026-05-18' } });
    assert.ok(out.includes('Вы тренировались 7 раз'));
    assert.ok(!out.includes('me__wallet'));
    assert.ok(out.includes('Найти тренера'));
  });

  it('склонение «раз» честное', () => {
    const { buildView } = loadModel();
    const label = (n) => buildView({ kind: 'dormant', history: { completed_count: n } }, NOW).status.label;
    assert.equal(label(1), 'Вы тренировались 1 раз');
    assert.equal(label(3), 'Вы тренировались 3 раза');
    assert.equal(label(7), 'Вы тренировались 7 раз');
    assert.equal(label(11), 'Вы тренировались 11 раз');
  });

  it('ни остатка, ни истории — заливки возврата не существует', () => {
    const { buildView } = loadModel();
    assert.equal(buildView({ kind: 'dormant' }, NOW), null);
    assert.equal(buildView({ kind: 'dormant', trainer: trainer(), history: { completed_count: 0 } }, NOW), null);
    assert.equal(buildView({ kind: 'dormant', passes: [pass({ sessions_remaining: 0 })] }, NOW), null);
  });
});

describe('happy path: city-ice', () => {
  it('лёд города: заголовок из факта сеанса, арена лицом, «Дальше на льду»', () => {
    const out = html({
      kind: 'city-ice',
      arena: {
        id: 5,
        name: 'Чижовка-Арена',
        address: 'ул. Ташкентская, 19',
        city_name: 'Минск',
        start_time: '19:00:00',
        kind_label: 'Массовое катание',
        price_label: '12 BYN',
      },
      slots: slots(3),
    });
    assert.ok(out.includes('class="k">На льду сегодня · Минск<'));
    assert.ok(out.includes('<div class="me__when"><b>19:00</b><span>Массовое катание · 12 BYN</span></div>'), out);
    assert.ok(out.includes('>❄</div>'));
    assert.ok(out.includes('Чижовка-Арена'));
    assert.ok(out.includes('⌖ ул. Ташкентская, 19'));
    assert.ok(out.includes('class="k">Дальше на льду<'));
    assert.ok(out.includes('Все сеансы →'));
    assert.ok(out.includes('data-me-arena-id="5"'));
  });

  it('нет ни имени, ни времени — карточки лёда нет', () => {
    const { buildView } = loadModel();
    assert.equal(buildView({ kind: 'city-ice' }, NOW), null);
    assert.equal(buildView({ kind: 'city-ice', arena: { city_name: 'Минск' } }, NOW), null);
  });
});

describe('happy path: city-pick', () => {
  it('города первым классом, геолокация тихой строкой, подвал — вся страна', () => {
    const cities = ['Минск', 'Брест', 'Гродно', 'Гомель', 'Витебск', 'Могилёв'].map((name, i) => ({ id: i + 1, name }));
    const out = html({ kind: 'city-pick', cities: cities });
    assert.ok(out.includes('class="k">С чего начнём<'));
    assert.ok(out.includes('me__head">Где вы катаетесь?<'));
    assert.ok(out.includes('me__cities'));
    assert.equal((out.match(/class="me__city"/g) || []).length, 6);
    assert.ok(out.includes('data-me-city-id="1"'));
    assert.ok(out.includes('class="me__geo"'));
    assert.ok(out.includes('Определить по геопозиции'));
    assert.ok(out.includes('me__foot'));
    assert.ok(out.includes('Показать всю Беларусь'));
    // Геолокация идёт ПОСЛЕ сетки городов: тап по городу дешевле системного диалога.
    assert.ok(out.indexOf('me__cities') < out.indexOf('me__geo'));
  });

  it('ровно шесть городов влезают целиком, «Другой город» не нужен', () => {
    const { buildView } = loadModel();
    const six = [];
    for (let i = 0; i < 6; i++) six.push({ id: i + 1, name: 'Город ' + (i + 1) });
    const view = buildView({ kind: 'city-pick', cities: six }, NOW);
    assert.equal(view.cities.length, 6);
    assert.equal(view.moreCities, false);
    const out = html({ kind: 'city-pick', cities: six });
    assert.equal((out.match(/class="me__city"/g) || []).length, 6);
    assert.ok(!out.includes('more-cities'));
    assert.ok(!out.includes('Другой город'));
  });

  it('DEC-008: городов больше шести — шестая кнопка «Другой город», хвост достижим', () => {
    const { buildView } = loadModel();
    for (const total of [7, 12, 90]) {
      const many = [];
      for (let i = 0; i < total; i++) many.push({ id: i + 1, name: 'Город ' + (i + 1) });
      const view = buildView({ kind: 'city-pick', cities: many }, NOW);
      assert.equal(view.cities.length, 5, `городов ${total}`);
      assert.equal(view.moreCities, true);
      const out = html({ kind: 'city-pick', cities: many });
      // Всего кнопок города — ровно шесть, последняя ведёт к остальным.
      assert.equal((out.match(/class="me__city"/g) || []).length, 6, out);
      assert.ok(out.includes('data-me-action="more-cities">Другой город</button>'), out);
      assert.ok(out.indexOf('more-cities') > out.lastIndexOf('data-me-city-id'), '«Другой город» последний');
      assert.ok(!out.includes('Город 7'), 'не влезший город не нарисован, но достижим через «Другой город»');
    }
  });

  it('городов нет — выбирать нечего, карточки нет', () => {
    const { buildView } = loadModel();
    assert.equal(buildView({ kind: 'city-pick' }, NOW), null);
    assert.equal(buildView({ kind: 'city-pick', cities: [] }, NOW), null);
    assert.equal(buildView({ kind: 'city-pick', cities: [{ id: 1 }, { name: '  ' }] }, NOW), null);
  });
});

describe('happy path: far', () => {
  it('развилка из двух действий, без льда и без обещаний', () => {
    const out = html({ kind: 'far', arena: { name: 'Брест-Арена', city_name: 'Брест' } });
    assert.ok(out.includes('me--warn'));
    assert.ok(out.includes('class="k">Мы пока не в вашем городе<'));
    assert.ok(out.includes('me__head">Ближайший лёд — Брест<'));
    assert.ok(out.includes('«Брест-Арена», Брест. Выберите город'));
    assert.ok(out.includes('btn-fill'));
    assert.ok(out.includes('Выбрать свой город'));
    assert.ok(out.includes('btn-ghost'));
    assert.ok(out.includes('Смотреть всю Беларусь'));
    assert.ok(!out.includes('me__when'));
    assert.ok(!out.includes('me__pick'));
  });

  it('дистанция есть в данных (геолокация отработала) — «Ближайший лёд — 180 км»', () => {
    const { buildView } = loadModel();
    const head = (km) => buildView({ kind: 'far', arena: { name: 'Брест-Арена', city_name: 'Брест', distance_km: km } }, NOW).head;
    assert.equal(head(180), 'Ближайший лёд — 180 км');
    assert.equal(head(179.6), 'Ближайший лёд — 180 км');
    assert.equal(head('180'), 'Ближайший лёд — 180 км');
    // Близко — километр с десятой: «0 км» было бы неправдой.
    assert.equal(head(2.34), 'Ближайший лёд — 2.3 км');
    assert.equal(head(0.4), 'Ближайший лёд — 0.4 км');
    const out = html({ kind: 'far', arena: { name: 'Брест-Арена', city_name: 'Брест', distance_km: 180 } });
    assert.ok(out.includes('me__head">Ближайший лёд — 180 км<'), out);
    // Город не потерян — он в строке под заголовком.
    assert.ok(out.includes('«Брест-Арена», Брест.'));
  });

  it('дистанции нет — говорим городом, километры не выдумываем', () => {
    const { buildView } = loadModel();
    const head = (km) => buildView({ kind: 'far', arena: { name: 'Брест-Арена', city_name: 'Брест', distance_km: km } }, NOW).head;
    for (const bad of [undefined, null, '', 'далеко', NaN, -5, {}]) {
      assert.equal(head(bad), 'Ближайший лёд — Брест', `distance_km=${String(bad)}`);
    }
  });

  it('даже без ближайшей арены остаётся честная развилка', () => {
    const { buildView } = loadModel();
    const view = buildView({ kind: 'far' }, NOW);
    assert.ok(view);
    assert.equal(view.head, 'Где вы катаетесь?');
    assert.equal(view.line, 'Выберите город, где катаетесь, — покажем, что в нём есть.');
    assert.equal(view.actions.length, 2);
  });
});

/* ── Пустые и битые входы ─────────────────────────────────────────────── */

describe('пустые и битые входы', () => {
  it('buildView возвращает null, renderHtml(null) — пустую строку', () => {
    const { buildView, renderHtml } = loadModel();
    for (const bad of [undefined, null, 0, '', 'booking', [], {}, { kind: '' }, { kind: 'что-то' }, { kind: 'BOOKING' }]) {
      assert.equal(buildView(bad, NOW), null, `input=${JSON.stringify(bad)}`);
    }
    assert.equal(renderHtml(null), '');
    assert.equal(renderHtml(undefined), '');
    assert.equal(renderHtml(buildView(null, NOW)), '');
    assert.equal(renderHtml('<div>'), '');
  });

  it('заливка без своих данных не рендерит каркас вместо карточки', () => {
    const { buildView } = loadModel();
    assert.equal(buildView({ kind: 'booking' }, NOW), null);
    assert.equal(buildView({ kind: 'booking', booking: {} }, NOW), null);
    assert.equal(buildView({ kind: 'booking', booking: { start_time: '' } }, NOW), null);
    assert.equal(buildView({ kind: 'trainer' }, NOW), null);
    assert.equal(buildView({ kind: 'trainer', trainer: { id: 7 } }, NOW), null);
  });

  it('мусор в коллекциях не ломает сборку', () => {
    const { buildView } = loadModel();
    const view = buildView(
      {
        kind: 'trainer',
        trainer: trainer(),
        slots: [null, 'x', {}, { start_time: '10:00', slot_date: 'мусор' }],
        passes: 'не массив',
        certificates: [null, 42],
      },
      NOW
    );
    assert.ok(view);
    assert.equal(view.pick.chips.length, 1);
    assert.equal(view.pick.chips[0].day, '');
    assert.deepEqual(view.wallet, []);
  });

  it('каждая заливка либо честный view с kind, либо null', () => {
    const { buildView } = loadModel();
    const kinds = ['booking', 'trainer', 'dormant', 'city-ice', 'city-pick', 'far'];
    for (const kind of kinds) {
      const view = buildView({ kind: kind }, NOW);
      if (view) assert.equal(view.kind, kind);
    }
  });
});
