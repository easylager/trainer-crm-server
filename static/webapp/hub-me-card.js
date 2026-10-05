/**
 * TASK-160 (S1): «Моя карточка» — единственный герой клиентского хаба.
 * Pure view-model + renderer (no DOM). Browser: window.HubMeCard. Node: module.exports.
 *
 * Разметка и классы — из design/prototypes/2026-10-04-client-hub-me-card.html
 * (meCard / meWho / mePick / meWallet). Ни один класс здесь не переименован.
 *
 * Карточка — одна рамка на шесть заливок (input.kind):
 *   booking    — моя запись (единственная заливка с крупным временем);
 *   trainer    — мой тренер: окна чипами либо честное «окон нет»;
 *   dormant    — возврат: не сгоревший остаток и история, а не выдуманный повод;
 *   city-ice   — личного нет, карточку заполняет лёд города;
 *   city-pick  — города нет: выбор города первым классом, геолокация тихой строкой;
 *   far        — мы не в этом городе: развилка без обещаний, которых мы не держим.
 *
 * Продуктовые правила, которые модель держит сама (их нельзя обойти рендером):
 *   1. Крупное время (`me__when`) не изображает персональное обязательство
 *      тренера передо мной. Моя запись (`booking`) — обязательство, сеанс
 *      площадки (`city-ice`) — факт мира, как сеанс в кино: там кикер «На льду
 *      сегодня», в строке `who` арена, а не человек, и штампа «подтверждена»
 *      нет, так что спутать их нельзя. А у тренера и возврата крупного времени
 *      нет ни при каких данных: чужое окно не должно читаться как моя запись,
 *      время там живёт только чипами.
 *   2. Кошелёк честный: ячейка есть только при положительном остатке, полоса —
 *      только при наличии хотя бы одной ячейки.
 *   3. Остаток показывается под тем лицом, которому принадлежит. Есть тренер в
 *      карточке — только его остаток; нет тренера — любой активный, но подпись
 *      обязана назвать владельца.
 *   4. Чипы окон — максимум MAX_PICK_CHIPS плюс обязательный вход «во все окна».
 *   5. Корень карточки не интерактивен: кликабельны только вложенные button.
 *   6. Нет поля — нет строки. Ни «ваш тренер» вместо арены, ни выдуманных имён.
 *
 * Модуль чистый: ни document, ni window.location, ни fetch, ни Date.now().
 * Текущее время приходит аргументом `now`; невалидный `now` просто лишает
 * подписи относительных форм («Сегодня», «через 8 дней»), но не врёт.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.HubMeCard = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var KINDS = ['booking', 'trainer', 'dormant', 'city-ice', 'city-pick', 'far'];

  /**
   * Заливки, которым разрешено крупное время. Моя запись — обязательство тренера
   * передо мной; сеанс площадки — факт мира. У тренера и возврата крупного
   * времени нет: чужое окно не должно читаться как моя запись.
   */
  var BIG_TIME_KINDS = ['booking', 'city-ice'];

  /** Полоса окон показывает, что окна есть, и впускает во все — она не расписание. */
  var MAX_PICK_CHIPS = 4;
  /**
   * DEC-008 (TASK-162): кнопок города не больше шести. Городов больше — шестой
   * кнопкой обязателен «Другой город», иначе остальные становятся недостижимы.
   */
  var MAX_CITY_BUTTONS = 6;
  /** «Сгорит скоро» — окно, в котором срок абонемента становится аргументом. */
  var EXPIRY_WARN_DAYS = 14;
  /** «Скоро» = те же 3 часа, что у hub-карточки (HUB_SOON_MS в client-home-main.js). */
  var SOON_MS = 3 * 60 * 60 * 1000;
  var DEFAULT_CURRENCY = 'BYN';

  var RU_MONTHS_SHORT = [
    'янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек',
  ];
  var RU_WEEKDAYS_SHORT = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];

  /* ─── Примитивы ───────────────────────────────────────────────────────── */

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function obj(v) {
    return v && typeof v === 'object' ? v : {};
  }

  function str(v) {
    return String(v == null ? '' : v).trim();
  }

  function posInt(v) {
    if (v == null || v === '') return 0;
    var n = Number(v);
    return isNaN(n) || n <= 0 ? 0 : Math.floor(n);
  }

  function idOrNull(v) {
    var s = str(v);
    return s === '' ? null : s;
  }

  /** Склейка фактов через « · ». Пустые части выпадают — пустых разделителей нет. */
  function joinDot(parts) {
    var out = [];
    (parts || []).forEach(function (p) {
      var s = str(p);
      if (s !== '') out.push(s);
    });
    return out.join(' · ');
  }

  function pluralRu(n, one, few, many) {
    var abs = Math.abs(n) % 100;
    if (abs >= 11 && abs <= 14) return many;
    var last = abs % 10;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
  }

  function pad2(n) {
    return n < 10 ? '0' + n : String(n);
  }

  /** Монограмма: только буквы и цифры, «Каток «Лидо»» → «КЛ» (как в хабе). */
  function initials(name) {
    var words = str(name)
      .replace(/[^0-9A-Za-zА-Яа-яЁё\s-]/g, ' ')
      .trim()
      .split(/[\s-]+/)
      .filter(Boolean);
    if (!words.length) return '?';
    if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
    return words[0].slice(0, 2).toUpperCase();
  }

  function photoUrl(key) {
    var k = str(key);
    return k ? '/api/public/photos/' + encodeURIComponent(k) : '';
  }

  function hhmm(v) {
    var s = str(v);
    return s.length >= 5 ? s.slice(0, 5) : s;
  }

  /**
   * Серверные заглушки имени («Тренер», «—») именем не являются: назвать человека
   * ими — то же самое, что выдумать. Такое имя для подписей не годится.
   */
  var NAMELESS = ['тренер', 'trainer', '—', '-', '?'];

  function firstName(name) {
    var s = str(name);
    if (!s) return '';
    var first = s.split(/\s+/)[0];
    return NAMELESS.indexOf(first.toLowerCase()) >= 0 ? '' : first;
  }

  /* ─── Даты (всё считается от аргумента now, никакого внешнего времени) ── */

  function isoDay(v) {
    var s = str(v).slice(0, 10);
    return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : '';
  }

  function dayIndex(iso) {
    var b = iso.split('-');
    return Math.round(Date.UTC(Number(b[0]), Number(b[1]) - 1, Number(b[2])) / 86400000);
  }

  function nowIsoDay(now) {
    if (!now) return '';
    return now.getFullYear() + '-' + pad2(now.getMonth() + 1) + '-' + pad2(now.getDate());
  }

  /** Целых дней от «сегодня» до даты. Нет валидного now — null (никаких догадок). */
  function daysUntil(iso, now) {
    var a = isoDay(iso);
    var b = nowIsoDay(now);
    if (!a || !b) return null;
    return dayIndex(a) - dayIndex(b);
  }

  /** Подпись чипа: «Сегодня» / «Завтра» / «Сб, 7 июн». */
  function dayChipLabel(iso, now) {
    var d = isoDay(iso);
    if (!d) return '';
    var diff = daysUntil(d, now);
    if (diff === 0) return 'Сегодня';
    if (diff === 1) return 'Завтра';
    var b = d.split('-');
    var wd = RU_WEEKDAYS_SHORT[new Date(Date.UTC(Number(b[0]), Number(b[1]) - 1, Number(b[2]))).getUTCDay()] || '';
    return (wd ? wd + ', ' : '') + Number(b[2]) + ' ' + (RU_MONTHS_SHORT[Number(b[1]) - 1] || '');
  }

  /** «30 ноя», с годом — когда год не текущий. */
  function shortDate(iso, now) {
    var d = isoDay(iso);
    if (!d) return '';
    var b = d.split('-');
    var out = Number(b[2]) + ' ' + (RU_MONTHS_SHORT[Number(b[1]) - 1] || '');
    if (now && now.getFullYear() !== Number(b[0])) out += ' ' + b[0];
    return out;
  }

  function money(cents) {
    var n = Number(cents);
    if (cents == null || cents === '' || isNaN(n)) return '';
    return (n / 100).toFixed(2).replace(/\.?0+$/, '');
  }

  /** ISO-строка или Date → Date. Разбор, а не чтение часов: внешнего времени нет. */
  function toDate(v) {
    if (v instanceof Date) return isNaN(v.getTime()) ? null : v;
    var s = str(v);
    if (!s) return null;
    var ms = Date.parse(s);
    return isNaN(ms) ? null : new Date(ms);
  }

  /** «через 40 минут» / «через час» / «через 2 часа» — как soonWhenPrefix в хабе. */
  function soonLabel(ms) {
    var mins = Math.max(1, Math.round(ms / 60000));
    if (mins < 60) return 'через ' + mins + ' ' + pluralRu(mins, 'минуту', 'минуты', 'минут');
    var h = Math.round(mins / 60);
    if (h <= 1) return 'через час';
    return 'через ' + h + ' ' + pluralRu(h, 'час', 'часа', 'часов');
  }

  /** «до 13:00» — только когда есть и начало, и длительность. */
  function endTimeLabel(start, durationMinutes) {
    var dur = posInt(durationMinutes);
    if (!start || !dur) return '';
    var end = new Date(start.getTime() + dur * 60000);
    return 'до ' + pad2(end.getHours()) + ':' + pad2(end.getMinutes());
  }

  /** «180 км». Нет поля — нет строки: дистанцию здесь не выдумывают. */
  function distanceLabel(value) {
    if (value == null || value === '') return '';
    var n = Number(value);
    if (isNaN(n) || n < 0) return '';
    var num = n >= 10 ? String(Math.round(n)) : String(Math.round(n * 10) / 10);
    return num + ' км';
  }

  /* ─── Кошелёк ─────────────────────────────────────────────────────────── */

  function activePasses(list) {
    var out = [];
    (Array.isArray(list) ? list : []).forEach(function (raw) {
      var p = obj(raw);
      if (str(p.status).toLowerCase() !== 'active') return;
      if (posInt(p.sessions_remaining) <= 0) return;
      out.push(p);
    });
    return out;
  }

  function activeCertificates(list) {
    var out = [];
    (Array.isArray(list) ? list : []).forEach(function (raw) {
      var c = obj(raw);
      // 'issued' — сертификат выдан, но этот клиент его не активировал: это ещё
      // не его баланс. Платить можно только активированным с остатком.
      if (str(c.status).toLowerCase() !== 'activated') return;
      if (posInt(c.amount_remaining_cents) <= 0) return;
      out.push(c);
    });
    return out;
  }

  /**
   * Остаток под правильным лицом. Есть тренер в карточке — берём только его
   * остаток (нет такого — ячейки нет вообще); нет тренера — любой активный.
   */
  function pickOwned(items, trainerId) {
    if (!items.length) return null;
    if (!trainerId) return items[0];
    for (var i = 0; i < items.length; i++) {
      if (idOrNull(items[i].trainer_id) === trainerId) return items[i];
    }
    return null;
  }

  function passExpirySub(pass, now) {
    var exp = isoDay(pass.expires_at);
    if (!exp) return { sub: '', warn: false };
    var left = daysUntil(exp, now);
    if (left == null) return { sub: 'до ' + shortDate(exp, now), warn: false };
    if (left < 0) return { sub: 'срок истёк', warn: true };
    if (left === 0) return { sub: 'сгорает сегодня', warn: true };
    if (left <= EXPIRY_WARN_DAYS) {
      return {
        sub: 'сгорит ' + shortDate(exp, now) + ' · через ' + left + ' ' + pluralRu(left, 'день', 'дня', 'дней'),
        warn: true,
      };
    }
    return { sub: 'до ' + shortDate(exp, now), warn: false };
  }

  /**
   * Подпись остатка, когда лица в карточке нет: назвать владельца обязательно.
   * Родительный падеж («у Марины») модель сама не строит — склонения живут в
   * ru-person-name.js, а модуль чистый. Пришёл готовый `trainer_name_genitive`
   * (его готовит вызывающий код) — «Абонемент у Марины»; не пришёл — честная
   * безпадежная форма «Абонемент · Марина», но имя есть в любом случае.
   */
  function ownerSuffix(row, base) {
    var gen = firstName(row.trainer_name_genitive);
    if (gen) return base + ' у ' + gen;
    var nom = firstName(row.trainer_name);
    return nom ? base + ' · ' + nom : base;
  }

  function passCell(pass, named, kind, now) {
    var remaining = posInt(pass.sessions_remaining);
    var total = posInt(pass.sessions_total);
    var label = kind === 'booking' ? 'Спишется с абонемента' : 'Абонемент';
    if (named && kind !== 'booking') label = ownerSuffix(pass, 'Абонемент');
    var expiry = passExpirySub(pass, now);
    var sub = expiry.sub;
    var warn = expiry.warn;
    // Последнее занятие на абонементе — факт, который важнее срока: после этой
    // записи абонемент закончится, и человек должен узнать об этом заранее.
    if (kind === 'booking' && remaining === 1) {
      sub = 'это последнее занятие';
      warn = true;
    }
    return {
      key: 'pass',
      label: label,
      value: String(remaining),
      unit: total > 0 ? 'из ' + total : '',
      sub: sub,
      bar: total > 0 ? Math.max(4, Math.min(100, Math.round((remaining / total) * 100))) : null,
      warn: warn,
      action: 'open-pass',
      trainerId: idOrNull(pass.trainer_id),
    };
  }

  function certificateCell(cert, named, currency) {
    return {
      key: 'cert',
      label: named ? ownerSuffix(cert, 'Сертификат') : 'Сертификат',
      value: money(cert.amount_remaining_cents),
      // Валюты в payload сертификата нет: её даёт вызывающий (`input.currency`).
      // Для московского рынка это рубль, и это не должно быть переписыванием.
      unit: currency,
      sub: '',
      bar: null,
      warn: false,
      action: 'open-cert',
      trainerId: idOrNull(cert.trainer_id),
    };
  }

  function buildWallet(kind, trainerId, input, now) {
    var cells = [];
    var currency = str(input.currency) || DEFAULT_CURRENCY;
    var pass = pickOwned(activePasses(input.passes), trainerId);
    if (pass) cells.push(passCell(pass, !trainerId, kind, now));
    var cert = pickOwned(activeCertificates(input.certificates), trainerId);
    if (cert) cells.push(certificateCell(cert, !trainerId, currency));
    return cells;
  }

  /* ─── Куски карточки ──────────────────────────────────────────────────── */

  /**
   * Склонённые формы имени. Модуль их не строит: падежи живут в
   * ru-person-name.js, а здесь нет доступа к глобалам. Вызывающий код (S2)
   * кладёт готовые `trainer.nameDative` / `trainer.nameGenitive`; без них
   * подписи переходят на безпадежные формы, а не на кривой падеж.
   */
  function declined(input) {
    var t = obj(input.trainer);
    return {
      dative: firstName(t.nameDative),
      genitive: firstName(t.nameGenitive),
    };
  }

  function writeLabel(forms) {
    return forms.dative ? 'Написать ' + forms.dative : 'Написать тренеру';
  }

  function allSlotsLabel(forms) {
    return forms.genitive ? 'Все окна ' + forms.genitive : 'Все окна';
  }

  function contact(username, telegramId) {
    var un = str(username).replace(/^@/, '');
    var tid = str(telegramId);
    if (!un && !tid) return null;
    return { username: un, telegramId: tid };
  }

  /**
   * Лицо карточки. Нет имени — нет блока: подставлять «Тренер» или «ваш тренер»
   * вместо настоящего имени значит врать о том, с кем человек имеет дело.
   */
  function buildWho(name, photoKey, place, trainerId, opts) {
    opts = opts || {};
    var n = str(name);
    if (!n) return null;
    return {
      name: n,
      initials: str(opts.initials) || initials(n),
      photo: photoUrl(photoKey),
      place: str(place),
      placeIcon: opts.placeIcon !== false,
      hero: !!opts.hero,
      trainerId: trainerId || null,
      dm: opts.dm || null,
    };
  }

  function buildPick(slots, head, allLabel, allAction, now) {
    var list = Array.isArray(slots) ? slots : [];
    var chips = [];
    for (var i = 0; i < list.length && chips.length < MAX_PICK_CHIPS; i++) {
      var s = obj(list[i]);
      var time = hhmm(s.start_time);
      if (!time) continue;
      chips.push({
        day: dayChipLabel(s.slot_date, now),
        time: time,
        slotId: idOrNull(s.id),
        serviceId: idOrNull(s.service_id),
        arenaId: idOrNull(s.arena_id),
        arenaName: str(s.arena_name),
      });
    }
    if (!chips.length) return null;
    return { head: str(head), chips: chips, allLabel: str(allLabel), allAction: allAction };
  }

  function emptyView(mod, statusLabel) {
    return {
      kind: '',
      mod: mod || '',
      status: { label: str(statusLabel), pill: null },
      when: null,
      head: '',
      who: null,
      line: '',
      pick: null,
      actions: [],
      cities: null,
      moreCities: false,
      geo: false,
      wallet: [],
      foot: null,
      trainerId: null,
    };
  }

  /* ─── Заливки ─────────────────────────────────────────────────────────── */

  /**
   * Штамп записи — тот же, что у существующей hub-карточки (`nextCardStamp`):
   * ожидание важнее «скоро», потому что ответ тренера — действие. «Через N» —
   * только когда начало известно и до него не больше SOON_MS; нет `start` —
   * штамп молчит о близости, а не угадывает её.
   */
  function bookingStamp(b, start, now) {
    if (str(b.status).toLowerCase() === 'pending') return { kind: 'wait', label: 'ждёт тренера' };
    if (b.hub_in_session) return { kind: 'soon', label: 'сейчас' };
    if (start && now) {
      var left = start.getTime() - now.getTime();
      if (left > 0 && left <= SOON_MS) return { kind: 'soon', label: soonLabel(left) };
    }
    return { kind: 'ok', label: 'подтверждена' };
  }

  /**
   * Моя запись: обязательство тренера передо мной, и крупное время здесь
   * законно — оно моё. Дата приходит готовой подписью (`date_label`), начало —
   * необязательным `start` (ISO-строка или Date) для штампа и конца занятия.
   */
  function buildBooking(input, now) {
    var b = obj(input.booking);
    var time = hhmm(b.start_time);
    if (!time) return null;
    var dayLabel = str(b.date_label);
    var isToday = dayLabel.toLowerCase() === 'сегодня';
    var dur = posInt(b.duration_minutes);
    var start = toDate(b.start);
    var pending = str(b.status).toLowerCase() === 'pending';
    var dm = contact(b.trainer_telegram_username, b.trainer_telegram_id);
    var fn = firstName(b.trainer_name);
    var forms = declined(input);

    var view = emptyView(pending ? 'warn' : 'accent', isToday ? 'Сегодня' : 'Ваша запись');
    view.status.pill = bookingStamp(b, start, now);
    view.when = {
      time: time,
      meta: joinDot([
        isToday ? '' : dayLabel,
        dur ? dur + ' мин' : '',
        // Время окончания — только у сегодняшнего занятия: человек планирует
        // им текущий день. У записи на послезавтра «до 13:00» — шум.
        isToday ? endTimeLabel(start, dur) : '',
      ]),
    };
    view.who = buildWho(b.trainer_name, b.trainer_list_photo_key, b.arena_name, idOrNull(b.trainer_id), {
      // В ожидании конверт из шапки уходит: глагол один и он залитой кнопкой.
      dm: pending ? null : dm,
    });
    view.trainerId = idOrNull(b.trainer_id);
    if (pending) {
      // Проверенный факт: pending считается занявшим слот (_count_occupying_bookings).
      view.line = 'Время держится за вами, пока ' + (fn || 'тренер') + ' не ответит.';
      if (dm) view.actions.push({ style: 'fill', label: writeLabel(forms), action: 'dm', dm: dm });
    } else {
      view.foot = { label: 'Детали, перенос, отмена', action: 'open-booking' };
    }
    return view;
  }

  /**
   * Мой тренер. Крупного времени нет намеренно: чужое окно — ещё не моя запись.
   * Выбор времени и есть действие, поэтому заливки при живых окнах тоже нет.
   */
  function buildTrainer(input, now) {
    var t = obj(input.trainer);
    var name = str(t.name);
    if (!name) return null;
    var dm = contact(t.username, t.telegramId);
    var canBook = t.canBook !== false;
    var pick = canBook ? buildPick(input.slots, 'Когда вам удобно', 'Все окна →', 'all-slots', now) : null;
    var fn = firstName(name);
    var forms = declined(input);
    var trainerId = idOrNull(t.id);

    var view = emptyView(pick ? 'accent' : '', 'Ваш тренер');
    view.who = buildWho(name, t.photo, joinDot([t.arena_name, t.city_name]), trainerId, {
      hero: true,
      dm: pick ? dm : null,
    });
    view.trainerId = trainerId;
    view.pick = pick;
    if (pick) {
      view.actions.push({ style: 'ghost', label: allSlotsLabel(forms), action: 'all-slots', trainerId: trainerId });
      return view;
    }
    // Окон нет — честный короткий ответ на «а когда?» вместо пустого места.
    if (dm) {
      view.line = 'Свободных окон в расписании нет. ' + (fn || 'Тренер') +
        ' ставит время сам — напишите, и он предложит ближайшее.';
      view.actions.push({ style: 'fill', label: writeLabel(forms), action: 'dm', dm: dm });
    } else {
      // Ни окон, ни контакта: предложить нечего, и врать об этом нельзя.
      view.line = 'Свободных окон в расписании нет, и способа написать тренеру у нас тоже нет.';
    }
    view.actions.push({ style: 'ghost', label: 'Все тренеры', action: 'all-trainers' });
    return view;
  }

  /**
   * Возврат. Самый сильный аргумент вернуться — не сгоревший остаток, поэтому
   * заливка существует только при остатке или при истории занятий. Срок назван
   * один раз — в кошельке; статус и строка его не повторяют.
   */
  function buildDormant(input, now, wallet) {
    var t = obj(input.trainer);
    var name = str(t.name);
    var hist = obj(input.history);
    var done = posInt(hist.completed_count);
    var passFirst = wallet.length && wallet[0].key === 'pass' ? wallet[0] : null;
    if (!wallet.length && !done) return null;

    var statusLabel;
    if (passFirst) statusLabel = 'У вас остался абонемент';
    else if (wallet.length) statusLabel = 'У вас остался сертификат';
    else statusLabel = 'Вы тренировались ' + done + ' ' + pluralRu(done, 'раз', 'раза', 'раз');

    var view = emptyView(wallet.length && wallet[0].warn ? 'warn' : '', statusLabel);
    var last = isoDay(hist.last_completed_at);
    view.who = buildWho(name, t.photo, last ? 'последнее занятие — ' + shortDate(last, now) : '', idOrNull(t.id), {
      hero: true,
      // Не место, а дата: иконка-пин здесь соврала бы о смысле строки.
      placeIcon: false,
    });
    view.trainerId = idOrNull(t.id);
    view.pick = buildPick(input.slots, 'Ближайшие окна', 'Все окна →', 'all-slots', now);
    if (view.pick) {
      view.actions.push({ style: 'ghost', label: allSlotsLabel(declined(input)), action: 'all-slots', trainerId: view.trainerId });
    } else {
      view.actions.push({ style: 'ghost', label: 'Найти тренера', action: 'all-trainers' });
    }
    return view;
  }

  /**
   * Личного ещё нет — карточку заполняет лёд города. Крупное время здесь
   * законно: сеанс площадки — факт мира, как сеанс в кино, а не чьё-то
   * обязательство. Спутать его с моей записью нечем: кикер «На льду сегодня»,
   * в строке who арена, а не человек, и штампа «подтверждена» нет.
   */
  function buildCityIce(input, now) {
    var a = obj(input.arena);
    var name = str(a.name);
    var time = hhmm(a.start_time);
    if (!name && !time) return null;
    var city = str(a.city_name);

    var view = emptyView('', joinDot(['На льду сегодня', city]));
    if (time) view.when = { time: time, meta: joinDot([a.kind_label, a.price_label]) };
    view.who = buildWho(name, '', str(a.address) || city, null, { initials: '❄' });
    view.pick = buildPick(input.slots, 'Дальше на льду', 'Все сеансы →', 'all-sessions', now);
    /*
     * Полный список сеансов — ОДИН вход, и он уже последним элементом полосы
     * чипов. Отдельная кнопка под ней дублировала и надпись, и адрес: два
     * контрола «Все сеансы» в двадцати пикселях друг от друга. Серая кнопка
     * остаётся только там, где чипов нет вовсе, — иначе выхода не будет.
     */
    if (!view.pick) {
      view.actions.push({ style: 'ghost', label: 'Все сеансы', action: 'all-sessions', arenaId: idOrNull(a.id) });
    }
    return view;
  }

  /**
   * Города нет. Список городов — первым классом: тап по «Минск» быстрее и
   * надёжнее, чем диалог разрешения плюс GPS-фикс, и не жжёт единственный
   * выстрел системного запроса. Геолокация остаётся тихой строкой.
   */
  function buildCityPick(input) {
    var all = [];
    (Array.isArray(input.cities) ? input.cities : []).forEach(function (raw) {
      var c = obj(raw);
      var nm = str(c.name);
      if (nm) all.push({ id: idOrNull(c.id), name: nm });
    });
    if (!all.length) return null;
    // DEC-008: кнопок ровно шесть максимум. Город, не попавший в сетку, обязан
    // быть достижим — поэтому при переполнении шестая кнопка это «Другой город»,
    // а не молча отрезанный хвост списка.
    var overflow = all.length > MAX_CITY_BUTTONS;
    var list = overflow ? all.slice(0, MAX_CITY_BUTTONS - 1) : all;

    var view = emptyView('accent', 'С чего начнём');
    view.head = 'Где вы катаетесь?';
    view.line = 'Покажем лёд, тренеров и магазины вашего города. Сменить можно в любой момент.';
    view.cities = list;
    view.moreCities = overflow;
    view.geo = true;
    view.foot = { label: 'Показать всю Беларусь', action: 'all-country' };
    return view;
  }

  /**
   * Мы не в вашем городе. Два действия — не дубль, а развилка. Обещания
   * «напишем, когда появимся» здесь нет: такой рассылки не существует.
   */
  function buildFar(input) {
    var a = obj(input.arena);
    var name = str(a.name);
    var city = str(a.city_name);

    var view = emptyView('warn', 'Мы пока не в вашем городе');
    // Дистанция существует только когда геолокация отработала (distance_km в
    // ice-teaser). Пришла — она и есть ответ на «насколько далеко»; не пришла —
    // честно называем город, а километры не придумываем.
    var distance = distanceLabel(a.distance_km);
    var nearest = distance || city || name;
    view.head = nearest ? 'Ближайший лёд — ' + nearest : 'Где вы катаетесь?';
    view.line = (name ? '«' + name + '»' + (city ? ', ' + city : '') + '. ' : '') +
      'Выберите город, где катаетесь, — покажем, что в нём есть.';
    view.actions.push({ style: 'fill', label: 'Выбрать свой город', action: 'pick-city' });
    view.actions.push({ style: 'ghost', label: 'Смотреть всю Беларусь', action: 'all-country' });
    return view;
  }

  /* ─── Сборка ──────────────────────────────────────────────────────────── */

  /** Чьё лицо в карточке — тот и владелец показываемого остатка. */
  function cardTrainerId(kind, input) {
    if (kind === 'booking') return idOrNull(obj(input.booking).trainer_id);
    if (kind === 'trainer') return idOrNull(obj(input.trainer).id);
    if (kind === 'dormant') {
      return str(obj(input.trainer).name) ? idOrNull(obj(input.trainer).id) : null;
    }
    return null;
  }

  function buildView(input, now) {
    if (!input || typeof input !== 'object') return null;
    var kind = str(input.kind);
    if (KINDS.indexOf(kind) < 0) return null;
    var when = now instanceof Date && !isNaN(now.getTime()) ? now : null;
    var wallet = buildWallet(kind, cardTrainerId(kind, input), input, when);

    var view;
    if (kind === 'booking') view = buildBooking(input, when);
    else if (kind === 'trainer') view = buildTrainer(input, when);
    else if (kind === 'dormant') view = buildDormant(input, when, wallet);
    else if (kind === 'city-ice') view = buildCityIce(input, when);
    else if (kind === 'city-pick') view = buildCityPick(input);
    else view = buildFar(input);
    if (!view) return null;

    view.kind = kind;
    view.wallet = wallet;
    return view;
  }

  /* ─── Рендер ──────────────────────────────────────────────────────────── */

  function attr(name, value) {
    var v = str(value);
    return v === '' ? '' : ' ' + name + '="' + esc(v) + '"';
  }

  function dmAttrs(dm) {
    return attr('data-me-dm-un', dm.username) + attr('data-me-dm-tid', dm.telegramId);
  }

  function statusHtml(status) {
    var s = obj(status);
    var label = str(s.label);
    var pill = obj(s.pill);
    var pillHtml = str(pill.label)
      ? '<span class="pill pill--' + esc(pill.kind) + '"><i></i>' + esc(pill.label) + '</span>'
      : '';
    if (!label && !pillHtml) return '';
    return '<div class="me__status">' +
      (label ? '<span class="k">' + esc(label) + '</span>' : '') +
      pillHtml +
      '</div>';
  }

  /**
   * Крупное время — только у моей записи и у сеанса площадки; у тренера и
   * возврата его нет. Правило держит и рендер, не только модель.
   */
  function whenHtml(view) {
    if (BIG_TIME_KINDS.indexOf(view.kind) < 0 || !view.when) return '';
    var w = obj(view.when);
    if (!str(w.time)) return '';
    return '<div class="me__when"><b>' + esc(w.time) + '</b>' +
      (str(w.meta) ? '<span>' + esc(w.meta) + '</span>' : '') +
      '</div>';
  }

  function avatarHtml(who) {
    var cls = 'avatar' + (who.hero ? ' avatar--lg' : '');
    if (who.photo) {
      /*
       * Инициалы едут рядом с фото в data-: фото может не загрузиться (файла
       * нет, CDN отдал 404 в Telegram WebView), и тогда хабу надо чем-то
       * заменить картинку, не угадывая имя заново. Сам откат делает хаб —
       * модель чистая и в DOM не ходит.
       */
      return '<div class="' + cls + ' avatar--photo" data-me-initials="' + esc(who.initials) +
        '"><img src="' + esc(who.photo) + '" alt="" loading="eager" decoding="async"></div>';
    }
    return '<div class="' + cls + '" aria-hidden="true">' + esc(who.initials) + '</div>';
  }

  /**
   * Лицо карточки. Есть id — аватар и имя становятся кнопкой: тап открывает
   * карточку тренера, а не запись (как trainerWhoLinkHtml в сегодняшнем хабе).
   * Конверт — отдельная кнопка-сестра, а не вложенная: кнопка в кнопке
   * невалидна и в WebView ведёт себя непредсказуемо.
   */
  function whoHtml(who) {
    if (!who) return '';
    var place = who.place
      ? '<span>' + (who.placeIcon ? '⌖ ' : '') + esc(who.place) + '</span>'
      : '';
    var body = avatarHtml(who) + '<div class="me__who-t"><b>' + esc(who.name) + '</b>' + place + '</div>';
    var main = who.trainerId
      ? '<button type="button" class="me__who-link" data-me-action="open-trainer"' +
        attr('data-me-trainer-id', who.trainerId) +
        ' aria-label="Карточка тренера, ' + esc(who.name) + '">' + body + '</button>'
      : body;
    var dm = who.dm
      ? '<button type="button" class="me__dm" data-me-action="dm"' + dmAttrs(who.dm) + '>' +
        '<span class="me__dm-ic" aria-hidden="true">✉</span>' +
        '<span class="me__dm-label">Написать</span></button>'
      : '';
    return '<div class="me__who' + (who.hero ? ' me__who--hero' : '') + '">' + main + dm + '</div>';
  }

  function pickHtml(pick) {
    if (!pick) return '';
    var chips = '';
    pick.chips.forEach(function (c) {
      chips += '<button type="button" class="me__chip" data-me-action="book-slot"' +
        attr('data-me-slot-id', c.slotId) +
        attr('data-me-service-id', c.serviceId) +
        attr('data-me-arena-id', c.arenaId) + '>' +
        (c.day ? '<em>' + esc(c.day) + '</em>' : '') +
        '<b>' + esc(c.time) + '</b></button>';
    });
    return '<div class="me__pick">' +
      (pick.head ? '<div class="me__pick-h"><span class="k">' + esc(pick.head) + '</span></div>' : '') +
      '<div class="me__chips">' + chips +
      '<button type="button" class="me__chip me__chip--all" data-me-action="' + esc(pick.allAction) + '">' +
      esc(pick.allLabel) + '</button>' +
      '</div></div>';
  }

  function citiesHtml(cities, more) {
    if (!cities || !cities.length) return '';
    var html = '';
    cities.forEach(function (c) {
      html += '<button type="button" class="me__city" data-me-action="pick-city"' +
        attr('data-me-city-id', c.id) + '>' + esc(c.name) + '</button>';
    });
    if (more) {
      html += '<button type="button" class="me__city" data-me-action="more-cities">Другой город</button>';
    }
    return '<div class="me__cities">' + html + '</div>';
  }

  function geoHtml(on) {
    if (!on) return '';
    return '<button type="button" class="me__geo" data-me-action="geo">' +
      '<span aria-hidden="true">⌖</span>Определить по геопозиции</button>';
  }

  function actionsHtml(actions) {
    var html = '';
    (actions || []).forEach(function (a) {
      html += '<div class="me__do"><button type="button" class="' +
        (a.style === 'fill' ? 'btn-fill' : 'btn-ghost') + '" data-me-action="' + esc(a.action) + '"' +
        (a.dm ? dmAttrs(a.dm) : '') +
        attr('data-me-trainer-id', a.trainerId) +
        attr('data-me-arena-id', a.arenaId) + '>' +
        esc(a.label) + '</button></div>';
    });
    return html;
  }

  /** Нет ни одной ячейки — нет и всей полосы (а не пустая рамка). */
  function walletHtml(cells) {
    if (!cells || !cells.length) return '';
    var html = '';
    cells.forEach(function (c) {
      html += '<button type="button" class="me__w' + (c.warn ? ' me__w--warn' : '') + '"' +
        ' data-me-action="' + esc(c.action) + '">' +
        '<span class="me__w-k">' + esc(c.label) + '</span>' +
        '<span class="me__w-v">' + esc(c.value) + (c.unit ? '<i>' + esc(c.unit) + '</i>' : '') + '</span>' +
        (c.sub ? '<span class="me__w-s">' + esc(c.sub) + '</span>' : '') +
        (c.bar != null ? '<span class="me__w-bar"><i style="width:' + Number(c.bar) + '%"></i></span>' : '') +
        '</button>';
    });
    return '<div class="me__wallet">' + html + '</div>';
  }

  function footHtml(foot) {
    if (!foot) return '';
    return '<button type="button" class="me__foot" data-me-action="' + esc(foot.action) + '">' +
      '<span>' + esc(foot.label) + '</span><span aria-hidden="true">›</span></button>';
  }

  /**
   * Разметка карточки. Корень `me` намеренно без onclick / role / tabindex:
   * «вся карточка кликабельна» означало бы, что тап куда попало делает что-то
   * непредсказуемое. Кликабельны только вложенные button.
   */
  function renderHtml(view) {
    if (!view || typeof view !== 'object') return '';
    var pad =
      statusHtml(view.status) +
      whenHtml(view) +
      (str(view.head) ? '<div class="me__head">' + esc(view.head) + '</div>' : '') +
      whoHtml(view.who) +
      (str(view.line) ? '<div class="me__line">' + esc(view.line) + '</div>' : '') +
      pickHtml(view.pick) +
      citiesHtml(view.cities, view.moreCities) +
      geoHtml(view.geo) +
      actionsHtml(view.actions);
    return '<div class="me' + (str(view.mod) ? ' me--' + esc(view.mod) : '') + '"' +
      attr('data-me-kind', view.kind) + '>' +
      '<div class="me__pad">' + pad + '</div>' +
      walletHtml(view.wallet) +
      footHtml(view.foot) +
      '</div>';
  }

  return {
    buildView: buildView,
    renderHtml: renderHtml,
  };
});
