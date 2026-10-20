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
    $('cmWhen').textContent = M.heroWhen(m.starts_at) + ' · ' + ((ev.arena && ev.arena.name) || 'Минск-Арена');
    var st = M.status(m);
    var pill = $('cmStatus');
    pill.textContent = st.text;
    pill.className = 'cm-status' + (st.live ? ' cm-status--live' : '');
    pill.hidden = false;
    doc.title = m.home.name + ' — ' + m.away.name;
  }

  // ---------- ответ ----------

  function paintRsvp(ev) {
    var box = $('cmSegs');
    var started = !!(ev.match.result || M.status(ev.match).live || ev.match.status === 'cancelled');
    $('cmRsvp').hidden = started;
    var bar = $('cmBar');
    if (bar) bar.hidden = started;
    if (started) return;
    box.replaceChildren.apply(box, M.ANSWERS.map(function (a) {
      var b = el('button', 'cm-seg', a.label);
      b.type = 'button';
      b.setAttribute('aria-pressed', ev.my_status === a.status ? 'true' : 'false');
      b.disabled = state.busy;
      b.addEventListener('click', function () { answer(a); });
      return b;
    }));
  }

  function answer(a) {
    if (state.busy || !state.ev || state.ev.my_status === a.status) return;
    haptic();
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
      match: { id: m.id, day: start[0] || '', time: start[1] || '' },
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
    box.hidden = !w;
    if (!w) return;
    $('cmWhoCount').textContent = w.count;
    $('cmWhoLine').textContent = w.line;
    $('cmFaces').replaceChildren.apply($('cmFaces'), w.initials.map(function (f) {
      return el('span', 'cm-face' + (f.me ? ' cm-face--me' : ''), f.letter);
    }));
  }

  // ---------- кто кого ----------

  function paintKk(ev) {
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
    tickets.hidden = !ev.tickets_url || started;
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
    paintWho(ev);
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
    api('GET', '/client/hockey/matches/' + matchId + '/event')
      .then(function (ev) {
        state.ev = ev;
        $('cmMain').setAttribute('aria-busy', 'false');
        paint(ev);
      })
      .catch(function (e) {
        fail(e.status === 404 ? 'Этот матч не на Минск-Арене или уже убран из календаря.' : 'Не получилось загрузить матч. Попробуйте ещё раз.');
      });
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start);
  else start();
})(window);
