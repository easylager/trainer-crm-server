/**
 * Вход для тренера на странице катка: строка «Тренируете на этом катке?» ведёт на лендинг
 * этого катка. Скрипт только считает тап (coach_open) — переход не задерживает.
 */
(function () {
  'use strict';

  var open = document.querySelector('[data-coach-open]');
  if (!open) return;

  var beacon = open.getAttribute('data-beacon') || '';
  open.addEventListener('click', function () {
    if (!beacon || !navigator.sendBeacon) return;
    try { navigator.sendBeacon(beacon + '&action=coach_open'); } catch (e) { /* учёт не важнее перехода */ }
  });
})();
