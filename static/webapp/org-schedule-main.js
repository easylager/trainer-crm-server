/**
 * Org Расписание (TASK-141 S6 + TASK-144 S1): управление расписанием тренеров школы.
 * Переключатель «чьё расписание» + создание слотов тапом по сетке часов (без нативных
 * JS-диалогов) + удаление через кастомную модалку (mini-app-confirm.js).
 * Тап-грид — порт паттерна из schedule-editor-main.js::renderHourGrid, не буквальный
 * extract (там auth/apiUrl завязаны на неявного «себя», здесь trainer_id — параметр
 * везде, включая state).
 */
(function () {
  'use strict';

  var DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

  function el(id) {
    return document.getElementById(id);
  }

  function show(node) {
    if (node) node.hidden = false;
  }

  function hide(node) {
    if (node) node.hidden = true;
  }

  function authHeaders() {
    return window.MiniAppRuntime ? window.MiniAppRuntime.authHeaders() : {};
  }

  function escapeHtml(text) {
    var d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  function getMonday(d) {
    var date = new Date(d);
    var day = date.getDay();
    var diff = date.getDate() - day + (day === 0 ? -6 : 1);
    return new Date(date.setDate(diff));
  }

  function formatDate(d) {
    return d.toISOString().split('T')[0];
  }

  function formatDisplayDate(d) {
    var months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
      'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
    return d.getDate() + ' ' + months[d.getMonth()];
  }

  function pad2(n) {
    return String(n).padStart(2, '0');
  }

  function minutesToHHMM(m) {
    return pad2(Math.floor(m / 60)) + ':' + pad2(m % 60);
  }

  function hhmmToMinutes(s) {
    var parts = String(s || '').split(':');
    var h = parseInt(parts[0], 10);
    var m = parseInt(parts[1], 10);
    if (isNaN(h) || isNaN(m)) return null;
    return h * 60 + m;
  }

  /** Mirrors backend allowed_start_minutes_from_preset (arena_schedule_preset.py) —
   * ported verbatim from schedule-editor-main.js, a pure function with no trainer-"me" coupling. */
  function allowedStartMinutesFromPreset(preset) {
    preset = preset || defaultGridPreset();
    var kind = (preset.kind || 'uniform_step').toString().trim();
    var h0 = Math.max(0, Math.min(23, parseInt(preset.hour_start, 10)));
    if (isNaN(h0)) h0 = 6;
    var h1 = Math.max(0, Math.min(23, parseInt(preset.hour_end, 10)));
    if (isNaN(h1)) h1 = 23;
    if (h1 < h0) {
      var swap = h0;
      h0 = h1;
      h1 = swap;
    }
    var out = [];
    if (kind === 'hourly_minute') {
      var mo = Math.max(0, Math.min(59, parseInt(preset.minute_offset, 10) || 0));
      for (var h = h0; h <= h1; h++) out.push(h * 60 + mo);
    } else if (kind === 'uniform_step') {
      var step = parseInt(preset.step_minutes, 10);
      if (isNaN(step) || step < 10) step = 15;
      if ([10, 15, 30, 60].indexOf(step) < 0) step = 15;
      for (var m = h0 * 60; m <= h1 * 60; m += step) out.push(m);
    } else {
      for (var m2 = h0 * 60; m2 <= h1 * 60; m2 += 15) out.push(m2);
    }
    return out;
  }

  function defaultGridPreset() {
    return { kind: 'uniform_step', minute_offset: 0, hour_start: 6, hour_end: 23, step_minutes: 15 };
  }

  var state = {
    members: [],
    selectedTrainerId: null,
    weekStart: getMonday(new Date()),
    slots: [],
    role: null,
    scheduleGrid: null,
    panelDay: null, // 'YYYY-MM-DD' — which day's add-panel is open, or null
    selectedStarts: null, // Set<number minute-of-day> — newly tapped, unsaved

    templates: [], // raw from GET .../schedule/templates (all weekdays)
    templateDay: null, // 0..6 (Mon..Sun) — which weekday's editor is open, or null
    templateSelectedStarts: null, // Set<number minute-of-day> — full desired state for templateDay
  };

  var WEEKDAY_FULL = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];

  function loadTeam() {
    return fetch('/api/webapp/org/team', { headers: authHeaders() })
      .then(function (resp) {
        if (resp.status === 401) throw new Error('Не удалось подтвердить вход. Откройте кабинет из бота.');
        if (!resp.ok) throw new Error('Не удалось загрузить список тренеров');
        return resp.json();
      })
      .then(function (data) {
        state.members = data.members || [];
        state.role = data.role;
        renderCoachPicker();
        if (state.members.length > 0) {
          state.selectedTrainerId = state.members[0].trainer_id;
          loadSchedule();
        } else {
          hide(el('orgScheduleLoading'));
          show(el('orgScheduleError'));
          el('orgScheduleErrorText').textContent = 'В школе пока нет тренеров.';
        }
      });
  }

  function renderCoachPicker() {
    var picker = el('orgScheduleCoachPicker');
    picker.innerHTML = state.members.map(function (m) {
      var name = m.display_name || (m.telegram_username ? '@' + m.telegram_username : 'Тренер #' + m.trainer_id);
      var active = m.trainer_id === state.selectedTrainerId;
      return '<button type="button" class="org-schedule-coach-chip' + (active ? ' is-active' : '') +
        '" data-trainer-id="' + m.trainer_id + '">' + escapeHtml(name) + '</button>';
    }).join('');

    picker.querySelectorAll('.org-schedule-coach-chip').forEach(function (chip) {
      chip.addEventListener('click', function () {
        var next = parseInt(chip.dataset.trainerId, 10);
        if (next === state.selectedTrainerId) return;
        state.selectedTrainerId = next;
        closePanel();
        closeTemplatePanel();
        renderCoachPicker();
        loadSchedule();
      });
    });
  }

  function loadSchedule() {
    if (!state.selectedTrainerId) return;

    show(el('orgScheduleLoading'));
    hide(el('orgScheduleRoot'));
    hide(el('orgScheduleError'));

    var from = formatDate(state.weekStart);
    var to = formatDate(new Date(state.weekStart.getTime() + 6 * 24 * 60 * 60 * 1000));

    fetch('/api/webapp/org/schedule?trainer_id=' + state.selectedTrainerId +
      '&from_date=' + from + '&to_date=' + to, { headers: authHeaders() })
      .then(function (resp) {
        if (resp.status === 404) throw new Error('Тренер не найден в школе.');
        if (resp.status === 401) throw new Error('Не удалось подтвердить вход.');
        if (!resp.ok) throw new Error('Не удалось загрузить расписание');
        return resp.json();
      })
      .then(function (data) {
        state.slots = data.slots || [];
        state.scheduleGrid = data.schedule_grid || defaultGridPreset();
        hide(el('orgScheduleLoading'));
        show(el('orgScheduleRoot'));
        renderWeek();
      })
      .catch(function (err) {
        hide(el('orgScheduleLoading'));
        show(el('orgScheduleError'));
        el('orgScheduleErrorText').textContent = err.message || 'Не удалось загрузить расписание';
      });
  }

  function daySlots(dayStr) {
    return state.slots.filter(function (s) { return s.slot_date === dayStr; });
  }

  function isBookedSlot(slot) {
    return slot.status !== 'available' || !!slot.booking_id;
  }

  function renderWeek() {
    var weekEnd = new Date(state.weekStart.getTime() + 6 * 24 * 60 * 60 * 1000);
    el('orgScheduleWeekLabel').textContent =
      formatDisplayDate(state.weekStart) + ' — ' + formatDisplayDate(weekEnd);

    var container = el('orgScheduleDays');
    container.innerHTML = '';

    for (var i = 0; i < 7; i++) {
      var dayDate = new Date(state.weekStart.getTime() + i * 24 * 60 * 60 * 1000);
      var dayStr = formatDate(dayDate);
      var slots = daySlots(dayStr);

      var dayHtml = '<div class="org-schedule-day">' +
        '<div class="org-schedule-day__header">' +
        '<span class="org-schedule-day__name">' + DAYS[i] + ', ' + formatDisplayDate(dayDate) + '</span>' +
        '<button type="button" class="org-schedule-day__add" data-day="' + dayStr + '">+ Слот</button>' +
        '</div>' +
        '<div class="org-schedule-slots">';

      if (slots.length === 0) {
        dayHtml += '<div class="org-schedule-empty">Нет слотов</div>';
      } else {
        slots.forEach(function (slot) {
          var booked = isBookedSlot(slot);
          dayHtml += '<div class="org-schedule-slot' + (booked ? ' org-schedule-slot--booked' : '') + '">' +
            '<div>' +
            '<div class="org-schedule-slot__time">' + slot.start_time + '–' + slot.end_time + '</div>' +
            (slot.service_label ? '<div class="org-schedule-slot__label">' + escapeHtml(slot.service_label) + '</div>' : '') +
            (booked ? '<div class="org-schedule-slot__label">' + (slot.client_preview ? escapeHtml(slot.client_preview) : 'Занято') + '</div>' : '') +
            '</div>' +
            (booked ? '' : '<button type="button" class="org-schedule-slot__del" data-slot-id="' + slot.id + '">Удалить</button>') +
            '</div>';
        });
      }

      dayHtml += '</div></div>';
      container.innerHTML += dayHtml;
    }

    container.querySelectorAll('.org-schedule-day__add').forEach(function (btn) {
      btn.addEventListener('click', function () {
        openPanel(btn.dataset.day);
      });
    });

    container.querySelectorAll('.org-schedule-slot__del').forEach(function (btn) {
      btn.addEventListener('click', function () {
        deleteSlot(btn.dataset.slotId);
      });
    });
  }

  function openPanel(dayStr) {
    state.panelDay = dayStr;
    state.selectedStarts = new Set();
    var dayDate = new Date(dayStr + 'T00:00:00');
    el('orgSchedulePanelTitle').textContent = 'Добавить слоты — ' + formatDisplayDate(dayDate);
    el('orgSchedulePanelHint').textContent = 'Отметьте начала — занятые уже недоступны';
    show(el('orgSchedulePanel'));
    el('orgSchedulePanel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    renderHourGrid();
  }

  function closePanel() {
    state.panelDay = null;
    state.selectedStarts = null;
    hide(el('orgSchedulePanel'));
  }

  function occupiedMinutesForDay(dayStr) {
    var out = new Set();
    daySlots(dayStr).forEach(function (s) {
      var m = hhmmToMinutes(s.start_time);
      if (m != null) out.add(m);
    });
    return out;
  }

  /** Generic tap-grid renderer — shared by the day add-panel (S1, locked=occupied slots)
   * and the template-day editor (S2, no locked concept — PUT replaces the whole day). */
  function renderGrid(gridEl, preset, selectedSet, lockedSet, pastCutoffMinutes, onToggle) {
    if (!gridEl) return;
    var h0 = Math.max(0, Math.min(23, parseInt(preset.hour_start, 10)));
    if (isNaN(h0)) h0 = 6;
    var h1 = Math.max(0, Math.min(23, parseInt(preset.hour_end, 10)));
    if (isNaN(h1)) h1 = 23;

    var list = allowedStartMinutesFromPreset(preset);
    var html = '';
    for (var h = h0; h <= h1; h++) {
      var chips = list.filter(function (m) { return Math.floor(m / 60) === h; });
      if (!chips.length) continue;
      html += '<div class="schedule-hour-row" role="row">';
      html += '<div class="schedule-hour-row__rail" aria-hidden="true"><span class="schedule-hour-row__label">' +
        pad2(h) + '</span></div>';
      html += '<div class="schedule-hour-row__chips" role="group">';
      chips.forEach(function (m) {
        var locked = lockedSet.has(m);
        var past = pastCutoffMinutes >= 0 && m < pastCutoffMinutes;
        var selected = selectedSet.has(m);
        var disabled = locked || past;
        html += '<button type="button" class="hour-chip' +
          (selected ? ' selected' : '') +
          (locked ? ' locked' : '') +
          '" data-minute="' + m + '"' +
          (disabled ? ' disabled' : '') +
          ' aria-label="' + minutesToHHMM(m) + (locked ? ', занято' : past ? ', время прошло' : '') + '"' +
          '>:' + pad2(m % 60) + '</button>';
      });
      html += '</div></div>';
    }
    gridEl.innerHTML = html;
    gridEl.querySelectorAll('.hour-chip:not(:disabled)').forEach(function (btn) {
      btn.addEventListener('click', function () {
        onToggle(parseInt(btn.dataset.minute, 10));
      });
    });
  }

  function renderHourGrid() {
    var grid = el('hourGrid');
    if (!grid || !state.panelDay) return;
    var preset = state.scheduleGrid || defaultGridPreset();
    var occupied = occupiedMinutesForDay(state.panelDay);
    var isToday = state.panelDay === formatDate(new Date());
    var nowMinutes = isToday ? (new Date().getHours() * 60 + new Date().getMinutes()) : -1;
    renderGrid(grid, preset, state.selectedStarts, occupied, nowMinutes, function (m) {
      if (state.selectedStarts.has(m)) state.selectedStarts.delete(m);
      else state.selectedStarts.add(m);
      renderHourGrid();
    });
  }

  function saveNewSlots() {
    if (!state.panelDay || !state.selectedStarts || state.selectedStarts.size === 0) return;
    var durationMinutes = parseInt(el('orgSchedulePanelDuration').value, 10) || 45;
    var existing = occupiedMinutesForDay(state.panelDay);
    var allMinutes = new Set(existing);
    state.selectedStarts.forEach(function (m) { allMinutes.add(m); });
    var startTimes = Array.from(allMinutes).sort(function (a, b) { return a - b; }).map(minutesToHHMM);

    var saveBtn = el('orgSchedulePanelSave');
    saveBtn.disabled = true;

    fetch('/api/webapp/org/schedule/slots', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
      body: JSON.stringify({
        trainer_id: state.selectedTrainerId,
        slot_date: state.panelDay,
        start_times: startTimes,
        duration_minutes: durationMinutes,
      }),
    })
      .then(function (resp) {
        if (resp.status === 403) throw new Error('Только владелец школы может редактировать расписание.');
        if (resp.status === 422 || resp.status === 400) {
          return resp.json().then(function (body) {
            throw new Error((body && body.detail) || 'Проверьте данные слота.');
          });
        }
        if (!resp.ok) throw new Error('Не удалось создать слот');
        return resp.json();
      })
      .then(function () {
        closePanel();
        loadSchedule();
      })
      .catch(function (err) {
        el('orgSchedulePanelHint').textContent = err.message || 'Не удалось создать слот';
      })
      .finally(function () {
        saveBtn.disabled = false;
      });
  }

  function deleteSlot(slotId) {
    window.showAppConfirm('Удалить этот слот?', { okText: 'Удалить', cancelText: 'Отмена' }).then(function (ok) {
      if (!ok) return;
      fetch('/api/webapp/org/schedule/slots/' + slotId + '?trainer_id=' + state.selectedTrainerId, {
        method: 'DELETE',
        headers: authHeaders(),
      })
        .then(function (resp) {
          if (resp.status === 403) throw new Error('Только владелец школы может удалять слоты.');
          if (resp.status === 404) throw new Error('Слот не найден или уже забронирован.');
          if (!resp.ok) throw new Error('Не удалось удалить слот');
          return resp.json();
        })
        .then(function () {
          loadSchedule();
        })
        .catch(function (err) {
          hide(el('orgScheduleRoot'));
          show(el('orgScheduleError'));
          el('orgScheduleErrorText').textContent = err.message || 'Не удалось удалить слот';
        });
    });
  }

  function openTemplatePanel() {
    show(el('orgScheduleTemplatePanel'));
    el('orgScheduleTemplatePanel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    hide(el('orgScheduleTemplateEditor'));
    state.templateDay = null;
    loadTemplates();
  }

  function closeTemplatePanel() {
    hide(el('orgScheduleTemplatePanel'));
    hide(el('orgScheduleTemplateEditor'));
    state.templateDay = null;
    state.templateSelectedStarts = null;
  }

  function loadTemplates() {
    if (!state.selectedTrainerId) return;
    fetch('/api/webapp/org/schedule/templates?trainer_id=' + state.selectedTrainerId, { headers: authHeaders() })
      .then(function (resp) {
        if (!resp.ok) throw new Error('Не удалось загрузить шаблон');
        return resp.json();
      })
      .then(function (data) {
        state.templates = data.templates || [];
        renderTemplateDayPicker();
        if (state.templateDay != null) openTemplateDay(state.templateDay);
      })
      .catch(function () {
        state.templates = [];
        renderTemplateDayPicker();
      });
  }

  function renderTemplateDayPicker() {
    var picker = el('orgScheduleTemplateDayPicker');
    picker.innerHTML = WEEKDAY_FULL.map(function (name, dow) {
      var count = state.templates.filter(function (t) { return t.day_of_week === dow; }).length;
      var active = dow === state.templateDay;
      return '<button type="button" class="org-schedule-coach-chip' + (active ? ' is-active' : '') +
        '" data-dow="' + dow + '">' + DAYS[dow] + (count ? ' (' + count + ')' : '') + '</button>';
    }).join('');
    picker.querySelectorAll('.org-schedule-coach-chip').forEach(function (chip) {
      chip.addEventListener('click', function () {
        openTemplateDay(parseInt(chip.dataset.dow, 10));
      });
    });
  }

  function openTemplateDay(dow) {
    state.templateDay = dow;
    var existing = state.templates.filter(function (t) { return t.day_of_week === dow; });
    state.templateSelectedStarts = new Set(existing.map(function (t) { return hhmmToMinutes(t.start_time); }));
    el('orgScheduleTemplateHint').textContent = WEEKDAY_FULL[dow] + ' — отметьте начала занятий';
    show(el('orgScheduleTemplateEditor'));
    renderTemplateDayPicker();
    renderTemplateGrid();
  }

  function renderTemplateGrid() {
    var grid = el('templateHourGrid');
    if (!grid || state.templateDay == null) return;
    var preset = state.scheduleGrid || defaultGridPreset();
    renderGrid(grid, preset, state.templateSelectedStarts, new Set(), -1, function (m) {
      if (state.templateSelectedStarts.has(m)) state.templateSelectedStarts.delete(m);
      else state.templateSelectedStarts.add(m);
      renderTemplateGrid();
    });
  }

  function saveTemplateDay() {
    if (state.templateDay == null || !state.templateSelectedStarts) return;
    var durationMinutes = parseInt(el('orgScheduleTemplateDuration').value, 10) || 45;
    var slots = Array.from(state.templateSelectedStarts).map(function (m) {
      return { hour: Math.floor(m / 60), minute: m % 60, capacity: 1 };
    });
    var saveBtn = el('orgScheduleTemplateSaveDay');
    saveBtn.disabled = true;
    fetch('/api/webapp/org/schedule/templates/day', {
      method: 'PUT',
      headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
      body: JSON.stringify({
        trainer_id: state.selectedTrainerId,
        day_of_week: state.templateDay,
        duration_minutes: durationMinutes,
        slots: slots,
      }),
    })
      .then(function (resp) {
        if (resp.status === 403) throw new Error('Только владелец школы может редактировать шаблон.');
        if (resp.status === 400 || resp.status === 422) {
          return resp.json().then(function (body) {
            throw new Error((body && body.detail) || 'Проверьте данные шаблона.');
          });
        }
        if (!resp.ok) throw new Error('Не удалось сохранить шаблон');
        return resp.json();
      })
      .then(function () {
        el('orgScheduleTemplateHint').textContent = 'Сохранено.';
        loadTemplates();
      })
      .catch(function (err) {
        el('orgScheduleTemplateHint').textContent = err.message || 'Не удалось сохранить шаблон';
      })
      .finally(function () {
        saveBtn.disabled = false;
      });
  }

  function applyWeek(weekStartDate) {
    fetch('/api/webapp/org/schedule/apply-week', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
      body: JSON.stringify({
        trainer_id: state.selectedTrainerId,
        week_start: formatDate(weekStartDate),
      }),
    })
      .then(function (resp) {
        if (resp.status === 403) throw new Error('Только владелец школы может применять шаблон.');
        if (!resp.ok) throw new Error('Не удалось применить шаблон на неделю');
        return resp.json();
      })
      .then(function (data) {
        el('orgScheduleTemplateHint').textContent = 'Создано слотов: ' + (data.slots_created != null ? data.slots_created : 0);
        if (formatDate(weekStartDate) === formatDate(state.weekStart)) loadSchedule();
      })
      .catch(function (err) {
        el('orgScheduleTemplateHint').textContent = err.message || 'Не удалось применить шаблон';
      });
  }

  function prevWeek() {
    closePanel();
    state.weekStart = new Date(state.weekStart.getTime() - 7 * 24 * 60 * 60 * 1000);
    loadSchedule();
  }

  function nextWeek() {
    closePanel();
    state.weekStart = new Date(state.weekStart.getTime() + 7 * 24 * 60 * 60 * 1000);
    loadSchedule();
  }

  var backBtn = el('orgScheduleBack');
  if (backBtn) {
    backBtn.addEventListener('click', function () {
      window.location.href = 'org-home';
    });
  }

  var retryBtn = el('orgScheduleRetry');
  if (retryBtn) retryBtn.addEventListener('click', loadTeam);

  var prevBtn = el('orgSchedulePrevWeek');
  if (prevBtn) prevBtn.addEventListener('click', prevWeek);

  var nextBtn = el('orgScheduleNextWeek');
  if (nextBtn) nextBtn.addEventListener('click', nextWeek);

  var panelCancelBtn = el('orgSchedulePanelCancel');
  if (panelCancelBtn) panelCancelBtn.addEventListener('click', closePanel);

  var panelSaveBtn = el('orgSchedulePanelSave');
  if (panelSaveBtn) panelSaveBtn.addEventListener('click', saveNewSlots);

  var durationSelect = el('orgSchedulePanelDuration');
  if (durationSelect) durationSelect.addEventListener('change', renderHourGrid);

  var templateOpenBtn = el('orgScheduleTemplateOpen');
  if (templateOpenBtn) templateOpenBtn.addEventListener('click', openTemplatePanel);

  var templateCloseBtn = el('orgScheduleTemplateClose');
  if (templateCloseBtn) templateCloseBtn.addEventListener('click', closeTemplatePanel);

  var templateSaveDayBtn = el('orgScheduleTemplateSaveDay');
  if (templateSaveDayBtn) templateSaveDayBtn.addEventListener('click', saveTemplateDay);

  var templateDurationSelect = el('orgScheduleTemplateDuration');
  if (templateDurationSelect) templateDurationSelect.addEventListener('change', renderTemplateGrid);

  var applyThisWeekBtn = el('orgScheduleApplyThisWeek');
  if (applyThisWeekBtn) applyThisWeekBtn.addEventListener('click', function () {
    applyWeek(state.weekStart);
  });

  var applyNextWeekBtn = el('orgScheduleApplyNextWeek');
  if (applyNextWeekBtn) applyNextWeekBtn.addEventListener('click', function () {
    applyWeek(new Date(state.weekStart.getTime() + 7 * 24 * 60 * 60 * 1000));
  });

  if (window.MiniAppRuntime && typeof window.MiniAppRuntime.ready === 'function') {
    window.MiniAppRuntime.ready();
  }

  loadTeam();
})();
