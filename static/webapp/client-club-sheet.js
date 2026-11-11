/**
 * «За кого болеешь?» (TASK-371 S2).
 * ClientClubSheet.open({ current: club|null, onSaved(club|null) }).
 * Клуб — строка (имя, как fav_club) или объект с name. onSaved получает объект каталога или null.
 */
(function (root) {
  'use strict';

  var CLUBS_URL = '/api/webapp/client/hockey/clubs';
  var PREFS_URL = '/api/webapp/client/hockey/bot-prefs';
  var SAVE_ERROR = 'Не сохранилось. Попробуй ещё раз';
  var LOAD_ERROR = 'Не загрузилось. Попробуй ещё раз';
  var LEAGUES = [
    { id: 'khl', title: 'КХЛ' },
    { id: 'extraliga', title: 'Экстралига' },
  ];

  function norm(value) {
    return String(value || '').toLowerCase().replace(/ё/g, 'е').trim();
  }

  function filterClubs(items, query) {
    var list = Array.isArray(items) ? items : [];
    var needle = norm(query);
    if (!needle) return list.slice();
    return list.filter(function (item) {
      return norm(item && item.name).indexOf(needle) !== -1;
    });
  }

  function groupClubs(items) {
    var buckets = { khl: [], extraliga: [] };
    var list = Array.isArray(items) ? items : [];
    for (var i = 0; i < list.length; i++) {
      var item = list[i];
      if (item && buckets[item.league]) buckets[item.league].push(item);
    }
    var out = [];
    for (var g = 0; g < LEAGUES.length; g++) {
      var league = LEAGUES[g];
      if (buckets[league.id].length) out.push({ league: league.id, title: league.title, items: buckets[league.id] });
    }
    return out;
  }

  function buttonState(selectedName, busy) {
    var name = typeof selectedName === 'string' ? selectedName : '';
    if (!name.trim()) return { label: 'Выбери команду', disabled: true };
    return { label: 'Болею за\u00a0' + name, disabled: !!busy };
  }

  // Что показывать вместо списка: loading | error | no-match | list.
  // «Такой команды нет» — только при поиске по загруженному списку.
  function listState(loadState, items, query) {
    if (loadState === 'error') return { kind: 'error', text: LOAD_ERROR };
    if (loadState !== 'loaded') return { kind: 'loading', text: '' };
    var groups = groupClubs(filterClubs(items, query));
    if (norm(query) && !groups.length) return { kind: 'no-match', text: 'Такой команды нет' };
    return { kind: 'list', text: '' };
  }

  function named(current) {
    if (typeof current === 'string') return current.trim() || null;
    if (current && typeof current === 'object' && typeof current.name === 'string' && current.name.trim()) return current.name.trim();
    return null;
  }

  function findByName(items, name) {
    if (!name) return null;
    for (var i = 0; i < items.length; i++) {
      if (items[i] && items[i].name === name) return items[i];
    }
    return null;
  }

  function initData() {
    var tg = root.Telegram && root.Telegram.WebApp;
    if (tg && tg.initData) return String(tg.initData);
    try {
      var search = root.location && root.location.search;
      if (!search) return '';
      return new URLSearchParams(search).get('init_data') || '';
    } catch (err) {
      return '';
    }
  }

  function authHeaders(json) {
    var headers = { 'X-Telegram-Init-Data': initData() };
    if (json) headers['Content-Type'] = 'application/json';
    return headers;
  }

  function hapticSuccess() {
    try {
      var tg = root.Telegram && root.Telegram.WebApp;
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    } catch (err) { /* нет вибрации */ }
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function svgIcon() {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS ? document.createElementNS(ns, 'svg') : document.createElement('svg');
    svg.setAttribute('width', '18');
    svg.setAttribute('height', '18');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.8');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    function part(name, attrs) {
      var node = document.createElementNS ? document.createElementNS(ns, name) : document.createElement(name);
      for (var key in attrs) if (Object.prototype.hasOwnProperty.call(attrs, key)) node.setAttribute(key, attrs[key]);
      svg.appendChild(node);
    }
    part('circle', { cx: '11', cy: '11', r: '7' });
    part('path', { d: 'm20 20-3.9-3.9' });
    return svg;
  }

  function open(opts) {
    opts = opts || {};
    var Sheet = root.ClientSheet;
    var wanted = named(opts.current);
    var selected = wanted ? (opts.current && typeof opts.current === 'object' ? opts.current : { name: wanted }) : null;
    var picked = false;
    var busy = false;
    var catalog = [];
    var alive = true;
    var loadState = 'loading';

    var content = el('div', 'cc');
    var title = el('h2', 'cc-title', 'За\u00a0кого болеешь?');
    title.id = 'cc-title';
    var sub = el('p', 'cc-sub', 'Её матчи будут первыми в\u00a0«Кто кого».');

    var search = el('label', 'cc-search');
    search.appendChild(svgIcon());
    search.appendChild(el('span', 'cs-sr', 'Найти команду'));
    var input = document.createElement('input');
    input.type = 'search';
    input.placeholder = 'Название команды';
    input.setAttribute('placeholder', 'Название команды');
    search.appendChild(input);

    var list = el('div', 'cs-scroll cc-list');
    var actions = el('div', 'cc-actions');
    var toast = el('p', 'cc-toast');
    toast.setAttribute('role', 'status');
    toast.hidden = true;
    var save = el('button', 'cc-save', 'Выбери команду');
    save.type = 'button';
    save.disabled = true;
    var clearBtn = el('button', 'cc-clear', 'Пока ни за\u00a0кого');
    clearBtn.type = 'button';
    actions.appendChild(toast);
    actions.appendChild(save);
    actions.appendChild(clearBtn);
    content.appendChild(title);
    content.appendChild(sub);
    content.appendChild(search);
    content.appendChild(list);
    content.appendChild(actions);

    function paintButton() {
      var state = buttonState(selected && selected.name, busy);
      save.textContent = state.label;
      save.disabled = state.disabled;
      save.classList.toggle('is-ready', !!(selected && selected.name && String(selected.name).trim()));
      clearBtn.disabled = !!busy;
    }

    function rowFor(item) {
      var label = el('label', 'cc-row');
      var mark = el('span', 'cc-mark');
      if (item.logo && String(item.logo).trim()) {
        var img = document.createElement('img');
        img.setAttribute('src', item.logo);
        img.setAttribute('alt', '');
        mark.appendChild(img);
      } else {
        mark.classList.add('cc-mark--letter');
        if (item.color) mark.style.backgroundColor = item.color;
        mark.textContent = item.short || '';
      }
      var radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'cc-club';
      radio.value = item.name || '';
      radio.checked = !!(selected && selected.name === item.name);
      radio.addEventListener('change', function () {
        if (!radio.checked) return;
        picked = true;
        selected = item;
        paintButton();
      });
      label.appendChild(mark);
      label.appendChild(el('span', 'cc-name', item.name || ''));
      label.appendChild(radio);
      return label;
    }

    function paintList() {
      var query = input.value;
      var groups = groupClubs(filterClubs(catalog, query));
      while (list.firstChild) list.removeChild(list.firstChild);
      var view = listState(loadState, catalog, query);
      if (view.kind === 'error' || view.kind === 'no-match') {
        list.appendChild(el('p', 'cc-empty', view.text));
        return;
      }
      for (var g = 0; g < groups.length; g++) {
        list.appendChild(el('h3', 'cc-league', groups[g].title));
        for (var i = 0; i < groups[g].items.length; i++) list.appendChild(rowFor(groups[g].items[i]));
      }
    }

    function showError() {
      toast.textContent = SAVE_ERROR;
      toast.hidden = false;
    }

    function submit(body, saved) {
      if (busy || !alive) return;
      busy = true;
      paintButton();
      fetch(PREFS_URL, {
        method: 'PUT',
        headers: authHeaders(true),
        body: JSON.stringify(body),
      }).then(function (response) {
        if (!response.ok) throw new Error('save');
        return response.json().catch(function () { return {}; });
      }).then(function () {
        if (!alive || sheet.el.getAttribute('data-closing') === '1') return;
        hapticSuccess();
        alive = false;
        sheet.close();
        if (typeof opts.onSaved === 'function') opts.onSaved(saved);
      }).catch(function () {
        if (!alive) return;
        busy = false;
        paintButton();
        showError();
      });
    }

    paintButton();
    var sheet = Sheet.open({
      labelledBy: 'cc-title',
      content: content,
      onClose: function () { alive = false; },
    });

    input.addEventListener('input', paintList);
    save.addEventListener('click', function () {
      if (!selected || !selected.name) return;
      submit({ fav_club: selected.name }, selected);
    });
    clearBtn.addEventListener('click', function () {
      submit({ clear_fav_club: true }, null);
    });

    fetch(CLUBS_URL, { method: 'GET', headers: authHeaders(false) }).then(function (response) {
      if (!response.ok) throw new Error('clubs');
      return response.json();
    }).then(function (data) {
      if (!alive) return;
      catalog = data && Array.isArray(data.items) ? data.items : [];
      loadState = 'loaded';
      if (!picked) selected = findByName(catalog, wanted);
      else if (selected) {
        var match = findByName(catalog, selected.name);
        if (match) selected = match;
      }
      paintList();
      paintButton();
    }).catch(function () {
      if (!alive) return;
      loadState = 'error';
      catalog = [];
      if (!picked) selected = null;
      paintList();
      paintButton();
    });

    return { close: sheet.close, el: sheet.el };
  }

  var api = {
    open: open,
    filterClubs: filterClubs,
    groupClubs: groupClubs,
    buttonState: buttonState,
    listState: listState,
  };
  root.ClientClubSheet = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
