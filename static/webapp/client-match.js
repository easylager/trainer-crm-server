/**
 * TASK-304: страница домашнего матча — ответ «Иду / Смотрю дома / Не смогу», «Позвать своих»,
 * «Кто из ваших», строка «КТО КОГО?» → игра. Тексты — в client-match-model.js.
 * Рисуем только через createElement/textContent.
 */
(function (global) {
  'use strict';

  var doc = global.document;
  var M = global.ClientMatchModel;
  var tg = global.Telegram && global.Telegram.WebApp;
  var params = new URLSearchParams(global.location.search);
  var matchId = Number(params.get('id')) || 0;
  // Код компании друга из ссылки «Позвать»: первый ответ кладёт меня в его компанию.
  var inviteCode = params.get('c') || '';
  var state = { ev: null, busy: false, kk: 'row' };

  function $(id) { return doc.getElementById(id); }

  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function initData() {
    return (tg && tg.initData) || params.get('init_data') || '';
  }

  function haptic(kind) {
    if (global.GlideTouch) return global.GlideTouch.haptic(kind || 'tap');
    try {
      if (!tg || !tg.HapticFeedback) return;
      if (kind) tg.HapticFeedback.notificationOccurred(kind);
      else tg.HapticFeedback.impactOccurred('light');
    } catch (e) { /* без вибрации — не беда */ }
  }

  function api(method, path, body) {
    var data = initData();
    var url = '/api/webapp' + path + (data ? (path.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(data) : '');
    var opts = { method: method, headers: { 'Content-Type': 'application/json' }, cache: 'no-store' };
    if (data) opts.headers['X-Telegram-Init-Data'] = data;
    if (body) opts.body = JSON.stringify(body);
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (json) {
        if (!r.ok) {
          var err = new Error((json && json.detail) || 'Не получилось');
          err.status = r.status;
          throw err;
        }
        return json;
      });
    });
  }

  function go(path) {
    var shell = global.ClientShell;
    if (shell && typeof shell.navigate === 'function') return shell.navigate(path);
    var data = initData();
    global.location.href = '/webapp/' + path + (data ? (path.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(data) : '');
  }

  var toastTimer = 0;
  function toast(text) {
    var t = $('cmToast');
    if (!t) return;
    t.textContent = text;
    t.hidden = false;
    global.clearTimeout(toastTimer);
    toastTimer = global.setTimeout(function () { t.hidden = true; }, 2400);
  }

  function svg(d, cls) {
    var ns = 'http://www.w3.org/2000/svg';
    var s = doc.createElementNS(ns, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '2');
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('aria-hidden', 'true');
    if (cls) s.setAttribute('class', cls);
    d.forEach(function (path) {
      var p = doc.createElementNS(ns, 'path');
      p.setAttribute('d', path);
      s.appendChild(p);
    });
    return s;
  }

  // ---------- шапка ----------

  // TASK-340: матч Экстралиги — та же страница, свои блоки (экран 12).
  function isXl(ev) { return !!ev && ev.league === 'extraliga'; }

  function started(ev) {
    return !!(ev.match.result || M.status(ev.match).live || ev.match.status === 'cancelled');
  }

  function logoEl(team) {
    var s = el('span', 'cm-logo');
    if (team && team.logo) {
      var img = el('img');
      img.src = team.logo;
      img.alt = '';
      s.appendChild(img);
    } else s.textContent = (team && team.short) || '';
    return s;
  }

  function openUrl(url) {
    if (!url) return;
    if (tg && typeof tg.openLink === 'function') tg.openLink(url);
    else global.open(url, '_blank', 'noopener');
  }

  function suffix(decided) {
    var d = String(decided || '').toLowerCase();
    if (d === 'ot' || d === 'overtime') return ' ОТ';
    if (d === 'so' || d === 'shootout') return ' Б';
    return '';
  }

  function dayMonth(iso) { return M.heroWhen(iso).split(' · ')[0].replace(/^[а-я]{2}, /, ''); }

  function paintHero(ev) {
    var m = ev.match;
    var title = $('cmTitle');
    var score = $('cmScore');
    var r = m.result;
    var final = !!(r && r.home_score != null);
    title.hidden = final;
    score.hidden = !final;
    if (final) {
      score.replaceChildren(
        el('span', 'cm-score__team', m.home.name),
        el('span', 'cm-score__num', r.home_score + ':' + r.away_score),
        el('span', 'cm-score__team', m.away.name)
      );
    } else {
      title.replaceChildren(el('span', null, m.home.name + ' —'), el('span', null, m.away.name));
    }
    var xl = isXl(ev);
    $('cmKicker').textContent = xl ? 'Матч · Экстралига' : 'Матч · КХЛ';
    var logos = $('cmLogos');
    logos.hidden = !xl;
    if (xl) logos.replaceChildren(logoEl(m.home), logoEl(m.away));
    var place = (ev.arena && ev.arena.name) || 'Минск-Арена';
    if (xl && ev.arena && ev.arena.city && place.indexOf(ev.arena.city) < 0) place += ', ' + ev.arena.city;
    $('cmWhen').textContent = M.heroWhen(m.starts_at) + ' · ' + place;
    var st = M.status(m);
    var pill = $('cmStatus');
    pill.textContent = st.text;
    pill.className = 'cm-status' + (st.live ? ' cm-status--live' : '');
    pill.hidden = false;
    doc.title = m.home.name + ' — ' + m.away.name;
  }

  // ---------- Экстралига: билет, перед матчем, итог ----------

  function paintBuy(ev) {
    var host = $('cmBuy');
    if (!isXl(ev) || !ev.tickets_url || started(ev)) return host.replaceChildren();
    var b = el('button', 'ga-btn ga-btn--dark ga-press cm-buy', 'Купить билет');
    b.type = 'button';
    b.addEventListener('click', function () { haptic(); openUrl(ev.tickets_url); });
    host.replaceChildren(b, el('p', 'cm-hint', 'Билеты продаёт ' + (ev.tickets_note || 'клуб') + ' — откроем их сайт'));
  }

  function formEl(form) {
    var box = el('span', 'cm-form');
    (form || []).forEach(function (f) {
      box.appendChild(el('span', 'cm-form__m' + (f.charAt(0) === 'В' ? ' cm-form__m--w' : ''), f));
    });
    return box;
  }

  function paintPre(ev) {
    var p = isXl(ev) && !started(ev) ? ev.preview : null;
    $('cmPre').hidden = !p;
    $('cmWatch').hidden = true;
    if (!p) return;
    var body = $('cmPreBody');
    var rows = [ev.match.home, ev.match.away].map(function (team, i) {
      var t = i ? p.away : p.home;
      var row = el('div', 'cm-team');
      row.appendChild(logoEl(team));
      var txt = el('span', 'cm-team__text');
      txt.appendChild(el('span', 'cm-team__name', team.name));
      if (t.place) txt.appendChild(el('span', 'cm-team__sub', t.place + '-е место · ' + t.points + ' ' + M.plural(t.points, 'очко', 'очка', 'очков')));
      row.appendChild(txt);
      row.appendChild(formEl(t.form));
      return row;
    });
    body.replaceChildren.apply(body, rows);
    var lm = p.last_meeting;
    if (lm) {
      var line = 'Прошлая встреча, ' + dayMonth(lm.starts_at) + ': ' + lm.home_team + ' — ' + lm.away_team + ' ' +
        lm.home_score + ':' + lm.away_score + suffix(lm.decided_in) + '.';
      if (lm.winning_goal) line += ' Победную забросил ' + lm.winning_goal.scorer + (lm.winning_goal.minute ? ' на ' + lm.winning_goal.minute + '-й минуте' : '') + '.';
      body.appendChild(el('p', 'cm-pre__meet', line));
    }
    var watch = [];
    [p.home, p.away].forEach(function (t) {
      var l = t.leaders || {};
      (l.forwards || []).forEach(function (f) {
        watch.push({ team: t.team, name: f.name, stat: f.points != null ? f.points + ' ' + M.plural(f.points, 'очко', 'очка', 'очков') + (f.goals != null ? ' (' + f.goals + '+' + (f.assists || 0) + ')' : '') : '' });
      });
      if (l.goalie && l.goalie.name) {
        watch.push({ team: t.team, name: l.goalie.name, stat: l.goalie.save_pct != null ? 'вратарь · ' + String(l.goalie.save_pct).replace('.', ',') + '% отражённых' : 'вратарь' });
      }
      (t.streaks || []).forEach(function (s) {
        watch.push({ team: t.team, name: s.player, stat: 'забивает ' + s.matches + ' ' + M.plural(s.matches, 'матч', 'матча', 'матчей') + ' подряд' });
      });
    });
    $('cmWatch').hidden = !watch.length;
    $('cmWatchBody').replaceChildren.apply($('cmWatchBody'), watch.map(function (w) {
      var r = el('div', 'cm-watch__row');
      r.appendChild(el('span', 'cm-watch__name', w.name));
      r.appendChild(el('span', 'cm-watch__stat', [w.team, w.stat].filter(Boolean).join(' · ')));
      return r;
    }));
  }

  function paintAfter(ev) {
    var d = isXl(ev) ? ev.details : null;
    $('cmAfter').hidden = !d;
    if (!d) return;
    var body = $('cmAfterBody');
    var parts = [];
    if (d.periods && d.periods.length) {
      parts.push(el('p', 'cm-after__line', 'По периодам: ' + d.periods.map(function (p) { return p[0] + ':' + p[1]; }).join(' · ')));
    }
    var goals = el('ol', 'cm-goals');
    (d.goals || []).forEach(function (g) {
      var team = g.side === 'away' ? ev.match.away : ev.match.home;
      var li = el('li', 'cm-goal' + (g.side === 'away' ? ' cm-goal--away' : ''));
      li.appendChild(el('span', 'cm-goal__min', g.minute != null ? String(g.minute) + '′' : ''));
      var t = el('span', 'cm-goal__text');
      t.appendChild(el('span', 'cm-goal__who', g.scorer));
      t.appendChild(el('span', 'cm-goal__sub', team.name + (g.assists && g.assists.length ? ' · ' + g.assists.join(', ') : '')));
      li.appendChild(t);
      goals.appendChild(li);
    });
    if (goals.children.length) parts.push(goals);
    var stats = [];
    if (d.shots && d.shots.length === 2) stats.push('Броски ' + d.shots[0] + ' — ' + d.shots[1]);
    if (d.attendance) stats.push('Зрителей ' + String(d.attendance).replace(/\B(?=(\d{3})+(?!\d))/g, ' '));
    if (stats.length) parts.push(el('p', 'cm-after__line', stats.join(' · ')));
    body.replaceChildren.apply(body, parts);
  }

  // ---------- ответ ----------

  function paintRsvp(ev) {
    var box = $('cmSegs');
    var started = !!(ev.match.result || M.status(ev.match).live || ev.match.status === 'cancelled');
    $('cmRsvp').hidden = started;
    var bar = $('cmBar');
    if (bar) bar.hidden = started;
    if (started) return;
    var crowd = M.crowdLine(ev.crowd);
    var crowdEl = $('cmCrowd');
    crowdEl.textContent = crowd;
    crowdEl.hidden = !crowd;
    paintReaction(ev);
    // Кнопки строятся один раз и дальше только переключаются: так выбор «вдавливается» плавно,
    // а не появляется заново. Пока ответ летит на сервер, кнопки не гаснут — answer() сам ждёт.
    if (box.children.length !== M.ANSWERS.length) {
      box.replaceChildren.apply(box, M.ANSWERS.map(function (a) {
        var b = el('button', 'cm-seg', a.label);
        b.type = 'button';
        b.setAttribute('data-haptic', 'select');
        b.addEventListener('click', function () { answer(a); });
        return b;
      }));
    }
    M.ANSWERS.forEach(function (a, i) {
      box.children[i].setAttribute('aria-pressed', ev.my_status === a.status ? 'true' : 'false');
    });
  }

  function paintReaction(ev) {
    var host = $('cmReact');
    var r = M.reaction(ev.my_status, ev);
    host.hidden = !r;
    if (!r) return host.replaceChildren();
    var btns = el('div', 'cm-react__btns');
    r.actions.forEach(function (act) {
      var b = el('button', 'ga-btn ga-press' + (act.dark ? ' ga-btn--dark' : ' ga-btn--soft'), act.label);
      b.type = 'button';
      b.addEventListener('click', function () { reactionAction(act); });
      btns.appendChild(b);
    });
    host.replaceChildren(el('p', 'cm-react__text', r.text), btns);
  }

  function reactionAction(act) {
    haptic();
    if (act.id === 'company') return openShare('company');
    if (act.id === 'invite') return openShare('invite');
    if (act.id === 'game') return go('kto-kogo');
    if (act.id === 'next' && act.href) return go(act.href);
    if (act.id === 'tickets' && state.ev && state.ev.tickets_url) {
      if (tg && typeof tg.openLink === 'function') tg.openLink(state.ev.tickets_url);
      else global.open(state.ev.tickets_url, '_blank', 'noopener');
    }
  }

  function answer(a) {
    if (state.busy || !state.ev || state.ev.my_status === a.status) return;
    var before = state.ev;
    // Сразу показываем выбор: ответ сервера придёт с обновлённым «Кто из ваших».
    state.ev = Object.assign({}, before, { my_status: a.status });
    state.busy = true;
    paintRsvp(state.ev);
    var body = { status: a.status };
    if (inviteCode) body.company = inviteCode;
    api('PUT', '/client/hockey/matches/' + matchId + '/rsvp', body)
      .then(function (ev) {
        state.busy = false;
        state.ev = ev;
        haptic('success');
        toast(a.toast);
        paint(ev);
      })
      .catch(function (e) {
        state.busy = false;
        state.ev = before;
        haptic('error');
        paint(before);
        toast(e.status === 403 ? 'Ответить можно из Telegram' : e.message);
      });
  }

  /*
   * «Позвать на матч» и «Собрать компанию» — общий шит шаринга, как у массового катания и ОХМ
   * (решение владельца 2026-10-20: один движок на все события). Варианты: «Погнали?», «Компания»,
   * «Открытка»; сеанс выбирать не нужно — это матч.
   */
  function openShare(variant) {
    if (!global.GlideShareSheet || !state.ev) return toast('Обновите страницу — шаринг не загрузился');
    haptic();
    var m = state.ev.match;
    var start = M.heroWhen(m.starts_at).split(' · ');
    global.GlideShareSheet.open({
      match: { id: m.id, day: start[0] || '', time: start[1] || '', title: m.home.name + ' — ' + m.away.name },
      invite: variant === 'invite',
      variant: variant === 'company' ? 'company' : '',
      company: true,
      venueType: 'ice',
      context: 'match_page',
      placeName: (state.ev.arena && state.ev.arena.name) || 'Минск-Арена',
    });
  }

  // ---------- кто из ваших ----------

  function paintWho(ev) {
    var w = M.who(ev.people);
    var box = $('cmWho');
    var waiting = !w && !!ev.company_open;
    box.hidden = !w && !waiting;
    box.classList.toggle('cm-who--wait', waiting);
    if (waiting) {
      // Компания собрана, ответов ещё нет: показываем, что карточка в чате и ответы появятся здесь.
      $('cmWhoTitle').textContent = 'Твоя компания';
      $('cmWhoCount').textContent = 'ждём ответов';
      $('cmFaces').replaceChildren(el('span', 'cm-face cm-face--me', 'Я'));
      $('cmWhoLine').textContent = 'Карточка в чате. Кто нажмёт «Иду» — появится здесь.';
      return;
    }
    $('cmWhoTitle').textContent = 'Кто из ваших';
    if (!w) return;
    $('cmWhoCount').textContent = w.count;
    $('cmWhoLine').textContent = w.line;
    $('cmFaces').replaceChildren.apply($('cmFaces'), w.initials.map(function (f) {
      return el('span', 'cm-face' + (f.me ? ' cm-face--me' : ''), f.letter);
    }));
  }

  // ---------- кто кого ----------

  // «Кто кого» на Экстралиге ещё нет: строка-подписка «Позвать» по клубу хозяев (срез 5).
  function paintSubscribe(ev) {
    var host = $('cmKk');
    var s = ev.kk_subscribe || {};
    var card = el('div', 'cm-card cm-kk cm-kk--sub');
    card.appendChild(el('span', 'cm-kk__tag', 'КТО КОГО?'));
    var text = el('span', 'cm-kk__text');
    text.appendChild(el('span', 'cm-kk__title', 'Угадывать Экстралигу'));
    text.appendChild(el('span', 'cm-kk__sub', s.subscribed ? 'Позовём в боте, как только откроем' : 'Скоро откроем — позвать тебя?'));
    card.appendChild(text);
    var b = el('button', 'cm-btn cm-sub' + (s.subscribed ? ' cm-sub--done' : ''), s.subscribed ? 'Позовём' : 'Позвать');
    b.type = 'button';
    b.disabled = !!s.subscribed;
    b.addEventListener('click', function () {
      haptic();
      b.disabled = true;
      api('POST', '/client/hockey/extraliga/subscribe', { club: s.club })
        .then(function () {
          state.ev.kk_subscribe = Object.assign({}, s, { subscribed: true });
          haptic('success');
          toast('Позовём, когда откроем');
          paintSubscribe(state.ev);
        })
        .catch(function (e) {
          b.disabled = false;
          toast(e.status === 403 ? 'Подписаться можно из Telegram' : e.message);
        });
    });
    card.appendChild(b);
    host.replaceChildren(card);
  }

  function paintKk(ev) {
    if (isXl(ev)) return paintSubscribe(ev);
    var host = $('cmKk');
    var kk = ev.kk || {};
    if (kk.hidden && state.kk !== 'hidden') {
      host.replaceChildren();
      return;
    }
    if (state.kk === 'hidden') {
      host.replaceChildren(el('p', 'cm-note', 'Игра скрыта. Вернуть — в «Ещё › Кто кого».'));
      return;
    }
    if (state.kk === 'confirm') {
      var c = el('section', 'cm-card cm-confirm');
      c.setAttribute('role', 'alertdialog');
      c.setAttribute('aria-labelledby', 'cmConfirmTitle');
      var h = el('p', 'cm-confirm__title', 'Скрыть «Кто кого» на матчах?');
      h.id = 'cmConfirmTitle';
      c.appendChild(h);
      c.appendChild(el('p', 'cm-confirm__text', 'Строка пропадёт со всех матчей. Очки и лиги сохранятся, вернуть можно в «Ещё».'));
      var btns = el('div', 'cm-confirm__btns');
      var keep = el('button', 'cm-btn', 'Оставить');
      keep.type = 'button';
      keep.addEventListener('click', function () { state.kk = 'row'; paintKk(state.ev); });
      var hide = el('button', 'cm-btn cm-btn--dark', 'Скрыть');
      hide.type = 'button';
      hide.addEventListener('click', hideGame);
      btns.appendChild(keep);
      btns.appendChild(hide);
      c.appendChild(btns);
      host.replaceChildren(c);
      keep.focus();
      return;
    }
    var row = M.kkRow(ev);
    var card = el('div', 'cm-card cm-kk');
    var main = el('a', 'cm-kk__main');
    main.href = row.href;
    main.addEventListener('click', function (e) {
      e.preventDefault();
      haptic();
      go(row.href);
    });
    main.appendChild(el('span', 'cm-kk__tag', 'КТО КОГО?'));
    var text = el('span', 'cm-kk__text');
    text.appendChild(el('span', 'cm-kk__title', row.title));
    text.appendChild(el('span', 'cm-kk__sub', row.sub));
    main.appendChild(text);
    card.appendChild(main);
    var x = el('button', 'cm-x');
    x.type = 'button';
    x.setAttribute('aria-label', 'Скрыть игру на матчах');
    x.appendChild(svg(['M6 6l12 12', 'M18 6L6 18']));
    x.addEventListener('click', function () { state.kk = 'confirm'; paintKk(state.ev); });
    card.appendChild(x);
    host.replaceChildren(card);
  }

  function hideGame() {
    api('PUT', '/client/hockey/prefs', { kk_hidden: true })
      .then(function () {
        state.kk = 'hidden';
        state.ev.kk = Object.assign({}, state.ev.kk, { hidden: true });
        paintKk(state.ev);
      })
      .catch(function (e) {
        state.kk = 'row';
        paintKk(state.ev);
        toast(e.message);
      });
  }

  // ---------- билеты, дорога, лёд ----------

  function paintLinks(ev) {
    var tickets = $('cmTickets');
    var started = !!ev.match.result || ev.match.status === 'cancelled';
    tickets.hidden = !ev.tickets_url || started || isXl(ev);
    var source = $('cmSource');
    source.hidden = !ev.source_url;
    if (ev.source_url) {
      source.href = ev.source_url;
      source.onclick = function (e) { e.preventDefault(); openUrl(ev.source_url); };
    }
    if (ev.tickets_url) {
      tickets.href = ev.tickets_url;
      tickets.onclick = function (e) {
        e.preventDefault();
        if (tg && typeof tg.openLink === 'function') tg.openLink(ev.tickets_url);
        else global.open(ev.tickets_url, '_blank', 'noopener');
      };
    }
    var route = $('cmRoute');
    var arena = ev.arena || {};
    route.hidden = !arena.arena_id || started;
    if (arena.arena_id) {
      var path = 'arena?ref=' + arena.arena_id;
      route.href = path;
      route.onclick = function (e) { e.preventDefault(); go(path); };
      if (arena.address) $('cmAddress').textContent = arena.address;
    }
  }

  function paintIce(ev) {
    var items = ev.ice_after || [];
    $('cmIce').hidden = !items.length;
    $('cmIceList').replaceChildren.apply($('cmIceList'), items.map(function (s) {
      var a = el('a', 'cm-ice__card');
      a.href = s.href;
      a.addEventListener('click', function (e) { e.preventDefault(); go(s.href); });
      var thumb = s.photo && (s.photo.thumb || s.photo.card);
      if (thumb) {
        var img = el('img', 'cm-ice__thumb');
        img.src = thumb;
        img.alt = '';
        img.loading = 'lazy';
        img.onerror = function () { img.replaceWith(el('span', 'cm-ice__thumb')); };
        a.appendChild(img);
      } else {
        a.appendChild(el('span', 'cm-ice__thumb'));
      }
      var t = el('span', 'cm-ice__text');
      t.appendChild(el('span', 'cm-ice__time', (s.day && s.day !== 'сегодня' ? s.day + ' ' : '') + s.time + (s.badge ? ' · ' + s.badge : '')));
      t.appendChild(el('span', 'cm-ice__place', s.place + (s.price ? ' · ' + s.price : '')));
      a.appendChild(t);
      return a;
    }));
  }

  // ---------- всё вместе ----------

  function paint(ev) {
    paintHero(ev);
    paintRsvp(ev);
    paintBuy(ev);
    paintWho(ev);
    paintAfter(ev);
    paintPre(ev);
    paintKk(ev);
    paintLinks(ev);
    paintIce(ev);
  }

  function fail(text) {
    $('cmMain').setAttribute('aria-busy', 'false');
    $('cmRsvp').hidden = true;
    var s = $('cmState');
    s.textContent = text;
    s.hidden = false;
    $('cmTitle').replaceChildren(el('span', null, 'Матч'));
  }

  function back() {
    haptic();
    if (global.history.length > 1) global.history.back();
    else go('client-home');
  }

  function start() {
    if (tg) {
      try { tg.ready(); } catch (e) { /* */ }
      try {
        tg.BackButton.show();
        tg.BackButton.onClick(back);
      } catch (e) { /* старый клиент — кнопка в шапке */ }
    }
    // Токены сайта темнеют по body.tg-dark, а тема Mini App ставит hub-is-dark на <html> — как на главной.
    var syncDark = function () {
      doc.body.classList.toggle('tg-dark', doc.documentElement.classList.contains('hub-is-dark'));
    };
    syncDark();
    if (global.MutationObserver) {
      new global.MutationObserver(syncDark).observe(doc.documentElement, { attributes: true, attributeFilter: ['class'] });
    }
    $('cmBack').addEventListener('click', back);
    $('cmInvite').addEventListener('click', function () { openShare('invite'); });
    $('cmCompany').addEventListener('click', function () { openShare('company'); });
    if (!matchId) return fail('Матч не найден. Вернитесь на главную — там ближайший.');
    // Вернулся из чата (отправил карточку, друзья ответили) — обновляем «Кто из ваших» без перезагрузки.
    doc.addEventListener('visibilitychange', function () {
      if (doc.visibilityState !== 'visible' || !state.ev || state.busy) return;
      api('GET', '/client/hockey/matches/' + matchId + '/event').then(function (ev) {
        state.ev = ev;
        paint(ev);
      }, function () { /* старые данные остаются */ });
    });
    api('GET', '/client/hockey/matches/' + matchId + '/event')
      .then(function (ev) {
        state.ev = ev;
        $('cmMain').setAttribute('aria-busy', 'false');
        paint(ev);
      })
      .catch(function (e) {
        fail(e.status === 404 ? 'Матч не найден или уже убран из календаря.' : 'Не получилось загрузить матч. Попробуйте ещё раз.');
      });
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start);
  else start();
})(window);
