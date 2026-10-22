/**
 * Неделя онбординга (TASK-312) — чистая логика без DOM: окна «утро / день / вечер», точные
 * старты внутри окна, наложения. Отдельно от trainer-onboarding-main.js, чтобы тестироваться в node.
 *
 * День — карта «минута старта → { a: id площадки | null, d: длительность | null }». d = null —
 * длительность по умолчанию (своя у площадки с фиксированной длительностью, иначе общая тренера);
 * так сохраняет и сервер. Окно — только способ выбрать: хранятся и уходят на сервер точные старты.
 */
(function (global) {
  'use strict';

  var WINDOWS = [
    { id: 'mor', label: 'Утро', from: 6, to: 12 },
    { id: 'day', label: 'День', from: 12, to: 17 },
    { id: 'eve', label: 'Вечер', from: 17, to: 23 },
  ];
  var DAY_SHORT = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];

  function windowById(id) {
    for (var i = 0; i < WINDOWS.length; i++) if (WINDOWS[i].id === id) return WINDOWS[i];
    return null;
  }

  /** Окно, в которое попадает старт; ранние (до 6:00) — в утро, поздние — в вечер. */
  function windowOf(minute) {
    var h = Math.floor(minute / 60);
    if (h < WINDOWS[1].from) return WINDOWS[0];
    if (h < WINDOWS[2].from) return WINDOWS[1];
    return WINDOWS[2];
  }

  function arenaOffset(arena) {
    return (arena && arena.grid_kind === 'hourly_minute') ? (arena.minute_offset || 0) : 0;
  }

  function effectiveDuration(arena, defaultDuration) {
    return (arena && arena.fixed_duration_minutes) || defaultDuration;
  }

  /**
   * Старты, которые окно предлагает для площадки, — строго по той же сетке, что проверяет сервер
   * (allowed_start_minutes_from_preset):
   *   - hourly_minute («Замок»): только ЧЧ:смещение в часах площадки; длинное занятие берёт
   *     следующий свободный час (45 мин → 10:15, 11:15; 90 мин → 10:15, 12:15);
   *   - quarter_15 и без площадки: кратно 15 минутам, шагом в длину занятия от начала окна или
   *     открытия площадки, последний старт — не позже hour_end:00.
   * Занятие целиком помещается в окно — соседние окна не пересекаются.
   */
  function windowStarts(win, arena, duration) {
    var dur = Math.max(15, duration | 0);
    var h0 = arena && arena.hour_start != null ? arena.hour_start : 0;
    var h1 = arena && arena.hour_end != null ? arena.hour_end : 23;
    var out = [];
    if (arena && arena.grid_kind === 'hourly_minute') {
      var off = arenaOffset(arena);
      var bound = win.to * 60 + off;
      var last = null;
      for (var h = Math.max(h0, win.from); h <= h1; h++) {
        var c = h * 60 + off;
        if (windowOf(c) !== win || c + dur > bound) continue;
        if (last != null && c < last + dur) continue;
        out.push(c);
        last = c;
      }
      return out;
    }
    var step = Math.ceil(dur / 15) * 15;
    var begin = Math.max(win.from * 60, h0 * 60);
    begin = Math.ceil(begin / 15) * 15;
    for (var s = begin; s + dur <= win.to * 60 && s <= h1 * 60; s += step) out.push(s);
    return out;
  }

  function slotDuration(slot, arenaById, defaultDuration) {
    if (slot && slot.d) return slot.d;
    var arena = slot && slot.a != null ? arenaById(slot.a) : null;
    return effectiveDuration(arena, defaultDuration);
  }

  /** Первый уже отмеченный старт дня, с которым пересечётся [start, start + duration). */
  function overlapWith(day, start, duration, arenaById, defaultDuration) {
    var keys = Object.keys(day || {});
    for (var i = 0; i < keys.length; i++) {
      var m = +keys[i];
      if (m === start) continue;
      var d = slotDuration(day[m], arenaById, defaultDuration);
      if (m < start + duration && start < m + d) return m;
    }
    return null;
  }

  function startsInWindow(day, win) {
    return Object.keys(day || {})
      .map(Number)
      .filter(function (m) { return windowOf(m) === win; })
      .sort(function (a, b) { return a - b; });
  }

  /** Отметить окно целиком: все предложенные старты площадки, что ни с чем не пересекаются. */
  function fillWindow(day, win, arena, defaultDuration, arenaById) {
    var dur = effectiveDuration(arena, defaultDuration);
    var aid = arena ? arena.id : null;
    windowStarts(win, arena, dur).forEach(function (s) {
      if (day[s]) return;
      if (overlapWith(day, s, dur, arenaById, defaultDuration) != null) return;
      day[s] = { a: aid, d: null };
    });
    return day;
  }

  /** Снять окно: только старты этой площадки (onlyArenaId) или все, если площадка не задана. */
  function clearWindow(day, win, onlyArenaId) {
    startsInWindow(day, win).forEach(function (m) {
      if (onlyArenaId === undefined || day[m].a === onlyArenaId) delete day[m];
    });
    return day;
  }

  /**
   * Тап по старту: снять отмеченный своей площадкой, отметить свободный. Чужой и
   * пересекающийся — нельзя: тренер не может быть в одно время в двух местах.
   * Возвращает 'added' | 'removed' | 'blocked'.
   */
  function toggleStart(day, start, arena, defaultDuration, arenaById) {
    var aid = arena ? arena.id : null;
    var cur = day[start];
    if (cur) {
      if (cur.a !== aid) return 'blocked';
      delete day[start];
      return 'removed';
    }
    var dur = effectiveDuration(arena, defaultDuration);
    if (overlapWith(day, start, dur, arenaById, defaultDuration) != null) return 'blocked';
    day[start] = { a: aid, d: null };
    return 'added';
  }

  function minuteLabel(minute) {
    var h = Math.floor(minute / 60);
    var m = minute % 60;
    return h + ':' + (m < 10 ? '0' + m : String(m));
  }

  /** «пн, ср, пт — 18:00 · 19:00»: дни с одинаковым набором стартов — одной строкой. */
  function weekSummary(week) {
    var groups = [];
    for (var dow = 0; dow < 7; dow++) {
      var starts = Object.keys(week[dow] || {}).map(Number).sort(function (a, b) { return a - b; });
      if (!starts.length) continue;
      var sig = starts.join(',');
      var g = null;
      for (var i = 0; i < groups.length; i++) if (groups[i].sig === sig) g = groups[i];
      if (g) g.days.push(DAY_SHORT[dow]);
      else groups.push({ sig: sig, days: [DAY_SHORT[dow]], starts: starts });
    }
    return groups.map(function (gr) {
      return { days: gr.days.join(', '), times: gr.starts.map(minuteLabel).join(' · ') };
    });
  }

  /** Первые старты недели — по одному на день, для превью «как увидит ученик». */
  function previewStarts(week, limit) {
    var out = [];
    for (var dow = 0; dow < 7 && out.length < limit; dow++) {
      var starts = Object.keys(week[dow] || {}).map(Number).sort(function (a, b) { return a - b; });
      if (starts.length) out.push({ day: DAY_SHORT[dow], time: minuteLabel(starts[0]) });
    }
    return out;
  }

  function totalStarts(week) {
    var n = 0;
    for (var dow = 0; dow < 7; dow++) n += Object.keys(week[dow] || {}).length;
    return n;
  }

  var api = {
    WINDOWS: WINDOWS,
    DAY_SHORT: DAY_SHORT,
    windowById: windowById,
    windowOf: windowOf,
    arenaOffset: arenaOffset,
    effectiveDuration: effectiveDuration,
    windowStarts: windowStarts,
    slotDuration: slotDuration,
    overlapWith: overlapWith,
    startsInWindow: startsInWindow,
    fillWindow: fillWindow,
    clearWindow: clearWindow,
    toggleStart: toggleStart,
    minuteLabel: minuteLabel,
    weekSummary: weekSummary,
    previewStarts: previewStarts,
    totalStarts: totalStarts,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.TrainerOnboardingWeekModel = api;
})(typeof window !== 'undefined' ? window : globalThis);
