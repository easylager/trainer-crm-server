/**
 * TASK-160 (S2 + S3): обвязка «моей карточки» в хабе.
 *
 * Модель карточки (hub-me-card.js) закрыта своими тестами
 * (tests/js/hub-me-card-model.test.js). Здесь проверяется ровно то, чего
 * модель о себе знать не может: что её подключили, что ветка записи в
 * applyHubState зовёт именно её, что вход карточки собирают из bootstrap
 * (включая сертификаты), что переходы разведены по data-me-action и что
 * список «остальных записей» больше не вкладывается в рамку карточки.
 *
 * S3 добавил к этому три заливки, завязанные на тренера: «окна есть»,
 * «окон нет» и возврат. Проверяется, что старые рендеры этих состояний
 * удалены (а не остались висеть без вызовов), что «все окна» ведут в
 * слот-пикер, а не на карточку тренера, и что чип ведёт на свой слот.
 *
 * Гварды статические, по исходникам — как в hub-catalog-blocks-wiring.test.js:
 * DOM здесь не поднимается, проверяется обвязка, а не поведение браузера.
 *
 * Run: node --test tests/js/hub-me-card-wiring.test.js
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

const homeHtml = read('client-home.html');
const homeMain = read('client-home-main.js');
const homeCss = read('mini-app-client-home.css');

/** Тело функции по имени: от `function name(` до следующей function того же отступа. */
function fnBody(name) {
  const start = homeMain.indexOf('function ' + name + '(');
  assert.ok(start > -1, 'нет функции ' + name);
  const next = homeMain.indexOf('\n      function ', start + 10);
  return homeMain.slice(start, next > -1 ? next : undefined);
}

/** Ветка «Priority 1» в applyHubState: только она в S2 переведена на карточку. */
function bookingBranch() {
  const apply = fnBody('applyHubState');
  const from = apply.indexOf('Priority 1: Has upcoming booking');
  const to = apply.indexOf('Priority 2: Has primary trainer');
  assert.ok(from > -1 && to > from, 'приоритеты applyHubState не найдены');
  return apply.slice(from, to);
}

describe('подключение модуля', () => {
  it('hub-me-card.js подключён рядом с моделями хаба и до client-home-main.js', () => {
    const meCard = homeHtml.indexOf('hub-me-card.js');
    const collections = homeHtml.indexOf('hub-collections-model.js');
    const iceToday = homeHtml.indexOf('hub-ice-today-model.js');
    // preload в <head> не считается: важен тег <script>, который грузит код.
    const mainJs = homeHtml.lastIndexOf('src="client-home-main.js');
    assert.ok(meCard > -1, 'hub-me-card.js не подключён в client-home.html');
    assert.ok(collections > -1 && iceToday > -1);
    assert.ok(meCard < mainJs, 'модель должна грузиться до client-home-main.js');
    assert.ok(meCard > iceToday, 'модель стоит в блоке моделей хаба');
  });

  it('ru-person-name.js подключён: без него падежей в подписях быть не может', () => {
    const ru = homeHtml.indexOf('ru-person-name.js');
    const mainJs = homeHtml.lastIndexOf('src="client-home-main.js');
    assert.ok(ru > -1 && ru < mainJs);
  });

  it('?v= у новых тегов совпадает с остальными ассетами страницы (общая версия)', () => {
    const versions = new Set(
      [...homeHtml.matchAll(/(?:href|src)="[^"?]+\.(?:css|js)\?v=([^"&]+)"/g)].map((m) => m[1])
    );
    assert.equal(versions.size, 1, 'частичный бамп ломает палитру: ' + [...versions]);
  });
});

describe('applyHubState: ветка записи рисует «мою карточку»', () => {
  it('герой записи — HubMeCard, старого renderNextBookingCard больше нет', () => {
    const branch = bookingBranch();
    assert.match(branch, /renderMeCardForBooking\(nextItem, hubMeta\)/);
    assert.ok(!branch.includes('renderNextBookingCard'), 'старый рендер в ветке записи');
    assert.ok(
      !homeMain.includes('function renderNextBookingCard('),
      'renderNextBookingCard остался без вызовов — его место заняла карточка'
    );
    // S3: модель зовёт общий painter — контейнер, слушатель и «сейчас» одни
    // на все заливки, иначе состояния разъедутся по мелочам обвязки.
    const body = fnBody('renderMeCard');
    assert.match(body, /window\.HubMeCard/);
    assert.match(body, /model\.buildView\(/);
    assert.match(body, /model\.renderHtml\(view\)/);
    assert.match(fnBody('renderMeCardForBooking'), /renderMeCard\(buildMeCardBookingInput\(item, hubMeta\)/);
  });

  it('рендер идёт в существующий #nextBookingBlock, нового контейнера нет', () => {
    assert.match(fnBody('renderMeCard'), /getElementById\('nextBookingBlock'\)/);
    assert.equal(homeHtml.split('id="nextBookingBlock"').length - 1, 1);
    assert.ok(!homeHtml.includes('id="meCard"'), 'новый контейнер карточке не нужен');
  });

  it('состояния S4 не тронуты: сохранённые и чистый старт', () => {
    const apply = fnBody('applyHubState');
    // DEC-002: полоска-кружки заменена секцией строк под карточкой-героем.
    assert.match(apply, /renderSavedTrainersSection\(cs\)/);
    assert.ok(!/renderSavedTrainersStrip/.test(apply));
    assert.match(apply, /renderHubSecondaryFill\(hubMeta/);
    assert.match(apply, /loadDiscoveryUnlessMarket\(\)/);
    // Ветка записи по-прежнему одна.
    assert.equal(apply.split('renderMeCardForBooking').length - 1, 1);
  });

  it('вторая форма остатка удалена: buildNextCardMeterHtml и его CSS', () => {
    assert.ok(!homeMain.includes('buildNextCardMeterHtml'), 'метр остался в коде');
    assert.ok(!homeMain.includes('hub-next-card-meter'), 'разметка метра осталась');
    assert.ok(!homeCss.includes('.hub-next-card-meter'), 'CSS метра остался');
    // Роль остатка теперь у кошелька карточки.
    assert.match(homeCss, /\.me__wallet\s*\{/);
    assert.match(homeCss, /\.me__w-bar\s*\{/);
  });
});

describe('вход карточки собирается из bootstrap', () => {
  const input = fnBody('buildMeCardBookingInput');

  it('kind, поля записи, start и date_label', () => {
    assert.match(input, /kind: 'booking'/);
    assert.match(input, /booking\.start = item && item\.start/);
    assert.match(input, /booking\.date_label = relativeDate\(day\.date, day\.day_label\)/);
  });

  it('абонементы и сертификаты — оба кошелька, сертификаты не теряются', () => {
    assert.match(input, /passes: hubBootstrapPasses\(hubMeta\)/);
    assert.match(input, /certificates: hubBootstrapCertificates\(hubMeta\)/);
    const certs = fnBody('hubBootstrapCertificates');
    assert.match(certs, /hubMeta\.certificates/);
    // Поля нет — пустой список, а не падение и не выдуманный баланс.
    assert.match(certs, /Array\.isArray\(hubMeta && hubMeta\.certificates\)/);
    assert.match(certs, /\[\]/);
  });

  it('падежи готовит хаб через RuPersonName; модуля нет — полей нет', () => {
    assert.match(input, /hubMeDeclinedForms\(b\.trainer_name\)/);
    assert.match(input, /if \(forms\) input\.trainer = forms/);
    const forms = fnBody('hubMeDeclinedForms');
    assert.match(forms, /window\.RuPersonName/);
    assert.match(forms, /inflectPersonName\(name, '', 'dat'\)/);
    assert.match(forms, /inflectPersonName\(name, '', 'gen'\)/);
    assert.match(forms, /nameDative/);
    assert.match(forms, /nameGenitive/);
    assert.match(forms, /return null/, 'без модуля формы не передаются');
  });
});

describe('один делегирующий обработчик на #nextBookingBlock', () => {
  const wire = fnBody('wireMeCardBlock');

  it('слушатель один и висит на блоке, а не на кнопках карточки', () => {
    assert.match(fnBody('renderMeCard'), /wireMeCardBlock\(block\)/);
    assert.match(wire, /if \(hubMeCardWired\) return/);
    assert.equal(wire.split('addEventListener').length - 1, 1);
    assert.match(wire, /block\.addEventListener\('click'/);
    assert.match(wire, /closest\('\[data-me-action\]'\)/);
  });

  it('обязательные в S2 действия разведены по переходам', () => {
    assert.match(wire, /action === 'dm'/);
    assert.match(wire, /openTelegramDm\(/);
    assert.match(wire, /action === 'open-booking'/);
    assert.match(wire, /client-bookings\?open_booking=/);
    assert.match(wire, /&from=hub/);
    assert.match(wire, /action === 'open-pass' \|\| action === 'open-cert'/);
    assert.match(wire, /client-passes-certificates/);
    assert.match(wire, /action === 'open-trainer'/);
    assert.match(wire, /catalog\?trainer_id=/);
    assert.match(wire, /catalogPrimaryServiceQuery\(\)/);
  });

  it('S4: действия заливок рынка обработаны; неизвестное молчит, а не падает', () => {
    // Было (S3): этих действий ещё не существовало, и гвард требовал их отсутствия.
    // Стало (S4): заливка «лёд города» их рисует, значит они обязаны работать.
    assert.match(wire, /action === 'all-sessions'/);
    for (const action of ['pick-city', 'geo', 'all-country', 'more-cities']) {
      assert.ok(
        !new RegExp("action === '" + action + "'").test(wire),
        action + ' принадлежит карточке выбора города — это TASK-162, не TASK-160'
      );
    }
    // Неизвестное действие уходит в ничто: ни throw, ni navigateTo по умолчанию.
    assert.ok(!/else\s*\{\s*navigateTo/.test(wire), 'дефолтного перехода быть не должно');
    assert.ok(!/throw/.test(wire));
  });

  it('id записи берётся из контекста карточки: модель его в разметку не кладёт', () => {
    assert.match(fnBody('renderMeCard'), /hubMeCardBookingId =/);
    assert.match(fnBody('renderMeCardForBooking'), /item\.b\.id/);
    assert.match(wire, /hubMeCardBookingId/);
  });
});

describe('остальные записи — блок под карточкой, а не внутри #nextCard', () => {
  const list = fnBody('renderUpcomingList');

  it('список больше не вкладывается в #nextCard', () => {
    assert.ok(!list.includes("getElementById('nextCard')"), 'список всё ещё ищет #nextCard');
    assert.ok(!list.includes('hub-next-card-rest'), 'обёртка внутри карточки осталась');
    assert.ok(!homeCss.includes('.hub-next-card-rest'), 'CSS обёртки внутри карточки остался');
    assert.match(list, /getElementById\('nextBookingBlock'\)/);
    assert.match(list, /block\.insertAdjacentHTML\('beforeend'/);
    assert.match(list, /<div class="rest">/);
    assert.match(homeCss, /\.rest\s*\{/);
  });

  it('поведение строк сохранено: своя запись и «Смотреть все»', () => {
    assert.match(list, /hub-next-card-line/);
    assert.match(list, /HUB_REST_MAX/);
    assert.match(list, /Смотреть все/);
    assert.match(list, /data-hub-action="all-bookings"/);
    const wire = fnBody('wireMeCardBlock');
    assert.match(wire, /closest\('\.hub-next-card-line\[data-bid\]'\)/);
    assert.match(wire, /\[data-hub-action="all-bookings"\]/);
    assert.match(wire, /navigateTo\('client-bookings'\)/);
  });
});

describe('стили карточки: прототип перенесён на токены темы', () => {
  /** Новый блок CSS карточки — от маркера TASK-160 до конца файла. */
  function meCss() {
    const idx = homeCss.indexOf('TASK-160 — «Моя карточка»');
    assert.ok(idx > -1, 'нет блока CSS карточки');
    return homeCss.slice(idx);
  }

  it('все классы разметки модели покрыты сразу, включая будущие заливки', () => {
    const css = meCss();
    for (const cls of [
      '.me', '.me__pad', '.me__status', '.me__when', '.me__who', '.me__who-t',
      '.me__who-link', '.me__dm', '.me__line', '.me__do', '.me__pick', '.me__chips',
      '.me__chip', '.me__chip--all', '.me__wallet', '.me__w', '.me__w-k', '.me__w-v',
      '.me__w-s', '.me__w-bar', '.me__foot', '.me__head', '.me__cities', '.me__city',
      '.me__geo', '.me--accent', '.me--warn',
    ]) {
      assert.ok(css.includes(cls), 'нет правила для ' + cls);
    }
    // Генерики, которые тоже рисует модель: монограмма, штамп, кнопки.
    assert.match(css, /\.me \.avatar\s*\{/);
    assert.match(css, /\.me \.avatar--photo img\s*\{/);
    assert.match(css, /\.me \.pill--wait\s*\{/);
    assert.match(css, /\.me \.btn-fill\s*\{/);
    assert.match(css, /\.me \.btn-ghost\s*\{/);
  });

  it('ни одного сырого hex: цвет берётся из theme.css', () => {
    const hex = meCss().match(/#[0-9a-fA-F]{3,8}\b/g);
    assert.equal(hex, null, 'сырые hex в CSS карточки: ' + hex);
  });
});

/* ── S3: три заливки, завязанные на тренера ───────────────────────────── */

describe('S3: старые рендеры состояний тренера удалены, а не оставлены без вызовов', () => {
  it('в исходнике нет ни определений, ни вызовов', () => {
    for (const fn of [
      'renderOpenWindowCard', 'renderMyTrainerCard', 'buildPrimarySlotsHtml',
      'buildPrimaryHistoryHtml', 'loadAndRenderPrimaryPanel',
      // Умерли вместе с ними: это были их единственные вызывающие.
      'trainerWhoLinkHtml', 'trainerAvatarHtml', 'slotDurationMin',
      'formatSlotDayLabel', 'shareTrainer',
    ]) {
      assert.ok(!homeMain.includes(fn), fn + ' остался в client-home-main.js');
    }
  });

  it('то, что нужно S4, оставлено живым и с вызовами', () => {
    // Полка остатка для «сохранённых» (приоритет 3) ещё не переведена на карточку:
    // её панель, её рендер и её контейнер обязаны остаться рабочими.
    for (const fn of ['renderHubSecondaryFill', 'renderPrimaryPassPanel', 'buildPrimaryPassHtml']) {
      assert.match(homeMain, new RegExp('function ' + fn + '\\('), fn);
      assert.ok(homeMain.split(fn).length - 1 >= 2, fn + ' остался без вызовов');
    }
    assert.ok(homeHtml.includes('id="hubPrimaryPanel"'), 'контейнер полки остатка нужен S4');
  });
});

describe('S3: «тренер есть» — одна рамка на «окна есть» и «окон нет»', () => {
  /** Ветка приоритета 2 в applyHubState. */
  function trainerBranch() {
    const apply = fnBody('applyHubState');
    const from = apply.indexOf('Priority 2: Has primary trainer');
    const to = apply.indexOf('Priority 3: Has saved trainers');
    assert.ok(from > -1 && to > from);
    return apply.slice(from, to);
  }

  it('ветка приоритета 2 зовёт карточку, а не карточку тренера с панелью', () => {
    const branch = trainerBranch();
    assert.match(branch, /loadAndRenderMeCardForTrainer\(hubPrimaryTrainer, hubMeta\)/);
    assert.ok(!branch.includes('renderMyTrainerCard'));
    assert.ok(!branch.includes('loadAndRenderPrimaryPanel'));
    // Старый блок карточки тренера в этом состоянии скрыт, а не заполнен.
    assert.match(branch, /hideMyTrainerBlock\(\)/);
  });

  it('вход — kind trainer, окна из /client/slots, кошелёк из bootstrap', () => {
    const input = fnBody('buildMeCardTrainerInput');
    assert.match(input, /kind: 'trainer'/);
    assert.match(input, /canBook: trainer\.canBook !== false/);
    assert.match(input, /slots: list/);
    assert.match(input, /passes: hubBootstrapPasses\(hubMeta\)/);
    assert.match(input, /certificates: hubBootstrapCertificates\(hubMeta\)/);
    const fetchSlots = fnBody('fetchTrainerSlots');
    assert.match(fetchSlots, /\/client\/slots\?trainer_id=/);
    assert.match(fetchSlots, /AbortController/, 'уход со страницы не должен держать запрос');
  });

  it('у тренера без онлайн-записи окна не спрашиваем: ответ известен заранее', () => {
    const load = fnBody('loadAndRenderMeCardForTrainer');
    assert.match(load, /trainer\.canBook === false \|\| !initData/);
    assert.match(load, /paintMeCardForTrainer\(trainer, \[\], hubMeta\)/);
    assert.match(load, /fetchTrainerSlots\(trainer\.id\)/);
  });

  it('полоса окон решает судьбу льда и нижнего FAB', () => {
    const paint = fnBody('paintMeCardForTrainer');
    assert.match(paint, /hubOpenWindowShown = !!view\.pick/);
    assert.match(paint, /hubPersonalSlot = !!view\.pick/);
    assert.match(paint, /syncClientHubBookFab\(\)/);
    assert.match(paint, /placeIceZone\('top'\)/);
    assert.match(paint, /placeIceZone\('below-trainer'\)/);
  });

  it('имени нет — карточки нет, но хаб остаётся живым', () => {
    const paint = fnBody('paintMeCardForTrainer');
    assert.match(paint, /if \(!view\)/);
    assert.match(paint, /renderHubSecondaryFill\(hubMeta, \{/);
  });

  it('падежи готовит хаб, модель в глобалы не лезет', () => {
    assert.match(fnBody('buildMeCardTrainerInput'), /withDeclinedForms\(/);
    const forms = fnBody('withDeclinedForms');
    assert.match(forms, /hubMeDeclinedForms\(fullName\)/);
    assert.match(forms, /nameDative/);
    assert.match(forms, /nameGenitive/);
    assert.match(forms, /if \(!forms\) return trainer/, 'нет модуля — нет полей, а не кривой падеж');
  });
});

describe('S3: возврат — остаток или история, окна тренера чипами', () => {
  function dormantBranch() {
    const apply = fnBody('applyHubState');
    const from = apply.indexOf('Priority 4: Has past sessions');
    const to = apply.indexOf('Priority 5: Clean state');
    assert.ok(from > -1 && to > from);
    return apply.slice(from, to);
  }

  it('ветка приоритета 4 зовёт карточку вместо полоски и полки остатка', () => {
    const branch = dormantBranch();
    assert.match(branch, /loadAndRenderMeCardForDormant\(hubMeta\)/);
    assert.ok(!branch.includes("renderQuickStrip('has-past'"));
    assert.ok(!branch.includes('renderHubSecondaryFill'));
  });

  it('вход — kind dormant; число занятий из activity, дата последнего из rebook_targets', () => {
    const input = fnBody('buildMeCardDormantInput');
    assert.match(input, /kind: 'dormant'/);
    assert.match(input, /hubMeta\.activity && hubMeta\.activity\.completed_total/);
    assert.match(input, /if \(done > 0\) input\.history/);
    // Было: поля не существовало в bootstrap, и выдумывать дату запрещалось.
    // Стало: `rebook_targets` несут `last_completed_at` — дата настоящая, из edges.
    assert.match(input, /last_completed_at/);
    assert.match(input, /passes: hubBootstrapPasses\(hubMeta\)/);
  });

  it('лицо карточки — тот, у кого остался абонемент', () => {
    const pick = fnBody('dormantReturnTrainer');
    assert.match(pick, /rebookTargets/);
    assert.match(pick, /selectPrimaryPassForTrainer\(passes, targets\[i\]\.trainer_id\)/);
    assert.match(pick, /return targets\[0\]/);
  });

  it('остальные тренеры — тихая строка под карточкой, а не вторая рамка', () => {
    const pills = fnBody('dormantRebookPills');
    assert.match(pills, /String\(t\.trainer_id\) !== String\(cardTrainerId\)/);
    assert.match(pills, /quiet: true/);
    assert.match(pills, /navigateToRebookTarget\(t\)/);
    assert.match(fnBody('loadAndRenderMeCardForDormant'), /mountQuickStripPills\(dormantRebookPills\(view\.trainerId\)\)/);
  });

  it('сказать нечего — карточки нет, хаб остаётся на прежнем наполнении', () => {
    const load = fnBody('loadAndRenderMeCardForDormant');
    assert.match(load, /if \(!view\)/);
    assert.match(load, /renderQuickStrip\('has-past', null\)/);
    assert.match(load, /renderHubSecondaryFill\(hubMeta/);
  });
});

describe('S3: переходы окон', () => {
  const wire = fnBody('wireMeCardBlock');

  it('«все окна» ведут в слот-пикер (action=book), а не на карточку тренера', () => {
    const from = wire.indexOf("action === 'all-slots'");
    const to = wire.indexOf("action === 'book-slot'");
    assert.ok(from > -1 && to > from, 'нет обработчика all-slots');
    const branch = wire.slice(from, to);
    assert.match(branch, /buildBookPathFromHubContext\(tid, \{/);
    assert.match(branch, /fallbackServiceQuery: catalogPrimaryServiceQuery\(\)/);
    // Карточка тренера здесь была бы лишним шагом между «хочу» и «записан».
    assert.ok(!branch.includes("'catalog?trainer_id='"), 'ведёт на карточку тренера');
    assert.ok(!/slotId/.test(branch), 'без slot_id путь и обязан быть action=book');
    // Ровно этот путь buildBookPathFromHubContext и строит без слота.
    const build = fnBody('buildBookPathFromHubContext');
    assert.match(build, /'action=book'/);
    assert.match(build, /'from=hub'/);
  });

  it('чип окна ведёт в форму записи на этот слот', () => {
    const from = wire.indexOf("action === 'book-slot'");
    const to = wire.indexOf("action === 'all-trainers'");
    assert.ok(from > -1 && to > from, 'нет обработчика book-slot');
    const branch = wire.slice(from, to);
    assert.match(branch, /buildBookPathFromHubContext\(tid, \{/);
    assert.match(branch, /data-me-slot-id/);
    assert.match(branch, /data-me-service-id/);
    assert.match(branch, /data-me-arena-id/);
  });

  it('«все тренеры» (окон нет) ведут в каталог, а не в никуда', () => {
    assert.match(wire, /action === 'all-trainers'/);
    const from = wire.indexOf("action === 'all-trainers'");
    assert.match(wire.slice(from, from + 220), /navigateTo\('catalog'\)/);
  });

  it('id тренера для чипов берётся из контекста карточки', () => {
    assert.match(wire, /btn\.getAttribute\('data-me-trainer-id'\) \|\| hubMeCardTrainerId/);
    assert.match(fnBody('renderMeCard'), /hubMeCardTrainerId = view\.trainerId/);
  });
});

describe('S3: CSS — долг S1 закрыт, мёртвые стили убраны', () => {
  it('.me__who-link и .avatar--photo описаны так, как требует разметка модели', () => {
    const link = homeCss.match(/\.me__who-link \{[^}]*\}/);
    assert.ok(link, 'нет правила .me__who-link');
    for (const decl of ['display: flex', 'align-items: center', 'gap: 11px', 'flex: 1',
      'min-width: 0', 'border: 0', 'background: transparent', 'padding: 0', 'text-align: left']) {
      assert.ok(link[0].includes(decl), '.me__who-link без ' + decl);
    }
    const photo = homeCss.match(/\.me \.avatar--photo img \{[^}]*\}/);
    assert.ok(photo, 'нет правила .me .avatar--photo img');
    for (const decl of ['width: 100%', 'height: 100%', 'object-fit: cover']) {
      assert.ok(photo[0].includes(decl), '.avatar--photo img без ' + decl);
    }
  });

  it('стили удалённых состояний удалены вместе с ними', () => {
    for (const cls of [
      '.hub-trainer-card', '.hub-trainer-avatar', '.hub-trainer-share-btn',
      '.hub-next-card-who', '.hub-next-card-fill', '.hub-next-card-alt',
      '.hub-next-card-quiet', '.hub-next-card-time', '.hub-next-card-trainer-avatar',
      '.hub-primary-panel__slot', '.hub-primary-panel__history',
    ]) {
      assert.ok(!homeCss.includes(cls), 'мёртвый CSS остался: ' + cls);
    }
    // Живое рядом не задето: штамп и строки списка записей, полка остатка.
    assert.match(homeCss, /\.hub-next-card-pill--ok\s*\{/);
    assert.match(homeCss, /\.hub-next-card-line\s*\{/);
    assert.match(homeCss, /\.hub-primary-panel__pass\s*\{/);
  });

  it('приветствие не называет владельца аккаунта, пока профили не резолвнуты', () => {
    const name = fnBody('hubGreetingName');
    // Имя действующего профиля — единственный источник правды, когда он известен.
    assert.match(name, /actingProfileFirstName\(\)/);
    // Пока не известен и переключатель профилей есть — имени нет вовсе.
    assert.match(name, /hubProfilesResolved/);
    assert.match(name, /return null/);
    // Флаг поднимается только после profilesReady, и там же перерисовка.
    assert.match(
      homeMain,
      /hubProfilesResolved = true;\s*\n\s*setHubGreeting\(defaultHubGreeting\(\)\);\s*\n\s*syncProfileSwitcherCompact\(\);/
    );
    // Первая отрисовка в loadAll идёт ДО profilesReady — значит она обязана быть безымянной.
    const load = fnBody('loadAll');
    assert.ok(load.indexOf('setHubGreeting') < load.indexOf('profilesReady'));
  });

  it('карточка держит ритм хаба и не прилипает к секции под ней', () => {
    // Отступ на контейнере, а не на .me: .rest обязан остаться продолжением
    // карточки (9px), а не отъехать на общий межсекционный интервал.
    const rule = homeCss.match(/#nextBookingBlock:not\(:empty\)\s*\{[^}]*\}/);
    assert.ok(rule, 'у блока карточки нет собственного отступа — он прилипнет к «Куда катимся»');
    assert.match(rule[0], /margin:\s*0\s+16px\s+20px/);
    // Тот же ритм, что у соседей по хабу.
    assert.match(homeCss, /\.hub-explore\s*\{[^}]*margin:\s*0\s+16px\s+20px/);
  });

  it('эмодзи из имени не протекает в подпись действия, но остаётся в заголовке', () => {
    const body = fnBody('hubNameForLabel');
    assert.match(body, /replace\(/);
    // Чистится имя ТОЛЬКО для склонения; сам заголовок карточки имя не трогает.
    assert.match(fnBody('hubMeDeclinedForms'), /hubNameForLabel\(fullName\)/);
    const who = fnBody('buildMeCardTrainerInput');
    assert.ok(!/hubNameForLabel/.test(who), 'имя в строке лица обязано остаться таким, как человек себя назвал');
  });

  it('сломанное фото откатывается на инициалы, а не остаётся битой картинкой', () => {
    const body = fnBody('wireMeCardPhoto');
    assert.match(body, /\.avatar--photo img/);
    assert.match(body, /onerror/);
    assert.match(body, /data-me-initials/);
    // Картинка могла отвалиться до навешивания обработчика.
    assert.match(body, /img\.complete && img\.naturalWidth === 0/);
    assert.match(fnBody('wireMeCardBlock'), /wireMeCardPhoto\(block\)/);
  });

  it('кнопка «написать» — подписанный контрол, а не голая иконка', () => {
    // Проверяем разметку, а не имя класса в CSS: класс можно переименовать,
    // и гвард бы этого не заметил — на мутационной проверке так и вышло.
    const card = require(path.join(webapp, 'hub-me-card.js'));
    const out = card.renderHtml(
      card.buildView(
        {
          kind: 'trainer',
          trainer: { id: 7, name: 'Максим', canBook: true, username: 'maksim' },
          // Конверт живёт рядом с полосой окон: без окон «написать» становится
          // главной залитой кнопкой, и отдельного кружка нет по замыслу.
          slots: [{ id: 1, start_time: '08:00', slot_date: '2026-10-06' }],
        },
        new Date('2026-10-05T12:00:00')
      )
    );
    assert.match(out, /data-me-action="dm"/);
    assert.match(out, />Написать</, 'у кнопки нет видимой подписи — голая иконка не читается как контрол');
    // И она остаётся пилюлей, а не кружком: у кружка нет горизонтального padding.
    const rule = homeCss.match(/\.me__dm \{[^}]*\}/);
    assert.ok(rule && /padding:\s*0\s+\d+px/.test(rule[0]), rule && rule[0]);
  });
});
