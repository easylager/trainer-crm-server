/**
 * Главная тренера по макету «Главная тренера» (TASK-314, волна 2): полоса недели, срочное
 * отдельной строкой, «Дела» одной строкой со шторкой, день — ближайшее занятие крупно,
 * остальные строками, и итог недели. Всё из одного ответа hub/bootstrap.
 *
 * Модуль только рисует. Действия (подтвердить, открыть запись, выполнить дело) — у главной:
 *   TrainerHubToday.mount({ host, onPending, onConfirm, onOpenBooking, onOpenSchedule,
 *                           onFreeTime, onRunItem, onDismissItem, compactTitle })
 *   TrainerHubToday.render({ bookings, inbox, now })
 */
(function (global) {
  'use strict';

  var F = global.TrainerFormat;
  var opts = null;
  var data = null;
  var selected = null;
  var sheet = null;

  var DOW = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
  var DOW_FULL = ['Воскресенье', 'Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота'];
  var MONTH_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  var CHEVRON = '<svg class="tu-row__chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function plural(n, a, b, c) { return F ? F.plural(n, a, b, c) : c; }
  function hm(t) { return F ? F.time(t) : String(t || '').slice(0, 5); }
  function iso(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function parseIso(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || ''));
    return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
  }
  function minutesOf(t) {
    var m = /^(\d{1,2}):(\d{2})/.exec(String(t || ''));
    return m ? +m[1] * 60 + +m[2] : 0;
  }
  function nbsp(s) { return String(s).replace(/ (\S{1,3})(?= |$)/g, ' $1'); }

  /* ---------- данные ---------- */

  function weekDays() {
    var w = data && data.bookings && data.bookings.week;
    if (w && w.days && w.days.length) return w.days;
    /* Старый ответ без недели: семь дней от сегодня, счёт из записей. */
    var out = [];
    var base = parseIso(iso(data.now));
    for (var i = 0; i < 7; i++) {
      var d = new Date(base.getTime() + i * 86400000);
      var list = bookingsOf(iso(d));
      out.push({ date: iso(d), sessions: list.length, pending: 0, free: 0, free_times: [] });
    }
    return out;
  }

  function bookingsOf(dateIso) {
    var days = (data && data.bookings && data.bookings.days) || [];
    for (var i = 0; i < days.length; i++) {
      if (String(days[i].date).slice(0, 10) === dateIso) {
        return (days[i].bookings || []).filter(function (b) {
          return b.status !== 'cancelled' && b.status !== 'declined';
        });
      }
    }
    return [];
  }

  function inboxItems() {
    return (data && data.inbox && data.inbox.items) || [];
  }
  function pendingItem() {
    return inboxItems().filter(function (it) { return it.kind === 'pending'; })[0] || null;
  }
  function taskItems() {
    return inboxItems().filter(function (it) { return it.kind !== 'pending'; });
  }

  function personName(b) {
    return [b.client_first_name, b.client_last_name].filter(Boolean).join(' ').trim() || 'Ученик';
  }
  function whatLine(b) {
    return [b.services_str, b.arenas_str].filter(Boolean).join(' · ');
  }

  /* ---------- куски ---------- */

  function stripHtml() {
    var todayIso = iso(data.now);
    return weekDays().map(function (d) {
      var dt = parseIso(d.date);
      var on = d.date === selected;
      var label = (d.date === todayIso ? 'Сегодня, ' : '') + DOW_FULL[dt.getDay()].toLowerCase() + ', ' + dt.getDate() + ' ' + MONTH_GEN[dt.getMonth()] +
        (d.sessions ? ', ' + d.sessions + ' ' + plural(d.sessions, 'занятие', 'занятия', 'занятий') : ', занятий нет');
      return (
        '<button type="button" role="tab" class="ht-day' + (on ? ' ht-day--on' : '') + (d.date === todayIso ? ' ht-day--today' : '') + '"' +
        ' aria-selected="' + on + '" aria-label="' + esc(label) + '" data-ht="day" data-date="' + d.date + '">' +
        '<span class="ht-day__dow">' + DOW[dt.getDay()] + '</span>' +
        '<span class="ht-day__num tu-mono">' + dt.getDate() + '</span>' +
        '<span class="ht-day__dot' + (d.sessions ? ' ht-day__dot--on' : '') + (d.pending ? ' ht-day__dot--warm' : '') + '"></span>' +
        '</button>'
      );
    }).join('');
  }

  function urgentHtml() {
    var p = pendingItem();
    if (!p) return '';
    var n = Number(p.count) || 1;
    return (
      '<div class="tu-urgent" role="status">' +
      '<span class="tu-row__main">' +
      '<span class="tu-row__title">' + n + ' ' + plural(n, 'запись ждёт', 'записи ждут', 'записей ждут') + ' подтверждения</span>' +
      '<span class="tu-row__sub">Ученики ждут ответа</span>' +
      '</span>' +
      '<button type="button" class="tu-btn tu-btn--dark tu-btn--small" data-ht="pending">' + (n > 1 ? 'Посмотреть' : 'Подтвердить') + '</button>' +
      '</div>'
    );
  }

  function tasksHtml() {
    var tasks = taskItems();
    if (!tasks.length) return '';
    var names = tasks.slice(0, 3).map(function (it) {
      return opts.compactTitle ? opts.compactTitle(it) : it.title;
    });
    return (
      '<button type="button" class="tu-card tu-row ht-tasks" data-ht="tasks" aria-haspopup="dialog">' +
      '<span class="tu-count" aria-hidden="true">' + tasks.length + '</span>' +
      '<span class="tu-row__main">' +
      '<span class="tu-row__title">Дела</span>' +
      '<span class="tu-row__sub">' + esc(names.join(', ')) + '</span>' +
      '</span>' + CHEVRON +
      '</button>'
    );
  }

  function untilText(b) {
    var now = data.now.getHours() * 60 + data.now.getMinutes();
    var start = minutesOf(b.start_time);
    var end = minutesOf(b.end_time);
    if (b.hub_in_session || (now >= start && now < end)) return 'Идёт сейчас';
    var diff = start - now;
    if (diff <= 0) return '';
    if (diff < 60) return 'Через ' + diff + ' мин';
    if (diff < 180) {
      var h = Math.floor(diff / 60);
      var m = diff % 60;
      return 'Через ' + h + ' ч' + (m ? ' ' + m + ' мин' : '');
    }
    return '';
  }

  function rowHtml(b) {
    var pending = b.status === 'pending';
    return (
      '<div class="tu-row ht-booking" data-ht="booking" data-id="' + esc(b.id) + '" role="button" tabindex="0">' +
      '<span class="ht-booking__time tu-mono">' + esc(hm(b.start_time)) + '</span>' +
      '<span class="tu-row__main">' +
      '<span class="tu-row__title">' + esc(personName(b)) + '</span>' +
      '<span class="tu-row__sub' + (pending ? ' tu-row__sub--warm' : '') + '">' +
      esc(pending ? 'Ждёт подтверждения' : whatLine(b)) + '</span>' +
      '</span>' +
      (pending
        ? '<button type="button" class="tu-btn tu-btn--primary tu-btn--small" data-ht="confirm" data-id="' + esc(b.id) + '">Подтвердить</button>'
        : '') +
      '</div>'
    );
  }

  function dayHtml() {
    var todayIso = iso(data.now);
    var isToday = selected === todayIso;
    var list = bookingsOf(selected).slice().sort(function (a, b) {
      return minutesOf(a.start_time) - minutesOf(b.start_time);
    });
    var nowMin = data.now.getHours() * 60 + data.now.getMinutes();
    if (isToday) list = list.filter(function (b) { return minutesOf(b.end_time) > nowMin || b.hub_in_session; });
    var dt = parseIso(selected);
    var dayName = isToday ? 'Сегодня' : (selected === iso(new Date(parseIso(todayIso).getTime() + 86400000)) ? 'Завтра' : DOW_FULL[dt.getDay()] + ', ' + dt.getDate() + ' ' + MONTH_GEN[dt.getMonth()]);
    var label = dayName + (list.length ? ' · ' + list.length + ' ' + plural(list.length, 'занятие', 'занятия', 'занятий') : '');
    var html = '<p class="tu-label">' + esc(label) + '</p>';

    if (!list.length) {
      var wd = weekDays().filter(function (d) { return d.date === selected; })[0];
      var free = (wd && wd.free_times) || [];
      if (free.length) {
        html +=
          '<div class="tu-card tu-card--pad ht-empty">' +
          '<p class="ht-empty__text">' + (isToday ? 'Больше записей сегодня нет.' : 'Записей пока нет.') + ' Свободные окна:</p>' +
          '<div class="ht-empty__chips">' +
          free.map(function (t) {
            return '<button type="button" class="tu-chip" data-ht="free" data-time="' + esc(t) + '" aria-label="Записать на ' + esc(t) + '">' + esc(t) + '</button>';
          }).join('') +
          '</div></div>';
      } else {
        html +=
          '<div class="tu-card tu-card--pad ht-empty">' +
          '<p class="ht-empty__text">' + (isToday ? 'На сегодня всё.' : 'Ни записей, ни свободных окон.') + '</p>' +
          '<button type="button" class="tu-btn tu-btn--ghost tu-btn--small ht-empty__link" data-ht="schedule">Открыть расписание</button>' +
          '</div>';
      }
      return html;
    }

    var rest = list;
    if (isToday) {
      var next = list[0];
      var until = untilText(next);
      rest = list.slice(1);
      html +=
        '<div class="tu-card tu-card--deep ht-next" data-ht="booking" data-id="' + esc(next.id) + '" role="button" tabindex="0">' +
        (until ? '<span class="ht-next__until">' + esc(until) + '</span>' : '') +
        '<span class="ht-next__time tu-mono">' + esc(hm(next.start_time)) + '–' + esc(hm(next.end_time)) + '</span>' +
        '<span class="ht-next__who">' + esc(personName(next)) + '</span>' +
        '<span class="ht-next__what">' + esc(next.status === 'pending' ? 'Ждёт подтверждения' : whatLine(next)) + '</span>' +
        (next.status === 'pending'
          ? '<button type="button" class="tu-btn tu-btn--primary tu-btn--small ht-next__confirm" data-ht="confirm" data-id="' + esc(next.id) + '">Подтвердить</button>'
          : '') +
        '</div>';
    }
    if (rest.length) {
      var shown = rest.slice(0, 3);
      html += '<div class="tu-card">' + shown.map(rowHtml).join('');
      if (rest.length > shown.length) {
        var more = rest.length - shown.length;
        html +=
          '<button type="button" class="tu-row ht-more" data-ht="schedule">' +
          '<span class="tu-row__main"><span class="tu-row__title">Ещё ' + more + ' ' + plural(more, 'занятие', 'занятия', 'занятий') + '</span></span>' +
          CHEVRON + '</button>';
      }
      html += '</div>';
    }
    return html;
  }

  function weekLineHtml() {
    var days = weekDays();
    var sessions = 0;
    var free = 0;
    days.forEach(function (d) { sessions += d.sessions || 0; free += d.free || 0; });
    if (!sessions && !free) return '';
    var parts = [];
    parts.push(sessions + ' ' + plural(sessions, 'занятие', 'занятия', 'занятий'));
    if (free) parts.push(free + ' ' + plural(free, 'свободное окно', 'свободных окна', 'свободных окон'));
    return (
      '<div class="ht-week">' +
      '<span>Неделя: ' + parts.join(', ') + '</span>' +
      '<button type="button" class="tu-btn tu-btn--quiet tu-btn--small" data-ht="schedule">Расписание</button>' +
      '</div>'
    );
  }

  /* ---------- «Дела» ---------- */

  function tgApp() { return global.Telegram && global.Telegram.WebApp ? global.Telegram.WebApp : null; }
  var backWasVisible = false;
  function onTgBack() { closeTasks(); }

  function ensureSheet() {
    if (sheet) return sheet;
    var back = document.createElement('div');
    back.className = 'tu-sheet-back';
    back.hidden = true;
    var el = document.createElement('div');
    el.className = 'tu-sheet ht-tasks-sheet';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.setAttribute('aria-labelledby', 'htTasksTitle');
    el.hidden = true;
    document.body.appendChild(back);
    document.body.appendChild(el);
    back.addEventListener('click', closeTasks);
    el.addEventListener('click', onSheetClick);
    bindDrag(el);
    sheet = { back: back, el: el };
    return sheet;
  }

  function bindDrag(panel) {
    var startY = null;
    var dy = 0;
    panel.addEventListener('touchstart', function (ev) {
      if (panel.scrollTop > 0 || !ev.touches || ev.touches.length !== 1) { startY = null; return; }
      startY = ev.touches[0].clientY;
      dy = 0;
      panel.style.transition = 'none';
    }, { passive: true });
    panel.addEventListener('touchmove', function (ev) {
      if (startY == null) return;
      dy = Math.max(0, ev.touches[0].clientY - startY);
      if (dy > 0) panel.style.transform = 'translateY(' + dy + 'px)';
    }, { passive: true });
    function end() {
      if (startY == null) return;
      startY = null;
      panel.style.transition = 'transform 0.2s ease';
      if (dy > 90) {
        closeTasks();
      }
      panel.style.transform = '';
      dy = 0;
    }
    panel.addEventListener('touchend', end);
    panel.addEventListener('touchcancel', end);
  }

  function renderSheet() {
    var tasks = taskItems();
    var s = ensureSheet();
    s.el.innerHTML =
      '<span class="tu-sheet__handle" aria-hidden="true"></span>' +
      '<div class="tu-sheet__head"><h2 class="tu-sheet__title" id="htTasksTitle">Дела</h2>' +
      '<button type="button" class="tu-sheet__close" data-ht="close" aria-label="Закрыть">' +
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
      '</button></div>' +
      (tasks.length
        ? tasks.map(function (it, i) {
            return (
              '<div class="ht-task">' +
              '<p class="ht-task__title">' + esc(it.title) + '</p>' +
              (it.subtitle ? '<p class="ht-task__text">' + esc(it.subtitle) + '</p>' : '') +
              '<div class="ht-task__actions">' +
              '<button type="button" class="tu-btn tu-btn--primary tu-btn--small" data-ht="task" data-i="' + i + '">' + esc(it.primaryLabel || it.primary_label || 'Открыть') + '</button>' +
              (it.dismissible
                ? '<button type="button" class="tu-btn tu-btn--quiet tu-btn--small" data-ht="later" data-i="' + i + '">Не сейчас</button>'
                : '') +
              '</div></div>'
            );
          }).join('')
        : '<p class="ht-task__text">Всё сделано.</p>');
  }

  function openTasks() {
    renderSheet();
    if (typeof opts.onTasksShown === 'function') opts.onTasksShown(taskItems());
    sheet.back.hidden = false;
    sheet.el.hidden = false;
    document.body.classList.add('ht-sheet-open');
    var tg = tgApp();
    try {
      if (tg) {
        if (typeof tg.disableVerticalSwipes === 'function') tg.disableVerticalSwipes();
        if (tg.BackButton) {
          backWasVisible = !!tg.BackButton.isVisible;
          tg.BackButton.onClick(onTgBack);
          tg.BackButton.show();
        }
      }
    } catch (e) { /* старые клиенты */ }
  }

  function closeTasks() {
    if (!sheet || sheet.el.hidden) return;
    sheet.el.hidden = true;
    sheet.back.hidden = true;
    document.body.classList.remove('ht-sheet-open');
    var tg = tgApp();
    try {
      if (tg) {
        if (typeof tg.enableVerticalSwipes === 'function') tg.enableVerticalSwipes();
        if (tg.BackButton) {
          tg.BackButton.offClick(onTgBack);
          if (!backWasVisible) tg.BackButton.hide();
        }
      }
    } catch (e) { /* старые клиенты */ }
  }

  function onSheetClick(ev) {
    var btn = ev.target.closest && ev.target.closest('[data-ht]');
    if (!btn) return;
    var act = btn.getAttribute('data-ht');
    var it = taskItems()[Number(btn.getAttribute('data-i'))];
    if (act === 'close') closeTasks();
    else if (act === 'task' && it) {
      closeTasks();
      opts.onRunItem(it);
    } else if (act === 'later' && it) {
      opts.onDismissItem(it);
      data.inbox.items = inboxItems().filter(function (x) { return x !== it; });
      render(data);
      if (taskItems().length) renderSheet();
      else closeTasks();
    }
  }

  /* ---------- главная ---------- */

  function onClick(ev) {
    var btn = ev.target.closest && ev.target.closest('[data-ht]');
    if (!btn || !opts.host.contains(btn)) return;
    var act = btn.getAttribute('data-ht');
    if (act === 'day') {
      selected = btn.getAttribute('data-date');
      render(data);
    } else if (act === 'pending') {
      var p = pendingItem();
      opts.onPending(p ? p.booking_ids || [] : []);
    } else if (act === 'tasks') {
      openTasks();
    } else if (act === 'confirm') {
      ev.stopPropagation();
      btn.setAttribute('aria-busy', 'true');
      Promise.resolve(opts.onConfirm(btn.getAttribute('data-id'))).catch(function () {
        btn.removeAttribute('aria-busy');
      });
    } else if (act === 'booking') {
      opts.onOpenBooking(btn.getAttribute('data-id'));
    } else if (act === 'schedule') {
      opts.onOpenSchedule(selected);
    } else if (act === 'free') {
      opts.onFreeTime(selected, btn.getAttribute('data-time'));
    }
  }

  function onKey(ev) {
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    var row = ev.target.closest && ev.target.closest('[data-ht="booking"]');
    if (row) { ev.preventDefault(); opts.onOpenBooking(row.getAttribute('data-id')); }
  }

  function render(next) {
    if (!opts) return;
    data = next || data;
    if (!data) return;
    data.now = data.now || new Date();
    var days = weekDays();
    if (!selected || !days.some(function (d) { return d.date === selected; })) selected = days.length ? days[0].date : iso(data.now);
    var urgent = urgentHtml();
    var tasks = tasksHtml();
    opts.host.innerHTML =
      '<div class="ht-strip" role="tablist" aria-label="Дни недели">' + stripHtml() + '</div>' +
      (urgent || tasks ? '<div class="ht-stack">' + urgent + tasks + '</div>' : '') +
      '<section class="ht-day-list" aria-live="polite">' + dayHtml() + '</section>' +
      weekLineHtml();
    opts.host.hidden = false;
  }

  function mount(o) {
    opts = o;
    opts.host.addEventListener('click', onClick);
    opts.host.addEventListener('keydown', onKey);
  }

  global.TrainerHubToday = { mount: mount, render: render, closeTasks: closeTasks };
})(typeof window !== 'undefined' ? window : globalThis);
