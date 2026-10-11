/**
 * TASK-234: создание приглашения /zovi.
 * Чистые функции — и в браузере (window.ZoviCreate), и в node:test (module.exports).
 * Имена держатся в паре с normalize_invite_name в src/application/ice_invites.py.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ZoviCreate = api;
  }
  if (root && root.document && root.document.getElementById('zovi')) {
    api.mount(root.document);
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var NAME_MAX = 20;
  var HOCKEY = 'hockey_practice';
  var MINE_KEY = 'zovi_mine';
  var MINE_LIMIT = 20;
  var WEEKDAYS = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
  var MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  var STOP_ROOTS = [
    'хуй', 'пизд', 'бляд', 'блять', 'ебат', 'ебан', 'мудак', 'гандон', 'пидор', 'пидар', 'нацист',
    'fuck', 'bitch', 'cunt'
  ];
  var STOP_WORDS = ['сука', 'shit', 'nazi'];
  var DASHES = /[\u2013\u2014\u2212\u2010\u2011]/g;
  var NAME_RE = /^[A-Za-z\u0410-\u044f\u0401\u0451\u0406\u0456\u040e\u045e'’ʼ -]+$/;
  var LETTER_RE = /[A-Za-z\u0410-\u044f\u0401\u0451\u0406\u0456\u040e\u045e]/;

  function pad2(n) {
    return n < 10 ? '0' + n : String(n);
  }

  function parseISODate(iso) {
    var parts = String(iso || '').split('-');
    return new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2])));
  }

  function formatISODate(date) {
    return date.getUTCFullYear() + '-' + pad2(date.getUTCMonth() + 1) + '-' + pad2(date.getUTCDate());
  }

  function addDays(iso, days) {
    var date = parseISODate(iso);
    date.setUTCDate(date.getUTCDate() + days);
    return formatISODate(date);
  }

  function daysBetween(fromIso, toIso) {
    return Math.round((parseISODate(toIso) - parseISODate(fromIso)) / 86400000);
  }

  function nextWeekday(iso, target) {
    var delta = (target - parseISODate(iso).getUTCDay() + 7) % 7;
    return addDays(iso, delta);
  }

  function nextSaturday(iso) {
    return nextWeekday(iso, 6);
  }

  function minskToday(now) {
    var fmt = new Intl.DateTimeFormat('en-US', {
      timeZone: 'Europe/Minsk',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit'
    });
    var parts = fmt.formatToParts(now || new Date());
    var bag = {};
    var i;
    for (i = 0; i < parts.length; i += 1) bag[parts[i].type] = parts[i].value;
    return bag.year + '-' + bag.month + '-' + bag.day;
  }

  function chooseDefaultDate(todayIso, candidateIso, limit) {
    var max = limit == null ? 6 : limit;
    return daysBetween(todayIso, candidateIso) <= max ? candidateIso : todayIso;
  }

  function defaultInviteDate(todayIso) {
    return chooseDefaultDate(todayIso, nextSaturday(todayIso), 6);
  }

  function dayChips(todayIso) {
    return [
      { key: 'today', label: 'Сегодня', date: todayIso },
      { key: 'tomorrow', label: 'Завтра', date: addDays(todayIso, 1) },
      { key: 'sat', label: 'Сб', date: nextSaturday(todayIso) },
      { key: 'sun', label: 'Вс', date: nextWeekday(todayIso, 0) },
      { key: 'date', label: 'Дата', date: null }
    ];
  }

  function rememberedChipKey(chipKey, selected, todayIso) {
    var chips = dayChips(todayIso);
    var i;
    if (chipKey) {
      for (i = 0; i < chips.length; i += 1) {
        var chip = chips[i];
        if (chip.key !== chipKey) continue;
        if (chip.key === 'date' || chip.date === selected) return chip.key;
      }
    }
    return activeChipKey(selected, todayIso);
  }

  function activeChipKey(selected, todayIso) {
    var chips = dayChips(todayIso);
    var i;
    var match = [];
    for (i = 0; i < chips.length; i += 1) {
      if (chips[i].date && chips[i].date === selected) match.push(chips[i].key);
    }
    if (!match.length) return 'date';
    if (selected === defaultInviteDate(todayIso) && match.indexOf('sat') !== -1) return 'sat';
    if (match.indexOf('today') !== -1) return 'today';
    if (match.indexOf('tomorrow') !== -1) return 'tomorrow';
    if (match.indexOf('sat') !== -1) return 'sat';
    if (match.indexOf('sun') !== -1) return 'sun';
    return 'date';
  }

  function shortDate(iso) {
    var date = parseISODate(iso);
    return WEEKDAYS[date.getUTCDay()] + ', ' + date.getUTCDate() + ' ' + MONTHS[date.getUTCMonth()];
  }

  function nextDayLabel(iso) {
    var date = parseISODate(iso);
    return 'Ближайший день — ' + date.getUTCDate() + ' ' + MONTHS[date.getUTCMonth()];
  }

  function previewQuestion(toName, kind) {
    var name = String(toName || '').trim();
    var where = kind === HOCKEY ? 'на хоккей' : 'на каток';
    if (!name) return 'Пойдёшь со мной ' + where + '?';
    return name + ', пойдёшь со мной ' + where + '?';
  }

  function previewMeta(iso, time, arenaName) {
    return shortDate(iso) + ' · ' + time + ' · ' + arenaName;
  }

  function foldName(value) {
    return String(value || '').toLowerCase().replace(/ё/g, 'е').replace(/і/g, 'и').replace(/ў/g, 'у');
  }

  function compactName(value) {
    return foldName(value).replace(/[^a-zа-я]+/g, '');
  }

  function nameHasStopWord(name) {
    var compact = compactName(name);
    var i;
    if (!compact) return false;
    for (i = 0; i < STOP_ROOTS.length; i += 1) {
      if (compact.indexOf(compactName(STOP_ROOTS[i])) !== -1) return true;
    }
    var parts = String(name).split(/[\s\-'’ʼ]+/);
    var words = {};
    for (i = 0; i < parts.length; i += 1) {
      if (parts[i]) words[compactName(parts[i])] = true;
    }
    for (i = 0; i < STOP_WORDS.length; i += 1) {
      if (words[compactName(STOP_WORDS[i])]) return true;
    }
    return false;
  }

  function validateInviteName(raw, field, required) {
    var collapsed = String(raw || '').replace(DASHES, '-').trim().replace(/\s+/g, ' ');
    if (!collapsed) {
      if (required) {
        return { ok: false, value: null, error: field + ': укажите имя — от 1 до ' + NAME_MAX + ' символов.' };
      }
      return { ok: true, value: null, error: '' };
    }
    if (collapsed.length > NAME_MAX) {
      return { ok: false, value: null, error: field + ': не длиннее ' + NAME_MAX + ' символов.' };
    }
    if (!LETTER_RE.test(collapsed) || !NAME_RE.test(collapsed)) {
      return { ok: false, value: null, error: field + ': только буквы, пробел, дефис и апостроф.' };
    }
    if (nameHasStopWord(collapsed)) {
      return { ok: false, value: null, error: field + ': это имя нельзя использовать.' };
    }
    return { ok: true, value: collapsed, error: '' };
  }

  function inviteRequestBody(input) {
    var to = validateInviteName(input.toName, 'to_name', false);
    var from = validateInviteName(input.fromName, 'from_name', true);
    if (!to.ok || !from.ok) {
      return { ok: false, toError: to.error, fromError: from.error };
    }
    if (!input.sessionId) {
      return { ok: false, toError: '', fromError: '', formError: 'Выберите сеанс.' };
    }
    return {
      ok: true,
      body: {
        session_id: input.sessionId,
        to_name: to.value,
        from_name: from.value,
        show_price: !!input.showPrice,
        parent_code: input.parentCode || null
      }
    };
  }

  function kindLabel(kind) {
    if (kind === HOCKEY) return 'ОХМ';
    if (kind === 'open_ice') return 'Открытый лёд';
    if (kind === 'public_skate') return 'Массовое катание';
    return '';
  }

  function citiesWithSessions(items) {
    var out = [];
    var i;
    var list = items || [];
    for (i = 0; i < list.length; i += 1) {
      if ((list[i].skate_count || 0) > 0 || (list[i].ohm_count || 0) > 0) out.push(list[i]);
    }
    return out;
  }

  function pickCityId(cities, requested) {
    var i;
    if (requested) {
      for (i = 0; i < cities.length; i += 1) {
        if (cities[i].id === requested) return cities[i].id;
      }
    }
    for (i = 0; i < cities.length; i += 1) {
      if (cities[i].name === 'Минск') return cities[i].id;
    }
    return cities.length ? cities[0].id : null;
  }

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"]/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch];
    });
  }

  function track() {}

  function selectedSession(state) {
    var arenas = (state.slots && state.slots.arenas) || [];
    var a;
    var s;
    for (a = 0; a < arenas.length; a += 1) {
      var sessions = arenas[a].sessions || [];
      for (s = 0; s < sessions.length; s += 1) {
        if (sessions[s].id === state.sessionId) {
          return { arena: arenas[a], session: sessions[s] };
        }
      }
    }
    return null;
  }

  function readQuery(search) {
    var params = new URLSearchParams(search || '');
    var city = parseInt(params.get('city') || '', 10);
    var sessionId = parseInt(params.get('s') || '', 10);
    var from = (params.get('from') || '').trim();
    return {
      cityId: city > 0 ? city : null,
      sessionId: sessionId > 0 ? sessionId : null,
      parentCode: from || null
    };
  }

  function loadMine() {
    try {
      var raw = localStorage.getItem(MINE_KEY);
      var items = raw ? JSON.parse(raw) : [];
      return Array.isArray(items) ? items.slice(0, MINE_LIMIT) : [];
    } catch (err) {
      return [];
    }
  }

  function saveMine(entry) {
    try {
      var items = loadMine().filter(function (item) { return item.code !== entry.code; });
      items.unshift(entry);
      localStorage.setItem(MINE_KEY, JSON.stringify(items.slice(0, MINE_LIMIT)));
    } catch (err) {}
  }

  function mount(doc) {
    var state = {
      cities: [],
      cityId: null,
      today: minskToday(new Date()),
      date: null,
      slots: null,
      sessionId: null,
      chipKey: null,
      showPrice: false,
      parentCode: null,
      link: '',
      question: '',
      shareQuestion: '',
      busy: false
    };
    var query = readQuery(doc.location.search);
    state.parentCode = query.parentCode;
    state.sessionId = query.sessionId;
    state.date = defaultInviteDate(state.today);

    var citySelect = doc.getElementById('city');
    var daysEl = doc.getElementById('days');
    var dateInput = doc.getElementById('date-input');
    var slotsEl = doc.getElementById('slots');
    var emptyEl = doc.getElementById('empty');
    var nextBtn = doc.getElementById('next-day');
    var showPrice = doc.getElementById('show-price');
    var toInput = doc.getElementById('to-name');
    var fromInput = doc.getElementById('from-name');
    var toError = doc.getElementById('to-error');
    var fromError = doc.getElementById('from-error');
    var slotError = doc.getElementById('slot-error');
    var formError = doc.getElementById('form-error');
    var previewQ = doc.getElementById('preview-q');
    var previewT = doc.getElementById('preview-t');
    var previewUrl = doc.getElementById('preview-url');
    var done = doc.getElementById('done');
    var doneUrl = doc.getElementById('done-url');
    var friend = doc.getElementById('friend');
    var mineList = doc.getElementById('mine-list');
    var toast = doc.getElementById('toast');
    var form = doc.getElementById('zovi-form');
    var toastTimer = 0;

    function showToast(text) {
      toast.textContent = text;
      toast.hidden = false;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(function () { toast.hidden = true; }, 2200);
    }

    function copyText(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text).then(function () {
          showToast('Ссылка скопирована');
        }).catch(function () {
          fallbackCopy(text);
        });
      }
      fallbackCopy(text);
      return Promise.resolve();
    }

    function fallbackCopy(text) {
      var area = doc.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.left = '-9999px';
      doc.body.appendChild(area);
      area.select();
      try {
        doc.execCommand('copy');
        showToast('Ссылка скопирована');
      } catch (err) {
        showToast('Скопируйте ссылку вручную');
      }
      area.remove();
    }

    function paintCities() {
      var html = '';
      var i;
      for (i = 0; i < state.cities.length; i += 1) {
        var city = state.cities[i];
        html += '<option value="' + city.id + '"' + (city.id === state.cityId ? ' selected' : '') + '>' +
          esc(city.name) + '</option>';
      }
      if (!html && state.slots && state.slots.city_name) {
        html = '<option value="' + state.cityId + '" selected>' + esc(state.slots.city_name) + '</option>';
      }
      citySelect.innerHTML = html;
    }

    function paintDays() {
      var chips = dayChips(state.today);
      var active = rememberedChipKey(state.chipKey, state.date, state.today);
      var html = '';
      var i;
      for (i = 0; i < chips.length; i += 1) {
        var chip = chips[i];
        html += '<button type="button" class="day" data-key="' + chip.key + '" data-date="' +
          (chip.date || '') + '" aria-pressed="' + (chip.key === active ? 'true' : 'false') + '">' +
          chip.label + '</button>';
      }
      daysEl.innerHTML = html;
      dateInput.hidden = active !== 'date';
      dateInput.value = state.date || '';
    }

    function paintSlots() {
      var arenas = (state.slots && state.slots.arenas) || [];
      var html = '';
      var a;
      var s;
      slotError.textContent = '';
      if (!state.slots) {
        slotsEl.innerHTML = '<p class="status">Загружаем сеансы…</p>';
        emptyEl.hidden = true;
        nextBtn.hidden = true;
        return;
      }
      for (a = 0; a < arenas.length; a += 1) {
        var arena = arenas[a];
        var sessions = arena.sessions || [];
        for (s = 0; s < sessions.length; s += 1) {
          var session = sessions[s];
          var checked = session.id === state.sessionId ? ' checked' : '';
          var kind = kindLabel(session.kind);
          var price = state.showPrice && session.price ? ' · ' + session.price : '';
          var address = arena.address ? esc(arena.address) : '';
          html += '<label class="slot"><input type="radio" name="session" value="' + session.id + '"' + checked + ' />' +
            '<span class="slot__time">' + esc(session.starts_at_local) + '</span>' +
            '<span class="slot__place">' + esc(arena.name) +
            '<small>' + esc(kind) + price + (address ? ' · ' + address : '') + '</small></span>' +
            '<span class="slot__mark"></span></label>';
        }
      }
      slotsEl.innerHTML = html;
      var empty = !arenas.length;
      emptyEl.hidden = !empty;
      if (empty && state.slots.next_date) {
        nextBtn.hidden = false;
        nextBtn.textContent = nextDayLabel(state.slots.next_date);
        nextBtn.dataset.date = state.slots.next_date;
      } else {
        nextBtn.hidden = true;
      }
    }

    function paintPreview() {
      var picked = selectedSession(state);
      var kind = picked ? picked.session.kind : '';
      state.question = previewQuestion(toInput.value, kind);
      previewQ.textContent = state.question;
      if (picked) {
        previewT.textContent = previewMeta(state.date, picked.session.starts_at_local, picked.arena.name);
      } else {
        previewT.textContent = shortDate(state.date);
      }
    }

    function paintMine() {
      var items = loadMine();
      var html = '';
      var i;
      for (i = 0; i < items.length; i += 1) {
        var item = items[i];
        var card = esc(item.to || 'компания') + ' · ' + esc(item.when || '');
        html += '<li><a href="' + esc(item.code ? '/zovi/' + item.code : '#') + '">' + card + '</a>';
        if (item.status_path) {
          html += ' · <a href="' + esc(item.status_path) + '">статус</a>';
        }
        html += '</li>';
      }
      mineList.innerHTML = html;
    }

    function paint() {
      paintCities();
      paintDays();
      paintSlots();
      paintPreview();
      paintMine();
    }

    function getJson(url) {
      return fetch(url, { headers: { Accept: 'application/json' } }).then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          return { status: res.status, body: body };
        });
      });
    }

    function loadSlots() {
      if (!state.cityId || !state.date) {
        state.slots = { arenas: [], next_date: null, date: state.date };
        paintSlots();
        paintPreview();
        return Promise.resolve();
      }
      slotsEl.innerHTML = '<p class="status">Загружаем сеансы…</p>';
      return getJson('/api/public/invites/slots?city_id=' + state.cityId + '&date=' + state.date).then(function (res) {
        if (res.status !== 200) {
          state.slots = { arenas: [], next_date: null };
          formError.textContent = (res.body && res.body.detail) || 'Не удалось загрузить сеансы.';
        } else {
          state.slots = res.body;
          formError.textContent = '';
          if (state.sessionId && !selectedSession(state)) state.sessionId = null;
        }
        paintSlots();
        paintPreview();
      }).catch(function () {
        state.slots = { arenas: [], next_date: null };
        formError.textContent = 'Не удалось загрузить сеансы.';
        paintSlots();
      });
    }

    function applyLocated(body) {
      state.slots = body;
      state.cityId = body.city_id;
      state.date = body.date;
      if (state.sessionId && !selectedSession(state)) state.sessionId = null;
      ensureCityOption(body);
      paint();
    }

    function ensureCityOption(body) {
      var i;
      for (i = 0; i < state.cities.length; i += 1) {
        if (state.cities[i].id === body.city_id) return;
      }
      state.cities.unshift({ id: body.city_id, name: body.city_name || 'Город', skate_count: 1, ohm_count: 0 });
    }

    citySelect.addEventListener('change', function () {
      state.cityId = parseInt(citySelect.value, 10);
      state.sessionId = null;
      loadSlots();
    });

    daysEl.addEventListener('click', function (event) {
      var button = event.target.closest('button');
      if (!button) return;
      state.chipKey = button.dataset.key;
      if (button.dataset.key === 'date') {
        dateInput.hidden = false;
        dateInput.focus();
        paintDays();
        return;
      }
      if (!button.dataset.date) return;
      state.date = button.dataset.date;
      state.sessionId = null;
      paintDays();
      loadSlots();
    });

    dateInput.addEventListener('change', function () {
      if (!dateInput.value) return;
      state.chipKey = 'date';
      state.date = dateInput.value;
      state.sessionId = null;
      paintDays();
      loadSlots();
    });

    showPrice.addEventListener('change', function () {
      state.showPrice = showPrice.checked;
      paintSlots();
    });

    slotsEl.addEventListener('change', function (event) {
      var input = event.target;
      if (!input || input.name !== 'session') return;
      state.sessionId = parseInt(input.value, 10);
      slotError.textContent = '';
      paintPreview();
    });

    function onToName() {
      paintPreview();
    }
    function onFromName() {
      fromError.textContent = '';
      paintPreview();
    }
    toInput.addEventListener('input', onToName);
    toInput.addEventListener('change', onToName);
    fromInput.addEventListener('input', onFromName);
    fromInput.addEventListener('change', onFromName);

    nextBtn.addEventListener('click', function () {
      if (!nextBtn.dataset.date) return;
      state.chipKey = null;
      state.date = nextBtn.dataset.date;
      state.sessionId = null;
      paintDays();
      loadSlots();
    });

    function showServerDetail(detail) {
      var text = typeof detail === 'string' ? detail : 'Проверьте имена и сеанс.';
      toError.textContent = '';
      fromError.textContent = '';
      slotError.textContent = '';
      formError.textContent = '';
      if (text.indexOf('to_name:') === 0) toError.textContent = text;
      else if (text.indexOf('from_name:') === 0) fromError.textContent = text;
      else if (text.indexOf('session_id:') === 0) slotError.textContent = text;
      else formError.textContent = text;
    }

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      if (state.busy) return;
      paintPreview();
      var built = inviteRequestBody({
        toName: toInput.value,
        fromName: fromInput.value,
        sessionId: state.sessionId,
        showPrice: state.showPrice,
        parentCode: state.parentCode
      });
      toError.textContent = built.toError || '';
      fromError.textContent = built.fromError || '';
      formError.textContent = built.formError || '';
      if (!built.ok) return;
      state.busy = true;
      track('invite_submit', { session_id: state.sessionId });
      fetch('/api/public/invites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(built.body)
      }).then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          return { status: res.status, body: body };
        });
      }).then(function (res) {
        state.busy = false;
        if (res.status === 422 || res.status === 409 || res.status === 404) {
          showServerDetail(res.body && res.body.detail);
          return;
        }
        if (res.status !== 201 || !res.body || !res.body.code) {
          formError.textContent = 'Не удалось создать приглашение. Попробуйте ещё раз.';
          return;
        }
        var origin = doc.location.origin || '';
        var pickedNow = selectedSession(state);
        state.link = origin + res.body.invite_path;
        state.shareQuestion = previewQuestion(
          built.body.to_name,
          pickedNow ? pickedNow.session.kind : ''
        );
        done.hidden = false;
        doneUrl.textContent = state.link;
        friend.href = state.link;
        previewUrl.textContent = state.link.replace(/^https?:\/\//, '');
        saveMine({
          code: res.body.code,
          to: built.body.to_name || 'компания',
          when: pickedNow ? previewMeta(state.date, pickedNow.session.starts_at_local, pickedNow.arena.name) : state.date,
          status_path: origin + res.body.status_path
        });
        paintMine();
        track('invite_created', { code: res.body.code });
        done.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }).catch(function () {
        state.busy = false;
        formError.textContent = 'Не удалось создать приглашение. Попробуйте ещё раз.';
      });
    });

    doc.getElementById('send').addEventListener('click', function () {
      if (!state.link) return;
      var text = (state.shareQuestion || state.question) + '\n' + state.link;
      track('invite_share', {});
      if (navigator.share) {
        navigator.share({ text: text, url: state.link }).catch(function (err) {
          if (err && err.name === 'AbortError') return;
          copyText(state.link);
        });
        return;
      }
      copyText(state.link);
    });

    doc.getElementById('copy').addEventListener('click', function () {
      if (state.link) copyText(state.link);
    });

    paintMine();
    paintDays();
    slotsEl.innerHTML = '<p class="status">Загружаем сеансы…</p>';

    getJson('/api/public/ice/cities').then(function (res) {
      state.cities = citiesWithSessions(res.status === 200 && res.body ? res.body.items : []);
      if (!state.cities.length && !query.sessionId) {
        formError.textContent = 'Сейчас нет сеансов, на которые можно позвать.';
      }
      if (query.sessionId) {
        return getJson('/api/public/invites/slots?session_id=' + query.sessionId).then(function (located) {
          if (located.status === 200 && located.body && located.body.city_id) {
            applyLocated(located.body);
            return;
          }
          state.cityId = pickCityId(state.cities, query.cityId);
          state.date = defaultInviteDate(state.today);
          paint();
          return loadSlots();
        });
      }
      state.cityId = pickCityId(state.cities, query.cityId);
      state.date = defaultInviteDate(state.today);
      paint();
      return loadSlots();
    }).catch(function () {
      formError.textContent = 'Не удалось загрузить сеансы.';
    });
  }

  return {
    previewQuestion: previewQuestion,
    previewMeta: previewMeta,
    defaultInviteDate: defaultInviteDate,
    chooseDefaultDate: chooseDefaultDate,
    nextSaturday: nextSaturday,
    dayChips: dayChips,
    activeChipKey: activeChipKey,
    rememberedChipKey: rememberedChipKey,
    nextDayLabel: nextDayLabel,
    validateInviteName: validateInviteName,
    inviteRequestBody: inviteRequestBody,
    kindLabel: kindLabel,
    citiesWithSessions: citiesWithSessions,
    pickCityId: pickCityId,
    minskToday: minskToday,
    readQuery: readQuery,
    mount: mount,
    track: track
  };
});
