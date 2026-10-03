/**
 * TASK-148 (AC-3): «Подборки» в хабе — пресеты-фильтры поверх данных каталога.
 * Pure view-model (no DOM). Browser: window.HubCollectionsModel. Node: module.exports.
 *
 * Правила рендера (план 2026-10-03-catalog-hub-v4-design.md):
 *   - карточка — только при счётчике > 0;
 *   - секция целиком — только при >= 2 живых карточках;
 *   - порядок — «Сегодня вечером» первым (окно времени), дальше по счётчику.
 *
 * Счётчики — только из данных, которые публичные запросы УЖЕ отдают:
 *   - facets      — venue_type_facets из GET /api/public/ice/arenas?intent=skate
 *                   (считаются сервером до фильтра: ice / outdoor / shop / …);
 *   - eveningHits — window.hits из того же запроса с
 *                   when=today_evening&venue_type=ice,outdoor;
 *   - outdoorLive — есть ли у открытых катков живой сеанс (сезонность «Открытые»).
 *
 * «Бесплатно» (цена сеанса = 0) и «Заточка» (amenity skate_sharpening) заявлены
 * в плане, но у публичного API нет ни фасета по цене/удобству, ни фильтра каталога,
 * куда такая карточка могла бы вести. Их countFrom возвращает null — карточка
 * не рендерится до появления контракта данных (см. отчёт дорожки B).
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.HubCollectionsModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function pluralRu(n, one, few, many) {
    var abs = Math.abs(n) % 100;
    if (abs >= 11 && abs <= 14) return many;
    var last = abs % 10;
    if (last === 1) return one;
    if (last >= 2 && last <= 4) return few;
    return many;
  }

  function facetCount(facets, key) {
    var list = facets || [];
    for (var i = 0; i < list.length; i++) {
      if (String((list[i] || {}).key) === key) {
        var n = Number(list[i].count);
        return isNaN(n) ? null : n;
      }
    }
    return null;
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function catalogHref(cityId) {
    var base = 'ice?city_id=' + encodeURIComponent(String(cityId));
    return base;
  }

  /**
   * Шесть пресетов из плана. countFrom(data) -> число или null (нет данных →
   * карточки нет). href — каталог с применённым фильтром по существующим
   * конвенциям диплинков (docs/product-knowledge/public-place-pages.md:
   * «Поиск» читает ?city_id= и ?venue=; окно времени URL не принимает).
   */
  var POD_DEFS = [
    {
      key: 'today_evening',
      title: 'Сегодня вечером',
      type: 'evening',
      countFrom: function (data) {
        var hits = data && data.eveningHits;
        return hits == null || isNaN(Number(hits)) ? null : Number(hits);
      },
      subFrom: function (count) {
        return count + ' ' + pluralRu(count, 'каток', 'катка', 'катков') + ' вечером';
      },
      hrefFrom: function (cityId) {
        // Окно в URL «Поиск» не принимает (только ?city_id / ?venue): до 21:00
        // сервер сам резолвит when=auto в «Сегодня вечером» — ровно этот пресет.
        return catalogHref(cityId);
      },
    },
    {
      key: 'ice',
      title: 'Крытые',
      type: 'ice',
      countFrom: function (data) {
        return facetCount(data && data.facets, 'ice');
      },
      subFrom: function (count) {
        return count + ' ' + pluralRu(count, 'каток', 'катка', 'катков');
      },
      hrefFrom: function (cityId) {
        return catalogHref(cityId) + '&venue=ice';
      },
    },
    {
      key: 'outdoor',
      title: 'Открытые',
      type: 'outdoor',
      countFrom: function (data) {
        // Сезонность: летом у открытых катков нет живых сеансов — карточка
        // исчезает сама (план, раздел «Риски»), хотя фасет мест не пуст.
        var count = facetCount(data && data.facets, 'outdoor');
        if (count == null || count <= 0) return null;
        return data && data.outdoorLive ? count : null;
      },
      subFrom: function (count) {
        return count + ' ' + pluralRu(count, 'каток', 'катка', 'катков') + ' под небом';
      },
      hrefFrom: function (cityId) {
        return catalogHref(cityId) + '&venue=outdoor';
      },
    },
    {
      key: 'free',
      title: 'Бесплатно',
      type: 'free',
      countFrom: function () {
        // Нет данных: публичный API не отдаёт ни счётчик сеансов с ценой 0,
        // ни фильтр «бесплатно» для ссылки. Без честного счётчика и ссылки
        // карточка не рендерится (костыль запрещён дорожкой).
        return null;
      },
      subFrom: function (count) {
        return count + ' ' + pluralRu(count, 'сеанс', 'сеанса', 'сеансов');
      },
      hrefFrom: function (cityId) {
        return catalogHref(cityId);
      },
    },
    {
      key: 'sharpening',
      title: 'Заточка',
      type: 'sharpening',
      countFrom: function () {
        // Нет данных: публичный API не отдаёт фасет по amenity skate_sharpening
        // и не принимает его как фильтр ленты. Карточка ждёт контракта данных.
        return null;
      },
      subFrom: function (count) {
        return count + ' ' + pluralRu(count, 'место', 'места', 'мест');
      },
      hrefFrom: function (cityId) {
        return catalogHref(cityId);
      },
    },
    {
      key: 'shop',
      title: 'Магазины',
      type: 'shop',
      countFrom: function (data) {
        return facetCount(data && data.facets, 'shop');
      },
      subFrom: function (count) {
        return count + ' ' + pluralRu(count, 'магазин', 'магазина', 'магазинов');
      },
      hrefFrom: function (cityId) {
        return catalogHref(cityId) + '&venue=shop';
      },
    },
  ];

  /**
   * Живые карточки: счётчик > 0, «Сегодня вечером» первым, дальше — по счётчику
   * по убыванию, при равенстве — порядок пресетов из POD_DEFS.
   */
  function buildPods(data, cityId) {
    var pods = [];
    POD_DEFS.forEach(function (def) {
      var count = def.countFrom(data || {});
      if (count == null || isNaN(Number(count)) || Number(count) <= 0) return;
      pods.push({
        key: def.key,
        title: def.title,
        type: def.type,
        count: Number(count),
        sub: def.subFrom(Number(count)),
        href: def.hrefFrom(cityId),
      });
    });
    pods.sort(function (a, b) {
      var ae = a.key === 'today_evening' ? 0 : 1;
      var be = b.key === 'today_evening' ? 0 : 1;
      if (ae !== be) return ae - be;
      if (b.count !== a.count) return b.count - a.count;
      return POD_DEFS.findIndex(function (d) { return d.key === a.key; }) -
             POD_DEFS.findIndex(function (d) { return d.key === b.key; });
    });
    return pods;
  }

  /** Секция «Подборки» существует только при >= 2 живых карточках. */
  function sectionVisible(pods) {
    return (pods || []).length >= 2;
  }

  function renderPodsHtml(pods) {
    var html = '';
    (pods || []).forEach(function (pod) {
      html +=
        '<a class="hub-pod hub-pod--' + escapeHtml(pod.type) + '" href="' +
        escapeHtml(pod.href) +
        '">' +
        '<span class="hub-pod__art hub-pod__art--' + escapeHtml(pod.type) + '" aria-hidden="true"></span>' +
        '<span class="hub-pod__body">' +
        '<span class="hub-pod__title">' + escapeHtml(pod.title) + '</span>' +
        '<span class="hub-pod__sub">' + escapeHtml(pod.sub) + '</span>' +
        '</span></a>';
    });
    return html;
  }

  return {
    POD_DEFS: POD_DEFS,
    buildPods: buildPods,
    sectionVisible: sectionVisible,
    renderPodsHtml: renderPodsHtml,
    podHref: function (key, cityId) {
      var def = POD_DEFS.find(function (d) { return d.key === key; });
      return def ? def.hrefFrom(cityId) : '';
    },
    facetCount: facetCount,
  };
});
