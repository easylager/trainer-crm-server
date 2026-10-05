/**
 * Catalog geolocation — pure view-model (no DOM; browser APIs only through injected deps).
 * Browser: window.CatalogGeoModel. Node tests: module.exports.
 *
 * TASK-163. Раньше каталог дёргал `navigator.geolocation` молча, на холодном старте:
 * системный диалог прилетал человеку, который ещё не понял, что это за приложение,
 * а любой отказ писал вечный флаг — и больше мы не спрашивали никогда (на iOS это
 * вообще снимается только через Настройки). Теперь геопозицию трогает ровно одна
 * функция — `requestLocation` — и вызывать её можно только из пользовательского
 * жеста (тап «Разрешить геопозицию» в нашей шторке-прайминге).
 *
 * Client catalog has no city picker. When a client opens it with zero city context
 * (no session city, no ?city_id=, no collective brand, no deep-linked/primary trainer),
 * the trainer list query omits city_id entirely and returns an unfiltered, rating-sorted
 * list across ALL cities — which today is dominated by Minsk simply because that's where
 * most of the trainer base already is. This isn't a hardcoded "default to Minsk"; it just
 * looks like one to a visitor from another city/country. This model decides when it's safe
 * to ask the browser for the visitor's real location instead of falling through to that
 * unfiltered global list.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.CatalogGeoModel = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var DECLINED_STORAGE_KEY = 'glide_geo_declined_v1';

  /**
   * @param {object} ctx
   * @param {number|null} ctx.cityId — resolved city after all existing session/query/
   *   collective/deep-link logic has run.
   * @param {boolean} ctx.hasExplicitQueryCityId — `?city_id=` was present in the URL.
   * @param {boolean} ctx.hasCollectiveContext — opened via `?collective=` brand.
   * @param {boolean} ctx.hasDeepLinkTrainer — `?trainer_id=` deep link.
   * @param {boolean} ctx.hasPrimaryTrainer — a primary trainer was resolved from saved edges.
   * @param {boolean} ctx.geolocationSupported — `!!navigator.geolocation` at call site.
   * @param {boolean} ctx.previouslyDeclined — decline flag already set (see declineFlag* below).
   * @param {boolean} [ctx.ipSaysUnserved] — server-side IP→country lookup (src/shared/ip_geo.py,
   *   surfaced as `ip_country_served: false` on GET /client/session) already confirmed this
   *   visitor is outside every served market. IP-country is the fast, zero-permission first
   *   signal; GPS is only ever a refinement — when IP already answered the question, don't
   *   also interrupt with a permission prompt to learn the same thing more slowly.
   * @returns {boolean} true only for a genuinely cold, contextless open.
   *
   * TASK-163: каталог этим гардом больше не пользуется — он вообще не запускает
   * геолокацию сам, у него есть чип «Рядом со мной» и шторка-прайминг. Контракт
   * сохранён целиком, потому что его читает хаб (`attemptHubGeoRefine` в
   * client-home-main.js): там попытка остаётся фоновой — она только уточняет
   * расстояния в тизере льда, города не ставит и своего диалога не показывает.
   * Поля про контекст открытия каталога (cityId / query / collective / deep-link /
   * primary trainer) для хаба тоже осмысленны: он передаёт свой контекст.
   */
  function shouldAutoGeolocate(ctx) {
    ctx = ctx || {};
    if (ctx.cityId) return false;
    if (ctx.hasExplicitQueryCityId) return false;
    if (ctx.hasCollectiveContext) return false;
    if (ctx.hasDeepLinkTrainer) return false;
    if (ctx.hasPrimaryTrainer) return false;
    if (!ctx.geolocationSupported) return false;
    if (ctx.previouslyDeclined) return false;
    if (ctx.ipSaysUnserved) return false;
    return true;
  }

  /**
   * The nearest match has no distance cap on the server (it always returns the closest
   * item in the whole database, however far). A visitor with no served city nearby would
   * otherwise get silently assigned whatever city happens to be geographically closest —
   * e.g. someone thousands of km away still "matches" Minsk. Beyond this radius we treat
   * it as "no confident match" rather than guessing.
   */
  var MAX_MATCH_DISTANCE_KM = 150;

  /**
   * Extract a usable city_id from GET /api/public/ice/arenas?near=...&limit=1.
   * Defensive against empty/malformed responses — never throws. Rejects matches farther
   * than MAX_MATCH_DISTANCE_KM (see above) — a distant nearest-anything is not a real match.
   */
  function pickCityFromNearResponse(data) {
    if (!data || !Array.isArray(data.items) || !data.items.length) return null;
    var first = data.items[0];
    if (!first || first.city_id == null) return null;
    var dist = first.distance_km;
    if (dist != null && Number(dist) > MAX_MATCH_DISTANCE_KM) return null;
    var id = parseInt(first.city_id, 10);
    return isNaN(id) || id <= 0 ? null : id;
  }

  /** Same endpoint/shape as the existing Ice-tab "Определить город" button (ice-tab.js). */
  function buildNearUrl(lat, lon) {
    var near = Number(lat).toFixed(5) + ',' + Number(lon).toFixed(5);
    return '/api/public/ice/arenas?intent=coach&near=' + encodeURIComponent(near) + '&limit=1';
  }

  /**
   * Nearest place from the same `near=` response — для подтверждения города
   * («Похоже, вы в Минске?» + ближайшая арена и расстояние). Город мы применяем
   * оптимистично, но человек должен видеть, на чём основана догадка (DEC-003).
   */
  function pickNearestPlaceFromNearResponse(data) {
    if (!data || !Array.isArray(data.items) || !data.items.length) return null;
    var first = data.items[0];
    if (!first) return null;
    var dist = first.distance_km == null ? null : Number(first.distance_km);
    return {
      name: String(first.name || ''),
      distanceKm: dist == null || isNaN(dist) ? null : dist,
    };
  }

  /**
   * Предложный падеж («вы в <Городе>») для городов, где мы работаем, —
   * см. scripts/seed_cities.py и scripts/seed_regional_arenas.py.
   */
  var CITY_LOCATIVE = {
    'Минск': 'Минске',
    'Гомель': 'Гомеле',
    'Могилёв': 'Могилёве',
    'Могилев': 'Могилеве',
    'Витебск': 'Витебске',
    'Гродно': 'Гродно',
    'Брест': 'Бресте',
    'Барановичи': 'Барановичах',
    'Берёза': 'Берёзе',
    'Береза': 'Березе',
    'Бобруйск': 'Бобруйске',
    'Горки': 'Горках',
    'Жодино': 'Жодино',
    'Ивацевичи': 'Ивацевичах',
    'Кобрин': 'Кобрине',
    'Лида': 'Лиде',
    'Лунинец': 'Лунинце',
    'Молодечно': 'Молодечно',
    'Новополоцк': 'Новополоцке',
    'Орша': 'Орше',
    'Островец': 'Островце',
    'Пинск': 'Пинске',
    'Пружаны': 'Пружанах',
    'Раубичи': 'Раубичах',
    'Силичи': 'Силичах',
    'Солигорск': 'Солигорске',
    'Шклов': 'Шклове',
    'Москва': 'Москве',
    'Санкт-Петербург': 'Санкт-Петербурге',
  };

  /**
   * Предложный падеж города. Сначала словарь наших рынков, дальше — только те
   * правила, которые не врут: «-а» → «-е», «-о» не склоняется, «-ск/-цк/-ов/
   * -ев/-ёв/-ин/-ын/-бург/-град» + «е».
   *
   * Остальное не угадываем. Русские топонимы склоняются слишком по-разному:
   * «Лунинец» → «Лунинце» (беглая гласная), «Тверь» → «Твери», но «Гомель» →
   * «Гомеле» — род по написанию не определить. null означает «падеж неизвестен»,
   * и заголовок переходит на формулировку без падежа.
   *
   * @returns {string|null}
   */
  function cityLocative(cityName) {
    var name = String(cityName == null ? '' : cityName).trim();
    if (!name) return null;
    if (Object.prototype.hasOwnProperty.call(CITY_LOCATIVE, name)) return CITY_LOCATIVE[name];
    if (/ия$/.test(name)) return name.slice(0, -1) + 'и';
    if (/[бвгджзклмнпрстфхцчшщ]а$/.test(name)) return name.slice(0, -1) + 'е';
    if (/о$/.test(name)) return name;
    if (/(ск|цк|ов|ёв|ев|ин|ын|бург|град)$/.test(name)) return name + 'е';
    return null;
  }

  /**
   * Заголовок подтверждения города. Падеж знаем — «Похоже, вы в Минске?»;
   * не знаем — «Похоже, ваш город — Тверь?»: переформулировать честнее, чем
   * переврать падеж. Имени города нет вовсе — нейтральное, без выдумок.
   */
  function formatCityGuessTitle(cityName) {
    var name = String(cityName == null ? '' : cityName).trim();
    if (!name) return 'Похоже, мы нашли ваш город';
    var locative = cityLocative(name);
    return locative ? 'Похоже, вы в ' + locative + '?' : 'Похоже, ваш город — ' + name + '?';
  }

  /** Та же запись расстояния, что в ленте льда (ice-tab-model.js / ice-teaser-model.js). */
  function formatDistanceKm(km) {
    if (km == null || km === '' || isNaN(Number(km))) return '';
    var n = Number(km);
    var text = Number.isInteger(n) ? String(n) : n.toFixed(1).replace('.', ',');
    return text + ' км';
  }

  /** Исходы попытки взять геопозицию. Отказ навсегда — только GEO_DENIED. */
  var GEO_STATUS = {
    GRANTED: 'granted',
    DENIED: 'denied',       // системный отказ: PERMISSION_DENIED / Telegram не дал доступ
    UNAVAILABLE: 'unavailable', // геолокации нет вообще (ни LocationManager, ни navigator)
    ERROR: 'error',         // таймаут, позиция недоступна, клиент не ответил — попробуем позже
  };

  var DEFAULT_TIMEOUT_MS = 6000;
  var DEFAULT_MAX_AGE_MS = 60000;

  /**
   * LocationManager (Bot API 8.0) — основной путь внутри Телеграма: нативный диалог
   * и, главное, путь восстановления через openSettings(), которого у веб-геолокации нет.
   * null — значит «тихо падаем в navigator.geolocation»: старый клиент, устройство без
   * геолокации (isLocationAvailable === false) или мы вообще вне Телеграма.
   */
  function telegramLocationManager(telegram) {
    var lm = telegram && telegram.LocationManager;
    if (!lm || typeof lm.getLocation !== 'function') return null;
    if (lm.isLocationAvailable === false) return null;
    return lm;
  }

  /** Состояние разрешения ДО системного вызова. */
  var GEO_PERMISSION = {
    GRANTED: 'granted',
    DENIED: 'denied',
    PROMPT: 'prompt',
    UNKNOWN: 'unknown', // спросить нельзя — считаем, что прайминг нужен
  };

  /** Что показать по тапу на чип «Рядом со мной». */
  var GEO_ENTRY = {
    PRIMING: 'priming',   // шторка-прайминг, системный запрос — вторым шагом
    REQUEST: 'request',   // разрешение уже есть: шторку не показываем (TASK-163 AC-6)
    RECOVERY: 'recovery', // системный отказ: путь восстановления
  };

  /**
   * Разрешение по флагам LocationManager — синхронно, без системного диалога.
   * null — LocationManager нам не подходит (нет его, старый клиент, устройство
   * без геолокации), спрашивать надо веб-API.
   */
  function telegramAccessState(telegram) {
    var lm = telegramLocationManager(telegram);
    if (!lm) return null;
    // До init() клиент флагов ещё не прислал — это не «отказано», это «неизвестно».
    if (!lm.isInited) return GEO_PERMISSION.UNKNOWN;
    if (lm.isAccessGranted === true) return GEO_PERMISSION.GRANTED;
    if (lm.isAccessRequested === true) return GEO_PERMISSION.DENIED;
    return GEO_PERMISSION.PROMPT;
  }

  /**
   * Читает состояние разрешения, НЕ вызывая системный диалог. Нужно ровно для
   * одного решения — показывать ли шторку-прайминг: объяснять второй раз то,
   * на что человек уже согласился, невежливо.
   *
   * Внутри Телеграма ответ синхронный (флаги LocationManager), иначе —
   * navigator.permissions, который есть не везде (Safari до 16); нет его или он
   * бросил — UNKNOWN, то есть прайминг покажем. Permissions API сам диалога
   * не поднимает.
   *
   * @param {object} deps — { telegram, navigator }
   * @param {function} done — done(oneOf(GEO_PERMISSION))
   */
  function readLocationPermission(deps, done) {
    deps = deps || {};
    var cb = typeof done === 'function' ? done : function () {};
    var fromTelegram = telegramAccessState(deps.telegram);
    if (fromTelegram) {
      cb(fromTelegram);
      return;
    }
    var nav = deps.navigator;
    var perms = nav && nav.permissions;
    if (!perms || typeof perms.query !== 'function') {
      cb(GEO_PERMISSION.UNKNOWN);
      return;
    }
    var pending;
    try {
      pending = perms.query({ name: 'geolocation' });
    } catch (e) {
      cb(GEO_PERMISSION.UNKNOWN);
      return;
    }
    if (!pending || typeof pending.then !== 'function') {
      cb(GEO_PERMISSION.UNKNOWN);
      return;
    }
    pending.then(
      function (status) {
        var state = status && status.state;
        if (state === GEO_PERMISSION.GRANTED) cb(GEO_PERMISSION.GRANTED);
        else if (state === GEO_PERMISSION.DENIED) cb(GEO_PERMISSION.DENIED);
        else if (state === GEO_PERMISSION.PROMPT) cb(GEO_PERMISSION.PROMPT);
        else cb(GEO_PERMISSION.UNKNOWN);
      },
      function () {
        cb(GEO_PERMISSION.UNKNOWN);
      }
    );
  }

  /**
   * Какой вид показать по тапу на чип. Выданное разрешение бьёт вечный флаг:
   * человек мог запретить, а потом разрешить в настройках — тогда наш флаг
   * устарел, и держать его перед живым разрешением было бы враньём.
   *
   * @param {object} ctx — { permission, declinedForever }
   */
  function pickGeoEntryView(ctx) {
    ctx = ctx || {};
    if (ctx.permission === GEO_PERMISSION.GRANTED) return GEO_ENTRY.REQUEST;
    if (ctx.declinedForever) return GEO_ENTRY.RECOVERY;
    if (ctx.permission === GEO_PERMISSION.DENIED) return GEO_ENTRY.RECOVERY;
    return GEO_ENTRY.PRIMING;
  }

  function canOpenLocationSettings(telegram) {
    var lm = telegram && telegram.LocationManager;
    return !!(lm && typeof lm.openSettings === 'function');
  }

  /**
   * Путь восстановления после системного отказа. Требует пользовательского жеста —
   * вызывать только из обработчика тапа, не само по себе.
   * @returns {boolean} удалось ли открыть настройки (false — честный текст без кнопки).
   */
  function openLocationSettings(telegram) {
    var lm = telegram && telegram.LocationManager;
    if (!lm || typeof lm.openSettings !== 'function') return false;
    try {
      lm.openSettings();
      return true;
    } catch (e) {
      return false;
    }
  }

  function webGeolocation(nav) {
    var geo = nav && nav.geolocation;
    return geo && typeof geo.getCurrentPosition === 'function' ? geo : null;
  }

  function requestFromWeb(deps, finish) {
    var geo = webGeolocation(deps.navigator);
    if (!geo) {
      finish({ status: GEO_STATUS.UNAVAILABLE, source: null, canOpenSettings: false });
      return;
    }
    geo.getCurrentPosition(
      function (pos) {
        var c = (pos && pos.coords) || {};
        if (c.latitude == null || c.longitude == null) {
          finish({ status: GEO_STATUS.ERROR, source: 'web', canOpenSettings: false });
          return;
        }
        finish({
          status: GEO_STATUS.GRANTED,
          source: 'web',
          lat: Number(c.latitude),
          lon: Number(c.longitude),
          canOpenSettings: false,
        });
      },
      function (err) {
        // PERMISSION_DENIED (1) — единственный исход, который стоит вечного флага.
        var deniedCode = err && err.PERMISSION_DENIED != null ? err.PERMISSION_DENIED : 1;
        var denied = !!err && err.code === deniedCode;
        finish({
          status: denied ? GEO_STATUS.DENIED : GEO_STATUS.ERROR,
          source: 'web',
          // Веб-геолокация пути восстановления не даёт — только честный текст.
          canOpenSettings: false,
        });
      },
      {
        timeout: deps.timeoutMs || DEFAULT_TIMEOUT_MS,
        maximumAge: deps.maximumAgeMs == null ? DEFAULT_MAX_AGE_MS : deps.maximumAgeMs,
      }
    );
  }

  function requestFromTelegram(lm, finish) {
    try {
      lm.getLocation(function (loc) {
        if (loc && loc.latitude != null && loc.longitude != null) {
          finish({
            status: GEO_STATUS.GRANTED,
            source: 'telegram',
            lat: Number(loc.latitude),
            lon: Number(loc.longitude),
            canOpenSettings: typeof lm.openSettings === 'function',
          });
          return;
        }
        // getLocation отдал null — доступа нет. Системный отказ («Запретить», или
        // доступ снят в настройках) отличаем от прочих сбоев по isAccessRequested/
        // isAccessGranted: вечный флаг стоит только настоящего отказа.
        var denied = lm.isAccessRequested === true && lm.isAccessGranted !== true;
        finish({
          status: denied ? GEO_STATUS.DENIED : GEO_STATUS.ERROR,
          source: 'telegram',
          canOpenSettings: typeof lm.openSettings === 'function',
        });
      });
    } catch (e) {
      finish({
        status: GEO_STATUS.ERROR,
        source: 'telegram',
        canOpenSettings: typeof lm.openSettings === 'function',
      });
    }
  }

  /**
   * Единственное место, где приложение действительно просит геопозицию.
   * Вызывать ТОЛЬКО из пользовательского жеста — системный диалог даётся один раз.
   *
   * Внутри Телеграма — LocationManager; нет его, или устройство/клиент не умеет, или
   * мы вне Телеграма — тихо уходим в navigator.geolocation. Диалог при этом ровно один:
   * к веб-фолбэку мы идём только до того, как у Телеграма что-то спросили, и защёлка
   * `finish` гасит опоздавшие колбэки (init, который ответил после таймаута).
   *
   * @param {object} deps
   * @param {object} [deps.telegram] — Telegram.WebApp (null вне Телеграма)
   * @param {object} [deps.navigator] — window.navigator
   * @param {number} [deps.timeoutMs]
   * @param {function} [deps.setTimeout]
   * @param {function} done — done({ status, source, lat, lon, canOpenSettings })
   */
  function requestLocation(deps, done) {
    deps = deps || {};
    var settled = false;
    function finish(res) {
      if (settled) return;
      settled = true;
      if (typeof done === 'function') done(res);
    }

    var lm = telegramLocationManager(deps.telegram);
    if (!lm) {
      requestFromWeb(deps, finish);
      return;
    }
    if (lm.isInited) {
      requestFromTelegram(lm, finish);
      return;
    }

    var timer = null;
    var later = deps.setTimeout || (typeof setTimeout === 'function' ? setTimeout : null);
    try {
      lm.init(function () {
        if (timer != null && typeof clearTimeout === 'function') clearTimeout(timer);
        if (settled) return; // init ответил после таймаута — второго диалога не будет
        // Клиент мог сообщить про отсутствие геолокации только после init.
        if (lm.isLocationAvailable === false) {
          requestFromWeb(deps, finish);
          return;
        }
        requestFromTelegram(lm, finish);
      });
    } catch (e) {
      requestFromWeb(deps, finish);
      return;
    }
    // Клиент может не ответить на init вообще — это сбой, а не отказ.
    if (later) {
      timer = later(function () {
        finish({ status: GEO_STATUS.ERROR, source: 'telegram', canOpenSettings: false });
      }, deps.timeoutMs || DEFAULT_TIMEOUT_MS);
    }
  }

  /**
   * Ставить ли вечный флаг `glide_geo_declined_v1`. Только системный отказ —
   * «Не сейчас» в нашей шторке, таймаут и сетевые сбои флага не стоят: чип
   * остаётся живым, спросим снова, когда польза снова очевидна (TASK-163).
   */
  function isPermanentDecline(result) {
    return !!result && result.status === GEO_STATUS.DENIED;
  }

  /**
   * @param {Storage} storage
   * @param {string} [key] — defaults to the catalog's own decline flag. Callers with an
   *   independent geolocation attempt (e.g. the hub's ice-teaser distance refine, which
   *   never sets a city and so must not be gated by — or gate — the catalog's flag) should
   *   pass their own key so the two don't cross-suppress each other.
   */
  function readDeclinedFlag(storage, key) {
    try {
      return !!(storage && storage.getItem(key || DECLINED_STORAGE_KEY));
    } catch (e) {
      return false;
    }
  }

  /**
   * Вечный флаг отказа. Писать только когда `isPermanentDecline(result)` — то есть
   * на системном «Запретить». Всё остальное (наше «Не сейчас», таймаут, сеть,
   * «город не распознали») флага не стоит: это не отказ, а неудачная попытка.
   */
  function writeDeclinedFlag(storage, key) {
    try {
      if (storage) storage.setItem(key || DECLINED_STORAGE_KEY, '1');
    } catch (e) {
      /* storage unavailable (e.g. private mode) — worst case we ask again next open */
    }
  }

  return {
    DECLINED_STORAGE_KEY: DECLINED_STORAGE_KEY,
    MAX_MATCH_DISTANCE_KM: MAX_MATCH_DISTANCE_KM,
    GEO_STATUS: GEO_STATUS,
    GEO_PERMISSION: GEO_PERMISSION,
    GEO_ENTRY: GEO_ENTRY,
    shouldAutoGeolocate: shouldAutoGeolocate,
    pickCityFromNearResponse: pickCityFromNearResponse,
    pickNearestPlaceFromNearResponse: pickNearestPlaceFromNearResponse,
    formatDistanceKm: formatDistanceKm,
    cityLocative: cityLocative,
    formatCityGuessTitle: formatCityGuessTitle,
    buildNearUrl: buildNearUrl,
    readDeclinedFlag: readDeclinedFlag,
    writeDeclinedFlag: writeDeclinedFlag,
    telegramLocationManager: telegramLocationManager,
    telegramAccessState: telegramAccessState,
    readLocationPermission: readLocationPermission,
    pickGeoEntryView: pickGeoEntryView,
    canOpenLocationSettings: canOpenLocationSettings,
    openLocationSettings: openLocationSettings,
    requestLocation: requestLocation,
    isPermanentDecline: isPermanentDecline,
  };
});
