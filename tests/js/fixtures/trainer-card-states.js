'use strict';
/**
 * Состояния единой карточки тренера (TASK-400) по доскам макета: тренер витрины + ответ /client/slots.
 * Один набор — для node-тестов (tests/js/trainer-card-unified.test.js) и для ручной сверки в браузере.
 * Демо-данные макета; имена катков — как в выдаче витрины (сырые), primary_arena_name — публичное имя.
 */

const tier = (id, kind, cents) => ({ id, tier_kind: kind, price_cents: cents, currency_code: 'BYN' });
const service = (id, extra = {}) => ({
  service_id: id, service_name: 'Услуга ' + id, title: '', is_public: true, is_online: false, currency_code: 'BYN',
  price_cents: null, group_price_cents: null, summary_hook: '', summary_body: '', client_notice: null, description: null,
  direction_service_id: null, price_tiers: [], ...extra,
});
const arena = (id, name, extra = {}) => ({
  id, name, city_id: 1, address: 'ул. Притыцкого, 156', map_link: 'https://yandex.by/maps/?pt=1,2', rental_cents: 900, rental_currency: 'BYN', ...extra,
});
const slot = (id, date, time, extra = {}) => ({
  id, slot_date: date, start_time: time, end_time: '', capacity: 1, spots_left: 1, arena_id: 3, is_online: false, ...extra,
});

const BIO = 'Учу кататься с нуля — детей и взрослых. Первое занятие без нагрузки: привыкаем ко льду, учимся падать и вставать. ' +
  'Дальше — по шагам, без спешки и крика. Ставлю технику шага, торможение и повороты. Занимаюсь на «Замке» по выходным, ' +
  'в будни — вечером. Коньки можно взять в прокате на катке, своё снаряжение не обязательно.';

const base = (extra) => ({
  id: 1, name: 'Анна Соколова', first_name: 'Анна', initial: 'А', photo_url: null, experience_years: null,
  description: '', education: '', rating_avg: null, rating_count: 0, session_duration_minutes: 60, glide_since: null,
  can_book: true, contact_url: '/r/tg/1', telegram_url: 'https://t.me/bot?start=trainer_1', phone: '',
  min_session_price_cents: null, min_session_price_currency: 'BYN', min_price_by_direction: {}, services: [], arenas: [],
  windows: [], primary_arena_name: null, ...extra,
});

const STATES = {
  // A — с фото, можно записаться: 7 лет · Любой возраст · «Замок»; два направления, тарифы 45/50, «двое».
  A: {
    trainer: base({
      photo_url: '/static/landing/assets/hero-ice-macro.webp', experience_years: 7, description: BIO, education: 'Высшее профильное образование',
      rating_avg: 4.9, rating_count: 14, glide_since: '2026-09', min_session_price_cents: 4500, primary_arena_name: '«Замок»',
      arenas: [arena(3, 'Замок')],
      services: [
        service(1, { title: 'С нуля', price_tiers: [tier(11, 'child', 4500), tier(12, 'adult', 5000), tier(13, 'two_children', 6000), tier(14, 'adult_and_child', 6500)] }),
        service(2, { title: 'Уже катаюсь', price_tiers: [tier(21, 'child', 5000), tier(22, 'adult', 5500)] }),
      ],
    }),
    slots: [slot(101, '2026-11-21', '10:00'), slot(102, '2026-11-21', '11:30'), slot(103, '2026-11-22', '09:00'), slot(104, '2026-11-24', '18:00')],
  },
  // B — без фото, хоккей: 12 лет · Дети · от 50 BYN (каток длиннее 10 знаков), одна цена.
  B: {
    trainer: base({
      id: 2, name: 'Дмитрий Петров', first_name: 'Дмитрий', experience_years: 12, glide_since: '2026-10', description: '[Короткое описание тренера своими словами.]',
      min_session_price_cents: 5000, primary_arena_name: '«Чижовка-Арена»', arenas: [arena(3, 'Чижовка-Арена')],
      services: [service(4, { title: 'Хоккейное катание', price_tiers: [tier(41, 'child', 5000)] })],
    }),
    slots: [slot(201, '2026-11-20', '19:00'), slot(202, '2026-11-21', '12:00')],
  },
  // C — нет окон: 9 лет · Любой возраст · от 55 BYN.
  C: {
    trainer: base({
      id: 3, name: 'Ольга Ковалёва', first_name: 'Ольга', photo_url: '/static/landing/assets/hero-ice-macro.webp', experience_years: 9,
      description: '[Короткое описание тренера своими словами — 2–3 предложения.]', min_session_price_cents: 5500,
      arenas: [arena(3, 'Ледовая арена Гродно')],
      services: [service(1, { title: 'С нуля', price_tiers: [tier(31, 'child', 5500), tier(32, 'adult', 6000)] })],
    }),
    slots: [],
  },
  // F — без онлайн-записи: карточки цены нет, «Оставить заявку» главная.
  F: {
    trainer: base({
      id: 4, name: 'Сергей Лавров', first_name: 'Сергей', photo_url: '/static/landing/assets/hero-ice-macro.webp', experience_years: 5, can_book: false,
      description: '[Короткое описание тренера своими словами — 2–3 предложения.]', min_session_price_cents: 6000,
      arenas: [arena(3, 'Ледовая арена «Брест»')],
      services: [service(4, { title: 'Хоккейное катание', price_tiers: [tier(51, 'adult', 6000)] })],
    }),
    slots: [],
  },
  // M2 — скудный профиль: ни фото, ни опыта, ни описания; одна цена.
  M2: {
    trainer: base({
      id: 5, name: 'Ирина Орлова', first_name: 'Ирина', arenas: [arena(3, 'ЛДС')], primary_arena_name: '«ЛДС»',
      services: [service(1, { title: 'С нуля', price_tiers: [tier(61, 'adult', 5500)] })],
    }),
    slots: [slot(501, '2026-11-24', '17:00'), slot(502, '2026-11-26', '17:00')],
  },
  // M3 — несколько катков: подпись площадки в чипе.
  M3: {
    trainer: base({
      id: 6, name: 'Павел Ким', first_name: 'Павел', experience_years: 3, arenas: [arena(3, 'Замок'), arena(4, 'Чижовка')],
      services: [service(1, { title: 'С нуля', price_tiers: [tier(71, 'child', 4000), tier(72, 'adult', 4500)] })],
    }),
    slots: [slot(601, '2026-11-21', '10:00', { arena_id: 3 }), slot(602, '2026-11-21', '16:00', { arena_id: 4 })],
  },
  // M4 — онлайн-занятие.
  M4: {
    trainer: base({
      id: 7, name: 'Вера Лис', first_name: 'Вера', session_duration_minutes: 45,
      services: [service(1, { title: 'С нуля', is_online: true, price_tiers: [tier(81, 'adult', 3000)] })],
    }),
    slots: [slot(701, '2026-11-25', '19:00', { is_online: true, arena_id: null })],
  },
  // M5 — группа: «осталось 3 места».
  M5: {
    trainer: base({
      id: 8, name: 'Глеб Орех', first_name: 'Глеб', arenas: [arena(3, 'Замок')],
      services: [service(1, { title: 'С нуля', price_cents: 2500 })],
    }),
    slots: [slot(801, '2026-11-22', '11:00', { capacity: 6, spots_left: 3 })],
  },
  // M6 — нет цены.
  M6: {
    trainer: base({
      id: 9, name: 'Лев Тур', first_name: 'Лев', arenas: [arena(3, 'Замок')],
      services: [service(1, { title: 'С нуля' })],
    }),
    slots: [slot(901, '2026-11-21', '10:00')],
  },
  // M7 — несколько направлений: вкладки прокручиваются.
  M7: {
    trainer: base({
      id: 10, name: 'Мария Дель', first_name: 'Мария', arenas: [arena(3, 'Замок')],
      services: [
        service(1, { title: 'С нуля', price_tiers: [tier(91, 'child', 4500), tier(92, 'adult', 5000)] }),
        service(2, { title: 'Уже катаюсь', price_tiers: [tier(93, 'child', 5000), tier(94, 'adult', 5500)] }),
        service(4, { title: 'Хоккейное катание', price_tiers: [tier(95, 'child', 5000), tier(96, 'adult', 5500)] }),
      ],
    }),
    slots: [slot(1001, '2026-11-21', '10:00')],
  },
};

module.exports = { STATES };
