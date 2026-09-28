/**
 * Раздел «Каталог»: вкладка в баре и экран состояния (TASK-140).
 *
 * Run: node --test "tests/js/*.test.js"
 *
 * Проверяем то, что раньше было неправдой в интерфейсе: публикация не живёт тумблером в
 * настройках, экран не дублирует состояние в двух местах, и хинт под тумблером больше не может
 * утверждать «клиенты находят вас в общем списке» в момент, когда тренер выпал из фильтров.
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

describe('бар: «Каталог» — постоянная пятая вкладка', () => {
  const shell = read('mini-app-trainer-shell.js');

  it('вкладка есть и ведёт на trainer-catalog', () => {
    assert.match(shell, /id: 'catalog'[\s\S]{0,120}path: 'trainer-catalog'/);
  });

  it('стоит четвёртой — перед «Ещё», после «Клиентов»', () => {
    const clients = shell.indexOf("id: 'clients'");
    const catalog = shell.indexOf("id: 'catalog'");
    const more = shell.indexOf("id: 'more'");
    assert.ok(clients > 0 && catalog > 0 && more > 0);
    assert.ok(clients < catalog, 'мышечную память первых вкладок не сдвигаем');
    assert.ok(catalog < more, '«Ещё» остаётся последней');
  });

  it('точка, а не число: для одной карточки «сколько» бессмысленно', () => {
    assert.match(shell, /badges\.catalog/);
    assert.match(shell, /trainer-tab-bar__badge--dot/);
    const css = read('mini-app-trainer-shell.css');
    assert.match(css, /\.trainer-tab-bar__badge--dot/);
  });
});

describe('экран «Каталог»', () => {
  const js = read('trainer-catalog-main.js');
  const html = read('trainer-catalog.html');

  it('всё состояние берёт из одного GET, а не собирает из флагов', () => {
    assert.match(js, /\/trainer\/catalog'\), \{ headers: headers\(\)/);
    /* Упоминание старого флага допустимо только в комментарии — читать его экран не должен. */
    const code = js.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    assert.equal((code.match(/is_catalog_visible/g) || []).length, 0);
  });

  it('действия ходят в машину состояний, каждое своим эндпоинтом', () => {
    for (const action of ['submit', 'hide', 'restore', 'withdraw', 'cancel-revision']) {
      assert.match(js, new RegExp(`'${action}'`), `нет действия ${action}`);
    }
    assert.match(js, /\/trainer\/catalog\/' \+ path/);
  });

  it('снятие с публикации спрашивает подтверждение и честно перечисляет последствия', () => {
    assert.match(js, /showAppConfirm/);
    assert.match(js, /Изменится:/);
    assert.match(js, /Не изменится:/);
    assert.match(js, /без повторной проверки/);
  });

  it('«Разместить» открывает существующую карусель с возвратом сюда', () => {
    assert.match(js, /trainer-profile\?task=catalog&return=trainer-catalog/);
  });

  it('обе версии карточки, когда правки на проверке', () => {
    assert.match(html, /id="tcRevisionCard"/);
    assert.match(js, /Сейчас клиенты видят/);
    assert.match(js, /tcRevisionCard/);
  });

  it('кнопки «Открыть как клиент» нет — из тренерского приложения она невозможна', () => {
    /* Клиентский Mini App проверяет initData токеном КЛИЕНТСКОГО бота, а этот экран живёт в
       тренерском: переход на `catalog` отдавал 401 и «Что-то пошло не так». */
    for (const gone of ['tcOpenAsClient', 'tc-open-as-client']) {
      assert.equal(html.indexOf(gone), -1, gone);
      assert.equal(js.indexOf(gone), -1, gone);
    }
    const code = js.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    assert.equal((code.match(/'catalog\?trainer_id=/g) || []).length, 0);
  });

  it('есть история и строка про подписку', () => {
    assert.match(html, /id="tcHistoryList"/);
    assert.match(html, /id="tcSubscriptionNote"/);
  });

  it('повторная отправка ходит в тот же эндпоинт, но называется своим именем', () => {
    // Карточка уже в очереди, но модератор видел прошлую версию — «Отправить на проверку» тут врёт.
    assert.match(js, /resubmit: 'Отправить обновлённую карточку'/);
    assert.match(js, /action === 'submit' \|\| action === 'resubmit'/);
  });

  it('снятие — текстовой ссылкой, не кнопкой в вес «Изменить»', () => {
    assert.match(js, /action === 'hide' \|\| action === 'withdraw'/);
    assert.match(js, /tc-link-btn--danger/);
  });
});

describe('экран живёт в дизайн-системе приложения', () => {
  const css = read('mini-app-trainer-catalog.css');
  const js = read('trainer-catalog-main.js');

  it('[hidden] побеждает display — иначе «Загрузка», контент и ошибка видны разом', () => {
    assert.match(css, /\.tc-page \[hidden\][\s\S]{0,60}display:\s*none\s*!important/);
  });

  it('ни одного своего hex — только токены GLIDE', () => {
    const body = css.replace(/\/\*[\s\S]*?\*\//g, '');
    const hexes = body.match(/#[0-9a-fA-F]{3,8}\b/g) || [];
    assert.deepEqual(hexes, [], 'палитра должна переключаться вместе с темой');
  });

  it('кнопки — общие компоненты, а не свои', () => {
    assert.match(js, /'btn-primary'/);
    assert.match(js, /'btn-soft'/);
    assert.equal((js.match(/tc-btn/g) || []).length, 0);
  });

  it('экран подхватывает тему тренерского кабинета', () => {
    assert.match(js, /__applyTrainerMiniAppTheme/);
    assert.match(js, /themeChanged/);
  });

  it('фразу служебного события отфильтровал сервер — экран её не перепроверяет', () => {
    // Клиентский фильтр по state_reason не срабатывал никогда: backfill писал reason только
    // в журнал, а колонку оставлял NULL. Правило переехало в trainer_catalog_view.
    assert.equal((js.match(/state_reason/g) || []).length, 0);
    assert.match(js, /detail\.textContent = p\.state_detail/);
  });
});

describe('draft: сначала действие, объяснение — под раскрытием', () => {
  const html = read('trainer-catalog.html');
  const js = read('trainer-catalog-main.js');

  it('блока-простыни «Если разместить карточку» на экране больше нет', () => {
    assert.equal((html.match(/tc-pitch/g) || []).length, 0);
    assert.equal((js.match(/tcPitch/g) || []).length, 0);
  });

  it('объяснение живёт в раскрытии «Зачем это нужно» и только в draft', () => {
    assert.match(html, /id="tcWhyToggle"[\s\S]{0,200}Зачем это нужно/);
    assert.match(html, /id="tcWhyBody" hidden/);
    assert.match(js, /show\(el\('tcWhySection'\), isDraft\)/);
  });

  it('в draft фраза состояния уезжает в раскрытие, в остальных — остаётся на виду', () => {
    assert.match(js, /el\('tcStatusBody'\)\.textContent = isDraft \? '' : \(p\.body \|\| ''\)/);
    assert.match(js, /el\('tcWhyLead'\)\.textContent = p\.body/);
  });

  it('«подписка не влияет» — там, где есть страх пропасть, а не на каждом состоянии', () => {
    assert.match(js, /subRelevant = p\.state === 'paused' \|\| p\.state === 'hidden'/);
  });

  it('«можно усилить» не стоит рядом со списком блокеров', () => {
    assert.match(js, /showOptional = optional\.length > 0 && required\.length === 0/);
  });

  it('правка существующей анкеты не идёт через карусель пробелов', () => {
    /* Рельс `task=catalog` собирается из submission-пробелов. Когда их нет — а у «можно
       усилить», у скрытой площадки и у «Изменить карточку» их нет по определению — карусель
       открывалась пустой, упиралась в «Базовый профиль готов» и возвращала тренера обратно.
       Кнопка выглядела рабочей и не делала ничего. */
    assert.match(js, /function openProfileForm\(\)[\s\S]{0,200}webappUrl\('trainer-profile'\);/);
    assert.match(js, /openProfileBtn\.addEventListener\('click', openProfileForm\)/);
    assert.match(js, /edit\.addEventListener\('click', openProfileForm\)/);
    // Карусель остаётся ровно одной дверью — и только там, где пробелы действительно есть.
    const code = js.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    assert.equal((code.match(/task=catalog/g) || []).length, 1);
  });

  it('у любого списка полей есть дверь в анкету', () => {
    // Тренер, который ещё ни разу не открывал профиль, читал названия полей и не знал, где они.
    assert.match(html, /id="tcOpenProfile"[\s\S]{0,80}Дополнить в анкете/);
    assert.match(js, /show\(el\('tcOpenProfile'\), !!p\.can_act && \(showOptional \|\| required\.length > 0\)\)/);
  });

  it('раздел — вкладка бара, а не тупик', () => {
    // Бар монтируется только по этому атрибуту; без него у экрана не было ни одного пути назад.
    assert.match(html, /<body[^>]*data-trainer-shell="tabs"/);
    const shell = read('mini-app-trainer-shell.js');
    assert.match(shell, /key === 'trainer-catalog'\) return 'catalog'/);
  });

  it('превью — карточка клиентского списка, а не своя выдумка', () => {
    // Город — фильтр, а не факт карточки; цена всегда при названии услуги.
    assert.equal((js.match(/city_name/g) || []).length, 0);
    assert.match(js, /person\.service_line/);
    assert.match(js, /Свободных слотов: /);
  });

  it('журнал называет событие, а не «состояние · автор»', () => {
    // «На проверке · вами» читалось так, будто тренер проверяет сам себя.
    assert.equal((js.match(/'вами'/g) || []).length, 0);
    assert.equal((js.match(/actor_type/g) || []).length, 0);
    assert.match(js, /esc\(e\.headline \|\| e\.to_state\)/);
  });
});

describe('«Профиль» больше не отвечает за каталог', () => {
  const html = read('trainer-profile.html');
  const js = read('trainer-profile-main.js');

  it('тумблера, пилюли статуса и баннера модератора там нет', () => {
    for (const gone of [
      'is_catalog_visible',
      'catalogVisibilityCard',
      'moderatorFeedbackBanner',
      'modStatusPill',
      'modMissingList',
    ]) {
      assert.equal(html.indexOf(gone), -1, `${gone} должен был уехать в раздел «Каталог»`);
    }
  });

  it('рендереры каталога и PATCH тумблера удалены вместе с разметкой', () => {
    for (const gone of [
      'renderCatalogVisibility',
      'renderModeratorFeedbackBanner',
      'renderModeration',
      'catalog-visibility',
    ]) {
      assert.equal(js.indexOf(gone), -1, `${gone} не должен остаться в профиле`);
    }
  });

  it('вместо них — ссылка в раздел, чтобы правка имени не выглядела приватной', () => {
    assert.match(html, /btnOpenCatalogSection/);
    assert.match(js, /webappPageUrl\('trainer-catalog'\)/);
  });

  it('карусель по-прежнему монтирует блоки формы — их не задели', () => {
    for (const container of [
      "containerId: 'anketaStart'",
      "containerId: 'profileNavContacts'",
      "containerId: 'profileNavPhoto'",
      "containerId: 'profileNavArenas'",
    ]) {
      assert.ok(js.includes(container), `${container} пропал — карусель сломается`);
    }
    for (const id of ['anketaStart', 'profileNavContacts', 'profileNavPhoto', 'profileNavArenas']) {
      assert.match(html, new RegExp(`id="${id}"`));
    }
  });
});
