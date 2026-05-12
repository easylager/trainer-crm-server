(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    if (typeof tg.ready === 'function') tg.ready();
    if (typeof tg.expand === 'function') tg.expand();
    if (typeof window.__applyClientMiniAppTheme === 'function') window.__applyClientMiniAppTheme();
    try {
      var darkUi = document.documentElement.classList.contains('client-mini-dark');
      var bgHex = darkUi ? '#1c1c1c' : '#fffbec';
      if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor(bgHex);
      if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor(bgHex);
    } catch (e) { /* theme script may not expose dark class on this page */ }
  }
  var initData = tg && tg.initData ? tg.initData : '';

  function headersJson() {
    var h = { 'Content-Type': 'application/json' };
    if (initData) h['X-Telegram-Init-Data'] = initData;
    return h;
  }

  function apiUrl(path) {
    var url = '/api/webapp' + path;
    if (initData) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
    return url;
  }

  function webappBasePath() {
    var p = window.location.pathname || '';
    return p.replace(/[^/]+$/, '') || '/webapp/';
  }

  function withInit(url) {
    if (!initData) return url;
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'init_data=' + encodeURIComponent(initData);
  }

  function navigateTo(pathWithQuery) {
    window.location.href = withInit(webappBasePath() + pathWithQuery);
  }

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function trainingSessionsPhrase(n) {
    n = Number(n) || 0;
    var abs100 = n % 100;
    var abs10 = n % 10;
    if (abs100 >= 11 && abs100 <= 14) return n + ' тренировок';
    if (abs10 === 1) return n + ' тренировка';
    if (abs10 >= 2 && abs10 <= 4) return n + ' тренировки';
    return n + ' тренировок';
  }

  function pluralWeeksWord(n) {
    n = Number(n) || 0;
    var abs100 = n % 100;
    var abs10 = n % 10;
    if (abs100 >= 11 && abs100 <= 14) return 'недель';
    if (abs10 === 1) return 'неделя';
    if (abs10 >= 2 && abs10 <= 4) return 'недели';
    return 'недель';
  }

  /** One friendly sentence (Duolingo-style), no jargon about «windows» or calendars. */
  function streakCelebrationLine(weeks) {
    var n = Number(weeks) || 0;
    if (n < 1) return '';
    if (n === 1) return 'Вы занимаетесь уже неделю подряд!';
    return 'Вы занимаетесь уже ' + n + ' ' + pluralWeeksWord(n) + ' подряд!';
  }

  var HOUR_MILESTONE_TARGETS = [5, 10, 25, 50, 100, 250];

  function splitTrainingCountPhrase(n) {
    var p = trainingSessionsPhrase(n);
    var m = /^(\d+)\s+(.+)$/.exec(p);
    if (!m) return { num: String(Number(n) || 0), unit: 'тренировок' };
    return { num: m[1], unit: m[2] };
  }

  function nextHourMilestone(minutesTotal) {
    var h = Number(minutesTotal) / 60;
    if (!h || h < 0.04) return null;
    for (var i = 0; i < HOUR_MILESTONE_TARGETS.length; i++) {
      var t = HOUR_MILESTONE_TARGETS[i];
      if (h < t - 1e-9) return { target: t, remainingHours: Math.max(0, t - h) };
    }
    return null;
  }

  function formatHoursStat(minutesTotal) {
    var m = Number(minutesTotal) || 0;
    if (m < 1) return null;
    if (m < 90) {
      return { num: String(Math.round(m)), unit: 'мин практики' };
    }
    var h = m / 60;
    var r = Math.round(h * 10) / 10;
    var numStr = r % 1 === 0 ? String(Math.round(r)) : String(r).replace('.', ',');
    return { num: numStr, unit: 'ч практики' };
  }

  function progressMarkup(pct, leftCap, rightCap) {
    var w = Math.max(6, Math.min(100, Number(pct) || 0));
    var bar =
      '<div class="st-progress" aria-hidden="true">' +
      '<div class="st-progress-fill" style="width:' +
      esc(String(w)) +
      '%"></div></div>';
    if (!leftCap && !rightCap) return bar;
    return (
      bar +
      '<div class="st-progress-cap"><span>' +
      esc(leftCap || '') +
      '</span><span>' +
      esc(rightCap || '') +
      '</span></div>'
    );
  }

  function formatRemainHours(h) {
    var x = Number(h);
    if (x >= 10) return String(Math.round(x * 10) / 10).replace('.', ',') + ' ч';
    if (x >= 1) return String(Math.round(x * 10) / 10).replace('.', ',') + ' ч';
    return 'меньше часа';
  }

  function buildWelcomeHero() {
    return (
      '<div class="st-hero-grid">' +
      '<div class="st-widget st-widget--welcome">' +
      '<div class="st-widget-lead">Пока без отметок — и это нормально</div>' +
      '<div class="st-hero-note">Как только тренер отметит первую тренировку проведённой, здесь появятся карточки: число тренировок, время на занятиях и серия недель.</div>' +
      '</div></div>'
    );
  }

  function buildSessionsWidget(data) {
    var total = Number(data.completed_total) || 0;
    var ms = data.next_milestone;
    var sp = splitTrainingCountPhrase(total);
    var head =
      '<div class="st-widget st-widget--sessions">' +
      '<div class="st-widget-kicker">Тренировки</div>' +
      '<div class="st-widget-lead">Столько раз вы уже были на тренировке. Так и держать.</div>' +
      '<div class="st-widget-stat-row">' +
      '<span class="st-widget-num">' +
      esc(sp.num) +
      '</span>' +
      '<span class="st-widget-unit">' +
      esc(sp.unit) +
      '</span>' +
      '</div>';

    var mid = '';
    if (ms && ms.target != null && ms.remaining != null && total < Number(ms.target)) {
      var tgt = Number(ms.target);
      var pct = (total / tgt) * 100;
      mid +=
        progressMarkup(
          pct,
          'сейчас ' + esc(String(total)),
          'цель «' + esc(String(tgt)) + '»'
        ) +
        '<div class="st-widget-sub">До отметки <strong>' +
        esc(String(tgt)) +
        '</strong> осталось <strong>' +
        esc(String(ms.remaining)) +
        '</strong> — спокойный ориентир, без гонки.</div>';
    } else if (!ms && total >= 1) {
      mid +=
        '<div class="st-widget-sub--muted">Выше отметок, которые мы сейчас подсвечиваем как ориентиры — держите курс и при необходимости обсудите с тренером следующий фокус.</div>';
    }

    return head + mid + '</div>';
  }

  function buildTimeWidget(data) {
    var minutes = Number(data.completed_minutes_total) || 0;
    var st = formatHoursStat(minutes);
    var head =
      '<div class="st-widget st-widget--time">' +
      '<div class="st-widget-kicker">Время</div>' +
      '<div class="st-widget-lead">Сколько всего времени вы уже провели на этих тренировках.</div>';

    if (!st) {
      return (
        head +
        '<div class="st-widget-sub--muted">Как только в слотах стабильно будут длительности, подсчитаем суммарное время. Счёт завершённых тренировок слева всё равно растёт.</div></div>'
      );
    }

    var hm = nextHourMilestone(minutes);
    var hNow = minutes / 60;
    var body =
      '<div class="st-widget-stat-row">' +
      '<span class="st-widget-num">' +
      esc(st.num) +
      '</span>' +
      '<span class="st-widget-unit">' +
      esc(st.unit) +
      '</span>' +
      '</div>';

    if (hm) {
      var pctH = (hNow / hm.target) * 100;
      var leftNow =
        minutes < 90
          ? 'сейчас ' + esc(st.num) + ' мин'
          : 'сейчас ≈ ' + esc(st.num) + ' ч';
      body +=
        progressMarkup(
          pctH,
          leftNow,
          'цель «' + esc(String(hm.target)) + ' ч»'
        ) +
        '<div class="st-widget-sub">До <strong>' +
        esc(String(hm.target)) +
        ' ч</strong> практики осталось примерно <strong>' +
        esc(formatRemainHours(hm.remainingHours)) +
        '</strong>.</div>';
    } else {
      body +=
        '<div class="st-widget-sub--muted">Солидный объём накоплен — дальше смысл не в цифре ради цифры, а в том, как вы себя чувствуете между тренировками.</div>';
    }

    return head + body + '</div>';
  }

  function buildStreakWidget(data) {
    var total = Number(data.completed_total) || 0;
    if (total < 1) return '';
    var streak = Number(data.streak_weeks) || 0;
    var head =
      '<div class="st-widget st-widget--streak">' +
      '<div class="st-widget-kicker">Серия</div>';

    if (streak < 1) {
      return (
        head +
        '<div class="st-widget-lead">Запишитесь на тренировку на этой неделе — и серия начнётся.</div>' +
        '<div class="st-widget-sub--muted">Не нужно каждый день: достаточно раз в неделю, чтобы радовать себя прогрессом.</div></div>'
      );
    }

    return (
      head +
      '<div class="st-widget-stat-row st-widget-stat-row--duo">' +
      '<span class="st-widget-duo-lead">' +
      esc(streakCelebrationLine(streak)) +
      '</span></div>' +
      '<div class="st-widget-sub">Новая неделя с тренировкой продлевает серию — приятно не сбивать счёт.</div></div>'
    );
  }

  function buildHeroWidgetsHtml(data) {
    var total = Number(data.completed_total) || 0;
    if (total < 1) return buildWelcomeHero();
    var chunks = [
      '<div class="st-hero-grid">',
      buildSessionsWidget(data),
      buildTimeWidget(data),
      buildStreakWidget(data),
      '</div>',
    ];
    return chunks.join('');
  }

  /** One short narrative block for optional «Недавно» card (hidden when streak carries the story). */
  function buildRhythmBody(l30, p30, ct) {
    var l = Number(l30) || 0;
    var p = Number(p30) || 0;
    var t = Number(ct) || 0;
    if (t < 1) return '';
    if (l === 0 && p === 0) {
      return (
        'Давненько не добавлялись новые завершённые занятия в этом маленьком обзоре — зато уже <strong>' +
        esc(trainingSessionsPhrase(t)) +
        '</strong> всего. Когда продолжите, картина снова станет понятнее.'
      );
    }
    if (p === 0 && l > 0) {
      return (
        'Недавно у вас <strong>' +
        esc(trainingSessionsPhrase(l)) +
        '</strong> — хороший момент, чтобы закрепить привычку и записаться ещё наперёд.'
      );
    }
    if (l > p && p > 0) {
      return (
        'Сейчас — <strong>' +
        esc(trainingSessionsPhrase(l)) +
        '</strong>, недавним заходом было <strong>' +
        esc(trainingSessionsPhrase(p)) +
        '</strong>. Похоже, вы добавляете в жизнь движения — многие так «прилипают» к тренировкам.'
      );
    }
    if (l < p && p > 0) {
      return (
        'Сейчас — <strong>' +
        esc(trainingSessionsPhrase(l)) +
        '</strong>, а чуть раньше успели <strong>' +
        esc(trainingSessionsPhrase(p)) +
        '</strong> — может, просто суматоха или перерыв. Когда будет настрой, записаться всегда недолго.'
      );
    }
    return (
      'Ритм спокойный и ровный: <strong>' +
      esc(trainingSessionsPhrase(l)) +
      '</strong> недавним периодом и столько же чуть раньше.'
    );
  }

  function pickNudge(data) {
    var upc = Number(data.upcoming_bookings_count) || 0;
    var ct = Number(data.completed_total) || 0;
    var d = data.days_since_last_completed;

    if (upc >= 3) {
      return (
        'У вас уже ' +
        trainingSessionsPhrase(upc) +
        ' в календаре — остаётся появиться на площадке и делать своё.'
      );
    }
    if (upc >= 1 && ct >= 1) {
      return (
        'Есть записи наперёд — после занятия крупная цифра выше может подрасти, когда тренер закроет тренировку у себя.'
      );
    }
    if (ct > 0 && upc === 0 && d != null && d >= 21) {
      return 'Давно не было завершённых занятий — когда захотите снова выйти к тренеру, запись рядом, в каталоге.';
    }
    return '';
  }

  function render(data) {
    var root = document.getElementById('statsRoot');
    var state = document.getElementById('statePanel');
    var cta = document.getElementById('ctaRow');
    var foot = document.getElementById('statsFoot');
    if (!root) return;

    var total = Number(data.completed_total) || 0;
    var l30 = Number(data.completed_last_30d) || 0;
    var p30 = Number(data.completed_prev_30d) || 0;
    var trainers = Number(data.distinct_trainers_completed) || 0;
    var upc = Number(data.upcoming_bookings_count) || 0;
    var streak = Number(data.streak_weeks) || 0;

    var parts = [];

    parts.push(buildHeroWidgetsHtml(data));

    var rhythmHtml = buildRhythmBody(l30, p30, total);
    if (rhythmHtml && streak < 1) {
      parts.push(
        '<div class="st-card">' +
          '<div class="st-card-title">Недавно</div>' +
          '<div class="st-card-body">' +
          rhythmHtml +
          '</div></div>'
      );
    }

    if (trainers >= 2) {
      parts.push(
        '<div class="st-card">' +
          '<div class="st-card-title">Тренеры</div>' +
          '<div class="st-card-body">' +
          'Вы уже знакомы с <strong>' +
          esc(String(trainers)) +
          '</strong> разными тренерами — проще понять, с кем особенно «по дороге» для следующей записи.</div></div>'
      );
    }

    var nudge = pickNudge(data);
    if (nudge) {
      parts.push('<div class="st-nudge">' + esc(nudge) + '</div>');
    }

    root.innerHTML = parts.join('');
    root.style.display = '';
    if (state) {
      state.style.display = 'none';
      state.textContent = '';
    }
    if (foot) foot.style.display = '';
    if (cta) cta.style.display = '';
  }

  function setError(msg) {
    var state = document.getElementById('statePanel');
    var root = document.getElementById('statsRoot');
    var cta = document.getElementById('ctaRow');
    if (root) root.style.display = 'none';
    if (cta) cta.style.display = 'none';
    if (state) {
      state.style.display = '';
      state.textContent = msg;
      state.className = 'st-state error';
    }
  }

  function setLoading() {
    var state = document.getElementById('statePanel');
    var root = document.getElementById('statsRoot');
    var cta = document.getElementById('ctaRow');
    if (root) root.style.display = 'none';
    if (cta) cta.style.display = 'none';
    if (state) {
      state.style.display = '';
      state.className = 'st-state';
      state.textContent = 'Загружаем…';
    }
  }

  document.getElementById('btnBook').onclick = function () {
    navigateTo('catalog?tab=catalog');
  };
  document.getElementById('btnBookings').onclick = function () {
    navigateTo('client-bookings');
  };

  if (!initData) {
    setError('Откройте раздел из клиентского бота, чтобы увидеть статистику.');
    return;
  }

  setLoading();
  fetch(apiUrl('/client/activity-stats'), { headers: headersJson() })
    .then(function (r) {
      if (!r.ok) return r.json().then(function (d) { throw new Error(d.detail || r.statusText); });
      return r.json();
    })
    .then(render)
    .catch(function () {
      setError('Не удалось загрузить данные. Попробуйте снова из бота.');
    });
})();
