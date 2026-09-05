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
    var ref = slug || id;
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

  function formatSlotPlaceCaption(slot) {
    if (!slot) return '';
    return String(slot.arena_name || '').trim();
  }

  return {
    VISIBLE_ARENA_CHIPS: VISIBLE_ARENA_CHIPS,
    OVERFLOW_FROM: OVERFLOW_FROM,
    buildTrainerArenaChips: buildTrainerArenaChips,
    renderTrainerArenaChipsHtml: renderTrainerArenaChipsHtml,
    formatSlotPlaceCaption: formatSlotPlaceCaption,
    arenaHref: arenaHref,
  };
});
