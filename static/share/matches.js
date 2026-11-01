/*
  TASK-347 · шторка перед переходом в Telegram и «До матча → Идёт» без запроса.
  Без JS остаётся обычная ссылка: колокольчик и «Кто кого» ведут сразу в Telegram.
*/
(function () {
  'use strict';

  var dialog = document.getElementById('mSheet');
  if (dialog && dialog.showModal) {
    var title = document.getElementById('mSheetTitle');
    var text = dialog.querySelector('[data-m-text]');
    var list = dialog.querySelector('[data-m-list]');
    var go = dialog.querySelector('[data-m-go]');
    var alt = dialog.querySelector('[data-m-alt]');

    var open = function (el) {
      var kind = el.getAttribute('data-m-sheet');
      var bell = kind === 'bell';
      var name = el.getAttribute('data-m-name') || '';
      var when = el.getAttribute('data-m-when') || '';
      title.textContent = bell ? 'Напомним о матче' : 'Угадай, кто победит';
      text.textContent = bell
        ? name + ', ' + when + '. Откроется бот Glide в Telegram — нажмите «Начать», и напоминание сразу встанет.'
        : 'Игра живёт в Telegram: один тап за команду — и вы в таблице всей страны. Без регистрации.';
      var points = bell
        ? ['Напомним за 3 часа до матча', 'После матча — счёт', 'Отписаться — одной кнопкой']
        : ['Очки после каждого матча', 'Короны каждый месяц — общая и по командам', 'Лиги с друзьями на любые команды'];
      var tick = '<svg class="b-icon b-icon--line" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
        '<path d="m5 12 5 5 9-10" stroke-width="2.4"/></svg>';
      list.innerHTML = '';
      points.forEach(function (p) {
        var li = document.createElement('li');
        li.innerHTML = tick;
        li.appendChild(document.createTextNode(p));
        list.appendChild(li);
      });
      go.setAttribute('href', el.getAttribute('href') || '#');
      var ics = el.getAttribute('data-m-ics');
      if (bell && ics) {
        alt.setAttribute('href', ics);
        alt.hidden = false;
      } else {
        alt.hidden = true;
      }
      dialog.showModal();
    };

    document.addEventListener('click', function (e) {
      var el = e.target && e.target.closest ? e.target.closest('[data-m-sheet]') : null;
      if (!el) return;
      e.preventDefault();
      open(el);
    });
    dialog.addEventListener('click', function (e) {
      if (e.target === dialog || (e.target.closest && e.target.closest('[data-sheet-close]'))) dialog.close();
    });
  }

  // До начала матча — «Билеты» и колокольчик; после — страница покажет «Идёт» при следующей загрузке.
  var start = document.querySelector('[data-m-start]');
  if (start) {
    var at = Date.parse(start.getAttribute('data-m-start') || '');
    if (!isNaN(at)) {
      var tick = function () {
        if (Date.now() < at) return;
        document.querySelectorAll('[data-m-before]').forEach(function (n) { n.hidden = true; });
        var badge = document.querySelector('[data-m-live-badge]');
        if (badge) badge.hidden = false;
      };
      setInterval(tick, 30000);
      tick();
    }
  }
})();
