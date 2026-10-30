/**
 * Каталог «Матчи»: все лиги на одной странице. Фильтры team / league / city / arena / when
 * живут в адресе, поэтому любой вход (Главная, матч, арена) — просто ссылка с параметрами.
 * Рисуем только через createElement/textContent.
 */
(function (global) {
  'use strict';

  var doc = global.document;
  var M = global.ClientMatchModel;
  var tg = global.Telegram && global.Telegram.WebApp;
  var params = new URLSearchParams(global.location.search);
  var KEYS = ['team', 'league', 'city', 'arena'];
  var state = { when: params.get('when') === 'results' ? 'results' : 'upcoming' };
  KEYS.forEach(function (k) { state[k] = params.get(k) || null; });
  var last = null;
  var seq = 0;

  function $(id) { return doc.getElementById(id); }

  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function button(cls, text, onClick) {
    var b = el('button', cls, text);
    b.type = 'button';
    b.addEventListener('click', onClick);
    return b;
  }

  function initData() { return (tg && tg.initData) || params.get('init_data') || ''; }

  function go(path) {
    var shell = global.ClientShell;
    if (shell && typeof shell.navigate === 'function') return shell.navigate(path);
    var data = initData();
    global.location.href = '/webapp/' + path + (data ? (path.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(data) : '');
  }

  function openLink(url) {
    if (tg && typeof tg.openLink === 'function') tg.openLink(url);
    else global.open(url, '_blank', 'noopener');
  }

  function query(s) {
    var q = new URLSearchParams();
    KEYS.forEach(function (k) { if (s[k]) q.set(k, s[k]); });
    if (s.when === 'results') q.set('when', 'results');
    return q;
  }

  function syncUrl() {
    var q = query(state);
    if (params.get('init_data')) q.set('init_data', params.get('init_data'));
    var qs = q.toString();
    try { global.history.replaceState(null, '', global.location.pathname + (qs ? '?' + qs : '') + global.location.hash); } catch (e) { /* file:// */ }
  }

  function logo(team) {
    var s = el('span', 'cm-logo');
    if (team && team.logo) {
      var img = el('img');
      img.src = team.logo;
      img.alt = '';
      s.appendChild(img);
    } else s.textContent = (team && team.short) || '';
    return s;
  }

  function timeText(m) {
    var r = m.result;
    if (r) return r.home_score + ':' + r.away_score + (r.decided_in === 'ot' ? ' ОТ' : r.decided_in === 'so' ? ' Б' : '');
    if (m.live) return 'идёт';
    return M.heroWhen(m.starts_at).split(' · ').pop();
  }

  function row(m) {
    var a;
    if (m.href) {
      a = el('a', 'cm-mrow');
      a.href = m.href;
      a.addEventListener('click', function (e) { e.preventDefault(); go(m.href); });
    } else if (m.external_url) {
      a = el('a', 'cm-mrow');
      a.href = m.external_url;
      a.addEventListener('click', function (e) { e.preventDefault(); openLink(m.external_url); });
    } else a = el('div', 'cm-mrow');
    var pair = el('span', 'cm-mrow__pair');
    pair.appendChild(logo(m.home));
    pair.appendChild(logo(m.away));
    a.appendChild(pair);
    var t = el('span', 'cm-mrow__text');
    t.appendChild(el('span', 'cm-mrow__name', m.home.name + ' — ' + m.away.name));
    var sub = el('span', 'cm-mrow__sub');
    if (!state.league) sub.appendChild(el('span', 'mx-tag' + (m.league === 'khl' ? ' mx-tag--khl' : ''), m.league_label));
    sub.appendChild(doc.createTextNode([m.arena, m.city].filter(Boolean).join(' · ') || (m.external_url ? 'выезд · hcdinamo.by' : '')));
    t.appendChild(sub);
    a.appendChild(t);
    a.appendChild(el('span', 'cm-mrow__time' + (m.live ? ' cm-mrow__time--live' : ''), timeText(m)));
    return a;
  }

  function paintHero(f) {
    var hero = $('cmHero');
    var title = $('cmTitle');
    $('cmKicker').textContent = f.league_label || 'Хоккей';
    hero.classList.toggle('cm-hero--team', !!f.team_card);
    if (f.team_card) {
      title.replaceChildren(logo(f.team_card), doc.createTextNode(f.team_card.name));
    } else {
      title.textContent = f.arena || (f.city ? 'Матчи · ' + f.city : 'Матчи');
    }
    doc.title = f.team_card ? f.team_card.name : 'Матчи';
  }

  function chip(text, on, onClick, img) {
    var c = button('mx-chip' + (on ? ' mx-chip--on' : ''), null, onClick);
    if (img) {
      var i = el('img');
      i.src = img;
      i.alt = '';
      c.appendChild(i);
    }
    c.appendChild(doc.createTextNode(text));
    if (on) c.appendChild(el('span', 'mx-chip__x', '×'));
    if (on) c.setAttribute('aria-label', text + ': убрать фильтр');
    return c;
  }

  function paintBar(f) {
    var bar = $('cmBar');
    var items = [chip('Фильтры', false, openSheet)];
    function drop(keys) { return function () { keys.forEach(function (k) { state[k] = null; }); load(); }; }
    if (f.team_card) items.push(chip(f.team_card.name, true, drop(['team']), f.team_card.logo));
    if (f.league_label) items.push(chip(f.league_label, true, drop(['league'])));
    if (f.city) items.push(chip(f.city, true, drop(['city', 'arena'])));
    if (f.arena) items.push(chip(f.arena, true, drop(['arena'])));
    bar.replaceChildren.apply(bar, items);
  }

  function paintList(matches) {
    var host = $('cmDays');
    var s = $('cmState');
    if (!matches.length) {
      var any = KEYS.some(function (k) { return state[k]; });
      s.replaceChildren(doc.createTextNode(state.when === 'results'
        ? 'За последний месяц результатов нет.'
        : any ? 'По этим фильтрам ближайших матчей нет.' : 'Ближайших матчей нет.'));
      if (any) {
        s.appendChild(doc.createElement('br'));
        s.appendChild(button('mx-reset', 'Сбросить фильтры', function () { KEYS.forEach(function (k) { state[k] = null; }); load(); }));
      }
      s.hidden = false;
      return host.replaceChildren();
    }
    s.hidden = true;
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
      var card = el('div', 'cm-card cm-mlist');
      g.items.forEach(function (m) { card.appendChild(row(m)); });
      sec.appendChild(card);
      return sec;
    }));
  }

  function closeSheet() {
    var host = $('cmSheet');
    host.hidden = true;
    host.replaceChildren();
  }

  function openSheet() {
    if (!last) return;
    var draft = { team: state.team, league: state.league, city: state.city, arena: state.arena };
    var facets = last.facets || {};
    var host = $('cmSheet');
    var dim = el('div', 'mx-dim');
    dim.addEventListener('click', closeSheet);
    var sheet = el('div', 'mx-sheet');
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-label', 'Фильтры матчей');

    function paint() {
      var parts = [el('div', 'mx-grab')];
      parts.push(el('h2', 'mx-sh', 'Команда'));
      var grid = el('div', 'mx-grid');
      (facets.teams || []).forEach(function (t) {
        var b = button('mx-tc', null, function () { draft.team = draft.team === t.slug ? null : t.slug; paint(); });
        b.setAttribute('aria-pressed', String(draft.team === t.slug));
        if (t.logo) {
          var i = el('img');
          i.src = t.logo;
          i.alt = '';
          b.appendChild(i);
        }
        b.appendChild(doc.createTextNode(t.short && t.name.length > 10 ? t.short : t.name));
        grid.appendChild(b);
      });
      parts.push(grid);
      if ((facets.leagues || []).length > 1 || draft.league) {
        parts.push(el('h2', 'mx-sh', 'Лига'));
        var leagues = el('div', 'mx-chips');
        leagues.appendChild(chipPick('Все', !draft.league, function () { draft.league = null; paint(); }));
        (facets.leagues || []).forEach(function (l) {
          leagues.appendChild(chipPick(l.label, draft.league === l.id, function () { draft.league = l.id; paint(); }));
        });
        parts.push(leagues);
      }
      parts.push(el('h2', 'mx-sh', 'Где'));
      var cities = el('div', 'mx-chips');
      cities.appendChild(chipPick('Вся Беларусь', !draft.city, function () { draft.city = null; draft.arena = null; paint(); }));
      (facets.cities || []).forEach(function (c) {
        cities.appendChild(chipPick(c.name, draft.city === c.name, function () {
          if (draft.city !== c.name) draft.arena = null;
          draft.city = c.name;
          paint();
        }));
      });
      parts.push(cities);
      if (draft.city && draft.city === state.city && (facets.arenas || []).length > 1) {
        var all = button('mx-arow', null, function () { draft.arena = null; paint(); });
        all.setAttribute('aria-pressed', String(!draft.arena));
        all.append('Все арены · ' + draft.city, el('span', null, ''));
        parts.push(all);
        facets.arenas.forEach(function (a) {
          var r = button('mx-arow', null, function () { draft.arena = a.name; paint(); });
          r.setAttribute('aria-pressed', String(draft.arena === a.name));
          r.append(a.name, el('span', null, a.count + ' ' + M.plural(a.count, 'матч', 'матча', 'матчей')));
          parts.push(r);
        });
      }
      parts.push(button('mx-go', 'Показать матчи', function () {
        KEYS.forEach(function (k) { state[k] = draft[k]; });
        closeSheet();
        load();
      }));
      sheet.replaceChildren.apply(sheet, parts);
    }

    paint();
    host.replaceChildren(dim, sheet);
    host.hidden = false;
  }

  function chipPick(text, on, onClick) {
    var c = button('mx-chip' + (on ? ' mx-chip--on' : ''), text, onClick);
    c.setAttribute('aria-pressed', String(on));
    return c;
  }

  function paintWhen() {
    Array.prototype.forEach.call(doc.querySelectorAll('.mx-when__b'), function (b) {
      b.setAttribute('aria-pressed', String(b.getAttribute('data-when') === state.when));
    });
  }

  function load() {
    syncUrl();
    paintWhen();
    var mine = ++seq;
    var data = initData();
    var q = query(state);
    if (data) q.set('init_data', data);
    $('cmMain').setAttribute('aria-busy', 'true');
    fetch('/api/webapp/client/hockey/matches/catalog?' + q.toString(), { headers: data ? { 'X-Telegram-Init-Data': data } : {}, cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(function (j) {
        if (mine !== seq) return;
        last = j;
        $('cmMain').setAttribute('aria-busy', 'false');
        paintHero(j.filters || {});
        paintBar(j.filters || {});
        paintList(j.matches || []);
      })
      .catch(function () {
        if (mine !== seq) return;
        var s = $('cmState');
        s.textContent = 'Не получилось загрузить матчи. Попробуйте ещё раз.';
        s.hidden = false;
      });
  }

  function back() {
    if (!$('cmSheet').hidden) return closeSheet();
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
    Array.prototype.forEach.call(doc.querySelectorAll('.mx-when__b'), function (b) {
      b.addEventListener('click', function () {
        var w = b.getAttribute('data-when');
        if (w === state.when) return;
        state.when = w;
        load();
      });
    });
    load();
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start);
  else start();
})(window);
