(function() {
  function escapeHtml(s) {
    if (s == null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // TASK-043/109: currency defaults to 'BYN'. Telegram WebView cannot paint the NBRB
  // private-use glyph, so BY amounts use the letters "BYN". Pass 'RUB' for ₽.
  function formatPriceBynHtml(priceByn, currency) {
    if (priceByn == null) return escapeHtml('по запросу');
    var num = priceByn === Math.floor(priceByn) ? String(priceByn) : priceByn.toFixed(2);
    if (currency === 'RUB') return escapeHtml(num) + ' ₽';
    return escapeHtml(num) + ' BYN';
  }

  function buildRatingText(profile) {
    if (!profile) return '—';
    if (profile.rating_avg == null || (profile.rating_count || 0) <= 0) return '—';
    return Number(profile.rating_avg).toFixed(1) + ' ★ (' + (profile.rating_count || 0) + ')';
  }

  function buildServicesListHtml(services, selectedServiceId, opts) {
    var options = opts || {};
    var listClass = options.listClass || 'trainer-services-list';
    var itemClass = options.itemClass || 'trainer-service-item';
    var selectedClass = options.selectedClass || 'trainer-service-item--selected';
    if (!Array.isArray(services) || !services.length) {
      return '<p class="trainer-detail-section-body">—</p>';
    }
    return '<ul class="' + listClass + '">' + services.map(function(s) {
      var selected = selectedServiceId != null && Number(s.service_id) === Number(selectedServiceId);
      var desc = '';
      if (selectedServiceId != null && Number(s.service_id) === Number(selectedServiceId)) {
        desc = (s.description && String(s.description).trim()) ? String(s.description).trim() : '';
      }
      return '<li class="' + itemClass + (selected ? (' ' + selectedClass) : '') + '">' +
        '<div class="trainer-service-item-row">' +
        '<span class="name service-name">' + escapeHtml(s.service_name || '—') + '</span>' +
        '<span class="value service-price">' + formatPriceBynHtml(s.price_byn) + '</span>' +
        '</div>' +
        (desc ? '<div class="trainer-service-item-desc">' + escapeHtml(desc).replace(/\n/g, '<br>') + '</div>' : '') +
      '</li>';
    }).join('') + '</ul>';
  }

  function buildArenasListHtml(arenaNames, arenaIds, selectedArenaId, opts) {
    var options = opts || {};
    var listClass = options.listClass || 'trainer-arenas-list';
    var itemClass = options.itemClass || 'trainer-arena-item';
    var selectedClass = options.selectedClass || 'trainer-arena-item--selected';
    if (!Array.isArray(arenaNames) || !arenaNames.length) {
      return '<p class="trainer-detail-section-body">—</p>';
    }
    return '<ul class="' + listClass + '">' + arenaNames.map(function(name, idx) {
      var arenaId = Array.isArray(arenaIds) ? arenaIds[idx] : null;
      var selected = selectedArenaId != null && arenaId != null && Number(arenaId) === Number(selectedArenaId);
      return '<li class="' + itemClass + (selected ? (' ' + selectedClass) : '') + '">' +
        '<span class="name arena-name">' + escapeHtml(name || '—') + '</span>' +
      '</li>';
    }).join('') + '</ul>';
  }

  function buildEducationListHtml(items, profileEducation, opts) {
    var options = opts || {};
    var listClass = options.listClass || 'trainer-education-list';
    var itemClass = options.itemClass || 'trainer-education-item';
    if (Array.isArray(items) && items.length) {
      return '<ul class="' + listClass + '">' + items.map(function(item) {
        var institution = (item.institution_name || '').trim();
        var program = (item.program_or_title || '').trim();
        var title = (institution && program) ? (institution + ' — ' + program) : (institution || program || '—');
        var subtitle = [];
        if (item.degree_level) subtitle.push(String(item.degree_level));
        if (item.city) subtitle.push(String(item.city));
        if (item.country) subtitle.push(String(item.country));
        return '<li class="' + itemClass + '">' +
          '<div class="trainer-education-title">' + escapeHtml(title) + '</div>' +
          (subtitle.length ? '<div class="trainer-education-subtitle">' + escapeHtml(subtitle.join(' · ')) + '</div>' : '') +
        '</li>';
      }).join('') + '</ul>';
    }
    if ((profileEducation || '').trim()) {
      return '<ul class="' + listClass + '"><li class="' + itemClass + '"><div class="trainer-education-title">' + escapeHtml(profileEducation.trim()) + '</div></li></ul>';
    }
    return '<p class="trainer-detail-section-body">—</p>';
  }

  window.TrainerCardShared = {
    escapeHtml: escapeHtml,
    formatPriceByn: formatPriceBynHtml,
    buildRatingText: buildRatingText,
    buildServicesListHtml: buildServicesListHtml,
    buildArenasListHtml: buildArenasListHtml,
    buildEducationListHtml: buildEducationListHtml
  };
})();

