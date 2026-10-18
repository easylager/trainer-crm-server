(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) { tg.ready(); tg.expand(); }
  var initData = tg ? tg.initData : '';

  var MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  var STATUS = {
    scheduled: 'ждёт итога',
    final: 'итог есть',
    review: 'на проверке',
    cancelled: 'отменён'
  };
  var SOURCE = { auto: 'автоматически', manual: 'вручную' };

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

  function formatWhen(iso) {
    var parts = {};
    new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Minsk',
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23'
    }).formatToParts(new Date(iso)).forEach(function (part) { parts[part.type] = part.value; });
    return Number(parts.day) + ' ' + MONTHS[Number(parts.month) - 1] + ', ' + parts.hour + ':' + parts.minute;
  }

  function renderList(el, items, showReason) {
    el.innerHTML = '';
    if (!items.length) {
      var empty = document.createElement('p');
      empty.className = 'empty';
      empty.textContent = showReason ? 'Нет матчей на проверке.' : 'Матчей пока нет.';
      el.appendChild(empty);
      return;
    }
    items.forEach(function (match) { el.appendChild(renderCard(match, showReason)); });
  }

  function renderCard(match, showReason) {
    var card = document.createElement('article');
    card.className = 'card';
    card.dataset.id = String(match.id);

    var teams = document.createElement('p');
    teams.className = 'teams';
    teams.textContent = match.home_team + ' — ' + match.away_team;

    var when = document.createElement('p');
    when.className = 'when';
    when.textContent = formatWhen(match.starts_at);

    var meta = document.createElement('p');
    meta.className = 'meta';
    var bits = [STATUS[match.status] || match.status];
    if (match.home_score != null && match.away_score != null) bits.push(match.home_score + ':' + match.away_score);
    if (SOURCE[match.result_source]) bits.push(SOURCE[match.result_source]);
    meta.textContent = bits.join(' · ');

    card.appendChild(teams);
    card.appendChild(when);
    card.appendChild(meta);
    if (showReason && match.review_reason) {
      var reason = document.createElement('p');
      reason.className = 'reason';
      reason.textContent = match.review_reason;
      card.appendChild(reason);
    }

    var form = document.createElement('form');
    var home = numberField('Хозяева', match.home_score);
    var away = numberField('Гости', match.away_score);
    var decided = document.createElement('label');
    decided.textContent = 'Как решён';
    var select = document.createElement('select');
    [['regulation', 'в основное время'], ['ot', 'в овертайме'], ['so', 'по буллитам']].forEach(function (opt) {
      var option = document.createElement('option');
      option.value = opt[0];
      option.textContent = opt[1];
      if (match.decided_in === opt[0]) option.selected = true;
      select.appendChild(option);
    });
    decided.appendChild(select);
    var button = document.createElement('button');
    button.type = 'submit';
    button.className = 'btn';
    button.textContent = 'Сохранить итог';
    var err = document.createElement('p');
    err.className = 'err';
    err.hidden = true;
    form.appendChild(home.label);
    form.appendChild(away.label);
    form.appendChild(decided);
    form.appendChild(button);
    form.appendChild(err);
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      err.hidden = true;
      err.textContent = '';
      request('POST', '/admin/hockey/matches/' + match.id + '/result', {
        home_score: Number(home.input.value),
        away_score: Number(away.input.value),
        decided_in: select.value
      }).then(function () {
        return load();
      }).catch(function (error) {
        err.hidden = false;
        err.textContent = error.message;
      });
    });
    card.appendChild(form);
    return card;
  }

  function numberField(caption, value) {
    var label = document.createElement('label');
    label.appendChild(document.createTextNode(caption));
    var input = document.createElement('input');
    input.type = 'number';
    input.min = '0';
    input.required = true;
    input.inputMode = 'numeric';
    if (value != null) input.value = String(value);
    label.appendChild(input);
    return { label: label, input: input };
  }

  var reviewEl = document.getElementById('review');
  var recentEl = document.getElementById('recent');

  function load() {
    return Promise.all([
      request('GET', '/admin/hockey/matches?status=review'),
      request('GET', '/admin/hockey/matches?status=all')
    ]).then(function (pair) {
      renderList(reviewEl, pair[0].items || [], true);
      renderList(recentEl, pair[1].items || [], false);
    }).catch(function (error) {
      recentEl.innerHTML = '';
      var fail = document.createElement('p');
      fail.className = 'err';
      fail.textContent = error.message;
      recentEl.appendChild(fail);
    });
  }

  load();
})();
