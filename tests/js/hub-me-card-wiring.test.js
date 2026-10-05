/**
 * TASK-160 (S2): обвязка «моей карточки» в хабе.
 *
 * Модель карточки (hub-me-card.js) закрыта своими тестами
 * (tests/js/hub-me-card-model.test.js). Здесь проверяется ровно то, чего
 * модель о себе знать не может: что её подключили, что ветка записи в
 * applyHubState зовёт именно её, что вход карточки собирают из bootstrap
 * (включая сертификаты), что переходы разведены по data-me-action и что
 * список «остальных записей» больше не вкладывается в рамку карточки.
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
    const body = fnBody('renderMeCardForBooking');
    assert.match(body, /window\.HubMeCard/);
    assert.match(body, /model\.buildView\(/);
    assert.match(body, /model\.renderHtml\(view\)/);
  });

  it('рендер идёт в существующий #nextBookingBlock, нового контейнера нет', () => {
    assert.match(fnBody('renderMeCardForBooking'), /getElementById\('nextBookingBlock'\)/);
    assert.equal(homeHtml.split('id="nextBookingBlock"').length - 1, 1);
    assert.ok(!homeHtml.includes('id="meCard"'), 'новый контейнер карточке не нужен');
  });

  it('остальные состояния в S2 не тронуты: окно, тренер, сохранённые, возврат', () => {
    const apply = fnBody('applyHubState');
    assert.match(apply, /loadAndRenderPrimaryPanel\(primaryTrainerId/);
    assert.match(apply, /renderSavedTrainersStrip\(cs\)/);
    assert.match(apply, /renderHubSecondaryFill\(hubMeta/);
    assert.match(apply, /loadDiscoveryUnlessMarket\(\)/);
    assert.match(homeMain, /function renderOpenWindowCard\(/);
    assert.match(homeMain, /function renderMyTrainerCard\(/);
    // HubMeCard зовут ровно из одного места: заливки S3/S4 ещё не подключены.
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
    assert.match(fnBody('renderMeCardForBooking'), /wireMeCardBlock\(block\)/);
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

  it('действия заливок S3/S4 молчат, а не падают', () => {
    for (const action of [
      'book-slot', 'all-slots', 'all-sessions', 'all-trainers',
      'pick-city', 'geo', 'all-country', 'more-cities',
    ]) {
      assert.ok(
        !new RegExp("action === '" + action + "'").test(wire),
        action + ' обработан в S2 — это заливки S3/S4'
      );
    }
    // Неизвестное действие уходит в ничто: ни throw, ni navigateTo по умолчанию.
    assert.ok(!/else\s*\{\s*navigateTo/.test(wire), 'дефолтного перехода быть не должно');
    assert.ok(!/throw/.test(wire));
  });

  it('id записи берётся из контекста карточки: модель его в разметку не кладёт', () => {
    assert.match(fnBody('renderMeCardForBooking'), /hubMeCardBookingId =/);
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
