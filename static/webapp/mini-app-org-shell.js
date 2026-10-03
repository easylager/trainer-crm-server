/**
 * Org Mini App shell (TASK-141 S1): bottom tab bar + «Ещё» sheet.
 *
 * Deliberately lean vs. mini-app-trainer-shell.js: no drill-down observers, no dynamic
 * badge counts yet — those land with the slices that give them real data (S4 Команда,
 * S2 Подписка, etc.). Mount with <body data-org-shell="tabs" data-org-active="home">.
 */
(function (global) {
  'use strict';

  var ICONS = {
    home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V9.5z"/></svg>',
    schedule: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
    clients: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    catalog: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h2M7 17h2"/></svg>',
    more: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none"/></svg>',
  };

  var TABS = [
    { id: 'home', label: 'Главная', path: 'org-home', icon: ICONS.home },
    { id: 'schedule', label: 'Расписание', path: null, icon: ICONS.schedule, soon: true },
    { id: 'clients', label: 'Клиенты', path: null, icon: ICONS.clients, soon: true },
    { id: 'catalog', label: 'Каталог', path: null, icon: ICONS.catalog, soon: true },
    { id: 'more', label: 'Ещё', path: null, icon: ICONS.more },
  ];

  // «Ещё» — DEC-003: Абонементы и сертификаты слиты в один пункт; Команда/Заявки/Статистика — скоро.
  var MORE_ITEMS = [
    { path: null, label: 'Команда', hint: 'Скоро', soon: true },
    { path: 'org-profile', label: 'Профиль школы', hint: null, soon: false },
    { path: 'org-subscription', label: 'Подписка', hint: null, soon: false }, // S2, реализовано
    { path: null, label: 'Абонементы и сертификаты', hint: 'Скоро', soon: true },
    { path: null, label: 'Заявки', hint: 'Скоро', soon: true },
    { path: null, label: 'Статистика', hint: 'Скоро', soon: true },
  ];

  function navigate(path) {
    if (!path) return;
    global.location.href = path + global.location.search;
  }

  function buildTabbar(activeId) {
    var nav = document.createElement('nav');
    nav.className = 'org-tabbar';
    nav.setAttribute('aria-label', 'Навигация');
    TABS.forEach(function (tab) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'org-tabbar__it' + (tab.id === activeId ? ' on' : '');
      if (tab.soon) btn.disabled = true;
      btn.innerHTML =
        tab.icon +
        '<span>' +
        tab.label +
        '</span>' +
        (tab.soon ? '<span class="org-more-row__soon">Скоро</span>' : '');
      btn.addEventListener('click', function () {
        if (tab.id === 'more') {
          openMoreSheet();
          return;
        }
        if (tab.soon || tab.id === activeId) return;
        navigate(tab.path);
      });
      nav.appendChild(btn);
    });
    return nav;
  }

  function buildMoreSheet() {
    var backdrop = document.createElement('div');
    backdrop.className = 'org-more-backdrop';
    backdrop.id = 'orgMoreBackdrop';

    var sheet = document.createElement('div');
    sheet.className = 'org-more-sheet';

    var handle = document.createElement('div');
    handle.className = 'org-more-sheet__handle';
    sheet.appendChild(handle);

    var title = document.createElement('p');
    title.className = 'org-more-sheet__title';
    title.textContent = 'Ещё';
    sheet.appendChild(title);

    var list = document.createElement('div');
    list.className = 'org-more-sheet__list';
    MORE_ITEMS.forEach(function (item) {
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'org-more-row';
      if (item.soon) row.disabled = true;
      var tx =
        '<span class="org-more-row__tx"><span class="org-more-row__tt">' +
        item.label +
        '</span>' +
        (item.hint ? '<span class="org-more-row__ts">' + item.hint + '</span>' : '') +
        '</span>';
      var trail = item.soon
        ? '<span class="org-more-row__soon">скоро</span>'
        : '<span class="org-more-row__go">›</span>';
      row.innerHTML = tx + trail;
      if (!item.soon) {
        row.addEventListener('click', function () {
          navigate(item.path);
        });
      }
      list.appendChild(row);
    });
    sheet.appendChild(list);
    backdrop.appendChild(sheet);

    backdrop.addEventListener('click', function (e) {
      if (e.target === backdrop) closeMoreSheet();
    });

    document.body.appendChild(backdrop);
    return backdrop;
  }

  var moreBackdropEl = null;

  function openMoreSheet() {
    if (!moreBackdropEl) moreBackdropEl = buildMoreSheet();
    moreBackdropEl.classList.add('open');
  }

  function closeMoreSheet() {
    if (moreBackdropEl) moreBackdropEl.classList.remove('open');
  }

  function mount() {
    var body = document.body;
    if (!body || body.getAttribute('data-org-shell') !== 'tabs') return;
    var activeId = body.getAttribute('data-org-active') || 'home';
    body.classList.add('org-page');
    body.appendChild(buildTabbar(activeId));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }

  global.OrgShell = { openMoreSheet: openMoreSheet, closeMoreSheet: closeMoreSheet };
})(window);
