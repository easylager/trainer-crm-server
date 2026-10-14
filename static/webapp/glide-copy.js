/**
 * TASK-209: словарь подписей каталога — JS-зеркало ``src/shared/copy_ru.json``.
 * Один источник для сайта (static/share/*) и Mini App (static/webapp/*): раньше
 * меню времени говорило «В выходные» в одном месте и «Выходные» в другом.
 * COPY ниже — валидный JSON, тест сверяет его с ``src/shared/copy_ru.json`` построчно.
 * Browser: window.GlideCopy. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GlideCopy = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var COPY = {
    "when.today": "Сегодня",
    "when.tomorrow": "Завтра",
    "when.weekend": "В выходные",
    "when.day": "День…",
    "when.evening": "Сегодня вечером",
    "basis.live": "с сайта катка",
    "basis.projected": "обычно",
    "basis.projected_long": "по обычной сетке катка — лучше уточнить",
    "basis.photo": "по фото афиши",
    "mode.phone": "Расписание — только по телефону",
    "mode.season_closed": "Сейчас закрыто",
    "mode.reopen": "Откроется {date}",
    "kind.public_skate": "Массовое катание",
    "kind.hockey_practice": "ОХМ",
    "cta.follow": "Следить за катком в Telegram",
    "cta.follow_closed": "Сообщить об открытии",
    "cta.following": "Вы следите за катком",
    "cta.metoo": "Я тоже иду",
    "cta.call": "Позвонить",
    "cta.route": "Маршрут",
    "cta.share": "Поделиться",
    "cta.report": "Нашли ошибку? Напишите нам",
    "price.with_rental": "с прокатом {total} {currency}",
    "footer.made_by": "Сделано теми, кто сам катается.",
    "home.counter.when.today": "Сегодня",
    "home.counter.today_done": "Сегодня сеансов нет, завтра лёд в {cities} {cities_word}",
    "home.counter.today_done_bare": "Сегодня сеансов нет",
    "home.counter.when.tomorrow": "Завтра",
    "home.counter.when.weekend": "В эти выходные",
    "home.counter.when.day": "В этот день",
    "home.counter": "{when} в Беларуси {sessions} {sessions_word} в {cities} {cities_word}",
    "home.when_phrase.today": "сегодня",
    "home.when_phrase.tomorrow": "завтра",
    "home.when_phrase.weekend": "в выходные",
    "home.when_phrase.day": "в этот день",
    "home.city_button.caption": "Ваш город · сменить",
    "home.city_button.title": "{city} — {sessions} {sessions_word} {when_phrase} →",
    "home.upcoming.city": "Ближайшие в {city}",
    "home.upcoming.weekend": "{city}, сб и вс",
    "home.map.aria": "Карта Беларуси: города с местами для катания",
    "home.minutes_until": "через {n} мин",
    "home.all_link": "Все →",
    "home.all_places": "Все места",
    "home.ice_today": "Лёд сегодня",
    "home.cities_empty": "Пока нет опубликованных городов.",
    "home.sessions_empty": "Ближайших сеансов пока нет — загляните в расписание по городу.",
    "chip.ice": "Лёд",
    "chip.hockey": "С клюшкой",
    "chip.first_time": "Первый раз",
    "route.skate": "Покататься",
    "route.service": "Заточка",
    "route.shops": "Магазины",
    "route.trainers": "Тренеры",
    "route.skate.hint": "каток, зал или трасса",
    "selection.ice.hint": "катки",
    "route.hockey.hint": "открытая тренировка, ОХМ",
    "route.service.hint": "заточка коньков",
    "brand.mark": "Glide",
    "ice.today.h1": "{city}: лёд сегодня",
    "hub.no_skate_times": "времени катания в расписании нет",
    "hub.open_until": "{name} открыт до {time}",
    "cta.invite_friends": "Позвать друзей",
    "share.story": "Картинка для истории",
    "share.card": "Открытка",
    "city.not_found": "Такого города нет в каталоге",
    "nav.back_city": "‹ {city}",
    "home.footer": "Glide делают люди, которые сами катаются.",
    "home.other_city": "Другой город",
    "hub.on_ice": "{city} на льду",
    "hub.nearest_ice": "Ближайший лёд",
    "hub.what": "Что нужно",
    "hub.today": "Сегодня",
    "hub.week": "Неделя",
    "hub.nearby": "Лёд рядом",
    "hub.nearby_scheduled": "Лёд по расписанию рядом",
    "hub.when_title": "Когда кататься",
    "hub.phone_when": "{name} называет время массового катания по телефону.",
    "hub.directions": "Как добраться",
    "cta.follow_rink": "Следить за катком",
    "cta.invite_short": "Позвать",
    "place.on_site": "На месте",
    "home.map.legend_on": "лёд сегодня",
    "home.map.legend_off": "сегодня нет",
    "place.phone_schedule": "Время массового катания называют по телефону.",
    "place.site_schedule": "Время массового катания — на сайте катка",
    "place.day_empty": "Сеансов нет",
    "feed.time_by_phone": "Время — по телефону",
    "feed.schedule_first": "сначала с расписанием",
    "place.tickets_online": "Билеты — на сайте катка ↗",
    "cta.enroll": "Записаться",
    "cta.write": "Написать",
    "place.trainers": "Тренеры",
    "hub.trainers_all": "Все тренеры",
    "tg.open": "Открыть в Telegram",
    "tg.open_short": "Telegram",
    "tg.map_all": "там карта всех катков",
    "tg.map_all_named": "в Telegram — карта всех катков",
    "tg.map_city": "там все катки города на карте",
    "tg.map_city_n": "там все {n} {word} на карте",
    "tg.map_city_one": "там этот каток на карте"
  };

  function t(key, kw) {
    var template = COPY[key];
    if (template === undefined) return key;
    if (!kw) return template;
    return template.replace(/\{(\w+)\}/g, function (match, name) {
      return Object.prototype.hasOwnProperty.call(kw, name) ? String(kw[name]) : match;
    });
  }

  return { COPY: COPY, t: t };
});
