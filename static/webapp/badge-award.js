/* TASK-451 (5.4): лист вручения значка (макет 19). window.GlideBadgeAward.open(opts).
   opts = {badges: [{key,name,family,total,next?}], onClose(keys)}.
   Несколько значков — листаются внутри одного листа; «Отправить другу» — жёлтая,
   «Позже» — тихая. Закрытие (любое) → onClose([keys]) — вызывающий шлёт seen.
   Арт — window.GlideBadgeArt (badge-art.js). */
(function () {
  'use strict';
  var dim = null, sheet = null, state = null;

  function tg() { return window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null; }
  function haptic(kind) {
    var t = tg();
    if (!t || !t.HapticFeedback) return;
    try {
      if (kind === 'ok') t.HapticFeedback.notificationOccurred('success');
      else t.HapticFeedback.impactOccurred('light');
    } catch (e) { /* тишина */ }
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function api(method, path, body) {
    var h = { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': (tg() && tg().initData) || '' };
    if (window.GlideProfileId) h['X-Profile-Id'] = String(window.GlideProfileId);
    return fetch('/api/webapp' + path, {
      method: method, headers: h, body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, status: r.status, json: j }; });
    });
  }
  function plural(n, one, few, many) {
    var n100 = Math.abs(n) % 100, n10 = n100 % 10;
    if (n10 === 1 && n100 !== 11) return one;
    if (n10 >= 2 && n10 <= 4 && !(n100 >= 12 && n100 <= 14)) return few;
    return many;
  }
  function unitWord(family, n) {
    if (family === 'streak') return plural(n, 'неделя', 'недели', 'недель');
    if (family === 'season') return plural(n, 'день', 'дня', 'дней');
    return '';
  }
  function subLine(b) {
    if (b.family === 'intro') return 'Первая отметка за сезон';
    if (b.family === 'streak') return b.total + ' ' + unitWord('streak', b.total) + ' подряд на льду';
    if (b.family === 'season') return b.total + ' ' + unitWord('season', b.total) + ' на льду за сезон';
    return '';
  }
  function nextLine(b) {
    var n = b && b.next;
    if (!n || !n.name || !n.remaining) return '';
    return 'Дальше — «' + esc(n.name) + '»: ещё ' + n.remaining + ' ' + unitWord(n.family, n.remaining);
  }
  function art(b) {
    var a = window.GlideBadgeArt || {};
    return a[b.key + '_earned'] || '';
  }

  function ensureDom() {
    if (dim) return;
    dim = document.createElement('div');
    dim.className = 'baw-dim';
    dim.hidden = true;
    sheet = document.createElement('div');
    sheet.className = 'baw';
    sheet.setAttribute('role', 'dialog');
    sheet.hidden = true;
    document.body.appendChild(dim);
    document.body.appendChild(sheet);
    dim.addEventListener('click', close);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !sheet.hidden) close();
    });
    /* Свайп вниз — закрыть; влево/вправо — листать значки. */
    var sx = null, sy = null;
    sheet.addEventListener('touchstart', function (e) {
      sx = e.touches[0].clientX; sy = e.touches[0].clientY;
    }, { passive: true });
    sheet.addEventListener('touchend', function (e) {
      if (sx === null) return;
      var dx = e.changedTouches[0].clientX - sx;
      var dy = e.changedTouches[0].clientY - sy;
      sx = null; sy = null;
      if (dy > 64 && Math.abs(dx) < 40) { close(); return; }
      if (Math.abs(dx) > 56 && state && state.badges.length > 1) {
        show(state.idx + (dx < 0 ? 1 : -1));
      }
    }, { passive: true });
  }

  function render() {
    var st = state, b = st.badges[st.idx];
    var pager = '';
    if (st.badges.length > 1) {
      var dots = '';
      for (var i = 0; i < st.badges.length; i++) dots += '<i class="' + (i === st.idx ? 'on' : '') + '"></i>';
      var left = st.badges.length - st.idx - 1;
      pager = '<div class="baw__pager">' + dots + '</div>' +
        (left > 0 ? '<div class="baw__more">ещё ' + left + '</div>' : '');
    }
    var nl = nextLine(b);
    sheet.innerHTML =
      '<div class="baw__grip"></div>' +
      '<div class="baw__stage">' +
        '<div class="baw__rays"></div>' +
        '<div class="baw__art">' + art(b) + '</div>' +
        '<div class="baw__snow"><i></i><i></i><i></i><i></i><i></i></div>' +
      '</div>' +
      '<div class="baw__new">Новый значок</div>' +
      '<div class="baw__name">' + esc(b.name) + '</div>' +
      '<div class="baw__sub">' + esc(subLine(b)) + '</div>' +
      (nl ? '<div class="baw__next">' + nl + '</div>' : '') +
      pager +
      '<button type="button" class="baw__share">Отправить другу</button>' +
      '<button type="button" class="baw__later">' +
        (st.badges.length - st.idx - 1 > 0 ? 'Смотреть дальше' : 'Позже') +
      '</button>';
    sheet.querySelector('.baw__share').addEventListener('click', share);
    sheet.querySelector('.baw__later').addEventListener('click', function () {
      if (state && state.badges.length - state.idx - 1 > 0) show(state.idx + 1);
      else close();
    });
  }

  function show(idx) {
    if (!state) return;
    state.idx = (idx + state.badges.length) % state.badges.length;
    sheet.classList.remove('baw-anim');
    render();
    /* перезапуск анимации появления */
    void sheet.offsetWidth;
    sheet.classList.add('baw-anim');
    haptic('tap');
  }

  function share() {
    var st = state;
    if (!st) return;
    var b = st.badges[st.idx];
    var btn = sheet.querySelector('.baw__share');
    btn.disabled = true;
    api('GET', '/client/badges/' + encodeURIComponent(b.key) + '/share').then(function (r) {
      btn.disabled = false;
      if (!r.ok || !r.json || !r.json.share_url) { haptic('tap'); return; }
      haptic('tap');
      var t = tg();
      var url = 'https://t.me/share/url?url=' + encodeURIComponent(r.json.share_url) +
        '&text=' + encodeURIComponent(r.json.share_text || '');
      if (t && typeof t.openTelegramLink === 'function') t.openTelegramLink(url);
      else window.open(url, '_blank');
    }).catch(function () {
      btn.disabled = false;
      haptic('tap');
    });
  }

  function close() {
    if (!dim) return;
    dim.classList.remove('baw-on');
    sheet.classList.remove('baw-on');
    var st = state;
    state = null;
    setTimeout(function () { dim.hidden = true; sheet.hidden = true; }, 260);
    if (st && typeof st.onClose === 'function') {
      st.onClose(st.badges.map(function (b) { return b.key; }));
    }
  }

  function open(opts) {
    ensureDom();
    opts = opts || {};
    var badges = Array.isArray(opts.badges) ? opts.badges.filter(function (b) { return b && b.key; }) : [];
    if (!badges.length) return;
    state = { badges: badges, idx: 0, onClose: opts.onClose || null };
    render();
    dim.hidden = false;
    sheet.hidden = false;
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        dim.classList.add('baw-on');
        sheet.classList.add('baw-on');
        sheet.classList.add('baw-anim');
      });
    });
    haptic('ok');
  }

  window.GlideBadgeAward = { open: open, close: close };
})();
