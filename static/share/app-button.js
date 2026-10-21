/**
 * Кнопка «Приложение» внизу экрана: знак Glide и слово, ведёт в то же место в Mini App.
 * Первый визит — с подписью «Запись и напоминания в Telegram» до первой прокрутки.
 * Когда виден подвал (у него своя «Открыть в Telegram»), кнопка уходит вниз.
 * Внутри Telegram её прячет CSS (body[data-client-shell] .tg-out).
 */
(function () {
  'use strict';

  var host = document.getElementById('appButton');
  if (!host) return;

  var KEY = 'glide.appbtn.seen';
  var sub = host.querySelector('.b-appbtn__sub');
  var seen = false;
  try { seen = window.localStorage.getItem(KEY) === '1'; } catch (e) { seen = true; }

  if (sub && !seen) {
    sub.hidden = false;
    host.classList.add('is-intro');
    try { window.localStorage.setItem(KEY, '1'); } catch (e) { /* приватный режим — подпись покажется снова */ }
    var collapse = function () {
      if (window.scrollY < 160) return;
      host.classList.remove('is-intro');
      sub.hidden = true;
      window.removeEventListener('scroll', collapse);
    };
    window.addEventListener('scroll', collapse, { passive: true });
  }

  var foot = document.querySelector('.b-site-foot');
  if (foot && typeof IntersectionObserver === 'function') {
    new IntersectionObserver(function (entries) {
      host.classList.toggle('is-away', entries[entries.length - 1].isIntersecting);
    }).observe(foot);
  }
})();
