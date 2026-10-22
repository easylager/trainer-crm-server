/**
 * «Первые три ученика» (TASK-310) — чистая логика без DOM: разбор вставленного списка и
 * состояние мест на карточке. Отдельно от trainer-first-students.js, чтобы тестироваться в node.
 */
(function (global) {
  'use strict';

  var GOAL = 3;
  var MAX_PASTE_ROWS = 30;

  /* Телефон в строке: «+375 29 111-22-33», «8 029 1112233», «29 111 22 33». Достаём цифры
     и решаем по длине; нормализует сервер, здесь — только отделить номер от имени. */
  var PHONE_RE = /(\+?\d[\d\s().-]{6,}\d)/;

  /* В заметке рядом с именем часто стоит время занятия: «Лиза пн 19:00». Это не часть имени —
     время тренер выберет из своих окон. */
  var TIME_RE = /(^|\s)\d{1,2}[:.]\d{2}(?=\s|$)/g;
  var WEEKDAY_RE = /(^|\s)(пн|вт|ср|чт|пт|сб|вс)\.?(?=\s|$)/gi;

  function cleanName(raw) {
    return String(raw || '')
      .replace(TIME_RE, ' ')
      .replace(WEEKDAY_RE, ' ')
      .replace(/(^|\s)\d+(?=\s|$)/g, ' ')
      .replace(/[,;:—–|•·\t]+/g, ' ')
      .replace(/\s+/g, ' ')
      .replace(/^[\s\d.)-]+(?=\D)/, '')
      .trim();
  }

  /** Одна строка заметки → {first_name, last_name, phone} или null, если имени нет. */
  function parseStudentLine(line) {
    var text = String(line || '').trim();
    if (!text) return null;
    var phone = '';
    var m = PHONE_RE.exec(text);
    if (m) {
      var digits = m[1].replace(/\D/g, '');
      if (digits.length >= 9) {
        phone = m[1].replace(/[^\d+]/g, '');
        text = (text.slice(0, m.index) + ' ' + text.slice(m.index + m[1].length));
      }
    }
    var name = cleanName(text);
    if (!name || !/[A-Za-zА-Яа-яЁёІіЎў]/.test(name)) return null;
    var parts = name.split(' ');
    var first = parts.shift().slice(0, 64);
    var last = parts.join(' ').slice(0, 64);
    return { first_name: first, last_name: last, phone: phone };
  }

  /** Вставленный текст → строки учеников; дубли по имени+номеру схлопываются. */
  function parseStudentList(text) {
    var seen = {};
    var out = [];
    String(text || '')
      .split(/\r?\n/)
      .forEach(function (line) {
        if (out.length >= MAX_PASTE_ROWS) return;
        var row = parseStudentLine(line);
        if (!row) return;
        var key = (row.first_name + ' ' + row.last_name).toLowerCase() + '|' + row.phone;
        if (seen[key]) return;
        seen[key] = true;
        out.push(row);
      });
    return out;
  }

  /** Места карточки: сначала уже перенесённые ученики, затем пустые до цели. */
  function seats(state) {
    var goal = (state && state.goal) || GOAL;
    var students = (state && state.students) || [];
    var out = students.slice(0, goal).map(function (s) {
      return { filled: true, initials: s.initials || '?', name: s.name || '' };
    });
    while (out.length < goal) out.push({ filled: false });
    return out;
  }

  function remaining(state) {
    var goal = (state && state.goal) || GOAL;
    var count = (state && state.count) || 0;
    return Math.max(0, goal - count);
  }

  /**
   * Заголовок листа. Было «Ученик 1 из 3» — тренер читал это как лимит на трёх учеников
   * (TASK-313). Три места на карточке — только начало, поэтому без счёта.
   */
  function sheetTitle() {
    return 'Новый ученик';
  }

  function addButtonLabel(state) {
    var count = (state && state.count) || 0;
    return count <= 0 ? 'Добавить ученика' : 'Добавить ещё';
  }

  /** Метка карточки после первого ученика: сколько уже, а не сколько «осталось». */
  function addedKicker(state) {
    var n = (state && state.count) || 0;
    return 'Уже ' + n + ' ' + plural(n, 'ученик', 'ученика', 'учеников');
  }

  function plural(n, one, few, many) {
    var m10 = n % 10;
    var m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }

  /** Шапка финальной карточки: «на неделе» — только если на неделю записаны все. */
  function doneKicker(state) {
    var students = (state && state.students) || [];
    var n = Math.max((state && state.count) || 0, students.length);
    var allBooked = students.length > 0 && students.length === n && students.every(function (s) { return !!s.next_label; });
    var word = plural(n, 'ученик', 'ученика', 'учеников');
    return allBooked ? n + ' ' + word + ' на неделе' : n + ' ' + word + ' в приложении';
  }

  /** Текст личной ссылки ученику. Обещаем только то, что уже есть: запись — если она стоит. */
  function inviteMessage(student) {
    if (student && student.next_label) {
      return 'Ваша ближайшая тренировка — ' + student.next_label +
        '. Откройте ссылку: бот напомнит о ней и покажет все ваши занятия.';
    }
    return 'Теперь веду расписание в Glide. Откройте ссылку: здесь будут ваши тренировки, а бот напомнит о каждой.';
  }

  /** Подводка карточки: что тренер получит. Утренняя сводка — правда для каждого с записью. */
  function cardLead(state) {
    if (state && state.can_book === false) {
      return 'Впишите имя — ученик появится в вашей базе. Записывать на время можно с активной подпиской.';
    }
    return 'Впишите имя и выберите время — тренировка появится в расписании, а утром придёт сводка дня. Ученику ничего устанавливать не нужно.';
  }

  function slotFieldLabel(state) {
    if (state && state.can_book === false) return 'Записать на время можно с активной подпиской — пока добавим в список';
    if (!((state && state.options) || []).length) return 'Свободных окон на две недели нет — добавим без записи';
    return 'Ближайшая тренировка — из вашей недели';
  }

  /** «Что теперь работает» — только то, что включено у этого тренера прямо сейчас. */
  function doneWorks(state) {
    var students = (state && state.students) || [];
    var out = [];
    if (students.some(function (s) { return !!s.next_label; })) out.push('Утром пришлём, кто сегодня придёт');
    out.push('Абонемент и оплату отметите в карточке ученика — остаток посчитаем сами');
    out.push('В воскресенье — итог недели и план на следующую');
    return out;
  }

  /** Ошибка сервера человеческими словами: 422 приходит списком полей, а не строкой. */
  function errorText(err) {
    var d = err && err.detail;
    if (Array.isArray(d) && d.length) {
      var first = d[0] || {};
      var loc = first.loc || [];
      var field = loc.length ? loc[loc.length - 1] : '';
      var msg = String(first.msg || '').replace(/^Value error,\s*/i, '');
      if (field === 'phone') return msg || 'Проверьте номер телефона, например +375 29 123-45-67.';
      if (field === 'first_name') return 'Впишите имя ученика.';
      return msg || 'Проверьте поля и попробуйте ещё раз.';
    }
    var text = (err && err.message) || '';
    if (!text || /^(Unprocessable Entity|Internal Server Error|Bad Request|Ошибка)$/i.test(text)) {
      return 'Не получилось сохранить. Попробуйте ещё раз.';
    }
    return text;
  }

  /** Услуга для окна: своя у окна, если шаблон её знает, иначе первая в списке (очные первыми). */
  function defaultServiceId(state, slotId) {
    var services = (state && state.services) || [];
    if (!services.length) return null;
    var opt = ((state && state.options) || []).filter(function (o) { return o.slot_id === slotId; })[0];
    var own = opt && opt.service_id;
    if (own != null && services.some(function (s) { return s.service_id === own; })) return own;
    return services[0].service_id;
  }

  var api = {
    defaultServiceId: defaultServiceId,
    cardLead: cardLead,
    slotFieldLabel: slotFieldLabel,
    doneWorks: doneWorks,
    errorText: errorText,
    plural: plural,
    doneKicker: doneKicker,
    inviteMessage: inviteMessage,
    GOAL: GOAL,
    parseStudentLine: parseStudentLine,
    parseStudentList: parseStudentList,
    seats: seats,
    remaining: remaining,
    sheetTitle: sheetTitle,
    addedKicker: addedKicker,
    addButtonLabel: addButtonLabel,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.TrainerFirstStudentsModel = api;
})(typeof window !== 'undefined' ? window : globalThis);
