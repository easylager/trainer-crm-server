/**
 * TASK-148 (AC-3, AC-4) → TASK-149: интеграционные гварды композиции хаба 05/06.
 * Проверяет статическую обвязку так же, как client-bookings-profile-race.test.js:
 * секции есть в разметке, модели подключены до client-home-main.js, рендеры
 * вызываются из applyHubState и скрываются в аварийных ветках.
 *
 * TASK-149 поменял структуру страницы: один блок льда (кикер + герой + строки
 * сеансов + «Весь лёд» + поиск) и одна секция рынка «Куда катимся» вместо
 * «Подборок» и второго блока «Сегодня на льду». Инварианты 148 перенесены, а не
 * сняты: там, где они изменились, это отмечено в комментарии «Было → Стало».
 *
 * Run: node --test tests/js/hub-catalog-blocks-wiring.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');

function read(name) {
  return fs.readFileSync(path.join(webapp, name), 'utf8');
}

const homeHtml = read('client-home.html');
const homeMain = read('client-home-main.js');
const homeCss = read('mini-app-client-home.css');

/** Позиция id в разметке; падает с понятным сообщением, если элемента нет. */
function at(id) {
  const idx = homeHtml.indexOf('id="' + id + '"');
  assert.ok(idx > -1, 'в client-home.html нет id="' + id + '"');
  return idx;
}

/** Тело функции по имени: от `function name(` до следующей function того же отступа. */
function fnBody(name) {
  const start = homeMain.indexOf('function ' + name + '(');
  assert.ok(start > -1, 'нет функции ' + name);
  const next = homeMain.indexOf('\n      function ', start + 10);
  return homeMain.slice(start, next > -1 ? next : undefined);
}

describe('разметка и подключение моделей', () => {
  // Было: «есть секции подборок и "Сегодня на льду", обе скрыты».
  // Стало: секция рынка скрыта, строки сеансов — внутри зоны льда и скрыты.
  it('«Куда катимся» и строки сеансов льда есть в разметке и скрыты по умолчанию', () => {
    assert.match(homeHtml, /id="hubExplore"[^>]*hidden/);
    assert.match(homeHtml, /id="hubIceSessions"[^>]*hidden/);
  });

  it('слова «Подборки» нет ни в разметке, ни в коде хаба (AC-002)', () => {
    assert.ok(!homeHtml.includes('Подборки'), 'Подборки в client-home.html');
    assert.ok(!homeMain.includes('Подборки'), 'Подборки в client-home-main.js');
    assert.doesNotMatch(homeHtml, /id="hubCollections"/);
    assert.ok(!homeMain.includes('hubCollections'));
  });

  it('ровно один блок сеансов льда: отдельной секции #hubIceToday внизу нет (AC-002)', () => {
    assert.doesNotMatch(homeHtml, /id="hubIceToday"/);
    assert.ok(!homeMain.includes("'hubIceToday'"));
    assert.equal(homeHtml.split('id="hubIceSessions"').length - 1, 1);
    assert.equal(homeHtml.split('hub-ice-today__card').length - 1, 1);
    // Блок сеансов — внутри зоны льда, не снаружи.
    const zone = at('hubIceZone');
    const sessions = at('hubIceSessions');
    const search = at('hubSearchRow');
    const zoneEnd = homeHtml.indexOf('<!-- ── SCENARIO 1', zone);
    assert.ok(sessions > zone && sessions < zoneEnd, 'hubIceSessions внутри hubIceZone');
    assert.ok(search > zone && search < zoneEnd, 'поиск внутри hubIceZone');
  });

  // Было: «новые секции стоят после upcomingSection и до футера».
  // Стало: рынок стоит ниже ВСЕХ персональных блоков и до футера.
  it('«Куда катимся» стоит ниже персональных блоков и до футера (AC-004)', () => {
    const explore = at('hubExplore');
    for (const id of ['nextBookingBlock', 'myTrainerBlock', 'hubPrimaryPanel', 'hubDiscovery', 'quickStrip', 'hubStreakRibbon', 'upcomingSection']) {
      assert.ok(at(id) < explore, id + ' должен быть выше hubExplore');
    }
    assert.ok(at('hubFooterAside') > explore, 'рынок до футера');
  });

  it('порядок гостя (AC-001): приветствие → кикер → герой → сеансы → поиск → «Куда катимся»', () => {
    const order = ['hubGreeting', 'hubIceZone', 'hubIceKicker', 'hubIceTeaser', 'hubIceSessions', 'hubSearchRow', 'hubExplore'];
    for (let i = 1; i < order.length; i++) {
      assert.ok(at(order[i - 1]) < at(order[i]), order[i - 1] + ' должен быть выше ' + order[i]);
    }
    // «Весь лёд» — в шапке блока льда, до героя.
    assert.ok(at('hubIceKicker') < at('hubIceAll') && at('hubIceAll') < at('hubIceTeaser'));
  });

  it('модели подключены до client-home-main.js', () => {
    const collectionsModel = homeHtml.indexOf('hub-collections-model.js');
    const iceTodayModel = homeHtml.indexOf('hub-ice-today-model.js');
    // preload в <head> не считается: важен тег <script>, который грузит код.
    const mainJs = homeHtml.lastIndexOf('src="client-home-main.js');
    assert.ok(collectionsModel > -1 && collectionsModel < mainJs);
    assert.ok(iceTodayModel > -1 && iceTodayModel < mainJs);
  });

  it('ice-teaser-model.js и renderIceTeaser не тронуты', () => {
    assert.match(homeMain, /function renderIceTeaser\(payload\)/);
    assert.match(homeHtml, /ice-teaser-model\.js/);
    // Кикер блока — ровно то, что отдаёт модель; своего текста у хаба нет.
    assert.match(fnBody('renderIceTeaser'), /kicker\.textContent = \(view && view\.kicker\) \|\| 'На льду'/);
  });

  it('копирайт кикера честный: «сейчас» в хабе не зашито (герой-сеанс ещё не идёт)', () => {
    assert.ok(!/На льду сейчас/.test(homeHtml), 'в разметке');
    assert.ok(!/На льду сейчас/.test(homeMain), 'в коде');
  });

  it('?v= затронутых ассетов поднят единообразно, preload совпадает с тегом (S4)', () => {
    const versionOf = (re) => {
      const all = [...homeHtml.matchAll(re)].map((m) => Number(m[1]));
      assert.ok(all.length >= 1, 'нет ' + re);
      assert.equal(new Set(all).size, 1, 'разные ?v= у одного файла: ' + all);
      return all[0];
    };
    const main = versionOf(/client-home-main\.js\?v=(\d+)/g);
    const model = versionOf(/hub-collections-model\.js\?v=(\d+)/g);
    const css = versionOf(/mini-app-client-home\.css\?v=(\d+)/g);
    // Было 202610028 (js/модель) и 202609287 (css): любой ассет, который я правил, должен быть новее.
    for (const v of [main, model, css]) assert.ok(v >= 202610031, 'версия не поднята: ' + v);
  });
});

describe('вызовы рендеров в client-home-main.js', () => {
  it('строки сеансов монтируются сразу после renderIceTeaser из того же payload', () => {
    assert.match(homeMain, /renderIceTeaser\(iceTeaser\);\s*\n\s*\/\*[^*]*\*\/\s*\n\s*renderIceTodaySessions\(iceTeaser\);/);
  });

  // Было: «Подборки монтируются после вычисления discoveryCityId» (renderHubCollections).
  it('«Куда катимся» монтируется после вычисления discoveryCityId', () => {
    assert.match(homeMain, /hubMarketPromise = renderHubExplore\(discoveryCityId\);/);
    assert.ok(
      homeMain.indexOf('discoveryCityId =') < homeMain.indexOf('renderHubExplore(discoveryCityId)'),
      'город должен быть вычислен до рендера рынка'
    );
  });

  // Было: аварийные ветки скрывали renderHubCollections(null).
  it('аварийные ветки (без initData и при ошибке) скрывают новые блоки', () => {
    // Без initData. Порядок тот же, но между вызовами теперь живёт правило
    // видимости поиска (DEC-001), поэтому соседство больше не построчное.
    assert.match(
      homeMain,
      /renderIceTeaser\(null\);[\s\S]{0,240}?renderIceTodaySessions\(null\);[\s\S]{0,240}?hubMarketPromise = renderHubExplore\(null\);/
    );
    // DEC-001: данных нет — работа клиента и есть «найти», строка поиска обязана остаться.
    assert.match(homeMain, /renderIceTodaySessions\(null\);\s*\n\s*setHubSearchVisible\(true\);/);
    // Ошибка загрузки.
    assert.match(homeMain, /hideUpcomingSection\(\);\s*\n\s*renderIceTodaySessions\(null\);\s*\n\s*renderHubExplore\(null\);/);
  });

  it('строки сеансов зависят от героя: после уточнения по геолокации перерисовываются вместе с ним', () => {
    assert.match(homeMain, /renderIceTeaser\(data && data\.ice_teaser\);\s*\n\s*\/\/[^\n]*\n\s*renderIceTodaySessions\(data && data\.ice_teaser\);/);
    const body = fnBody('renderIceTodaySessions');
    assert.match(body, /formatIceCard/);
    assert.match(body, /view\.isFar/);
  });

  it('счётчики берутся из существующих публичных запросов, новых эндпоинтов нет', () => {
    assert.match(homeMain, /\/api\/public\/ice\/arenas\?intent=skate&city_id=/);
    assert.match(homeMain, /when=today_evening/);
    assert.match(homeMain, /venue_type_facets/);
    // Тренеры: тот же публичный список, что у «Поиска» (total).
    assert.match(homeMain, /\/api\/public\/trainers\?order_by=rating&limit=1&city_id=/);
    const endpoints = new Set([...homeMain.matchAll(/\/api\/public\/[a-z\/-]+/g)].map((m) => m[0].replace(/\/$/, '')));
    assert.deepEqual([...endpoints].sort(), ['/api/public/ice/arenas', '/api/public/photos', '/api/public/trainers']);
  });

  it('плитки «Сервис» / «Заточка» / «Бесплатно» в хабе не существуют', () => {
    for (const banned of ['skate_sharpening', 'sharpening', 'Сервис', 'Заточка', 'Бесплатно']) {
      assert.ok(!homeMain.includes(banned), banned + ' в client-home-main.js');
      assert.ok(!homeHtml.includes(banned), banned + ' в client-home.html');
    }
  });
});

describe('карусель #hubDiscovery не дублирует навигацию по рынку (DEC-004)', () => {
  it('loadAndRenderDiscovery вызывается только из loadDiscoveryUnlessMarket', () => {
    // Определение функции не считается вызовом.
    const calls = homeMain.match(/(?<!function )loadAndRenderDiscovery\(\)/g) || [];
    assert.equal(calls.length, 1, 'ровно один вызов — внутри loadDiscoveryUnlessMarket');
    assert.ok(fnBody('loadDiscoveryUnlessMarket').includes('loadAndRenderDiscovery()'));
  });

  it('все сценарии берут карусель через loadDiscoveryUnlessMarket', () => {
    assert.match(homeMain, /if \(opts\.showDiscovery\) return loadDiscoveryUnlessMarket\(\);/);
    assert.match(homeMain, /return finishHubApply\(loadDiscoveryUnlessMarket\(\)\);/);
    assert.match(homeMain, /return loadDiscoveryUnlessMarket\(\)\.then\(finishHubInitialLoading/);
  });

  it('плитки, появившись, прячут карусель; карусель сама проверяет, не успели ли плитки', () => {
    assert.match(fnBody('renderHubExplore'), /hideDiscovery\(\);/);
    assert.match(fnBody('loadAndRenderDiscovery'), /getElementById\('hubExplore'\)/);
  });

  it('ожидание рынка ограничено таймаутом: зависший запрос не держит хаб под скелетоном', () => {
    assert.match(homeMain, /var HUB_MARKET_WAIT_MS = \d+;/);
    assert.match(fnBody('loadDiscoveryUnlessMarket'), /withTimeout\(hubMarketPromise, HUB_MARKET_WAIT_MS, false\)/);
  });
});

describe('порядок для своего клиента: placeIceZone и Intent Engine не тронуты (AC-004)', () => {
  it('placeIceZone двигает весь #hubIceZone (лёд + сеансы + поиск) единым целым', () => {
    const body = fnBody('placeIceZone');
    assert.match(body, /getElementById\('hubIceZone'\)/);
    assert.match(body, /mode === 'below-trainer'/);
    assert.match(body, /getElementById\('hubDiscovery'\)/);
    assert.match(body, /getElementById\('myTrainerBlock'\)/);
    // Рынок якорится в разметке, а не двигается вместе с льдом.
    assert.ok(!body.includes('hubExplore'));
    assert.ok(!body.includes('hubIceSessions'));
  });

  it('applyHubState сохраняет приоритеты и оба режима размещения льда', () => {
    assert.ok(homeMain.includes("placeIceZone('top')"));
    assert.ok(homeMain.includes("placeIceZone('below-trainer')"));
    const idx = (s) => homeMain.indexOf(s);
    assert.ok(idx('Priority 1: Has upcoming booking') < idx('Priority 2: Has primary trainer'));
    assert.ok(idx('Priority 2: Has primary trainer') < idx('Priority 3: Has saved trainers'));
    assert.ok(idx('Priority 3: Has saved trainers') < idx('Priority 4: Has past sessions'));
    assert.ok(idx('Priority 4: Has past sessions') < idx('Priority 5: Clean state'));
    // Клиент с записью лёд не теряет: рендер льда до развилки приоритетов.
    assert.ok(idx('renderIceTeaser(iceTeaser);') < idx('Priority 1: Has upcoming booking'));
  });

  it('персональные блоки на месте и не переписаны (id и рендеры)', () => {
    for (const id of ['nextBookingBlock', 'myTrainerBlock', 'hubPrimaryPanel', 'quickStrip', 'upcomingSection']) {
      at(id);
    }
    // Было: renderNextBookingCard. Стало (TASK-160 S2): renderMeCardForBooking —
    // карточку записи рисует hub-me-card.js, старый рендер удалён вместе с метром.
    // Стало (S3): карточка тренера — тоже заливка «моей карточки», поэтому
    // renderMyTrainerCard удалён; его место в списке занял общий painter.
    for (const fn of ['renderMeCard', 'renderMeCardForBooking', 'renderSavedTrainersSection', 'renderUpcomingList', 'buildPrimaryPassHtml']) {
      assert.match(homeMain, new RegExp('function ' + fn + '\\('));
    }
  });

  // Было: «время — герой, абонемент строкой-метром внутри .hub-next-card».
  // Стало (TASK-160 S2): герой записи — «моя карточка» hub-me-card.js, остаток
  // показывает кошелёк карточки. Инвариант не снят, а переехал: на карточке
  // записи нет шеринга и нет тулбара, а хаб по-прежнему занимает личный слот.
  it('карточка ближайшей записи: рендер отдан модели, шеринга и тулбара на ней нет', () => {
    // S3: рисует общий painter renderMeCard, ветка записи только собирает вход.
    const body = fnBody('renderMeCard') + fnBody('renderMeCardForBooking');
    assert.match(body, /HubMeCard/);
    assert.match(body, /renderHtml\(view\)/);
    assert.ok(!body.includes('share-trainer'), 'шеринг ушёл с карточки записи');
    assert.ok(!body.includes('hub-next-card-toolbar'));
    assert.match(fnBody('applyHubState'), /hubPersonalSlot = true/);
  });
});

describe('приветствие (S1): факты, без погоды, без сдвига макета', () => {
  it('текст приветствия собирает чистая модель; имя — из Telegram', () => {
    const body = fnBody('defaultHubGreeting');
    assert.match(body, /model\.greetingText\(new Date\(\)\.getHours\(\), name\)/);
    // Было: имя бралось прямо здесь. Стало (TASK-160): выбор имени вынесен в
    // hubGreetingName — до резолва профилей имя владельца аккаунта было бы
    // чужим. Инвариант тот же: источник имени — Telegram, а не поле сервера.
    assert.match(body, /hubGreetingName\(\)/);
    assert.match(fnBody('hubGreetingName'), /getTelegramFirstName\(\)/);
  });

  it('подпись собирает чистая модель из фактов тизера; в коде хаба нет погоды', () => {
    assert.match(fnBody('paintHubGreetingSub'), /model\.greetingSub\(hubGreetingFacts\)/);
    const facts = fnBody('setHubGreetingFacts');
    assert.match(facts, /teaser\.city_name/);
    assert.match(facts, /is_country_fallback/);
    const greetingCode = fnBody('defaultHubGreeting') + fnBody('paintHubGreetingSub') + facts;
    assert.ok(!/погод|°|градус|лёд держит|идеальн|temperature|weather/i.test(greetingCode));
    // Комментарии разметки объясняют, чего нет; смотрим только то, что видит клиент.
    const visibleHtml = homeHtml.replace(/<!--[\s\S]*?-->/g, '');
    assert.ok(!/погод|°|лёд держит|идеальн/i.test(visibleHtml));
  });

  it('число катков вечером приходит из рынка и перерисовывает подпись (без сдвига макета)', () => {
    assert.match(fnBody('renderHubExplore'), /hubGreetingFacts\.eveningHits = evening;\s*\n\s*paintHubGreetingSub\(\);/);
  });

  it('подпись лежит внутри зарезервированной строки приветствия (TASK-091/095)', () => {
    const top = homeHtml.indexOf('class="hub-hero-top"');
    const greeting = at('hubGreeting');
    const sub = at('hubGreetingSub');
    const switcher = at('clientProfileSwitcherMount');
    assert.ok(top < greeting && greeting < sub && sub < switcher);
    assert.match(homeCss, /\.hub-hero-top\s*\{[^}]*min-height:\s*38px/);
    const subRule = homeCss.match(/\.hub-hero-greeting__sub\s*\{[^}]*\}/);
    assert.ok(subRule, 'нет стиля подписи');
    assert.match(subRule[0], /white-space:\s*nowrap/, 'подпись в одну строку: перенос вышел бы за 38px');
    assert.match(homeCss, /\.hub-hero-greeting__sub\[hidden\]\s*\{\s*display:\s*none/);
  });
});

describe('стили композиции только на токенах (AC-007)', () => {
  it('плитки красятся токенами типов --app-venue-*, а не хексами', () => {
    for (const [cls, token] of [['ice', 'ice'], ['trainer', 'trainer'], ['shop', 'shop']]) {
      const re = new RegExp('\\.hub-cg__ic--' + cls + '\\s*\\{[^}]*var\\(--app-venue-' + token + '\\)');
      assert.match(homeCss, re, cls);
    }
    const block = homeCss.slice(homeCss.indexOf('/* ─── TASK-149 (S3)'), homeCss.indexOf('/* ─── TASK-148 (AC-4)'));
    assert.ok(block.length > 500);
    assert.ok(!/#[0-9a-fA-F]{3,8}\b/.test(block), 'хекс в стилях плиток');
  });

  it('пустая секция и скрытые блоки не занимают места', () => {
    assert.match(homeCss, /\.hub-explore\[hidden\]\s*\{[^}]*display:\s*none/);
    assert.match(homeCss, /\.hub-ice-today__card\[hidden\]\s*\{\s*display:\s*none/);
    assert.match(homeCss, /body\.hub-body--loading #hubExplore/);
  });

  it('старая сетка .hub-explore-tile не конкурирует с .hub-cg', () => {
    assert.doesNotMatch(homeCss, /\.hub-explore-tile\b/);
    assert.doesNotMatch(homeCss, /\.hub-explore-grid\b/);
  });
});

describe('своё одним куском: слот, остальные записи, потом город', () => {
  it('следующие записи живут в карточке слота тем же штампом, без кнопки сообщения', () => {
    const body = fnBody('renderUpcomingList');
    assert.match(body, /hub-next-card-line/);
    assert.match(body, /nextCardStamp\(b, item\.start\)/);
    assert.match(body, /HUB_REST_MAX/);
    assert.match(body, /data-hub-action="all-bookings"/);
    assert.ok(!body.includes('hub-booking-msg-btn'), 'кнопка сообщения ушла со строки');
    assert.ok(!body.includes('Подтверждено'), 'статус без галочки и отдельного чипа');
    assert.match(body, /section\.style\.display = 'none'/);
  });

  it('при записи «Ещё занятие» — тихая строка сразу под слотом, поиск после', () => {
    const quiet = fnBody('rebookQuietItems');
    assert.match(quiet, /Ещё занятие/);
    assert.match(quiet, /quiet: true/);
    assert.ok(!quiet.includes('hub-quick-pill--primary'));
    const apply = fnBody('applyHubState');
    const booking = apply.indexOf('Priority 1: Has upcoming booking');
    const nextPri = apply.indexOf('Priority 2: Has primary trainer');
    const slice = apply.slice(booking, nextPri);
    assert.ok(slice.includes("renderQuickStrip('has-booking'"));
    assert.ok(slice.includes("placeQuickStrip('after-slot')"));
    assert.ok(slice.indexOf('renderUpcomingList') < slice.indexOf("placeQuickStrip('after-slot')"));
    const place = fnBody('placeQuickStrip');
    assert.match(place, /mode === 'after-slot'/);
    assert.match(place, /getElementById\('hubIceZone'\)/);
    assert.match(place, /insertBefore\(strip, explore\)/);
    const quietRule = homeCss.match(/\.hub-quick-strip--quiet\s*\{[^}]*\}/);
    assert.ok(quietRule, 'тихая полоска rebook без своих отступов уедет от «Куда катимся»');
    assert.match(quietRule[0], /margin:\s*0\s+16px/);
    assert.doesNotMatch(quietRule[0], /margin:\s*-4px\s+20px/);
    assert.match(
      homeCss,
      /#quickStrip\.hub-quick-strip--quiet:not\(\[hidden\]\)\s*\+\s*#hubExplore:not\(\[hidden\]\)/
    );
  });
});
