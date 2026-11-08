/**
 * Витрина тренеров и запись в Mini App (TASK-357, PDEC-033) — чистая логика без DOM.
 *
 * Три слоя текста (эпик trainer-catalog): направления пишем мы (здесь), слова тренера — дословно
 * (описание, «О себе»), цифры — из данных (`/api/public/trainer-showcase`, `/client/slots`).
 * Браузер: window.TrainerShowcaseModel. Node-тесты: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.TrainerShowcaseModel = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /* ── Направления = вкладки. «С клюшкой» = Хоккейное катание (4) + ОХМ (6). Ролики (5) и ОФП/СФП (7)
     вкладками не бывают — только на карточке тренера. Своя услуга (is_public=false) — во вкладке направления, к которому её привязал админ
     (direction_service_id, TASK-353); без привязки во вкладки не идёт. */
  var DIRECTIONS = [
    { key: 'all', title: 'Все', ids: null,
      lead: 'Учат кататься с нуля и ставят технику. Есть фигурное катание и хоккей.' },
    { key: 's-nulya', title: 'С нуля', ids: [1],
      lead: 'Для детей и взрослых, которые ни разу не стояли на коньках или стояли пару раз.' },
    { key: 'uzhe-katayus', title: 'Уже катаюсь', ids: [2],
      lead: 'Ровный ход, повороты, торможение и катание назад — для детей и взрослых.' },
    { key: 'figurnoe', title: 'Фигурное катание', ids: [3],
      lead: 'Прыжки, вращения, дорожки шагов и программы — для детей и взрослых.' },
    { key: 's-klyushkoy', title: 'С клюшкой', ids: [4, 6],
      lead: 'Стойка, ход, повороты и торможение — чтобы на площадке думать об игре, а не о коньках.' },
  ];
  var TAB_SERVICE_IDS = [1, 2, 3, 4, 6];

  var TIER_TITLE = {
    child: 'Ребёнок',
    adult: 'Взрослый',
    two_children: 'Двое детей',
    adult_and_child: 'Взрослый и ребёнок',
    two_adults: 'Двое взрослых',
  };
  var SINGLE_KINDS = ['child', 'adult'];
  var DUO_KINDS = ['two_children', 'adult_and_child', 'two_adults'];

  var MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
    'сентября', 'октября', 'ноября', 'декабря'];
  var WEEKDAY_SHORT = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

  function plural(n, one, few, many) {
    var m = n % 10;
    var h = n % 100;
    if (m === 1 && h !== 11) return one;
    if (m >= 2 && m <= 4 && (h < 12 || h > 14)) return few;
    return many;
  }

  function word(n, one, few, many) {
    return n + ' ' + plural(n, one, few, many);
  }

  function direction(key) {
    for (var i = 0; i < DIRECTIONS.length; i++) if (DIRECTIONS[i].key === key) return DIRECTIONS[i];
    return null;
  }

  function directionKeyForServiceId(sid) {
    var n = Number(sid);
    for (var i = 1; i < DIRECTIONS.length; i++) if (DIRECTIONS[i].ids.indexOf(n) >= 0) return DIRECTIONS[i].key;
    return null;
  }

  /** Публичная услуга, по которой услуга тренера попадает во вкладку: своя — по привязке админа. */
  function tabServiceId(s) {
    if (s.is_public !== false) return Number(s.service_id);
    return s.direction_service_id != null ? Number(s.direction_service_id) : null;
  }

  /** Услуги тренера во вкладке: публичные и из её списка, своя — по привязке. «Все» — любая вкладочная. */
  function servicesInDirection(trainer, key) {
    var dir = direction(key) || DIRECTIONS[0];
    var ids = dir.ids || TAB_SERVICE_IDS;
    return (trainer.services || []).filter(function (s) {
      return ids.indexOf(tabServiceId(s)) >= 0;
    });
  }

  function serviceHasPrice(s) {
    if ((s.price_tiers || []).some(function (t) { return Number(t.price_cents) > 0; })) return true;
    return Number(s.price_cents) > 0;
  }

  /** Правило показа (эпик): услуга направления **и** (цена **или** каток). */
  function trainerInDirection(trainer, key) {
    var svcs = servicesInDirection(trainer, key);
    if (!svcs.length) return false;
    return svcs.some(serviceHasPrice) || (trainer.arenas || []).length > 0;
  }

  function trainerOnArena(trainer, arenaId) {
    if (arenaId == null) return true;
    return (trainer.arenas || []).some(function (a) { return Number(a.id) === Number(arenaId); });
  }

  /** Направления, где тренер виден (для переключателя на его экране). */
  function trainerDirections(trainer) {
    return DIRECTIONS.slice(1).filter(function (d) { return trainerInDirection(trainer, d.key); });
  }

  /** Сортировка (подпись на витрине): с онлайн-записью — по ближайшему окну; дальше — как пришли (рейтинг). */
  function sortForShowcase(items) {
    return items
      .map(function (t, i) { return { t: t, i: i }; })
      .sort(function (a, b) {
        var ra = rank(a.t);
        var rb = rank(b.t);
        if (ra !== rb) return ra - rb;
        if (ra === 0) {
          var sa = a.t.windows[0].starts_at;
          var sb = b.t.windows[0].starts_at;
          if (sa !== sb) return sa < sb ? -1 : 1;
        }
        return a.i - b.i;
      })
      .map(function (x) { return x.t; });
    function rank(t) {
      if (t.can_book && (t.windows || []).length) return 0;
      if (t.can_book) return 1;
      return 2;
    }
  }

  function visibleTrainers(items, key, arenaId) {
    return sortForShowcase(
      (items || []).filter(function (t) { return trainerInDirection(t, key) && trainerOnArena(t, arenaId); })
    );
  }

  function tabCounts(items, arenaId) {
    var out = {};
    DIRECTIONS.forEach(function (d) { out[d.key] = visibleTrainers(items, d.key, arenaId).length; });
    return out;
  }

  /**
   * «от N» для вкладки: минимум `min_price_by_direction[key]` показанных тренеров. Сервер считает его
   * так же, как `direction_min_price` сайта: тарифы/цена услуг вкладки, их групповая цена и абонементы
   * тренера, покрывающие эти услуги. «Все» — по всем вкладкам (без роликов и ОФП/СФП). Один расчёт для
   * витрины и блока входов; здесь цены не пересчитываем.
   */
  function minPriceOf(list, key) {
    var best = null;
    (list || []).forEach(function (t) {
      var p = (t.min_price_by_direction || {})[key || 'all'];
      var c = p ? Number(p.cents) : 0;
      if (c > 0 && (!best || c < best.cents)) best = { cents: c, currency: p.currency || 'BYN' };
    });
    return best;
  }

  /** Катки для фильтра: лёд у тренеров вкладки, с числом тренеров. */
  function arenaOptions(items, key) {
    var byId = {};
    (items || []).forEach(function (t) {
      if (!trainerInDirection(t, key)) return;
      (t.arenas || []).forEach(function (a) {
        if (!byId[a.id]) byId[a.id] = { id: a.id, name: a.name, count: 0 };
        byId[a.id].count += 1;
      });
    });
    return Object.keys(byId)
      .map(function (k) { return byId[k]; })
      .sort(function (a, b) { return b.count - a.count || (a.name < b.name ? -1 : 1); });
  }

  /* ── Цены ───────────────────────────────────────────────────────────── */

  function formatMoney(cents, currency) {
    var n = Number(cents) / 100;
    var num = n === Math.floor(n) ? String(n) : n.toFixed(2).replace('.', ',');
    return num + ' ' + (currency === 'RUB' ? 'руб.' : 'BYN');
  }

  function tierByKind(service, kind) {
    var tiers = (service && service.price_tiers) || [];
    for (var i = 0; i < tiers.length; i++) if (tiers[i].tier_kind === kind) return tiers[i];
    return null;
  }

  /** «Ребёнок — 50 BYN · взрослый — 55 BYN» / «Дети и взрослые — 50 BYN» / «55 BYN за занятие» / «Цену уточните у тренера». */
  function cardPriceHtml(service) {
    if (!service) return 'Цену уточните у тренера';
    var cur = service.currency_code || 'BYN';
    var child = tierByKind(service, 'child');
    var adult = tierByKind(service, 'adult');
    var b = function (c) { return '<b>' + formatMoney(c, cur) + '</b>'; };
    if (child && adult) {
      if (Number(child.price_cents) === Number(adult.price_cents)) return 'Дети и взрослые — ' + b(child.price_cents);
      return 'Ребёнок — ' + b(child.price_cents) + ' · взрослый — ' + b(adult.price_cents);
    }
    if (child) return 'Ребёнок — ' + b(child.price_cents);
    if (adult) return 'Взрослый — ' + b(adult.price_cents);
    var tiers = service.price_tiers || [];
    if (tiers.length) {
      var min = Math.min.apply(null, tiers.map(function (t) { return Number(t.price_cents); }));
      return 'от ' + b(min) + ' за занятие';
    }
    if (Number(service.price_cents) > 0) return b(service.price_cents) + ' за занятие';
    return 'Цену уточните у тренера';
  }

  var NOTICE_LEAD = /^\s*(?:в\s+(?:стоимость|цену)\s+не\s+(?:входят|входит)|не\s+(?:входят|входит)\s+в\s+(?:стоимость|цену))\s*[:\-–—]?\s*/i;

  /**
   * Заметка тренера «в цену не входит» → {lead, text}. Вводную («В стоимость не входят:») снимаем — её заменяет
   * подпись «Не входит в цену»; первая буква заглавная. Другая заметка остаётся дословно (lead=false).
   */
  function noticeParts(notice) {
    var raw = String(notice == null ? '' : notice).trim();
    if (!raw) return null;
    var stripped = raw.replace(NOTICE_LEAD, '');
    if (stripped === raw || !stripped) return { lead: false, text: raw };
    return { lead: true, text: stripped.charAt(0).toUpperCase() + stripped.slice(1) };
  }

  /**
   * Блок «О занятии» одной услуги — только наши тексты (крючок, подробности) и слова тренера дословно.
   * Ничего нет → null (карточку не рисуем).
   */
  function serviceAbout(service) {
    if (!service) return null;
    var hook = String(service.summary_hook || '').trim();
    var body = String(service.summary_body || '').split(/\n\s*\n/).map(function (x) { return x.trim(); }).filter(Boolean);
    var words = String(service.description || '').trim();
    var notice = noticeParts(service.client_notice);
    if (!hook && !body.length && !words && !notice) return null;
    return {
      title: String(service.title || service.service_name || '').trim(),
      hook: hook, body: body, words: words, notice: notice,
    };
  }

  /** Текст тренера как есть, но без «слово ,» и двойных пробелов. */
  function tidyText(text) {
    return String(text || '').replace(/[ \t]+([,.;:!?])/g, '$1').replace(/[ \t]{2,}/g, ' ').trim();
  }

  /** «Кого учит»: из тарифов; тарифов нет — строки нет. */
  function whoTeaches(services) {
    var kids = false;
    var adults = false;
    (services || []).forEach(function (s) {
      (s.price_tiers || []).forEach(function (t) {
        if (t.tier_kind === 'child' || t.tier_kind === 'two_children' || t.tier_kind === 'adult_and_child') kids = true;
        if (t.tier_kind === 'adult' || t.tier_kind === 'two_adults' || t.tier_kind === 'adult_and_child') adults = true;
      });
    });
    if (kids && adults) return 'детей и взрослых';
    if (kids) return 'детей';
    if (adults) return 'взрослых';
    return '';
  }

  function experienceBadge(years) {
    var n = Number(years);
    if (!isFinite(n) || n < 1) return '';
    n = Math.floor(n);
    return 'Тренирует ' + word(n, 'год', 'года', 'лет');
  }

  /** Оценка — только при 3+ оценках (дизайн). */
  function ratingLine(avg, count) {
    var c = Number(count) || 0;
    var a = Number(avg);
    if (c < 3 || !isFinite(a) || a <= 0) return '';
    return '★ ' + a.toFixed(1).replace('.', ',') + ' · ' + word(c, 'оценка', 'оценки', 'оценок');
  }

  /** «В Glide с апреля 2026» из «2026-04». Число занятий не показываем никогда (решение владельца). */
  function glideSince(ym) {
    var m = /^(\d{4})-(\d{2})$/.exec(String(ym || ''));
    if (!m) return '';
    var mi = Number(m[2]) - 1;
    if (mi < 0 || mi > 11) return '';
    return 'В Glide с ' + MONTHS_GEN[mi] + ' ' + m[1];
  }

  function whereLine(arenas) {
    var list = arenas || [];
    if (!list.length) return '';
    if (list.length === 1) return list[0].name;
    return 'на ' + word(list.length, 'катке', 'катках', 'катках');
  }

  function lessonLine(minutes) {
    var n = Number(minutes);
    if (!isFinite(n) || n <= 0) return '';
    return n + ' мин, индивидуально';
  }

  /** Строки каркаса карточки; пустые не показываем. */
  function cardFacts(trainer, key) {
    var svcs = servicesInDirection(trainer, key);
    var rows = [];
    var who = whoTeaches(svcs);
    if (who) rows.push(['Кого учит', who]);
    // «45 мин, индивидуально» — про онлайн-запись (окна на одного); без неё длительность и формат решает тренер.
    var lesson = trainer.can_book ? lessonLine(trainer.session_duration_minutes) : '';
    if (lesson) rows.push(['Занятие', lesson]);
    if (!who && trainer.description) rows.unshift(['О себе', '«' + truncate(trainer.description, 90) + '»']);
    var online = svcs.length > 0 && svcs.every(function (s) { return s.is_online; });
    var where = online ? 'онлайн' : whereLine(trainer.arenas);
    if (where) rows.push(['Где', where]);
    return rows;
  }

  function truncate(s, n) {
    var t = String(s || '').replace(/\s+/g, ' ').trim();
    return t.length > n ? t.slice(0, n - 1).replace(/\s+\S*$/, '') + '…' : t;
  }

  /* ── «Кто будет заниматься?» ─────────────────────────────────────────── */

  /**
   * Строки нового ученика из тарифов услуги. Ответ = тариф. Нет тарифа — нет строки;
   * цены в группе равны — без цены справа. Тарифов нет совсем — Ребёнок/Взрослый без цены, тариф null.
   */
  function whoOptions(service, opts) {
    opts = opts || {};
    var tiers = (service && service.price_tiers) || [];
    var cur = (service && service.currency_code) || 'BYN';
    if (opts.group || !tiers.length) {
      return {
        single: SINGLE_KINDS.map(function (k) { return { kind: k, title: TIER_TITLE[k], variantId: null, priceCents: null, price: '' }; }),
        duo: [],
      };
    }
    function rows(kinds) {
      var list = kinds
        .map(function (k) {
          var t = tierByKind(service, k);
          return t ? { kind: k, title: TIER_TITLE[k], variantId: Number(t.id), priceCents: Number(t.price_cents), price: formatMoney(t.price_cents, cur) } : null;
        })
        .filter(Boolean);
      var same = list.length > 1 && list.every(function (r) { return r.priceCents === list[0].priceCents; });
      if (same) list.forEach(function (r) { r.price = ''; });
      return list;
    }
    return { single: rows(SINGLE_KINDS), duo: rows(DUO_KINDS) };
  }

  /**
   * Строки цен услуги для карточки тренера: Ребёнок/Взрослый; цены равны — одна строка «Дети и взрослые»
   * (то же правило «без дубля», что в whoOptions). Нет цен — [].
   */
  function priceRows(service) {
    var cur = (service && service.currency_code) || 'BYN';
    var rows = whoOptions(service).single.filter(function (r) { return r.priceCents != null; });
    if (rows.length > 1 && rows.every(function (r) { return r.priceCents === rows[0].priceCents; })) {
      return [{ title: 'Дети и взрослые', priceCents: rows[0].priceCents, price: formatMoney(rows[0].priceCents, cur) }];
    }
    return rows.map(function (r) { return { title: r.title, priceCents: r.priceCents, price: formatMoney(r.priceCents, cur) }; });
  }

  /** Короткая цена в строке выбора услуги: «50 BYN», если цена одна, иначе «от 45 BYN». Цены нет — ''. */
  function priceFrom(service) {
    if (!service) return '';
    var cur = service.currency_code || 'BYN';
    var list = (service.price_tiers || []).map(function (t) { return Number(t.price_cents); }).filter(function (n) { return n > 0; });
    if (!list.length && Number(service.price_cents) > 0) list = [Number(service.price_cents)];
    if (!list.length) return '';
    var min = Math.min.apply(null, list);
    var max = Math.max.apply(null, list);
    return (min === max ? '' : 'от ') + formatMoney(min, cur);
  }

  /** Поля имён на выбранный тариф: каждому участнику — своё. Взрослому — имя из Telegram. */
  function nameFields(kind, tgName) {
    var me = { key: 'self', label: 'Ваше имя', value: tgName || '', placeholder: '' };
    var kid = { key: 'child', label: 'Имя ребёнка', value: '', placeholder: 'Например, Соня' };
    switch (kind) {
      case 'child': return [kid];
      case 'adult': return [me];
      case 'two_children':
        return [
          { key: 'child', label: 'Имя первого ребёнка', value: '', placeholder: 'Например, Соня' },
          { key: 'child2', label: 'Имя второго ребёнка', value: '', placeholder: 'Например, Миша' },
        ];
      case 'adult_and_child': return [me, kid];
      case 'two_adults': return [me, { key: 'adult2', label: 'Имя второго взрослого', value: '', placeholder: '' }];
      default: return [];
    }
  }

  /**
   * Как записать выбор нового ученика при модели «одна запись = один профиль»
   * (`bookings.client_id` один; второго участника бэкенд не хранит):
   * профиль записи — первый участник; ребёнок — свой профиль (POST /client/profiles);
   * второй участник — строкой в комментарии тренеру.
   */
  function newClientBookingPlan(kind, names) {
    names = names || {};
    var second = '';
    if (kind === 'two_children') second = names.child2;
    if (kind === 'adult_and_child') second = names.child;
    if (kind === 'two_adults') second = names.adult2;
    var childFirst = kind === 'child' || kind === 'two_children';
    return {
      profile: childFirst ? 'child' : 'self',
      childName: childFirst ? String(names.child || '').trim() : '',
      selfName: childFirst ? '' : String(names.self || '').trim(),
      participant: childFirst ? String(names.child || '').trim() : String(names.self || '').trim(),
      secondName: String(second || '').trim(),
    };
  }

  /** Комментарий тренеру: второй участник (если есть) + текст человека. */
  function bookingComment(secondName, userComment) {
    var lines = [];
    if (secondName) lines.push('Второй участник: ' + secondName);
    var c = String(userComment || '').trim();
    if (c) lines.push(c);
    return lines.join('\n');
  }

  /* ── Постоянный ученик ──────────────────────────────────────────────── */

  /**
   * Вид профиля для тарифа. Взрослый — только свой профиль (`self`); детский — только профиль,
   * про который точно известно, что это ребёнок (`knownChildIds`: добавлен как ребёнок здесь же).
   * Профиль семьи (`guardian`, `family_access`) сам по себе возраста не знает — `null`, не угадываем.
   */
  function profileKind(p, opts) {
    if (!p) return null;
    if (p.role === 'self') return 'adult';
    var known = (opts && opts.knownChildIds) || {};
    return known[p.client_id] ? 'child' : null;
  }

  function duoKindFor(kinds) {
    var k = kinds.slice().sort().join('+');
    if (k === 'child+child') return 'two_children';
    if (k === 'adult+adult') return 'two_adults';
    if (k === 'adult+child') return 'adult_and_child';
    return null;
  }

  function isDuoKind(kind) {
    return DUO_KINDS.indexOf(kind) >= 0;
  }

  /** Тарифы, из которых выбирают явно: на одного — одиночные, на двоих — «двое». */
  function tierChoices(service, count) {
    var want = count === 2 ? DUO_KINDS : SINGLE_KINDS;
    return ((service && service.price_tiers) || []).filter(function (t) { return want.indexOf(t.tier_kind) >= 0; });
  }

  /**
   * Тариф прошлой записи ЭТОГО профиля у ЭТОГО тренера на ЭТУ услугу: `hints[client_id]` — id тарифа
   * из `/client/session?for_trainer_id=` с `X-Profile-Id` этого профиля (сервис уже сверен). Иначе null.
   */
  function hintTier(service, profile, opts) {
    var hints = (opts && opts.hints) || {};
    var vid = profile ? hints[profile.client_id] : null;
    if (vid == null) return null;
    var t = ((service && service.price_tiers) || []).filter(function (x) { return Number(x.id) === Number(vid); })[0];
    return t && SINGLE_KINDS.indexOf(t.tier_kind) >= 0 ? t : null;
  }

  /**
   * Тариф по выбранным профилям или null — тогда форма просит выбрать тариф явно.
   * Один: явный выбор → тариф прошлой записи этого профиля → тариф его вида (только точное совпадение).
   * Двое: явный выбор на двоих → тариф пары, если вид обоих известен.
   */
  function regularTier(service, selected, opts) {
    opts = opts || {};
    var count = selected.length;
    if (!count) return null;
    if (opts.override != null) {
      var o = tierChoices(service, count).filter(function (t) { return Number(t.id) === Number(opts.override); })[0];
      if (o) return o;
    }
    if (count === 2) {
      var k1 = profileKind(selected[0], opts);
      var k2 = profileKind(selected[1], opts);
      return k1 && k2 ? tierByKind(service, duoKindFor([k1, k2])) : null;
    }
    var p = selected[0];
    var hinted = hintTier(service, p, opts);
    if (hinted) return hinted;
    var kind = profileKind(p, opts);
    return kind ? tierByKind(service, kind) : null;
  }

  /**
   * Можно ли отметить ещё одного: до двоих и только если у услуги есть тариф на двоих (на эту пару,
   * когда вид обоих известен). Нет тарифов на двоих — второго не выбрать.
   * Групповой слот (`opts.group`): одна запись = одно место = один участник — второго не отметить.
   */
  function canAddProfile(service, selected, candidate, opts) {
    if (selected.length >= 2) return false;
    if (!selected.length) return true;
    if (opts && opts.group) return false;
    var duo = tierChoices(service, 2);
    if (!duo.length) return false;
    var k1 = profileKind(selected[0], opts);
    var k2 = profileKind(candidate, opts);
    if (k1 && k2) return !!tierByKind(service, duoKindFor([k1, k2]));
    return true;
  }

  /**
   * Абонемент профиля у этого тренера на эту услугу. `certain` — занятие точно спишется с него:
   * сервер знает тарифы абонемента (`tier_kinds`, пусто — любые) и тариф записи подходит
   * (как SQL_PASS_PRODUCT_COVERS_BOOKING). Нет данных о тарифах — `certain: false`.
   */
  function usablePass(passes, trainerId, serviceId, tierKind) {
    var now = Date.now();
    var found = (passes || []).filter(function (p) {
      if (Number(p.trainer_id) !== Number(trainerId)) return false;
      if (p.status !== 'active' || !(Number(p.sessions_remaining) > 0) || p.is_expired) return false;
      if (p.expires_at && Date.parse(p.expires_at) < now) return false;
      var ids = p.service_ids || [];
      return !ids.length || ids.indexOf(Number(serviceId)) >= 0;
    });
    if (!found.length) return null;
    for (var i = 0; i < found.length; i++) {
      var kinds = found[i].tier_kinds;
      if (Array.isArray(kinds) && (!kinds.length || (tierKind && kinds.indexOf(tierKind) >= 0))) {
        return { pass: found[i], certain: true };
      }
    }
    return { pass: found[0], certain: false };
  }

  /**
   * Строка оплаты под формой. До отправки видна вся цена: занятие, билет, прокат.
   * `pass` — результат usablePass: «спишем 1» только при `certain`; иначе обычная цена и осторожная строка.
   */
  function payLine(opts) {
    var tier = opts.tier;
    var cur = opts.currency || 'BYN';
    var online = !!opts.online;
    var rental = opts.rentalCents ? formatMoney(opts.rentalCents, opts.rentalCurrency || cur) : '';
    var ticket = online ? '' : rental
      ? ' Билет на сеанс — в кассе катка, прокат коньков — ' + rental + ', если нужен.'
      : ' Билет на сеанс — в кассе катка.';
    var pass = opts.pass || null;
    if (pass && pass.certain && !opts.duo) {
      var left = Number(pass.pass.sessions_remaining) - 1;
      return '<b>Абонемент «' + esc(pass.pass.product_name) + '»</b>: спишем 1, останется ' + left + '.' + ticket;
    }
    var maybePass = pass && !opts.duo ? ' Если есть абонемент — тренер может списать занятие с него.' : '';
    var priceCents = tier ? tier.price_cents : opts.fallbackCents;
    if (!(Number(priceCents) > 0)) return 'Цену уточните у тренера.' + maybePass + ticket;
    var money = formatMoney(priceCents, cur);
    if (opts.duo && tier) {
      return '<b>' + esc(TIER_TITLE[tier.tier_kind] || tier.label) + ' — ' + money + '</b> за двоих тренеру' + (online ? '' : ' на месте') + '.' +
        (pass ? ' Вместо оплаты тренер может списать занятие с абонемента.' : '') + ticket;
    }
    return '<b>' + money + '</b> — тренеру' + (online ? '' : ' на месте') + '.' + maybePass + ticket;
  }

  /* ── Услуга и слот ──────────────────────────────────────────────────── */

  /**
   * Подходит ли услуга к формату слота — то же правило, что у сервера (`post_client_booking` → 422):
   * онлайн-слот (`is_online` и без катка) — только онлайн-услуга, очный — только очная.
   */
  function serviceFitsSlot(service, slot) {
    if (!service || !slot) return false;
    var slotOnline = !!slot.is_online && slot.arena_id == null;
    return !!service.is_online === slotOnline;
  }

  function servicesForSlot(services, slot) {
    return (services || []).filter(function (s) { return serviceFitsSlot(s, slot); });
  }

  /**
   * Карточка каталога (`/client/catalog-trainer/{id}`, `/public/trainers/{id}`) → тренер витрины.
   * Тренер не из выдачи города (личная ссылка) — та же форма, те же поля услуги, что у `_service_out`
   * (в т.ч. `group_price_cents`: сервер записывает в группу COALESCE(group_price_cents, price_cents)).
   */
  function trainerFromCatalogCard(t) {
    var p = t.profile || {};
    var name = ((p.first_name || '') + ' ' + (p.last_name || '')).trim() || 'Тренер';
    var photo = (t.photos || [])[0] || {};
    var initial = (name.match(/\p{L}/u) || ['Т'])[0].toUpperCase();
    return {
      id: t.id,
      name: name,
      first_name: (p.first_name || '').trim() || name,
      initial: initial,
      photo_url: photo.url || photo.list_url || null,
      experience_years: p.experience_years,
      description: (p.description || '').trim(),
      education: (p.education || '').trim(),
      rating_avg: p.rating_avg,
      rating_count: p.rating_count || 0,
      session_duration_minutes: p.session_duration_minutes,
      glide_since: null,
      can_book: !!t.can_book,
      contact_url: t.contact_telegram_url || null,
      city_id: p.city_id != null ? p.city_id : null,
      services: (t.services || []).map(function (s) {
        return {
          service_id: s.service_id, service_name: s.service_name,
          is_public: s.is_public !== false, direction_service_id: s.direction_service_id != null ? s.direction_service_id : null,
          is_online: !!s.is_online,
          price_cents: s.price_cents, group_price_cents: s.group_price_cents != null ? s.group_price_cents : null,
          currency_code: s.currency_code || 'BYN', description: s.description,
          price_tiers: s.price_tiers || [],
        };
      }),
      arenas: (t.arena_ids || []).map(function (id, i) { return { id: id, name: (t.arena_names || [])[i] || '' }; }).filter(function (a) { return a.name; }),
      windows: [],
    };
  }

  /* ── Даты ───────────────────────────────────────────────────────────── */

  function parseIsoDate(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || ''));
    return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : null;
  }

  function isoOf(d) {
    return d.toISOString().slice(0, 10);
  }

  function addDays(iso, n) {
    var d = parseIsoDate(iso);
    d.setUTCDate(d.getUTCDate() + n);
    return isoOf(d);
  }

  function daysBetween(a, b) {
    return Math.round((parseIsoDate(b) - parseIsoDate(a)) / 86400000);
  }

  /** «Сегодня» / «Завтра» / «Вт, 10 ноября». */
  function dayLabel(iso, todayIso) {
    var diff = daysBetween(todayIso, iso);
    if (diff === 0) return 'Сегодня';
    if (diff === 1) return 'Завтра';
    var d = parseIsoDate(iso);
    var wd = WEEKDAY_SHORT[d.getUTCDay()];
    return wd.charAt(0).toUpperCase() + wd.slice(1) + ', ' + d.getUTCDate() + ' ' + MONTHS_GEN[d.getUTCMonth()];
  }

  /** Подпись под временем: «сегодня» / «завтра» / «вт, 10 ноября». */
  function daySmall(iso, todayIso) {
    return dayLabel(iso, todayIso).toLowerCase();
  }

  /** Кнопка «Записаться на …»: «сегодня» / «завтра» / «10 ноября» — без дня недели, чтобы влезть в строку. */
  function ctaDay(iso, todayIso) {
    var diff = daysBetween(todayIso, iso);
    if (diff === 0) return 'сегодня';
    if (diff === 1) return 'завтра';
    var d = parseIsoDate(iso);
    return d.getUTCDate() + ' ' + MONTHS_GEN[d.getUTCMonth()];
  }

  /** «Сегодня, 17:15–18:00» — конец занятия вместо длительности. */
  function slotWhen(slot, todayIso) {
    var t = String(slot.start_time || '').slice(0, 5);
    var e = String(slot.end_time || '').slice(0, 5);
    return dayLabel(slot.slot_date, todayIso) + ', ' + t + (e ? '–' + e : '');
  }

  function slotMinutes(slot) {
    var a = String(slot.start_time || '').split(':');
    var b = String(slot.end_time || '').split(':');
    if (a.length < 2 || b.length < 2) return 0;
    var m = (+b[0] * 60 + +b[1]) - (+a[0] * 60 + +a[1]);
    return m > 0 ? m : 0;
  }

  /** «7–13 ноября» / «28 ноября – 4 декабря». */
  function weekRange(startIso) {
    var a = parseIsoDate(startIso);
    var b = parseIsoDate(addDays(startIso, 6));
    if (a.getUTCMonth() === b.getUTCMonth()) return a.getUTCDate() + '–' + b.getUTCDate() + ' ' + MONTHS_GEN[b.getUTCMonth()];
    return a.getUTCDate() + ' ' + MONTHS_GEN[a.getUTCMonth()] + ' – ' + b.getUTCDate() + ' ' + MONTHS_GEN[b.getUTCMonth()];
  }

  function weekDays(startIso, slots) {
    var has = {};
    (slots || []).forEach(function (s) { has[s.slot_date] = true; });
    var out = [];
    for (var i = 0; i < 7; i++) {
      var iso = addDays(startIso, i);
      var d = parseIsoDate(iso);
      out.push({ iso: iso, wd: WEEKDAY_SHORT[d.getUTCDay()], day: d.getUTCDate(), off: !has[iso] });
    }
    return out;
  }

  function sortSlots(slots) {
    return (slots || []).slice().sort(function (a, b) {
      var ka = a.slot_date + ' ' + a.start_time;
      var kb = b.slot_date + ' ' + b.start_time;
      return ka < kb ? -1 : ka > kb ? 1 : 0;
    });
  }

  /** Окно витрины (`windows[]`) → форма слота клиентского API. */
  function windowToSlot(w) {
    var s = String(w.starts_at || '');
    var e = String(w.ends_at || '');
    return {
      id: w.slot_id,
      slot_date: s.slice(0, 10),
      start_time: s.slice(11, 16),
      end_time: e ? e.slice(11, 16) : '',
      arena_id: w.arena_id,
      capacity: 1,
    };
  }

  /* ── Имена ──────────────────────────────────────────────────────────── */

  function isCyrillic(s) {
    return /^[А-Яа-яЁё-]+$/.test(String(s || ''));
  }

  /** Дательный падеж имени тренера — тем же склонятелем, что заявки (RuPersonName). Латиница — как есть. */
  function dativeFirst(first, ruName) {
    var f = String(first || '').trim().split(/\s+/)[0] || '';
    if (!f) return 'тренеру';
    if (!isCyrillic(f) || !ruName || typeof ruName.inflectPersonName !== 'function') return f;
    return ruName.inflectPersonName(f, '', 'dat') || f;
  }

  /** «Katusha записывает сама — …». Пол угадываем только по кириллице; иначе — без глагола в роде. */
  /**
   * Текст без онлайн-записи. Не обещает «напишите», если кнопки «Написать» нет
   * (``canWrite`` / ``canRequest`` / ``hasPhone`` — что реально покажем).
   */
  function selfBookingLine(first, ruName, opts) {
    opts = opts || {};
    var f = String(first || '').trim().split(/\s+/)[0] || 'Тренер';
    var who = '';
    if (isCyrillic(f) && ruName && typeof ruName.guessGender === 'function') {
      who = f + ' записывает ' + (ruName.guessGender(f) === 'f' ? 'сама' : 'сам') + ' — ';
    } else {
      who = 'Онлайн-записи нет. ';
    }
    if (opts.canWrite) return who + 'напишите и договоритесь о времени и цене.';
    if (opts.canRequest) return who + 'оставьте заявку и договоритесь о времени и цене.';
    if (opts.hasPhone) return who + 'позвоните и договоритесь о времени и цене.';
    return who + 'откройте Telegram и договоритесь о времени и цене.';
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /** Номер из `requestContact` (ответ разных версий клиента) → E.164 или ''. */
  function phoneFromContact(res) {
    if (!res) return '';
    var c = (res.responseUnsafe && res.responseUnsafe.contact) || res.contact || null;
    var raw = c && c.phone_number;
    if (!raw && typeof res.response === 'string') {
      try {
        var q = new URLSearchParams(res.response);
        var cj = JSON.parse(q.get('contact') || 'null');
        raw = cj && cj.phone_number;
      } catch (e) { raw = ''; }
    }
    var d = String(raw || '').replace(/\D/g, '');
    return d.length >= 9 ? '+' + d : '';
  }

  /** Что взять с собой: слой «пишем мы», по направлению; прокат — цифра катка. */
  function takeWithYou(dirKey, arena) {
    var base = dirKey === 's-klyushkoy'
      ? 'Шлем, перчатки и клюшку — как минимум.'
      : 'Тёплую одежду, в которой удобно двигаться, и перчатки.';
    if (arena && arena.rental_cents) {
      base += ' Нет коньков — прокат в ' + arena.name + ', ' + formatMoney(arena.rental_cents, arena.rental_currency) + '.';
    }
    return base + ' Билет на сеанс — в кассе.';
  }

  return {
    DIRECTIONS: DIRECTIONS,
    TIER_TITLE: TIER_TITLE,
    plural: plural,
    direction: direction,
    directionKeyForServiceId: directionKeyForServiceId,
    servicesInDirection: servicesInDirection,
    trainerInDirection: trainerInDirection,
    trainerDirections: trainerDirections,
    visibleTrainers: visibleTrainers,
    tabCounts: tabCounts,
    minPriceOf: minPriceOf,
    word: word,
    arenaOptions: arenaOptions,
    formatMoney: formatMoney,
    tierByKind: tierByKind,
    cardPriceHtml: cardPriceHtml,
    noticeParts: noticeParts,
    serviceAbout: serviceAbout,
    whoTeaches: whoTeaches,
    tidyText: tidyText,
    experienceBadge: experienceBadge,
    ratingLine: ratingLine,
    glideSince: glideSince,
    cardFacts: cardFacts,
    whoOptions: whoOptions,
    priceRows: priceRows,
    priceFrom: priceFrom,
    nameFields: nameFields,
    newClientBookingPlan: newClientBookingPlan,
    bookingComment: bookingComment,
    profileKind: profileKind,
    isDuoKind: isDuoKind,
    tierChoices: tierChoices,
    hintTier: hintTier,
    regularTier: regularTier,
    canAddProfile: canAddProfile,
    serviceFitsSlot: serviceFitsSlot,
    servicesForSlot: servicesForSlot,
    trainerFromCatalogCard: trainerFromCatalogCard,
    usablePass: usablePass,
    payLine: payLine,
    addDays: addDays,
    daysBetween: daysBetween,
    dayLabel: dayLabel,
    daySmall: daySmall,
    ctaDay: ctaDay,
    slotWhen: slotWhen,
    slotMinutes: slotMinutes,
    weekRange: weekRange,
    weekDays: weekDays,
    sortSlots: sortSlots,
    windowToSlot: windowToSlot,
    dativeFirst: dativeFirst,
    selfBookingLine: selfBookingLine,
    phoneFromContact: phoneFromContact,
    takeWithYou: takeWithYou,
    esc: esc,
  };
});
