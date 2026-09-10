/**
 * Флоу «карточка арены → тренер → выбор времени → назад».
 *
 * Один из основных клиентских путей, и в нём было два тупика подряд:
 *   1. на пустом «Выберите время» текст называл два выхода («оставьте заявку»,
 *      «посмотрите слоты на других аренах») и ни один не нажимался;
 *   2. «Назад» с этого экрана уходило на карточку тренера, которая при входе с
 *      арены никогда не отрисовывалась, — то есть на пустую страницу.
 *
 * Гейт, а не разовая проверка: оба места легко откатить обратно одной правкой.
 *
 * Run: node --test tests/js/arena-to-booking-flow.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');

function read(name) {
  return fs.readFileSync(path.join(webapp, name), 'utf8');
}

function loadBookingClient() {
  const p = path.join(webapp, 'booking-client.js');
  delete require.cache[require.resolve(p)];
  const m = require(p);
  return m.BookingClient || m;
}

function loadArenaModel() {
  const p = path.join(webapp, 'arena-card-model.js');
  delete require.cache[require.resolve(p)];
  return require(p);
}

describe('тренер с арены ведёт строго на карточку тренера', () => {
  it('ссылка несёт происхождение и арену для возврата', () => {
    const { buildBookingHref } = loadArenaModel();
    const href = buildBookingHref({ trainerId: 710, arenaId: 42 });
    assert.match(href, /^catalog\?/);
    assert.match(href, /from=arena/);
    assert.match(href, /trainer_id=710/);
    assert.match(href, /arena_id=42/);
  });

  it('ни один вызов с арены не может уйти на выбор времени', () => {
    // Проверяем РЕЗУЛЬТАТ, а не текст обработчика. Прошлая версия теста читала
    // тело обработчика и пропустила `action || 'book'` в самой goBooking:
    // вызов передавал null, а по умолчанию всё равно подставлялось 'book'.
    const src = read('arena-card.js');
    const start = src.indexOf('function goBooking');
    const body = src.slice(start, src.indexOf('function photoUrl'));
    assert.ok(!/action/.test(body), 'goBooking снова умеет подставлять действие');

    const { buildBookingHref } = loadArenaModel();
    assert.ok(!buildBookingHref({ trainerId: 7, arenaId: 1 }).includes('action='));
    assert.ok(!buildBookingHref({ trainerId: 7, arenaId: 1, groupId: 3 }).includes('action='));
  });

  it('развилки по can_book больше нет', () => {
    const src = read('arena-card.js');
    const start = src.indexOf("if (action === 'trainer')");
    const body = src.slice(start, src.indexOf("if (action === 'group')"));
    assert.ok(!body.includes('data-can-book'));
  });

  it('группа доносит свой id до карточки тренера', () => {
    const { buildBookingHref } = loadArenaModel();
    assert.match(buildBookingHref({ trainerId: 7, arenaId: 1, groupId: 33 }), /group_id=33/);

    const src = read('arena-card.js');
    const start = src.indexOf("if (action === 'group')");
    const body = src.slice(start, start + 400);
    assert.match(body, /groupId: t\.getAttribute\('data-group'\)/);
  });

  it('увод в личку из списка на арене убран вместе с развилкой', () => {
    const src = read('arena-card.js');
    assert.ok(!/function goWrite/.test(src));
    assert.ok(!/contact_telegram_url/.test(src));
  });
});

describe('контракт возврата знает про арену', () => {
  it('«Назад» с арены ведёт на ту же арену, а не в каталог', () => {
    const { resolveBookingReturn } = loadBookingClient();
    const target = resolveBookingReturn('arena', { arenaId: 42, trainerId: 710 });
    assert.equal(target.type, 'arena');
    assert.equal(target.path, 'arena?ref=42');
  });

  it('без id арены не выдумывает адрес, а падает в прежнее поведение', () => {
    const { resolveBookingReturn } = loadBookingClient();
    const target = resolveBookingReturn('arena', { trainerId: 710 });
    assert.notEqual(target.type, 'arena');
    assert.match(target.path, /trainer_id=710/);
  });

  it('прежние источники не сломаны', () => {
    const { resolveBookingReturn } = loadBookingClient();
    assert.equal(resolveBookingReturn('hub', {}).type, 'hub');
    assert.equal(resolveBookingReturn('requests', {}).path, 'client-requests');
    assert.equal(resolveBookingReturn('saved-trainers', {}).path, 'client-saved-trainers');
  });
});

describe('пустой «Выберите время» больше не тупик', () => {
  const src = read('catalog-main.js');

  it('у пустого состояния есть отрисовщик с кнопками, а не голый текст', () => {
    assert.match(src, /function renderSlotPickEmptyState/);
    const fn = src.slice(src.indexOf('function renderSlotPickEmptyState'));
    const body = fn.slice(0, fn.indexOf('\n      function renderSlotPickList'));
    assert.match(body, /data-slotpick="request"/, 'нет выхода в заявку');
    assert.match(body, /data-slotpick="all-arenas"/, 'нет выхода на другие арены');
    assert.match(body, /data-slotpick="trainer-card"/, 'нет выхода в карточку тренера');
    // Каждая кнопка обязана быть привязана — разметка без обработчика это тот же тупик.
    assert.match(body, /reqBtn\.onclick/);
    assert.match(body, /allBtn\.onclick/);
    assert.match(body, /cardBtn\.onclick/);
  });

  it('кнопка «на других аренах» показывается только когда фильтр реально стоит', () => {
    const fn = src.slice(src.indexOf('function renderSlotPickEmptyState'));
    const body = fn.slice(0, fn.indexOf('\n      function renderSlotPickList'));
    assert.match(body, /var filtered = \(state\.trainerSlotsArenaIds \|\| \[\]\)\.length > 0/);
    assert.match(body, /if \(filtered\) \{/);
  });

  it('renderSlotPickList больше не рисует пустое состояние сам', () => {
    const start = src.indexOf('function renderSlotPickList');
    const body = src.slice(start, start + 700);
    assert.match(body, /renderSlotPickEmptyState\(list\)/);
    assert.ok(!/'<div class="slots-empty">' \+\s*escapeHtml\(emptyHint/.test(body));
  });
});

describe('«Назад» не приводит на пустой экран', () => {
  const src = read('catalog-main.js');

  it('вход прямо на выбор времени сначала отрисовывает карточку тренера', () => {
    const start = src.indexOf('function openTrainerDeepLinkSlotPick');
    const body = src.slice(start, src.indexOf('function openTrainerDeepLinkTrainerCard'));
    const renders = body.match(/renderTrainerDetail\(\)/g) || [];
    // И в успешной ветке, и в catch: пустой экран после ошибки — тот же пустой экран.
    assert.equal(renders.length, 2);
  });

  it('происхождение входа больше не захардкожено на «hub»', () => {
    assert.match(src, /function directBookEntryOrigin/);
    const start = src.indexOf('function directBookEntryOrigin');
    const body = src.slice(start, start + 600);
    assert.match(body, /from === 'hub' \|\| from === 'arena'/);
  });

  it('«Назад» с карточки тренера возвращает на арену, с которой пришли', () => {
    const start = src.indexOf("sid === 'screenTrainerDetail' && arenaOriginId()");
    assert.ok(start > 0, 'нет ветки возврата на арену');
    const body = src.slice(start, start + 700);
    assert.match(body, /navigateBookingReturn\('arena', \{ arenaId: arenaOriginId\(\) \}\)/);
  });

  it('id арены для возврата не зависит от action=book', () => {
    const start = src.indexOf('function arenaOriginId');
    const body = src.slice(start, start + 500);
    assert.match(body, /qp\.get\('from'\) !== 'arena'/);
    assert.ok(!body.includes("action"), 'возврат снова привязан к action=book');
  });
});

describe('шапка называет объект и шаг, а не всегда «Тренеры»', () => {
  const src = read('catalog-main.js');

  it('заголовок пересчитывается на каждом showScreen', () => {
    assert.match(src, /function syncCatalogHeaderTitle/);
    const start = src.indexOf('function showScreen');
    const body = src.slice(start, start + 1400);
    assert.match(body, /syncCatalogHeaderTitle\(id\)/);
  });

  it('на трёх шагах записи держится имя тренера, а не название шага', () => {
    const start = src.indexOf('function syncCatalogHeaderTitle');
    const body = src.slice(start, src.indexOf('function syncClientShellTabBarForScreen'));
    assert.match(body, /screenTrainerDetail/);
    assert.match(body, /screenSlotPick/);
    assert.match(body, /screenBookingForm/);
    assert.match(body, /title = name/);
    assert.match(body, /screenSuccess.*'Готово'|'Готово'/s);
    assert.match(body, /'Заявка'/);
  });
});

describe('форма записи называет тренера и помнит, откуда открыта', () => {
  const src = read('catalog-main.js');

  it('на форме есть строка с именем тренера', () => {
    const html = read('catalog.html');
    assert.match(html, /id="bookingFormTrainerLine"/);
    const start = src.indexOf('function openCatalogBookingFormForSlot');
    const body = src.slice(start, start + 1200);
    assert.match(body, /bookingFormTrainerLine/);
    assert.match(body, /Запись к тренеру/);
  });

  it('источник открытия проставлен на обоих экранах', () => {
    assert.match(src, /openCatalogBookingFormForSlot\(state\.slotsForTrainer\[ii\], \{ from: 'trainerDetail' \}\)/);
    assert.match(src, /openCatalogBookingFormForSlot\(state\.slotsForTrainer\[i\], \{ from: 'slotPick' \}\)/);
  });

  it('«Назад» с формы возвращает в список времени, если пришли оттуда', () => {
    const start = src.indexOf('function syncCatalogHeaderBack');
    const body = src.slice(start, start + 2200);
    assert.match(body, /state\.bookingFormOpenedFrom === 'slotPick'/);
  });
});

describe('группа с арены находится на карточке', () => {
  const src = read('catalog-main.js');

  it('group_id разбирается из адреса', () => {
    assert.match(src, /qp\.get\('group_id'\)/);
    assert.match(src, /state\.pendingFocusGroupId/);
  });

  it('блок «Набор в группы» раскрывается и подсвечивает нужную', () => {
    assert.match(src, /function focusRequestedTrainingGroup/);
    const start = src.indexOf('function focusRequestedTrainingGroup');
    const body = src.slice(start, start + 900);
    assert.match(body, /details\.open = true/);
    assert.match(body, /trainer-detail-group-card--focus/);
    // id гасится после применения — иначе подсветка возвращалась бы при каждом
    // возврате на карточку.
    assert.match(body, /state\.pendingFocusGroupId = null/);
  });
});

describe('успех ведёт туда, где лежит созданное', () => {
  const src = read('catalog-main.js');

  it('после заявки главная кнопка — «Мои заявки»', () => {
    assert.match(src, /function paintCatalogSuccessActions/);
    const start = src.indexOf('function paintCatalogSuccessActions');
    const body = src.slice(start, start + 900);
    assert.match(body, /'client-requests'/);
    assert.match(body, /'Мои заявки'/);
    assert.match(body, /'client-bookings'/);
  });

  it('обе ветки успеха выставляют свой вид явно', () => {
    assert.match(src, /paintCatalogSuccessActions\('request'\)/);
    assert.match(src, /paintCatalogSuccessActions\('booking'\)/);
    // Без сброса на 'booking' кнопка после заявки осталась бы «Мои заявки»
    // и увела бы из записи не туда.
    const bookingIdx = src.indexOf("paintCatalogSuccessActions('booking');\n              if (window.BookingClient)");
    assert.ok(bookingIdx > 0, 'ветка записи не сбрасывает вид экрана успеха');
  });
});

describe('нативных alert в клиентском флоу больше нет', () => {
  const src = read('catalog-main.js');

  it('ни одного alert()', () => {
    assert.equal((src.match(/\balert\(/g) || []).length, 0);
  });

  it('длинные исходы записи остаются на экране, а не мигают тостом', () => {
    assert.match(src, /function showBookingNotice/);
    // Три случая: ответ не распознан, ошибка сервера, сеть не ответила.
    assert.equal((src.match(/showBookingNotice\(/g) || []).length, 4);
    const html = read('catalog.html');
    assert.match(html, /id="bookingFormNotice"/);
    assert.match(html, /role="alert"/);
  });

  it('сообщение гасится при открытии формы — чужой исход не липнет к новому слоту', () => {
    const start = src.indexOf('function openCatalogBookingFormForSlot');
    const body = src.slice(start, start + 900);
    assert.match(body, /clearBookingNotice\(\)/);
  });
});

describe('экран времени объясняет, чьи это слоты и где', () => {
  const src = read('catalog-main.js');

  it('над списком есть строка с именем тренера', () => {
    assert.match(src, /function paintSlotPickContext/);
    const start = src.indexOf('function paintSlotPickContext');
    const body = src.slice(start, src.indexOf('function renderSlotPickList'));
    assert.match(body, /trainerName\(t\)/);
    // Место называем только когда оно однозначно — иначе честнее сказать «на разных».
    assert.match(body, /на разных площадках/);
    assert.match(body, /names\.length === 1/);
  });

  it('renderSlotPickList рисует эту строку на каждом проходе', () => {
    const start = src.indexOf('function renderSlotPickList');
    const body = src.slice(start, start + 400);
    assert.match(body, /paintSlotPickContext\(\)/);
  });

  it('у каждой строки слота подписана площадка', () => {
    const start = src.indexOf('function renderSlotPickList');
    const body = src.slice(start, start + 3000);
    assert.match(body, /slot-card-place/);
    assert.match(body, /formatSlotPlaceCaption/);
  });
});
