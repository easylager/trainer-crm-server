(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) { tg.ready(); tg.expand(); }
  var initData = tg ? tg.initData : '';

  function withInit(url) {
    var sep = url.indexOf('?') >= 0 ? '&' : '?';
    if (initData) url += sep + 'init_data=' + encodeURIComponent(initData);
    return url;
  }
  function request(method, path, body) {
    var opts = { method: method, headers: {} };
    if (body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(withInit('/api/webapp' + path), opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var msg = (data && data.detail) || ('Ошибка ' + r.status);
          throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
        }
        return data;
      });
    });
  }

  var citySelect = document.getElementById('citySelect');
  var slotsEl = document.getElementById('slots');
  var flagNote = document.getElementById('flagNote');
  var toast = document.getElementById('toast');
  var cityId = '';
  var searchTimer = {};

  function showToast(text, bad) {
    toast.textContent = text;
    toast.className = 'toast visible' + (bad ? ' bad' : '');
    setTimeout(function () { toast.className = 'toast' + (bad ? ' bad' : ''); }, 1800);
  }

  function loadCities() {
    return request('GET', '/admin/cities').then(function (data) {
      var items = (data && data.items) || [];
      citySelect.innerHTML = '';
      var blank = document.createElement('option');
      blank.value = '';
      blank.textContent = 'Выберите город';
      citySelect.appendChild(blank);
      items.forEach(function (city) {
        var opt = document.createElement('option');
        opt.value = String(city.id);
        opt.textContent = city.name;
        citySelect.appendChild(opt);
      });
    });
  }

  function renderBoard(data) {
    flagNote.textContent = data.enabled
      ? 'Город включён: свободные места добирает алгоритм.'
      : 'Город выключен флагом: на сайте подборки нет, закрепы сохраняются.';
    slotsEl.innerHTML = '';
    (data.positions || []).forEach(function (slot) {
      var box = document.createElement('section');
      box.className = 'slot';
      var title = document.createElement('h2');
      title.textContent = 'Позиция ' + slot.position;
      var line = document.createElement('div');
      line.className = 'line';
      line.textContent = slot.line;
      var input = document.createElement('input');
      input.type = 'text';
      input.placeholder = 'Поиск места по названию';
      var hits = document.createElement('ul');
      hits.className = 'hits';
      box.appendChild(title);
      box.appendChild(line);
      box.appendChild(input);
      box.appendChild(hits);
      if (slot.pin) {
        var drop = document.createElement('button');
        drop.type = 'button';
        drop.className = 'btn btn-ghost';
        drop.textContent = 'Снять';
        drop.style.marginTop = '8px';
        drop.addEventListener('click', function () {
          request('DELETE', '/admin/cities/' + cityId + '/for-you/' + slot.position)
            .then(renderBoard)
            .catch(function (err) { showToast(err.message, true); });
        });
        box.appendChild(drop);
      }
      input.addEventListener('input', function () {
        var q = input.value.trim();
        clearTimeout(searchTimer[slot.position]);
        if (!q) { hits.innerHTML = ''; return; }
        searchTimer[slot.position] = setTimeout(function () {
          request('GET', '/admin/cities/' + cityId + '/for-you/places?q=' + encodeURIComponent(q))
            .then(function (found) {
              hits.innerHTML = '';
              (found.items || []).forEach(function (place) {
                var li = document.createElement('li');
                var name = document.createElement('span');
                name.textContent = place.name + (place.kind_label ? ' · ' + place.kind_label : '');
                var pin = document.createElement('button');
                pin.type = 'button';
                pin.className = 'btn';
                pin.textContent = 'Закрепить';
                pin.addEventListener('click', function () {
                  request('POST', '/admin/cities/' + cityId + '/for-you', {
                    position: slot.position,
                    arena_id: place.arena_id
                  }).then(function (next) {
                    showToast('Закреплено');
                    renderBoard(next);
                  }).catch(function (err) { showToast(err.message, true); });
                });
                li.appendChild(name);
                li.appendChild(pin);
                hits.appendChild(li);
              });
            })
            .catch(function (err) { showToast(err.message, true); });
        }, 200);
      });
      slotsEl.appendChild(box);
    });
  }

  function loadBoard() {
    if (!cityId) { slotsEl.innerHTML = ''; flagNote.textContent = ''; return; }
    request('GET', '/admin/cities/' + cityId + '/for-you')
      .then(renderBoard)
      .catch(function (err) { showToast(err.message, true); });
  }

  citySelect.addEventListener('change', function () {
    cityId = citySelect.value;
    loadBoard();
  });

  loadCities().catch(function (err) { showToast(err.message, true); });
})();
