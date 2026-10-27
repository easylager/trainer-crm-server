/**
 * «Первые три ученика» (TASK-310) — карточка хаба и лист «Ученик 1 из 3».
 *
 * Сразу после расписания хаб просит не «отправьте ссылку», а добавить учеников, с которыми тренер уже занимается:
 * имя (телефон по желанию) и ближайшее окно этой же недели. Ученику ничего устанавливать не нужно,
 * бот он подключит позже по личной ссылке. Хаб отдаёт сюда только транспорт (get/post),
 * тост и отбой — сама карточка ничего о trainer-home-main.js не знает.
 */
(function (global) {
  'use strict';

  var M = global.TrainerFirstStudentsModel;
  var STATE_PATH = '/trainer/first-students';

  var opts = null;
  var host = null;
  var state = null;
  var loading = null;
  var justFinished = false;
  /* Ученик добавлен в этом сеансе — карточка держит прогресс, даже если инбокс хаба собран
     из старого снимка (день ноль: снимок был до расписания, строки first_students в нём нет). */
  var touched = false;
  var sheet = null;
  var mode = 'one';
  var busy = false;
  var lastAdded = '';
  var lastWarning = false;
  var bindLinks = {};

  /** Валюта тренера (из /trainer/access): рубли — Россия, иначе Беларусь. */
  function trainerCurrency() {
    return global.TrainerFormat && global.TrainerFormat.currencyCode ? global.TrainerFormat.currencyCode() : 'BYN';
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function haptic(kind) {
    try {
      var hf = global.Telegram && global.Telegram.WebApp && global.Telegram.WebApp.HapticFeedback;
      if (!hf) return;
      if (kind === 'select') hf.selectionChanged();
      else hf.notificationOccurred(kind);
    } catch (e) {}
  }

  /* Встроенный тост хаба (не showAlert): подтверждение не должно требовать «ОК». */
  function notify(title, text, kind) {
    if (opts && typeof opts.notify === 'function') opts.notify(title, text, kind || 'success');
    else if (opts && typeof opts.toast === 'function') opts.toast([title, text].filter(Boolean).join('. '));
  }

  function load() {
    if (loading) return loading;
    loading = opts
      .get(STATE_PATH)
      .then(function (data) {
        state = data;
        return data;
      })
      .then(
        function (data) {
          loading = null;
          return data;
        },
        function (err) {
          loading = null;
          throw err;
        }
      );
    return loading;
  }

  /* ---------- карточка ---------- */

  function seatHtml(seat) {
    if (seat.filled) {
      return (
        '<div class="tfs-seat tfs-seat--on">' +
        '<span class="tfs-ava" aria-hidden="true">' + esc(seat.initials) + '</span>' +
        '<span class="tfs-seat__name">' + esc(seat.name) + '</span>' +
        '</div>'
      );
    }
    return (
      '<button type="button" class="tfs-seat" data-tfs="add" aria-label="Добавить ученика">' +
      '<span class="tfs-seat__plus" aria-hidden="true">+</span>' +
      '<span class="tfs-seat__name">ученик</span>' +
      '</button>'
    );
  }

  function progressHtml() {
    var left = M.remaining(state);
    /* Не «Ещё 2» / «Остался один»: так звучало, будто учеников можно только трое (TASK-313). */
    var kicker = state.count > 0 ? M.addedKicker(state) : 'Следующий шаг';
    void left;
    return (
      '<div class="tfs-card">' +
      '<div class="tfs-card__head">' +
      '<span class="tfs-kicker">' + esc(kicker) + '</span>' +
      '<button type="button" class="tfs-x" data-tfs="dismiss" aria-label="Скрыть">×</button>' +
      '</div>' +
      (state.count > 0
        ? ''
        : '<h2 class="tfs-title">Добавьте учеников, с которыми уже занимаетесь</h2>' +
          '<p class="tfs-lead">' + esc(M.cardLead(state)) + '</p>') +
      '<div class="tfs-seats">' + M.seats(state).map(seatHtml).join('') + '</div>' +
      '<button type="button" class="btn-block btn-primary tfs-cta" data-tfs="add">' + esc(M.addButtonLabel(state)) + '</button>' +
      '<div class="tfs-links">' +
      '<button type="button" class="tfs-link" data-tfs="paste">Вставить список из заметок</button>' +
      '<button type="button" class="tfs-link tfs-link--quiet" data-tfs="share">Позвать по ссылке</button>' +
      '</div>' +
      '</div>'
    );
  }

  function doneHtml() {
    var students = state.students || [];
    var works = M.doneWorks(state);
    var noBot = students.filter(function (s) { return !s.has_bot; });
    var rows = noBot
      .map(function (s) {
        return (
          '<div class="tfs-row">' +
          '<span class="tfs-ava" aria-hidden="true">' + esc(s.initials) + '</span>' +
          '<span class="tfs-row__who"><b>' + esc(s.name) + '</b>' +
          '<span>' + esc(s.next_label || 'без записи') + '</span></span>' +
          '<button type="button" class="tfs-chipbtn" data-tfs="bind" data-client="' + esc(s.client_id) + '">Отправить</button>' +
          '</div>'
        );
      })
      .join('');
    return (
      '<div class="tfs-card">' +
      '<div class="tfs-card__head">' +
      '<span class="tfs-kicker">' + esc(M.doneKicker(state)) + '</span>' +
      '<button type="button" class="tfs-x" data-tfs="close" aria-label="Скрыть">×</button>' +
      '</div>' +
      '<ul class="tfs-works">' + works.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul>' +
      (rows
        ? '<h2 class="tfs-title tfs-title--sm">Пусть напоминания приходят и ученикам</h2>' +
          '<p class="tfs-lead">Отправьте каждому его ссылку: он откроет бот один раз и будет видеть свои тренировки.</p>' +
          '<div class="tfs-rows">' + rows + '</div>'
        : '') +
      '</div>'
    );
  }

  function renderCard() {
    if (!host || !state) return;
    var finished = state.count >= state.goal;
    if (finished && !justFinished) {
      hide();
      return;
    }
    host.innerHTML = finished ? doneHtml() : progressHtml();
    host.removeAttribute('hidden');
    if (finished) prefetchBindLinks();
  }

  function hide() {
    if (!host) return;
    host.setAttribute('hidden', '');
    host.innerHTML = '';
  }

  /* ---------- личные ссылки ученикам ---------- */

  function prefetchBindLinks() {
    (state.students || []).forEach(function (s) {
      if (s.has_bot || bindLinks[s.client_id]) return;
      bindLinks[s.client_id] = { pending: true };
      opts
        .get('/trainer/clients/' + encodeURIComponent(s.client_id) + '/welcome-link')
        .then(function (data) {
          bindLinks[s.client_id] = { link: (data && data.welcome_link) || '' };
        })
        .catch(function () {
          delete bindLinks[s.client_id];
        });
    });
  }

  function shareBind(clientId, btn) {
    var entry = bindLinks[clientId];
    var link = entry && entry.link;
    if (!link) {
      notify('Ссылка ещё готовится', 'Нажмите ещё раз через секунду.', 'warning');
      prefetchBindLinks();
      return;
    }
    var student = (state.students || []).filter(function (s) { return String(s.client_id) === String(clientId); })[0];
    var body = M.inviteMessage(student);
    var opened = false;
    if (typeof global.openTelegramShareUrlFromMiniApp === 'function') {
      opened = !!global.openTelegramShareUrlFromMiniApp({ shareUrl: link, shareBody: body, fullMessage: body + '\n' + link });
    }
    if (!opened && global.navigator && navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(link).then(function () { notify('Ссылка скопирована', 'Вставьте её в чат с учеником.'); });
    }
    if (btn) {
      btn.textContent = 'Отправлено';
      btn.classList.add('tfs-chipbtn--done');
    }
  }

  /* ---------- лист ---------- */

  function ensureSheet() {
    if (sheet) return sheet;
    sheet = document.createElement('div');
    sheet.className = 'tfs-overlay';
    sheet.setAttribute('hidden', '');
    sheet.innerHTML =
      '<div class="tfs-sheet" role="dialog" aria-modal="true" aria-labelledby="tfsSheetTitle">' +
      '<div class="tfs-sheet__handle" aria-hidden="true"></div>' +
      '<button type="button" class="tfs-sheet__close" data-tfs="close" aria-label="Закрыть">' +
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
      '</button>' +
      '<div class="tfs-sheet__body" id="tfsSheetBody"></div>' +
      '</div>';
    document.body.appendChild(sheet);
    sheet.addEventListener('click', function (ev) {
      if (ev.target === sheet) close();
    });
    sheet.addEventListener('click', onSheetClick);
    bindSheetDrag(sheet.querySelector('.tfs-sheet'));
    sheet.addEventListener('input', onSheetInput);
    /* Курсор в поле телефона — после готового кода страны, чтобы он не оказался перед «+7». */
    sheet.addEventListener('focusin', function (ev) {
      var t = ev.target;
      if (!t || t.id !== 'tfsPhone') return;
      setTimeout(function () {
        try { t.setSelectionRange(t.value.length, t.value.length); } catch (e) { /* type=tel не везде умеет */ }
      }, 0);
    });
    sheet.addEventListener('submit', function (ev) {
      ev.preventDefault();
      submit();
    });
    return sheet;
  }

  /*
   * На телефоне лист занимает почти весь экран: тапнуть мимо негде, а свайп вниз забирал
   * Telegram и сворачивал всё приложение. Поэтому три выхода: крестик, «Назад» Telegram и
   * свайп вниз за верх листа (вертикальные свайпы Telegram на это время выключены).
   */
  function tgApp() {
    return global.Telegram && global.Telegram.WebApp ? global.Telegram.WebApp : null;
  }

  var backWasVisible = false;

  function onTgBack() { close(); }

  function holdTelegram(on) {
    var tg = tgApp();
    if (!tg) return;
    try {
      if (on) {
        if (typeof tg.disableVerticalSwipes === 'function') tg.disableVerticalSwipes();
        if (tg.BackButton) {
          backWasVisible = !!tg.BackButton.isVisible;
          tg.BackButton.onClick(onTgBack);
          tg.BackButton.show();
        }
      } else {
        if (typeof tg.enableVerticalSwipes === 'function') tg.enableVerticalSwipes();
        if (tg.BackButton) {
          tg.BackButton.offClick(onTgBack);
          if (!backWasVisible) tg.BackButton.hide();
        }
      }
    } catch (e) { /* старые клиенты */ }
  }

  function bindSheetDrag(panel) {
    if (!panel) return;
    var startY = null;
    var dy = 0;
    panel.addEventListener('touchstart', function (ev) {
      /* Тянуть можно, только когда лист прокручен к началу, — иначе это обычная прокрутка. */
      if (panel.scrollTop > 0 || !ev.touches || ev.touches.length !== 1) { startY = null; return; }
      var t = ev.target;
      if (t && t.closest && t.closest('input, textarea, select')) { startY = null; return; }
      startY = ev.touches[0].clientY;
      dy = 0;
      panel.style.transition = 'none';
    }, { passive: true });
    panel.addEventListener('touchmove', function (ev) {
      if (startY == null) return;
      dy = Math.max(0, ev.touches[0].clientY - startY);
      if (dy > 0) panel.style.transform = 'translateY(' + dy + 'px)';
    }, { passive: true });
    var end = function () {
      if (startY == null) return;
      startY = null;
      panel.style.transition = 'transform 0.2s ease';
      if (dy > 90) {
        panel.style.transform = 'translateY(100%)';
        setTimeout(function () {
          close();
          panel.style.transition = '';
          panel.style.transform = '';
        }, 180);
      } else {
        panel.style.transform = '';
      }
      dy = 0;
    };
    panel.addEventListener('touchend', end);
    panel.addEventListener('touchcancel', end);
  }

  function optionChips() {
    var options = (state && state.options) || [];
    var chips = options.map(function (o, i) {
      return (
        '<button type="button" class="tfs-chip' + (i === 0 ? ' tfs-chip--on' : '') + '" data-tfs="slot" data-slot="' + esc(o.slot_id) + '" aria-pressed="' + (i === 0) + '">' +
        esc(o.label) +
        '</button>'
      );
    });
    chips.push(
      '<button type="button" class="tfs-chip' + (options.length ? '' : ' tfs-chip--on') + '" data-tfs="slot" data-slot="" aria-pressed="' + !options.length + '">Без записи</button>'
    );
    return chips.join('');
  }

  /* Две и больше услуг — тренер выбирает, что это за занятие. По умолчанию — услуга самого окна
     (если шаблон её знает), иначе первая очная: так запись сразу правильная, без похода в расписание. */
  function serviceFieldHtml(hasOptions) {
    var services = (state && state.services) || [];
    if (services.length < 2) return '';
    var first = ((state && state.options) || [])[0];
    var def = M.defaultServiceId(state, first ? first.slot_id : null);
    return (
      '<div class="tfs-field" id="tfsSvcRow"' + (hasOptions ? '' : ' hidden') + '><span>Занятие</span>' +
      '<div class="tfs-chips" id="tfsSvc">' +
      services
        .map(function (s) {
          var on = s.service_id === def;
          return (
            '<button type="button" class="tfs-chip' + (on ? ' tfs-chip--on' : '') + '" data-tfs="svc" data-svc="' + esc(s.service_id) + '" aria-pressed="' + on + '">' +
            esc(s.name) + '</button>'
          );
        })
        .join('') +
      '</div></div>'
    );
  }

  function pickChip(groupSel, chip) {
    var group = sheet.querySelector(groupSel);
    if (!group) return;
    group.querySelectorAll('.tfs-chip').forEach(function (c) {
      var on = c === chip;
      c.classList.toggle('tfs-chip--on', on);
      c.setAttribute('aria-pressed', String(on));
    });
  }

  function oneFormHtml() {
    var hasOptions = !!((state && state.options) || []).length;
    return (
      (lastAdded ? '<p class="tfs-added' + (lastWarning ? ' tfs-added--warn' : '') + '" role="status">' + esc(lastAdded) + '</p>' : '') +
      '<h2 class="tfs-sheet__title" id="tfsSheetTitle">' + esc(M.sheetTitle(state)) + '</h2>' +
      '<form class="tfs-form" novalidate>' +
      '<label class="tfs-field"><span>Имя</span>' +
      '<input id="tfsName" type="text" autocomplete="off" maxlength="64" placeholder="Имя и фамилия" required /></label>' +
      '<label class="tfs-field"><span>Телефон — если хотите звонить из приложения</span>' +
      '<input id="tfsPhone" type="tel" autocomplete="off" inputmode="tel" value="' + esc(M.phonePrefix(trainerCurrency())) + '" placeholder="' + (trainerCurrency() === 'RUB' ? '+7 912 …' : '+375 29 …') + '" /></label>' +
      '<div class="tfs-field"><span>' + esc(M.slotFieldLabel(state)) + '</span>' +
      '<div class="tfs-chips" id="tfsChips">' + optionChips() + '</div></div>' +
      serviceFieldHtml(hasOptions) +
      '<label class="tfs-toggle" id="tfsWeeklyRow"' + (hasOptions ? '' : ' hidden') + '><span>Каждую неделю в это время</span>' +
      '<input id="tfsWeekly" type="checkbox" checked /></label>' +
      '<p class="tfs-error" id="tfsError" hidden></p>' +
      '<button type="submit" class="btn-block btn-primary" id="tfsSubmit">' + (hasOptions ? 'Добавить и записать' : 'Добавить') + '</button>' +
      (state && state.count > 0
        ? '<button type="button" class="btn-block btn-secondary" data-tfs="close">Готово</button>'
        : '<button type="button" class="tfs-link" data-tfs="paste">Вставить список из заметок</button>') +
      '</form>'
    );
  }

  function pasteFormHtml() {
    return (
      '<h2 class="tfs-sheet__title" id="tfsSheetTitle">Список учеников</h2>' +
      '<p class="tfs-lead">Вставьте из заметок или переписки — по одному на строку. Телефон можно не писать.</p>' +
      '<form class="tfs-form" novalidate>' +
      '<textarea id="tfsPaste" rows="5" placeholder="' + esc('Маша Ковалёва ' + (trainerCurrency() === 'RUB' ? '+7 912 111-22-33' : '+375 29 111-22-33')) + '&#10;Даня&#10;Лиза ' + (trainerCurrency() === 'RUB' ? '912 444 55 66' : '29 444 55 66') + '"></textarea>' +
      '<p class="tfs-preview" id="tfsPreview" aria-live="polite"></p>' +
      '<p class="tfs-error" id="tfsError" hidden></p>' +
      '<button type="submit" class="btn-block btn-primary" id="tfsSubmit" disabled>Добавить</button>' +
      '<button type="button" class="tfs-link" data-tfs="one">По одному</button>' +
      '</form>'
    );
  }

  function renderSheet() {
    var body = ensureSheet().querySelector('#tfsSheetBody');
    body.innerHTML = mode === 'paste' ? pasteFormHtml() : oneFormHtml();
  }

  function open(nextMode) {
    if (!opts) return;
    mode = nextMode || 'one';
    lastAdded = '';
    lastWarning = false;
    var go = function () {
      renderSheet();
      sheet.removeAttribute('hidden');
      document.body.classList.add('tfs-sheet-open');
      holdTelegram(true);
      var focus = sheet.querySelector(mode === 'paste' ? '#tfsPaste' : '#tfsName');
      if (focus) {
        try { focus.focus({ preventScroll: true }); } catch (e) { focus.focus(); }
      }
    };
    if (state) {
      go();
      return;
    }
    load().then(go, function () {
      notify('Не получилось открыть', 'Проверьте связь и попробуйте ещё раз.', 'warning');
    });
  }

  function close() {
    if (!sheet) return;
    if (sheet.hasAttribute('hidden')) return;
    sheet.setAttribute('hidden', '');
    document.body.classList.remove('tfs-sheet-open');
    holdTelegram(false);
    renderCard();
    if (opts && typeof opts.onChanged === 'function') opts.onChanged(state);
  }

  function showError(msg) {
    var el = sheet && sheet.querySelector('#tfsError');
    if (!el) return;
    el.textContent = msg;
    el.removeAttribute('hidden');
    haptic('error');
  }

  function setBusy(on) {
    busy = !!on;
    var btn = sheet && sheet.querySelector('#tfsSubmit');
    if (btn) btn.disabled = busy;
    if (sheet) sheet.classList.toggle('tfs-overlay--busy', busy);
  }

  function selectedSlot() {
    var on = sheet.querySelector('#tfsChips .tfs-chip--on');
    var v = on ? on.getAttribute('data-slot') : '';
    return v ? parseInt(v, 10) : null;
  }

  function selectedService() {
    var on = sheet.querySelector('#tfsSvc .tfs-chip--on');
    return on ? parseInt(on.getAttribute('data-svc'), 10) : null;
  }

  function onSheetClick(ev) {
    var el = ev.target.closest('[data-tfs]');
    if (!el || !sheet.contains(el)) return;
    var act = el.getAttribute('data-tfs');
    if (act === 'svc') {
      pickChip('#tfsSvc', el);
      haptic('select');
    } else if (act === 'slot') {
      pickChip('#tfsChips', el);
      var withSlot = !!el.getAttribute('data-slot');
      var row = sheet.querySelector('#tfsWeeklyRow');
      if (row) row.hidden = !withSlot;
      var svcRow = sheet.querySelector('#tfsSvcRow');
      if (svcRow) svcRow.hidden = !withSlot;
      if (withSlot) {
        var own = M.defaultServiceId(state, parseInt(el.getAttribute('data-slot'), 10));
        var svcChip = own != null && sheet.querySelector('#tfsSvc [data-svc="' + own + '"]');
        if (svcChip) pickChip('#tfsSvc', svcChip);
      }
      var btn = sheet.querySelector('#tfsSubmit');
      if (btn) btn.textContent = withSlot ? 'Добавить и записать' : 'Добавить';
      haptic('select');
    } else if (act === 'close') {
      close();
    } else if (act === 'paste' || act === 'one') {
      mode = act;
      renderSheet();
    }
  }

  function onSheetInput(ev) {
    if (ev.target && ev.target.id === 'tfsPaste') {
      var rows = M.parseStudentList(ev.target.value);
      var prev = sheet.querySelector('#tfsPreview');
      var btn = sheet.querySelector('#tfsSubmit');
      if (prev) {
        prev.textContent = rows.length
          ? 'Нашли ' + rows.length + ': ' + rows.slice(0, 6).map(function (r) {
              return (r.first_name + (r.last_name ? ' ' + r.last_name : '')) + (r.phone ? ' · ' + r.phone : '');
            }).join(', ') + (rows.length > 6 ? '…' : '')
          : '';
      }
      if (btn) {
        btn.disabled = !rows.length;
        btn.textContent = rows.length ? 'Добавить ' + rows.length : 'Добавить';
      }
    }
    var err = sheet.querySelector('#tfsError');
    if (err) err.setAttribute('hidden', '');
  }

  function splitName(full) {
    var parts = String(full || '').trim().replace(/\s+/g, ' ').split(' ');
    return { first: parts.shift() || '', last: parts.join(' ') };
  }

  function submit() {
    if (busy) return;
    if (mode === 'paste') return submitPaste();
    var name = splitName(sheet.querySelector('#tfsName').value);
    if (!name.first) {
      showError('Впишите имя ученика.');
      return;
    }
    var slotId = selectedSlot();
    var weeklyEl = sheet.querySelector('#tfsWeekly');
    var body = {
      first_name: name.first,
      last_name: name.last,
      phone: M.phoneForSave(sheet.querySelector('#tfsPhone').value, trainerCurrency()),
      slot_id: slotId,
      service_id: slotId ? selectedService() : null,
      weekly: !!(slotId && weeklyEl && weeklyEl.checked),
    };
    setBusy(true);
    opts
      .post(STATE_PATH, body)
      .then(function (res) {
        setBusy(false);
        state = res.state;
        touched = true;
        haptic(res.warning ? 'warning' : 'success');
        lastWarning = !!res.warning;
        lastAdded = res.warning
          ? res.warning
          : res.booked_label
            ? '✓ ' + name.first + ' — ' + res.booked_label + (res.weekly ? ', каждую неделю' : '')
            : '✓ ' + name.first + ' — в списке, без записи';
        if (state.count >= state.goal) {
          justFinished = true;
          close();
          notify(res.warning ? 'Ученик добавлен' : 'Готово', lastAdded.replace('✓ ', ''), res.warning ? 'warning' : 'success');
          return;
        }
        renderSheet();
        renderCard();
        var focus = sheet.querySelector('#tfsName');
        if (focus) focus.focus();
      })
      .catch(function (err) {
        setBusy(false);
        showError(M.errorText(err, trainerCurrency()));
      });
  }

  function submitPaste() {
    var rows = M.parseStudentList(sheet.querySelector('#tfsPaste').value);
    if (!rows.length) {
      showError('Не нашли ни одного имени.');
      return;
    }
    setBusy(true);
    var added = 0;
    var failed = [];
    var chain = Promise.resolve();
    rows.forEach(function (r) {
      chain = chain.then(function () {
        return opts
          .post(STATE_PATH, { first_name: r.first_name, last_name: r.last_name, phone: r.phone || null })
          .then(function (res) {
            added += 1;
            touched = true;
            state = res.state;
          })
          .catch(function () {
            failed.push(r.first_name);
          });
      });
    });
    chain.then(function () {
      setBusy(false);
      if (!added) {
        showError('Не получилось добавить. Проверьте номера телефонов.');
        return;
      }
      haptic(failed.length ? 'warning' : 'success');
      notify(
        'Добавили ' + added + ' ' + M.plural(added, 'ученика', 'ученика', 'учеников'),
        (failed.length ? 'Не получилось: ' + failed.join(', ') + '. ' : '') + 'Записать их на время можно в расписании.',
        failed.length ? 'warning' : 'success'
      );
      if (state.count >= state.goal) justFinished = true;
      close();
    });
  }

  /* ---------- вход ---------- */

  function onHostClick(ev) {
    var el = ev.target.closest('[data-tfs]');
    if (!el || !host.contains(el)) return;
    var act = el.getAttribute('data-tfs');
    if (act === 'add') open('one');
    else if (act === 'paste') open('paste');
    else if (act === 'share') {
      if (typeof opts.shareLink === 'function') opts.shareLink();
    } else if (act === 'dismiss') {
      touched = false;
      hide();
      if (typeof opts.dismiss === 'function') opts.dismiss();
    } else if (act === 'close') {
      justFinished = false;
      touched = false;
      hide();
    } else if (act === 'bind') {
      shareBind(el.getAttribute('data-client'), el);
    }
  }

  /** Хаб вызывает, когда сервер прислал строку first_students (или убрал её). */
  function sync(visible) {
    if (!host) return;
    if (!visible && !justFinished && !touched) {
      hide();
      return;
    }
    if (state) {
      renderCard();
      return;
    }
    load().then(renderCard, hide);
  }

  function mount(options) {
    opts = options || {};
    host = opts.host || null;
    if (host && !host.dataset.tfsWired) {
      host.dataset.tfsWired = '1';
      host.addEventListener('click', onHostClick);
    }
  }

  global.TrainerFirstStudents = { mount: mount, sync: sync, open: open, close: close };
})(typeof window !== 'undefined' ? window : globalThis);
