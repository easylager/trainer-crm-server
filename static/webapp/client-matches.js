/**
 * TASK-340: «Все матчи» — Экстралига на 7 дней по дням. Тап по матчу → client-match.
 * Рисуем только через createElement/textContent.
 */
(function (global) {
  'use strict';

  var doc = global.document;
  var M = global.ClientMatchModel;
  var tg = global.Telegram && global.Telegram.WebApp;
  var params = new URLSearchParams(global.location.search);

  function $(id) { return doc.getElementById(id); }

  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function initData() { return (tg && tg.initData) || params.get('init_data') || ''; }

  function go(path) {
    var shell = global.ClientShell;
    if (shell && typeof shell.navigate === 'function') return shell.navigate(path);
    var data = initData();
    global.location.href = '/webapp/' + path + (data ? (path.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(data) : '');
  }

  function logo(team) {
    var s = el('span', 'cm-logo');
    if (team.logo) {
      var img = el('img');
      img.src = team.logo;
      img.alt = '';
      s.appendChild(img);
    } else s.textContent = team.short || '';
    return s;
  }

  function row(m) {
    var a = el('a', 'cm-mrow');
    a.href = m.href;
    a.addEventListener('click', function (e) { e.preventDefault(); go(m.href); });
    var pair = el('span', 'cm-mrow__pair');
    pair.appendChild(logo(m.home));
    pair.appendChild(logo(m.away));
    a.appendChild(pair);
    var t = el('span', 'cm-mrow__text');
    t.appendChild(el('span', 'cm-mrow__name', m.home.name + ' — ' + m.away.name));
    t.appendChild(el('span', 'cm-mrow__sub', [m.arena, m.city].filter(Boolean).join(' · ')));
    a.appendChild(t);
    var r = m.result;
    a.appendChild(el('span', 'cm-mrow__time' + (m.live ? ' cm-mrow__time--live' : ''),
      r ? r.home_score + ':' + r.away_score : m.live ? 'идёт' : M.heroWhen(m.starts_at).split(' · ').pop()));
    return a;
  }

  function paint(matches) {
    var host = $('cmDays');
    if (!matches.length) {
      var s = $('cmState');
      s.textContent = 'На этой неделе матчей нет.';
      s.hidden = false;
      return host.replaceChildren();
    }
    var groups = [];
    matches.forEach(function (m) {
      var day = M.heroWhen(m.starts_at).split(' · ')[0];
      var g = groups[groups.length - 1];
      if (!g || g.day !== day) groups.push(g = { day: day, items: [] });
      g.items.push(m);
    });
    host.replaceChildren.apply(host, groups.map(function (g) {
      var sec = el('section', 'cm-day');
      sec.appendChild(el('h2', 'cm-h2', g.day));
      var card = el('div', 'cm-card cm-links');
      g.items.forEach(function (m) { card.appendChild(row(m)); });
      sec.appendChild(card);
      return sec;
    }));
  }

  function back() {
    if (global.history.length > 1) global.history.back();
    else go('client-home');
  }

  function start() {
    if (tg) {
      try { tg.ready(); tg.BackButton.show(); tg.BackButton.onClick(back); } catch (e) { /* старый клиент */ }
    }
    var syncDark = function () { doc.body.classList.toggle('tg-dark', doc.documentElement.classList.contains('hub-is-dark')); };
    syncDark();
    if (global.MutationObserver) new global.MutationObserver(syncDark).observe(doc.documentElement, { attributes: true, attributeFilter: ['class'] });
    $('cmBack').addEventListener('click', back);
    var data = initData();
    var url = '/api/webapp/client/hockey/extraliga/week' + (data ? '?init_data=' + encodeURIComponent(data) : '');
    fetch(url, { headers: data ? { 'X-Telegram-Init-Data': data } : {}, cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function (j) { $('cmMain').setAttribute('aria-busy', 'false'); paint(j.matches || []); })
      .catch(function () {
        var s = $('cmState');
        s.textContent = 'Не получилось загрузить матчи. Попробуйте ещё раз.';
        s.hidden = false;
      });
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start);
  else start();
})(window);
