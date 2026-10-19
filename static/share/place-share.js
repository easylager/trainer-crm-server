/**
 * TASK-252: выбор сеанса на /p/… и GlideShareSheet как в Mini App.
 */
(function () {
  'use strict';

  var boot = window.__PLACE_SHARE__;
  if (!boot || !boot.ref) return;

  var root = document.documentElement;
  root.classList.add('js');

  var M = window.ArenaCardModel;
  var PD = window.PublicDisplayModel;
  var MT = window.MinskTime;
  if (!M || !PD || !MT || !window.GlideShareSheet) return;

  var pickId = boot.sessionId != null ? String(boot.sessionId) : null;
  var invite = !!boot.invite;

  function queryHasSession() {
    try {
      return new URL(location.href).searchParams.has('s');
    } catch (e) {
      return false;
    }
  }

  /* Прокрутка окна — только если сеанс пришёл в адресе (?s=) или после тапа. */
  var openedOnSession = queryHasSession();

  function todayIso() {
    return boot.today || MT.todayIsoInTz(boot.timezone || 'Europe/Minsk');
  }

  function combinedDays() {
    return M.combineSessionDayLists(boot.days || [], boot.ohmDays || []);
  }

  function scheduleSlots() {
    return M.shareSlots(combinedDays(), todayIso(), 0);
  }

  function sessionExists(id) {
    if (id == null) return false;
    var sid = String(id);
    return scheduleSlots().some(function (s) {
      return String(s.id) === sid;
    });
  }

  function resolvedSessionId() {
    if (pickId && sessionExists(pickId)) return pickId;
    var slots = scheduleSlots();
    return slots.length ? String(slots[0].id) : null;
  }

  var PLAN_WD_FULL = [
    'Понедельник',
    'Вторник',
    'Среда',
    'Четверг',
    'Пятница',
    'Суббота',
    'Воскресенье',
  ];
  var PLAN_MONTHS_GEN = [
    'января',
    'февраля',
    'марта',
    'апреля',
    'мая',
    'июня',
    'июля',
    'августа',
    'сентября',
    'октября',
    'ноября',
    'декабря',
  ];

  function weekdayMon0FromIso(iso) {
    var sun = MT.weekdaySun0FromIso(iso);
    return sun === 0 ? 6 : sun - 1;
  }

  function findSession(sessionId) {
    var sid = String(sessionId);
    var days = combinedDays();
    for (var i = 0; i < days.length; i++) {
      var sessions = days[i].sessions || [];
      for (var j = 0; j < sessions.length; j++) {
        if (sessions[j] && String(sessions[j].id) === sid) return sessions[j];
      }
    }
    return null;
  }

  function planDayHeading(localDate) {
    var day = String(localDate || '').slice(0, 10);
    var today = todayIso();
    if (!day) return '';
    var wd = PLAN_WD_FULL[weekdayMon0FromIso(day)];
    if (day === today) return 'Сегодня, ' + wd.toLowerCase();
    if (day === MT.addDaysIso(today, 1)) return 'Завтра, ' + wd.toLowerCase();
    var bits = day.split('-');
    return wd + ', ' + Number(bits[2]) + ' ' + PLAN_MONTHS_GEN[Number(bits[1]) - 1];
  }

  function planPriceLine(session) {
    session = session || {};
    var cur = session.currency_code || 'BYN';
    var lines = [];
    var adult = session.price_adult_minor != null ? session.price_adult_minor : session.price_minor;
    if (adult != null) lines.push('Взрослый — ' + PD.formatPriceMinor(adult, cur));
    if (session.price_child_minor != null) {
      lines.push('Детский — ' + PD.formatPriceMinor(session.price_child_minor, cur));
    }
    if (session.price_rental_minor != null) {
      lines.push('Прокат коньков — ' + PD.formatPriceMinor(session.price_rental_minor, cur));
    }
    var note = String(session.price_note || '').trim();
    if (note) lines.push(note);
    return lines.join(' · ');
  }

  /* Зал («Большая арена») не говорит, что это ОХМ: тип впереди, как на сервере. */
  function planKindLabel(session) {
    var label = M.iceKindLabel ? M.iceKindLabel(session) : '';
    if (session.kind === 'hockey_practice' && session.session_label) {
      var ohm = M.iceKindLabel(Object.assign({}, session, { session_label: '' }));
      if (label.toLowerCase().indexOf(ohm.toLowerCase()) === -1) return ohm + ' · ' + label;
    }
    return label;
  }

  function pluralRu(n, one, few, many) {
    var m10 = n % 10;
    var m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }

  /* «Начнётся через 40 минут» — те же правила, что starts_in_label на сервере. */
  function planSoonLine(session) {
    var starts = Date.parse(String(session.starts_at_utc || ''));
    if (isNaN(starts)) return '';
    var minutes = Math.floor((starts - Date.now()) / 60000);
    if (minutes <= 0 || minutes > 180) return '';
    if (minutes < 60) return 'Начнётся через ' + minutes + ' ' + pluralRu(minutes, 'минуту', 'минуты', 'минут');
    var hours = Math.floor(minutes / 60);
    var rest = minutes % 60;
    if (rest < 10) return 'Начнётся через ' + hours + ' ' + pluralRu(hours, 'час', 'часа', 'часов');
    return 'Начнётся через ' + hours + ' ч ' + rest + ' мин';
  }

  function setPlanText(plan, cls, text) {
    var el = plan.querySelector('.b-plan__' + cls);
    if (!el) return;
    el.textContent = text || '';
    el.hidden = !text;
  }

  function paintPlan(sessionId) {
    var section = document.getElementById('plan');
    var plan = section && section.querySelector('.b-plan');
    if (!plan || plan.classList.contains('b-plan--gone')) return;
    var session = findSession(sessionId);
    if (!session) return;
    var start = PD.formatClock(String(session.starts_at_local || '').slice(0, 5));
    var end = PD.formatClock(String(session.ends_at_local || '').slice(0, 5));
    setPlanText(plan, 'day', planDayHeading(session.local_date));
    setPlanText(plan, 'time', end ? start + '–' + end : start);
    setPlanText(plan, 'line', [planKindLabel(session), planPriceLine(session)].filter(Boolean).join(' · '));
    setPlanText(plan, 'soon', planSoonLine(session));
    paintPlanLoad(plan, session.typical_load_level, seatsPlanLine(session.capacity_note));
  }

  /* Слово к черточкам на квадрате: здесь человек и узнаёт, что они значат. Тексты — как в
     src/application/session_load.py LOAD_PLAN_LINES. */
  var LOAD_LINES = {
    calm: 'Обычно свободно — можно без спешки',
    medium: 'Обычно народу в меру',
    busy: 'Обычно людно — билет лучше взять заранее',
  };

  /* Живой остаток кассы («70 мест» / «нет мест») — как live_seats_plan_line на сервере. */
  function seatsPlanLine(note) {
    var text = String(note || '').trim();
    if (/^нет мест$/i.test(text)) return 'Мест не осталось';
    var m = /^(\d+)\s+мест[а-я]*$/i.exec(text);
    if (!m) return '';
    var n = Number(m[1]);
    var word = n % 10 === 1 && n % 100 !== 11 ? 'место'
      : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'места' : 'мест';
    return 'Осталось ' + n + ' ' + word + (n <= 30 ? ' — лучше взять сейчас' : '');
  }

  function paintPlanLoad(plan, level, seatsLine) {
    var row = plan.querySelector('.b-plan__load');
    if (!row) return;
    var text = seatsLine || LOAD_LINES[level] || '';
    row.hidden = !text;
    if (!text) return;
    var word = row.querySelector(':scope > span:not(.b-load)');
    if (seatsLine) {
      var old = row.querySelector('.b-load');
      if (old) old.remove();
      if (word) word.textContent = text;
      return;
    }
    var meter = row.querySelector('.b-load');
    if (!meter) {
      meter = document.createElement('span');
      meter.className = 'b-load';
      meter.setAttribute('role', 'img');
      meter.innerHTML = '<i></i><i></i><i></i>';
      row.insertBefore(meter, row.firstChild);
    }
    meter.setAttribute('data-level', level);
    meter.setAttribute('aria-label', text);
    var word = row.querySelector(':scope > span:not(.b-load)');
    if (word) word.textContent = text;
  }

  /* Тап на время показывает скрытый билет «Выбранный сеанс» над расписанием. Он
     толкает всё ниже — докручиваем окно на ту же величину, чтобы тапнутое время
     осталось под пальцем. */
  function showPlan(anchorEl) {
    var section = document.getElementById('plan');
    if (!section || !section.hidden) return;
    var before = anchorEl ? anchorEl.getBoundingClientRect().top : null;
    section.hidden = false;
    if (before != null) window.scrollBy(0, anchorEl.getBoundingClientRect().top - before);
  }

  function inviteLabel(sessionId) {
    if (!sessionId || !PD.inviteCtaWhen) return 'Позвать с собой';
    var sid = String(sessionId);
    var slots = scheduleSlots();
    var slot = null;
    for (var i = 0; i < slots.length; i++) {
      if (String(slots[i].id) === sid) {
        slot = slots[i];
        break;
      }
    }
    if (!slot) return 'Позвать с собой';
    var when = PD.inviteCtaWhen(slot.localDate, slot.time, todayIso());
    return when ? 'Позвать на ' + when : 'Позвать с собой';
  }

  function sharePayload() {
    var days = combinedDays();
    var today = todayIso();
    return {
      slots: M.shareSlots(days, today, 0),
      slotSections: M.shareSlotsGrouped(days, today),
    };
  }

  function syncUrl(sessionId) {
    if (!sessionId || !boot.basePath) return;
    try {
      var u = new URL(boot.basePath, location.origin);
      u.searchParams.set('s', String(sessionId));
      if (invite) u.searchParams.set('i', '1');
      else u.searchParams.delete('i');
      history.replaceState(null, '', u.pathname + u.search + u.hash);
    } catch (e) {
      /* */
    }
  }

  function applyPick(sessionId, opts) {
    var sid = sessionId != null ? String(sessionId) : null;
    if (!sid || !sessionExists(sid)) return;
    pickId = sid;
    document.querySelectorAll('.b-ticket[data-session-id]').forEach(function (el) {
      var on = el.getAttribute('data-session-id') === sid;
      el.classList.toggle('b-ticket--picked', on);
      var fb = el.nextElementSibling;
      if (fb && fb.classList.contains('place-share-fallback')) {
        fb.hidden = !on;
      }
    });
    var btn = document.getElementById('placeShareBtn');
    if (btn) btn.textContent = inviteLabel(sid);
    paintPlan(sid);
    if (opts && opts.showPlan) showPlan(opts.anchor);
    if (!opts || !opts.skipUrl) syncUrl(sid);
    if (opts && opts.reveal) revealAboveDock();
  }

  function dockClearanceTop() {
    var dock = document.getElementById('placeShareDock');
    if (!dock) return window.innerHeight;
    return dock.getBoundingClientRect().top - 8;
  }

  /* Полос дней две — массовое катание и ОХМ: каждая докручивает свой текущий день. */
  function alignCurrentDay() {
    document.querySelectorAll('.b-sched').forEach(function (strip) {
      var day = strip.querySelector(':scope > .b-day:target') || strip.querySelector(':scope > .b-day--current');
      if (!day || !day.getBoundingClientRect) return;
      var dayRect = day.getBoundingClientRect();
      var stripRect = strip.getBoundingClientRect();
      if (dayRect.left < stripRect.left) strip.scrollLeft -= stripRect.left - dayRect.left;
      else if (dayRect.right > stripRect.right) strip.scrollLeft += dayRect.right - stripRect.right;
    });
  }

  function revealAboveDock() {
    var ticket = document.querySelector('.b-ticket--picked');
    if (!ticket) return;
    var nodes = [ticket];
    var run = function () {
      var limit = dockClearanceTop();
      var maxBottom = 0;
      var minTop = Infinity;
      for (var i = 0; i < nodes.length; i++) {
        var r = nodes[i].getBoundingClientRect();
        if (r.bottom > maxBottom) maxBottom = r.bottom;
        if (r.top < minTop) minTop = r.top;
      }
      if (maxBottom > limit) window.scrollBy(0, maxBottom - limit);
      if (minTop < 0) window.scrollBy(0, minTop);
    };
    run();
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(function () {
        requestAnimationFrame(run);
      });
    }
  }

  function openShare() {
    var sid = resolvedSessionId();
    if (!sid) return;
    var payload = sharePayload();
    var loadSlots =
      payload.slots.length <= 1
        ? function () {
            var today = todayIso();
            var to = MT.addDaysIso(today, 13);
            return fetch(
              '/api/public/arenas/' +
                encodeURIComponent(String(boot.ref)) +
                '/sessions?from=' +
                encodeURIComponent(today) +
                '&to=' +
                encodeURIComponent(to),
              { credentials: 'same-origin' }
            )
              .then(function (r) {
                return r.ok ? r.json() : null;
              })
              .then(function (data) {
                if (!data) return payload;
                var days = M.combineSessionDayLists(data.days || [], data.ohm_days || []);
                return {
                  slots: M.shareSlots(days, today, 0),
                  slotSections: M.shareSlotsGrouped(days, today),
                };
              })
              .catch(function () {
                return payload;
              });
          }
        : null;
    window.GlideShareSheet.open({
      ref: boot.ref,
      slots: payload.slots,
      slotSections: payload.slotSections,
      sessionId: sid,
      sessionMissing: boot.sessionMissing && !sessionExists(sid),
      invite: true,
      venueType: 'ice',
      context: 'arena_card',
      placeName: boot.placeName || '',
      loadSlots: loadSlots,
    });
  }

  document.querySelectorAll('.b-ticket[data-session-id]').forEach(function (el) {
    el.addEventListener('click', function (event) {
      event.preventDefault();
      applyPick(el.getAttribute('data-session-id'), { reveal: true, showPlan: true, anchor: el });
    });
  });

  window.addEventListener('load', function () {
    alignCurrentDay();
    if (openedOnSession) revealAboveDock();
  });

  var btn = document.getElementById('placeShareBtn');
  var dockEl = document.getElementById('placeShareDock');
  if (dockEl) dockEl.hidden = false;
  if (btn) {
    btn.hidden = false;
    // Рядом с «Позвать» Telegram сжимается до короткой кнопки (TASK-278).
    if (btn.parentNode && btn.parentNode.classList) btn.parentNode.classList.add('has-invite');
  }
  if (btn) {
    btn.addEventListener('click', function () {
      openShare();
    });
  }

  document.querySelectorAll('.place-share-fallback [data-copy]').forEach(function (copyBtn) {
    copyBtn.addEventListener('click', function () {
      var text = copyBtn.getAttribute('data-copy') || '';
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).catch(function () {});
      }
    });
  });

  var initial = resolvedSessionId();
  if (initial) applyPick(initial, { skipUrl: true, reveal: openedOnSession });
  else if (btn) btn.disabled = true;
})();
