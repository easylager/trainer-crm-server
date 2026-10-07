/**
 * TASK-148 (AC-1, AC-2): чипы категорий рендерятся только при данных;
 * место без фото рендерится бесфотошной карточкой — иконка типа на цветной
 * плашке, без серого плейсхолдера изображения.
 *
 * Чисто модель + точечные проверки источников рендеров (ice-tab.js, ice-map.js,
 * ice-tab.css) — тем же приёмом, что ice-map-sheet-fab.test.js и
 * client-empty-states.test.js: рендереры живут в DOM-скриптах, гонять браузер
 * ради них не нужно, а регресс «вернули серую заглушку» ловится на уровне кода.
 *
 * Run: node --test tests/js/venue-chips-nophoto-cards.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');
const modelPath = path.resolve(webapp, 'ice-tab-model.js');

function read(name) {
  return fs.readFileSync(path.join(webapp, name), 'utf8');
}

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

describe('лента категорий: чипы только при данных (TASK-148 AC-1)', () => {
  it('все счётчики нулевые — ленты нет вовсе', () => {
    const { venueChipsView } = loadModel();
    assert.deepEqual(
      venueChipsView(
        [
          { key: 'ice', chip: 'Лёд', count: 0 },
          { key: 'gym', chip: 'Зал', count: 0 },
          { key: 'shop', chip: 'Магазин', count: 0 },
        ],
        []
      ),
      []
    );
  });

  it('нулевая категория не тянет ленту из одного чипа', () => {
    const { venueChipsView } = loadModel();
    // Единственная живая категория + нули: по-прежнему правило «фильтр из
    // одного варианта — шум», и нулевой чип не рендерится.
    assert.deepEqual(
      venueChipsView(
        [
          { key: 'ice', chip: 'Лёд', count: 8 },
          { key: 'gym', chip: 'Зал', count: 0 },
        ],
        []
      ),
      []
    );
  });

  it('категория с нулём выпадает, живые остаются (0/1/N)', () => {
    const { venueChipsView } = loadModel();
    const chips = venueChipsView(
      [
        { key: 'ice', chip: 'Лёд', count: 7 },
        { key: 'gym', chip: 'Зал', count: 0 },
        { key: 'shop', chip: 'Магазин', count: 2 },
        { key: 'pool', chip: 'Бассейн', count: 1 },
      ],
      []
    );
    assert.deepEqual(chips.map((c) => c.label), ['Все', 'Лёд', 'Магазин', 'Бассейн']);
    assert.equal(chips.find((c) => c.key === 'shop').count, 2);
    assert.ok(!chips.some((c) => c.key === 'gym'), 'чип с нулём не рендерится');
  });

  it('отрицательный счётчик — мусор из ответа, чип не рендерится', () => {
    const { venueChipsView } = loadModel();
    const chips = venueChipsView(
      [
        { key: 'ice', chip: 'Лёд', count: 3 },
        { key: 'gym', chip: 'Зал', count: -1 },
      ],
      []
    );
    assert.deepEqual(chips.map((c) => c.label), []);
  });

  it('N живых категорий — N чипов плюс «Все»', () => {
    const { venueChipsView } = loadModel();
    const facets = [
      { key: 'ice', chip: 'Лёд', count: 1 },
      { key: 'gym', chip: 'Зал', count: 2 },
      { key: 'choreo', chip: 'Хореография', count: 3 },
      { key: 'pool', chip: 'Бассейн', count: 4 },
    ];
    const chips = venueChipsView(facets, []);
    assert.deepEqual(chips.map((c) => c.key), ['', 'ice', 'gym', 'choreo', 'pool']);
    assert.equal(chips[0].label, 'Все');
    assert.equal(chips[0].active, true);
  });
});

describe('бесфотошная карточка: иконка типа на плашке (TASK-148 AC-2)', () => {
  it('boardCardView без фото: photo пуст, иконка типа приезжает с сервера', () => {
    const { boardCardView } = loadModel();
    const v = boardCardView({ id: 1, name: 'Юность', venue_type: 'ice', venue_icon: '❄️' });
    assert.equal(v.photo, '', 'нет фото — нет фото-блока');
    assert.equal(v.venueIcon, '❄️');
  });

  it('boardCardView без venue_icon не падает: фолбэк — монограмма', () => {
    const { boardCardView } = loadModel();
    const v = boardCardView({ id: 1, name: 'Юность', venue_type: 'ice' });
    assert.equal(v.venueIcon, '');
    assert.equal(v.initial, 'Ю');
  });

  it('карточка С фото не меняется: photo из card/thumb как раньше', () => {
    const { boardCardView } = loadModel();
    const v = boardCardView({
      id: 1,
      name: 'Каток с фото',
      venue_type: 'ice',
      card: 'https://img/1-card.jpg',
    });
    assert.equal(v.photo, 'https://img/1-card.jpg');
    const both = boardCardView({
      id: 3,
      name: 'Каток',
      card: 'https://img/3-card.jpg',
      thumb: 'https://img/3-thumb.jpg',
    });
    assert.equal(both.photo, 'https://img/3-card.jpg');
    assert.match(both.photoSrcset, /3-thumb.jpg 320w/);
    assert.match(both.photoSrcset, /3-card.jpg 800w/);
    const v2 = boardCardView({ id: 2, name: 'Каток', thumb: 'https://img/2-thumb.jpg' });
    assert.equal(v2.photo, 'https://img/2-thumb.jpg');
  });

  it('список каталога: пустой вариант рисует иконку, а не картинку и не монограмму-серость', () => {
    const js = read('ice-tab.js');
    const start = js.indexOf("ice-board__photo ice-board__photo--empty");
    const end = js.indexOf("'</span>';", start);
    const branch = js.slice(start, end);
    assert.ok(branch.length > 0, 'бесфотошная ветка существует');
    assert.match(branch, /v\.venueIcon \|\| v\.initial/, 'иконка типа, фолбэк — монограмма');
    assert.ok(!/<img/i.test(branch), 'в бесфотошном варианте нет тега img');
    assert.ok(!/listPhotoHtml/.test(branch), 'в бесфотошном варианте нет ленивого img');
  });

  it('карусель шторки карты: плашка типа с иконкой, класс типа на карточке', () => {
    const js = read('ice-map.js');
    assert.match(js, /ice-acard--type-' \+ esc\(venueType\)/, 'тип места на карточке карусели');
    assert.match(js, /ice-acard__icon/);
    assert.match(js, /item\.venue_icon/, 'иконка берётся из данных, не из словаря клиента');
    const start = js.indexOf('var phInner = item.thumb');
    const end = js.indexOf("');", start);
    const block = js.slice(start, end);
    assert.match(block, /item\.venue_icon/, 'фолбэк-буква допустима, источник — данные');
    assert.ok(!/<img/i.test(block), 'в бесфотошном варианте нет тега img');
  });

  it('CSS: плашка катка — цвет типа из токенов, серых полос нет', () => {
    const css = read('ice-tab.css');
    const start = css.indexOf('.ice-board__photo--empty {');
    const block = css.slice(start, css.indexOf('}', start));
    assert.match(block, /background:\s*var\(--app-venue-ice\)/);
    assert.ok(!/127,\s*127,\s*127/.test(block), 'серый плейсхолдер не вернулся');
    assert.match(css, /\.ice-board--type-shop \.ice-board__photo--empty\s*{[^}]*var\(--app-venue-shop\)/);
    assert.match(css, /\.ice-acard--type-pool \.ice-acard__ph--empty\s*{[^}]*var\(--app-venue-pool\)/);
    const iconStart = css.indexOf('.ice-acard__icon {');
    const iconBlock = css.slice(iconStart, css.indexOf('}', iconStart));
    assert.match(iconBlock, /var\(--app-on-media\)/, 'иконка читается по цветной плашке');
  });

  it('новые токены типов объявлены в theme.css рядом с рейкой venue', () => {
    const css = read('theme.css');
    assert.match(css, /--app-venue-trainer:\s*#0B6E70/);
    assert.match(css, /--app-venue-track:\s*#2A7FD4/);
    assert.match(css, /--app-venue-service:\s*#47535E/);
    const venue = css.indexOf('--app-venue-pool: #2A7FD4;');
    const trainer = css.indexOf('--app-venue-trainer:');
    assert.ok(venue > 0 && trainer > venue, 'токены идут за существующей рейкой');
  });
});

describe('лента услуг тренеров: без данных чип не рендерится (TASK-148 AC-1)', () => {
  it('renderServiceChips прячет ленту, когда живых услуг (trainer_count > 0) нет', () => {
    const js = read('ice-tab.js');
    const start = js.indexOf('function renderServiceChips()');
    const end = js.indexOf('function renderVenueChips', start);
    const body = js.slice(start, end);
    assert.match(body, /!state\.services\.length/, 'пустой список услуг — лента скрыта');
    assert.match(body, /box\.hidden = true/);
  });
});
