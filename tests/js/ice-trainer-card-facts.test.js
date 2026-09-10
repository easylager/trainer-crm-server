/**
 * Карточка тренера на вкладке «Лёд» обязана давать основание для выбора.
 *
 * До этой правки на карточке были фотография, имя и арена — по ним выбрать
 * тренера нельзя. Теперь есть специализация (есть у каждого) и один факт по
 * наличию: цена → стаж → рейтинг.
 *
 * Гейт, а не разовая проверка: самый дешёвый способ «починить» пустое поле —
 * подставить «цена по запросу» или «стаж не указан». Такая строка не сообщает
 * ничего, но читается как недостаток тренера, а не как недостаток данных.
 *
 * Run: node --test tests/js/ice-trainer-card-facts.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/webapp/ice-tab-model.js');

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

function trainer(over) {
  return Object.assign(
    {
      id: 1,
      profile: { first_name: 'Дмитрий', last_name: 'Шевчук' },
      primary_arena_name: 'Чижовка-арена',
      services: [],
      can_book: true,
    },
    over || {}
  );
}

describe('специализация — различающий факт, который есть у всех', () => {
  it('показывает услуги ярлыками, а не административными названиями справочника', () => {
    const { trainerCardView } = loadModel();
    const view = trainerCardView(
      trainer({
        services: [
          { service_name: 'Обучение катанию «с нуля»' },
          { service_name: 'Совершенствование катания' },
        ],
      })
    );
    assert.equal(view.spec, 'С нуля · Техника');
  });

  it('третью услугу сворачивает в «+N», а не режет строку посередине', () => {
    const { trainerCardView } = loadModel();
    const view = trainerCardView(
      trainer({
        services: [
          { service_name: 'Обучение катанию «с нуля»' },
          { service_name: 'Хоккейное катание' },
          { service_name: 'Фигурное катание' },
        ],
      })
    );
    assert.equal(view.spec, 'С нуля · Хоккей +1');
  });

  it('без услуг строки специализации нет вовсе', () => {
    const { trainerCardView } = loadModel();
    assert.equal(trainerCardView(trainer({ services: [] })).spec, '');
  });

  it('не дублирует одну и ту же услугу, пришедшую дважды', () => {
    const { trainerCardView } = loadModel();
    const view = trainerCardView(
      trainer({
        services: [
          { service_name: 'Хоккейное катание' },
          { service_name: 'Хоккей для взрослых' },
        ],
      })
    );
    assert.equal(view.spec, 'Хоккей');
  });
});

describe('факт для выбора: цена → стаж → рейтинг, и только по наличию', () => {
  it('цена берётся минимальная по услугам и подписывается «от»', () => {
    const { trainerCardView } = loadModel();
    const view = trainerCardView(
      trainer({
        services: [
          { service_name: 'Хоккейное катание', price_byn_min: 45 },
          { service_name: 'Фигурное катание', price_byn_min: 32 },
        ],
      })
    );
    assert.match(view.meta, /от 32 BYN/);
    assert.match(view.meta, /Чижовка-арена/);
  });

  it('цена вытесняет стаж: платить важнее, чем считать годы', () => {
    const { trainerCardView } = loadModel();
    const view = trainerCardView(
      trainer({
        profile: { first_name: 'Д', experience_years: 9 },
        services: [{ service_name: 'Хоккейное катание', price_byn_min: 45 }],
      })
    );
    assert.match(view.meta, /от 45 BYN/);
    assert.ok(!view.meta.includes('опыта'));
  });

  it('без цены показывает стаж', () => {
    const { trainerCardView } = loadModel();
    const view = trainerCardView(
      trainer({
        profile: { first_name: 'Д', experience_years: 9 },
        services: [{ service_name: 'Хоккейное катание' }],
      })
    );
    assert.match(view.meta, /9 лет опыта/);
  });

  it('склоняет годы по-русски', () => {
    const { trainerCardView } = loadModel();
    const one = trainerCardView(trainer({ profile: { first_name: 'A', experience_years: 1 } }));
    const few = trainerCardView(trainer({ profile: { first_name: 'A', experience_years: 3 } }));
    assert.match(one.meta, /1 год опыта/);
    assert.match(few.meta, /3 года опыта/);
  });

  it('без цены и стажа показывает рейтинг — но только когда есть отзывы', () => {
    const { trainerCardView } = loadModel();
    const rated = trainerCardView(
      trainer({ profile: { first_name: 'A', rating_avg: 4.8, rating_count: 12 } })
    );
    const unrated = trainerCardView(
      trainer({ profile: { first_name: 'A', rating_avg: 5, rating_count: 0 } })
    );
    assert.match(rated.meta, /★ 4\.8/);
    assert.ok(!unrated.meta.includes('★'), 'нулевой рейтинг — не рейтинг');
  });

  it('нет ни одного факта — остаётся только арена, без заглушек', () => {
    const { trainerCardView } = loadModel();
    const view = trainerCardView(trainer({ profile: { first_name: 'A' } }));
    assert.equal(view.meta, 'Чижовка-арена');
    for (const forbidden of ['по запросу', 'не указан', 'уточняйте', '—']) {
      assert.ok(!view.meta.includes(forbidden), 'заглушка вместо факта: ' + forbidden);
    }
  });

  it('в мета-строку не набивается больше одного факта', () => {
    const { trainerCardView } = loadModel();
    const view = trainerCardView(
      trainer({
        profile: { first_name: 'A', experience_years: 9, rating_avg: 4.8, rating_count: 12 },
        services: [{ service_name: 'Хоккейное катание', price_byn_min: 45 }],
      })
    );
    assert.equal(view.meta.split(' · ').length, 2, 'арена + один факт, не больше');
  });
});

describe('строка действия не изменилась', () => {
  it('слоты по-прежнему считаются и склоняются', () => {
    const { trainerCardView } = loadModel();
    assert.equal(trainerCardView(trainer({ free_slots_14d: 15 })).live, 'Записаться · 15 слотов');
    assert.equal(trainerCardView(trainer({ free_slots_14d: 1 })).live, 'Записаться · 1 слот');
    assert.equal(trainerCardView(trainer({ free_slots_14d: 0 })).live, 'Записаться');
  });

  it('без права записи ведёт в профиль, а не обещает запись', () => {
    const { trainerCardView } = loadModel();
    assert.equal(trainerCardView(trainer({ can_book: false })).live, 'Открыть профиль');
  });
});
