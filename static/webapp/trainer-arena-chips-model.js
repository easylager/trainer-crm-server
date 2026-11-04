/**
 * TASK-055 trainer-card arena chips — pure view-model (no DOM).
 * Browser: window.TrainerArenaChips. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.TrainerArenaChips = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var VISIBLE_ARENA_CHIPS = 4;
  var OVERFLOW_FROM = 6;
  var EYEBROW = 'Работает на аренах';

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function arenaHref(id, slug) {
    // id важнее slug: slug уникален только в городе (TASK-146).
    var ref = id != null && id !== '' ? id : slug;
    if (ref == null || ref === '') return '';
    return 'arena?ref=' + encodeURIComponent(String(ref));
  }

  function buildTrainerArenaChips(trainer) {
    trainer = trainer || {};
    var ids = trainer.arena_ids || [];
    var names = trainer.arena_names || [];
    var slugs = trainer.arena_slugs || [];
    var items = [];
    var primaryId = trainer.primary_arena_id != null ? Number(trainer.primary_arena_id) : NaN;
    var i;
    for (i = 0; i < ids.length; i++) {
      var id = Number(ids[i]);
      if (isNaN(id)) continue;
      var name = String(names[i] || '').trim() || 'Арена';
      var slug = slugs[i] ? String(slugs[i]).trim() : '';
      items.push({
        id: id,
        name: name,
        href: arenaHref(id, slug || null),
        primary: !isNaN(primaryId) && id === primaryId,
      });
    }
    if (!items.length) {
      return { hidden: true, eyebrow: EYEBROW, items: [], moreCount: 0, moreLabel: '' };
    }
    items.sort(function (a, b) {
      if (a.primary === b.primary) return 0;
      return a.primary ? -1 : 1;
    });
    var moreCount = 0;
    var visible = items;
    if (items.length >= OVERFLOW_FROM) {
      moreCount = items.length - VISIBLE_ARENA_CHIPS;
      visible = items.slice(0, VISIBLE_ARENA_CHIPS);
    }
    return {
      hidden: false,
      eyebrow: EYEBROW,
      items: visible,
      moreCount: moreCount,
      moreLabel: moreCount ? 'ещё ' + moreCount : '',
    };
  }

  function renderTrainerArenaChipsHtml(view) {
    if (!view || view.hidden) return '';
    var items = view.items || [];
    if (!items.length) return '';
    var html = '<div class="trainer-arena-chips">';
    html += '<p class="trainer-arena-chips__eyebrow">' + escapeHtml(view.eyebrow || EYEBROW) + '</p>';
    html += '<div class="trainer-arena-chips__row" role="group" aria-label="' + escapeHtml(view.eyebrow || EYEBROW) + '">';
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      html +=
        '<a class="trainer-arena-chip" href="' +
        escapeHtml(it.href) +
        '"' +
        (it.primary ? ' aria-pressed="true"' : '') +
        '>' +
        escapeHtml(it.name) +
        '</a>';
    }
    if (view.moreCount > 0) {
      html +=
        '<span class="trainer-arena-chip trainer-arena-chip--more">' +
        escapeHtml(view.moreLabel || 'ещё ' + view.moreCount) +
        '</span>';
    }
    html += '</div></div>';
    return html;
  }

  /**
   * «Показать слоты» на карточке тренера: арены со слотами (с числом) идут первыми,
   * без слотов — приглушены в конце. ``counts`` — ``arena_slot_counts`` из /client/slots
   * (ключи — строки id); нет ответа — меток нет, порядок прежний.
   */
  function buildArenaSlotFilter(trainer, counts, selectedIds) {
    trainer = trainer || {};
    var ids = trainer.arena_ids || [];
    var names = trainer.arena_names || [];
    var slugs = trainer.arena_slugs || [];
    var known = counts && typeof counts === 'object';
    var selected = (selectedIds || []).map(Number);
    var items = [];
    var total = 0;
    for (var i = 0; i < ids.length; i++) {
      var id = Number(ids[i]);
      if (isNaN(id)) continue;
      var n = known ? Number(counts[String(id)] || 0) : null;
      if (known) total += n;
      items.push({
        id: id,
        name: String(names[i] || '').trim() || 'Площадка ' + id,
        href: arenaHref(id, slugs[i] ? String(slugs[i]).trim() : null),
        count: n,
        hasSlots: known ? n > 0 : null,
        selected: selected.indexOf(id) >= 0,
        order: i,
      });
    }
    if (known) {
      items.sort(function (a, b) {
        if (a.hasSlots !== b.hasSlots) return a.hasSlots ? -1 : 1;
        if (a.hasSlots && a.count !== b.count) return b.count - a.count;
        return a.order - b.order;
      });
    }
    var picked = items.filter(function (it) { return it.selected; });
    return {
      allActive: selected.length === 0,
      marked: !!known,
      total: known ? total : null,
      items: items,
      selectedArena: picked.length === 1 ? picked[0] : null,
    };
  }

  function renderArenaSlotFilterHtml(view) {
    if (!view || !(view.items || []).length) return '';
    var base = 'trainer-detail-arena-chip';
    var html = '<div class="trainer-detail-arena-filter">';
    html += '<div class="trainer-detail-arena-filter-title">Показать слоты</div>';
    html += '<div class="trainer-detail-arena-filter-chips" role="group" aria-label="Площадки">';
    html +=
      '<button type="button" class="' + base + (view.allActive ? ' ' + base + '--active' : '') +
      (view.marked && view.total > 0 ? ' ' + base + '--has' : '') +
      '" data-catalog-arena-filter="all">' +
      (view.marked && view.total > 0 ? '<span class="trainer-detail-arena-dot" aria-hidden="true"></span>' : '') +
      '<span>Все площадки</span>' +
      (view.marked ? '<span class="trainer-detail-arena-count">' + view.total + '</span>' : '') +
      '</button>';
    for (var i = 0; i < view.items.length; i++) {
      var it = view.items[i];
      var cls = base;
      if (it.selected) cls += ' ' + base + '--active';
      if (it.hasSlots === true) cls += ' ' + base + '--has';
      if (it.hasSlots === false) cls += ' ' + base + '--none';
      html +=
        '<button type="button" class="' + cls + '" data-catalog-arena-filter="' + it.id + '">' +
        (it.hasSlots === true ? '<span class="trainer-detail-arena-dot" aria-hidden="true"></span>' : '') +
        '<span>' + escapeHtml(it.name) + '</span>' +
        (it.hasSlots === true ? '<span class="trainer-detail-arena-count">' + it.count + '</span>' : '') +
        '</button>';
    }
    html += '</div>';
    if (view.marked) {
      html +=
        '<div class="trainer-detail-arena-legend"><span class="trainer-detail-arena-dot" aria-hidden="true"></span>' +
        'есть слоты · число — сколько их впереди</div>';
    }
    if (view.selectedArena && view.selectedArena.href) {
      html +=
        '<a class="trainer-detail-arena-link" href="' + escapeHtml(view.selectedArena.href) + '">Страница арены ' +
        escapeHtml(view.selectedArena.name) + ' ›</a>';
    }
    html += '</div>';
    return html;
  }

  function formatSlotPlaceCaption(slot) {
    if (!slot) return '';
    return String(slot.arena_name || '').trim();
  }

  return {
    VISIBLE_ARENA_CHIPS: VISIBLE_ARENA_CHIPS,
    OVERFLOW_FROM: OVERFLOW_FROM,
    buildTrainerArenaChips: buildTrainerArenaChips,
    renderTrainerArenaChipsHtml: renderTrainerArenaChipsHtml,
    buildArenaSlotFilter: buildArenaSlotFilter,
    renderArenaSlotFilterHtml: renderArenaSlotFilterHtml,
    formatSlotPlaceCaption: formatSlotPlaceCaption,
    arenaHref: arenaHref,
  };
});
