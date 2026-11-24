/* TASK-446: лист отметки «Я здесь» (макет C). window.GlideCheckin.open(opts).
   opts = {session_id, arena_name, checkin_id?, load_level?, season_days?, streak_weeks?, onDone}.
   POST /client/checkins при открытии, если checkin_id нет; PATCH по тапу оценки;
   «Позвать сюда» — POST share → shareMessage / openTelegramLink fallback. */
(function () {
  'use strict';
  var dim = null, sheet = null, state = null;

  function tg() { return window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null; }
  function haptic(kind, arg) {
    var t = tg();
    if (!t || !t.HapticFeedback) return;
    try {
      if (kind === 'sel') t.HapticFeedback.selectionChanged();
      else if (kind === 'ok') t.HapticFeedback.notificationOccurred('success');
      else if (kind === 'err') t.HapticFeedback.notificationOccurred('error');
      else t.HapticFeedback.impactOccurred(arg || 'light');
    } catch (e) { /* тишина */ }
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function headers() {
    var h = { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': (tg() && tg().initData) || '' };
    if (window.GlideProfileId) h['X-Profile-Id'] = String(window.GlideProfileId);
    return h;
  }
  function api(method, path, body) {
    return fetch('/api/webapp' + path, {
      method: method, headers: headers(), body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, status: r.status, json: j }; });
    });
  }
  function pluralWeek(n) {
    var n10 = n % 10, n100 = n % 100;
    if (n10 === 1 && n100 !== 11) return 'неделя';
    if (n10 >= 2 && n10 <= 4 && !(n100 >= 12 && n100 <= 14)) return 'недели';
    return 'недель';
  }
  function weekPills(streak) {
    var out = '';
    var n = Math.min(4, Math.max(1, streak));
    for (var i = 0; i < 4; i++) out += '<i class="' + (i < n ? 'on' : '') + '"></i>';
    return out;
  }
  function errText(code) {
    if (code === 'not_ongoing') return 'Сеанс уже закончился';
    if (code === 'daily_limit') return 'Сегодня уже три отметки — хватит на сегодня';
    return 'Не получилось отметиться. Попробуйте ещё раз';
  }
  function codeOf(resp) {
    var d = resp && resp.json && resp.json.detail;
    return d && d.code ? d.code : '';
  }

  function ensureDom() {
    if (dim) return;
    dim = document.createElement('div');
    dim.className = 'cis-dim';
    dim.hidden = true;
    sheet = document.createElement('div');
    sheet.className = 'cis';
    sheet.setAttribute('role', 'dialog');
    sheet.hidden = true;
    document.body.appendChild(dim);
    document.body.appendChild(sheet);
    dim.addEventListener('click', close);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !sheet.hidden) close();
    });
    /* Свайп вниз за ручку — закрыть. */
    var startY = null;
    sheet.addEventListener('touchstart', function (e) { startY = e.touches[0].clientY; }, { passive: true });
    sheet.addEventListener('touchend', function (e) {
      if (startY === null) return;
      if (e.changedTouches[0].clientY - startY > 64) close();
      startY = null;
    }, { passive: true });
  }

  function render() {
    var st = state;
    var lvl = st.load_level;
    var nth = st.season_days ? esc(st.arena_name) + ' · ' + st.season_days + '-й раз за сезон' : esc(st.arena_name);
    var streakRow = '';
    if (st.streak_weeks) {
      streakRow =
        '<div class="cis__streak">' +
          '<svg class="cis__streak-ic" viewBox="0 0 24 24" fill="none"><path d="M12 3c2 4-3 5-3 9a3 3 0 006 0c0-2-1-3-1-3s4 2 4 6a6 6 0 11-12 0c0-6 6-8 6-12z" style="fill:currentColor"/></svg>' +
          '<div><div class="cis__streak-t">Серия: ' + st.streak_weeks + ' ' + pluralWeek(st.streak_weeks) + ' подряд</div>' +
          '<div class="cis__streak-s">Отмечайся каждую неделю — серия растёт</div></div>' +
          '<div class="cis__weeks">' + weekPills(st.streak_weeks) + '</div>' +
        '</div>';
    }
    sheet.innerHTML =
      '<div class="cis__grip"></div>' +
      '<div class="cis__done-row">' +
        '<div class="cis__check"><svg viewBox="0 0 24 24" fill="none"><path d="M5 12.5l4.5 4.5L19 7.5" style="fill:none;stroke:#15803d;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round"/></svg></div>' +
        '<div><div class="cis__title">Отмечено</div><div class="cis__sub">' + nth + '</div></div>' +
      '</div>' +
      '<div class="cis__err" hidden></div>' +
      '<div class="cis__q">Сколько сейчас народу?</div>' +
      '<div class="cis__hint">Увидят все, кто выбирает, куда ехать</div>' +
      '<div class="cis__levels">' +
        '<button type="button" class="cis__lvl' + (lvl === 1 ? ' cis-sel' : '') + '" data-level="1"><span class="cis__bars"><i></i><i></i><i></i></span>Свободно</button>' +
        '<button type="button" class="cis__lvl' + (lvl === 2 ? ' cis-sel' : '') + '" data-level="2"><span class="cis__bars"><i></i><i></i><i></i></span>В меру</button>' +
        '<button type="button" class="cis__lvl' + (lvl === 3 ? ' cis-sel' : '') + '" data-level="3"><span class="cis__bars"><i></i><i></i><i></i></span>Людно</button>' +
      '</div>' +
      streakRow +
      '<button type="button" class="cis__share">Позвать сюда</button>' +
      '<button type="button" class="cis__close">Готово</button>';
    sheet.querySelectorAll('.cis__lvl').forEach(function (b) {
      b.addEventListener('click', function () { pickLevel(parseInt(b.getAttribute('data-level'), 10)); });
    });
    sheet.querySelector('.cis__share').addEventListener('click', share);
    sheet.querySelector('.cis__close').addEventListener('click', close);
  }

  function showErr(text) {
    var el = sheet.querySelector('.cis__err');
    if (!el) return;
    if (!text) { el.hidden = true; return; }
    el.textContent = text;
    el.hidden = false;
  }

  function pickLevel(level) {
    if (!state || !state.checkin_id || state.load_level) {
      if (state && state.load_level) return; // оценка ставится один раз
      return;
    }
    var prev = state.load_level;
    state.load_level = level;
    sheet.querySelectorAll('.cis__lvl').forEach(function (b) {
      b.classList.toggle('cis-sel', parseInt(b.getAttribute('data-level'), 10) === level);
    });
    haptic('sel');
    api('PATCH', '/client/checkins/' + state.checkin_id, { load_level: level }).then(function (r) {
      if (r.ok) {
        if (state.onLive && r.json && r.json.live) state.onLive(r.json.live);
        return;
      }
      state.load_level = prev;
      sheet.querySelectorAll('.cis__lvl').forEach(function (b) {
        b.classList.toggle('cis-sel', parseInt(b.getAttribute('data-level'), 10) === prev);
      });
      haptic('err');
      showErr(errText(codeOf(r)) === 'Не получилось отметиться. Попробуйте ещё раз'
        ? 'Не сохранилась оценка. Попробуйте ещё раз' : errText(codeOf(r)));
    }).catch(function () {
      state.load_level = prev;
      haptic('err');
      showErr('Нет сети — оценка не сохранилась');
    });
  }

  function share() {
    var st = state;
    if (!st || !st.checkin_id) return;
    var btn = sheet.querySelector('.cis__share');
    btn.disabled = true;
    api('POST', '/client/checkins/' + st.checkin_id + '/share').then(function (r) {
      btn.disabled = false;
      if (!r.ok) { haptic('err'); showErr('Не получилось собрать сообщение'); return; }
      haptic('tap');
      var t = tg();
      var id = r.json && r.json.prepared_message_id;
      if (t && id && typeof t.isVersionAtLeast === 'function' && t.isVersionAtLeast('8.0') && typeof t.shareMessage === 'function') {
        t.shareMessage(id, function () {});
      } else if (t && r.json && r.json.share_url && typeof t.openTelegramLink === 'function') {
        t.openTelegramLink(r.json.share_url);
      } else if (r.json && r.json.share_url) {
        window.open(r.json.share_url, '_blank');
      }
    }).catch(function () {
      btn.disabled = false;
      haptic('err');
      showErr('Нет сети — не получилось собрать сообщение');
    });
  }

  function close() {
    if (!dim) return;
    dim.classList.remove('cis-on');
    sheet.classList.remove('cis-on');
    var done = state && state.onDone;
    state = null;
    setTimeout(function () { dim.hidden = true; sheet.hidden = true; }, 260);
    if (typeof done === 'function') done();
  }

  function open(opts) {
    ensureDom();
    opts = opts || {};
    state = {
      session_id: opts.session_id,
      arena_name: opts.arena_name || 'катке',
      checkin_id: opts.checkin_id || null,
      load_level: opts.load_level || null,
      season_days: opts.season_days || null,
      streak_weeks: opts.streak_weeks || null,
      onDone: opts.onDone || null,
      onLive: opts.onLive || null,
    };
    render();
    dim.hidden = false;
    sheet.hidden = false;
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        dim.classList.add('cis-on');
        sheet.classList.add('cis-on');
      });
    });
    if (!state.checkin_id && state.session_id) {
      api('POST', '/client/checkins', { session_id: state.session_id }).then(function (r) {
        if (!state) return;
        if (r.ok && r.json) {
          state.checkin_id = r.json.checkin_id;
          state.season_days = r.json.season_days;
          state.streak_weeks = r.json.streak_weeks;
          state.load_level = r.json.load_level || state.load_level;
          haptic('ok');
          render();
          try {
            window.dispatchEvent(new CustomEvent('glide:checkin-done', {
              detail: { session_id: state.session_id, checkin_id: state.checkin_id, season_days: state.season_days },
            }));
          } catch (e) { /* старый WebView без CustomEvent — не страшно */ }
          return;
        }
        haptic('err');
        showErr(errText(codeOf(r)));
      }).catch(function () {
        if (!state) return;
        haptic('err');
        showErr('Нет сети — отметка не сохранилась');
      });
    }
  }

  window.GlideCheckin = { open: open, close: close };
})();
