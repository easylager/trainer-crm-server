/**
 * TASK-232: открытка «Пойдёшь со мной на каток?» — чистые функции, без DOM.
 * Browser: window.ZoviModel. Node tests: module.exports.
 * Тексты повторяют src/application/zovi_card_page.py: og:title и картинки собирает сервер.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ZoviModel = api;
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var WEEKDAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
  var WEEKDAYS_LONG = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];
  var MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  var MONTHS_LONG = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

  /* Склонение имени отправителя: «от Макса», «отправь Максу». Эвристика из прототипа. */
  function decline(name, kind) {
    var n = String(name || '').trim();
    if (!n) return kind === 'dat' ? 'другу' : 'друга';
    if (/[ая]$/i.test(n)) return n.slice(0, -1) + (kind === 'dat' ? 'е' : (/[гкхжшщч]а$/i.test(n) ? 'и' : (/я$/i.test(n) ? 'и' : 'ы')));
    if (/[бвгджзклмнпрстфхцчшщ]$/i.test(n)) return n + (kind === 'dat' ? 'у' : 'а');
    if (/й$/i.test(n)) return n.slice(0, -1) + (kind === 'dat' ? 'ю' : 'я');
    return n;
  }

  /* Вид сеанса → что зовут делать. ОХМ — хоккей, остальное — каток. */
  function activity(kind) {
    return kind === 'hockey_practice' ? 'на хоккей' : 'на каток';
  }

  /* Вопрос открытки частями: имя красится тиловым отдельно от остального текста. */
  function questionParts(toName, kind) {
    var to = String(toName || '').trim();
    var tail = 'пойдёшь со мной ' + activity(kind) + '?';
    if (!to) return { name: '', rest: 'П' + tail.slice(1) };
    return { name: to, rest: ', ' + tail };
  }

  function questionText(toName, kind) {
    var p = questionParts(toName, kind);
    return (p.name + p.rest).replace(/ /g, ' ');
  }

  /* Вердикт без рода: открытку шлют кому угодно. */
  function verdict(tries, falls, tricked) {
    if (tricked) return 'Нажали «Нет». Это была «Да» в маскировке. Засчитано.';
    if (tries === 0) return 'Ответ «да» — с первой секунды. Кнопка «Нет» даже не проснулась.';
    if (tries <= 2) return 'Пара секунд на раздумья. Для приличия.';
    if (tries >= 5) return 'Кнопка «Нет» сдалась первой.';
    if (falls) return 'Кнопку «Нет» довели до падения. Беспощадно.';
    return 'Долго думали. Но правильно.';
  }

  /* Секунды сопротивления на билете: как в прототипе — хоть одна, если «нет» трогали. */
  function resistSeconds(ms) {
    var v = Number(ms) || 0;
    return v > 0 ? Math.max(1, Math.round(v / 1000)) : 0;
  }

  /* Кто на билете: «Лера + Макс»; без имени получателя — «Макс + компания». */
  function ticketWho(toName, fromName) {
    var to = String(toName || '').trim(), from = String(fromName || '').trim();
    return to ? [to, from] : [from, 'компания'];
  }

  function parseDay(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    if (!m) return null;
    var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return { wd: (d.getUTCDay() + 6) % 7, day: +m[3], month: +m[2] - 1 };
  }

  /* Дата по Минску (local_date уже минская): short «Сб, 17 окт», ticket «Сб, 17 октября», long «Суббота, 17 октября». */
  function dayLabel(iso, style) {
    var d = parseDay(iso);
    if (!d) return '';
    if (style === 'long') return WEEKDAYS_LONG[d.wd] + ', ' + d.day + ' ' + MONTHS_LONG[d.month];
    if (style === 'ticket') return WEEKDAYS_SHORT[d.wd] + ', ' + d.day + ' ' + MONTHS_LONG[d.month];
    return WEEKDAYS_SHORT[d.wd] + ', ' + d.day + ' ' + MONTHS_SHORT[d.month];
  }

  function clampInt(v, lo, hi) {
    var n = Math.round(Number(v) || 0);
    return Math.min(hi, Math.max(lo, n));
  }

  /* Тело POST answer в пределах API (TASK-231). */
  function answerBody(deviceToken, tries, resistMs, falls, tricked) {
    return {
      device_token: deviceToken,
      tries: clampInt(tries, 0, 10),
      resist_ms: clampInt(resistMs, 0, 600000),
      falls: clampInt(falls, 0, 5),
      tricked: !!tricked
    };
  }

  /* Воронка (TASK-237): тело маячка и ?src= для запроса открытки. Сервер сверяет оба с белым списком. */
  function eventBody(kind, deviceToken, act) {
    var body = { kind: kind, device_token: deviceToken };
    if (act != null) body.act = clampInt(act, 0, 10);
    return body;
  }

  function srcQuery(search) {
    var m = /[?&]src=([a-z]{2,8})(?:&|$)/.exec(String(search || ''));
    return m ? '?src=' + m[1] : '';
  }

  /* Картинка билета: имена и сеанс сервер берёт из базы, в query — только статистика. */
  function ticketQuery(tries, sec, falls, tricked) {
    return '?t=' + clampInt(tries, 0, 10) + '&s=' + clampInt(sec, 0, 600) + '&f=' + clampInt(falls, 0, 5) + '&k=' + (tricked ? 1 : 0);
  }

  /* Календарь по устройству: iPhone открывает .ics сам, Android — Google Календарь по ссылке,
     компьютер — оба. ua — navigator.userAgent, touchMac — iPad, который притворяется Mac. */
  function calendarPlatform(ua, touchMac) {
    var u = String(ua || '');
    if (/iPhone|iPad|iPod/.test(u) || (touchMac && /Macintosh/.test(u))) return 'ios';
    if (/Android/.test(u)) return 'android';
    return 'desktop';
  }

  function gcalStamp(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  }

  function googleCalendarUrl(title, startIso, endIso, location, details) {
    var dates = gcalStamp(startIso) + '/' + gcalStamp(endIso);
    return 'https://calendar.google.com/calendar/render?action=TEMPLATE' +
      '&text=' + encodeURIComponent(title || '') +
      '&dates=' + dates +
      '&location=' + encodeURIComponent(location || '') +
      '&details=' + encodeURIComponent(details || '');
  }

  return {
    calendarPlatform: calendarPlatform,
    googleCalendarUrl: googleCalendarUrl,
    decline: decline,
    activity: activity,
    questionParts: questionParts,
    questionText: questionText,
    verdict: verdict,
    resistSeconds: resistSeconds,
    ticketWho: ticketWho,
    dayLabel: dayLabel,
    answerBody: answerBody,
    eventBody: eventBody,
    srcQuery: srcQuery,
    ticketQuery: ticketQuery
  };
});
