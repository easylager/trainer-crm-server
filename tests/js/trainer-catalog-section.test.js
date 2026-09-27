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
    assert.equal((js.match(/is_catalog_visible/g) || []).length, 0);
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

  it('есть история и строка про подписку', () => {
    assert.match(html, /id="tcHistoryList"/);
    assert.match(html, /id="tcSubscriptionNote"/);
  });

  it('снятие — текстовой ссылкой, не кнопкой в вес «Изменить»', () => {
    assert.match(js, /action === 'hide' \|\| action === 'withdraw'/);
    assert.match(js, /tc-link-btn--danger/);
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
