/**
 * Вход для тренера на странице катка: строка «Тренируете на этом катке?» открывает
 * шторку-мини-лендинг. Без JS (или без <dialog>) строка остаётся ссылкой на /trainers.
 * Учёт: coach_open — открыли шторку, coach_join — нажали «Начать в Telegram».
 */
(function () {
  'use strict';

  var sheet = document.getElementById('coachSheet');
  var open = document.querySelector('[data-coach-open]');
  if (!sheet || !open || typeof sheet.showModal !== 'function') return;

  var beacon = sheet.getAttribute('data-beacon') || '';
  function track(action) {
    if (!beacon || !navigator.sendBeacon) return;
    try { navigator.sendBeacon(beacon + '&action=' + action); } catch (e) { /* учёт не важнее перехода */ }
  }

  function close() {
    if (sheet.open) sheet.close();
  }

  open.addEventListener('click', function (e) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
    e.preventDefault();
    sheet.showModal();
    track('coach_open');
  });

  sheet.addEventListener('click', function (e) {
    // Тап по затемнению вокруг шторки (сам <dialog>, не его содержимое) — закрыть.
    if (e.target === sheet || e.target.closest('[data-coach-close]')) close();
  });

  var join = sheet.querySelector('[data-coach-join]');
  if (join) join.addEventListener('click', function () { track('coach_join'); });
})();
