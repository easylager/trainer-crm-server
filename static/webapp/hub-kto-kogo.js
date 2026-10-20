/**
 * Строка «Кто кого» на главной (TASK-299, экраны 6–8 макета).
 *
 * Одна строка, один матч, сразу под «На льду». Бэкенд решает, показывать ли её (GET /client/hockey/hub):
 *   before — выездной до матча ≤ 48 ч (домашний — карточкой-событием за 14 дней): тап за команду прямо здесь; после хода — тихая строка;
 *   result — итог, пока игрок его не открыл (не дольше суток);
 *   null   — строки нет, главная как была.
 * Ничего не рисует без initData и при любой ошибке — главная не должна страдать из-за игры.
 */
(function () {
  'use strict';

  var M = window.KtoKogoModel;
  var tg = window.Telegram && window.Telegram.WebApp;
  // Как в самой игре: в Telegram — его initData, в браузерном превью — параметр init_data.
  var initData = (tg && tg.initData) || new URLSearchParams(location.search).get('init_data') || '';
  if (!M || !initData) return;

  var strip = null;

  function api(method, path, body) {
    var opts = { method: method, headers: { 'X-Telegram-Init-Data': initData } };
    if (body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch('/api/webapp' + path, opts).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.status === 204 ? null : r.json();
    });
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function gameUrl(query) {
    return 'kto-kogo' + (query ? '?' + query : '');
  }

  function open(query) {
    var shell = window.ClientShell;
    if (shell && typeof shell.navigate === 'function') shell.navigate(gameUrl(query));
    else location.href = '/webapp/' + gameUrl(query);
  }

  function badge(team, color) {
    var b = el('span', 'hub-kk__badge');
    b.style.setProperty('--team', color);
    if (team && team.logo) {
      b.classList.add('hub-kk__badge--logo');
      var img = el('img');
      img.src = team.logo;
      img.alt = '';
      b.appendChild(img);
    } else {
      b.textContent = (team && team.short) || '';
    }
    return b;
  }

  /** Встать сразу после «На льду». Зону главная двигает сама — переставляем при каждой отрисовке. */
  function place(node) {
    var zone = document.getElementById('hubIceZone');
    if (zone && zone.parentNode) {
      if (zone.nextSibling !== node) zone.parentNode.insertBefore(node, zone.nextSibling);
    } else if (!node.parentNode) {
      var shell = document.getElementById('hubShell') || document.body;
      shell.appendChild(node);
    }
  }

  function render(card) {
    if (!card || !card.mode || !card.match) {
      if (strip && strip.parentNode) strip.parentNode.removeChild(strip);
      strip = null;
      return;
    }
    var m = card.match;
    var colors = M.pairColors(m.home, m.away);
    var node = el('section', 'hub-kk');
    node.id = 'hubKtoKogo';
    node.setAttribute('aria-label', 'Кто кого');

    if (card.mode === 'result') {
      var pts = card.points == null ? 0 : card.points;
      var v = M.verdict(pts);
      var a = el('a', 'hub-kk__row hub-kk__row--' + v.tone);
      a.href = gameUrl('reveal=' + m.id);
      a.addEventListener('click', function (e) {
        e.preventDefault();
        open('reveal=' + m.id);
      });
      a.appendChild(el('span', 'hub-kk__sticker', v.sticker));
      var body = el('span', 'hub-kk__body');
      body.appendChild(el('span', 'hub-kk__head hub-kk__display', v.head));
      var r = m.result || {};
      var line = m.home.name + ' — ' + m.away.name + ' ' + r.home_score + ':' + r.away_score;
      if (card.place) line += ' · ты ' + card.place.rank + '-й в лиге';
      body.appendChild(el('span', 'hub-kk__sub', line));
      a.appendChild(body);
      a.appendChild(el('span', 'hub-kk__chev', '›'));
      node.appendChild(a);
    } else if (card.my_pick) {
      var side = card.my_pick.side;
      var q = el('a', 'hub-kk__row');
      q.href = gameUrl('');
      q.addEventListener('click', function (e) {
        e.preventDefault();
        open('');
      });
      var mark = badge(m[side], colors[side]);
      mark.classList.add('hub-kk__badge--big');
      q.appendChild(mark);
      var qb = el('span', 'hub-kk__body');
      qb.appendChild(el('span', 'hub-kk__head', 'Ты за ' + m[side].name));
      qb.appendChild(el('span', 'hub-kk__sub', M.whenLabel(m.starts_at, new Date())));
      q.appendChild(qb);
      var hasScore = card.my_pick.home_score != null;
      q.appendChild(el('span', 'hub-kk__chip', hasScore ? card.my_pick.home_score + ':' + card.my_pick.away_score : 'счёт +5'));
      node.appendChild(q);
    } else {
      var row = el('div', 'hub-kk__row hub-kk__row--pick');
      ['home', 'away'].forEach(function (which, i) {
        var btn = el('button', 'hub-kk__half');
        btn.type = 'button';
        btn.style.setProperty('--team', colors[which]);
        btn.setAttribute('aria-label', 'Я за ' + m[which].name);
        btn.appendChild(badge(m[which], colors[which]));
        btn.addEventListener('click', function () {
          try { tg.HapticFeedback.selectionChanged(); } catch (e) { /* */ }
          render({ mode: 'before', match: m, my_pick: { side: which, home_score: null, away_score: null } });
          api('PUT', '/client/hockey/matches/' + m.id + '/pick', { side: which }).catch(function () {
            render(card);
          });
        });
        if (i === 1) {
          var mid = el('a', 'hub-kk__mid');
          mid.href = gameUrl('');
          mid.addEventListener('click', function (e) {
            e.preventDefault();
            open('');
          });
          mid.appendChild(el('span', 'hub-kk__kicker hub-kk__display', 'кто кого?'));
          mid.appendChild(el('span', 'hub-kk__teams', m.home.name + ' — ' + m.away.name));
          mid.appendChild(el('span', 'hub-kk__sub', M.whenLabel(m.starts_at, new Date())));
          row.appendChild(mid);
        }
        row.appendChild(btn);
      });
      node.appendChild(row);
    }

    if (strip && strip.parentNode) strip.parentNode.removeChild(strip);
    strip = node;
    place(node);
  }

  function load() {
    api('GET', '/client/hockey/hub')
      .then(render)
      .catch(function () {
        render(null);
      });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
  else load();
  // Вернулись на главную из игры — итог уже открыт, ход уже сделан.
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) load();
  });
})();
