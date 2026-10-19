/**
 * TASK-303 (PDEC-023): главная клиента — направление А «Сайт в кармане».
 * Run: node --test tests/js/hub-home-wiring.test.js
 *
 * Заменяет hub-catalog-blocks-wiring.test.js: тот проверял зоны прежней главной
 * (лёд-тизер, «Куда катимся», карусель), которых больше нет.
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const webapp = path.resolve(__dirname, '../../static/webapp');
const homeHtml = fs.readFileSync(path.join(webapp, 'client-home.html'), 'utf8');
const homeMain = fs.readFileSync(path.join(webapp, 'client-home-main.js'), 'utf8');
const hubJs = fs.readFileSync(path.join(webapp, 'hub-home.js'), 'utf8');
const hubCss = fs.readFileSync(path.join(webapp, 'hub-home.css'), 'utf8');
const homeCss = fs.readFileSync(path.join(webapp, 'mini-app-client-home.css'), 'utf8');
const HubHome = require(path.join(webapp, 'hub-home.js'));

function fnBody(name) {
  const start = homeMain.indexOf('function ' + name + '(');
  assert.ok(start >= 0, 'нет функции ' + name);
  let depth = 0;
  for (let i = homeMain.indexOf('{', start); i < homeMain.length; i++) {
    if (homeMain[i] === '{') depth++;
    else if (homeMain[i] === '}' && --depth === 0) return homeMain.slice(start, i + 1);
  }
  throw new Error('не закрыта ' + name);
}

describe('разметка главной', () => {
  it('порядок как в макете: шапка → слот → мои занятия → ближайший лёд → что нужно', () => {
    const ids = ['hubHero', 'hubNow', 'hubMine', 'hubNearest', 'hubNeeds'].map((id) => homeHtml.indexOf('id="' + id + '"'));
    ids.forEach((pos, i) => assert.ok(pos > 0, 'нет блока #' + ['hubHero', 'hubNow', 'hubMine', 'hubNearest', 'hubNeeds'][i]));
    assert.deepEqual([...ids].sort((a, b) => a - b), ids);
  });

  it('старых зон нет: лёд-тизер, поиск, «Куда катимся», карусель, полосы, FAB, футер', () => {
    for (const id of ['hubIceZone', 'hubSearchRow', 'hubExplore', 'hubDiscovery', 'quickStrip', 'hubStreakRibbon', 'hubBookFab', 'hubFooterAside']) {
      assert.ok(!homeHtml.includes('id="' + id + '"'), '#' + id + ' остался');
    }
    assert.ok(!/Подборки/.test(homeHtml + homeMain + hubJs), 'слова «Подборки» нет');
    assert.ok(!/«Сервис»|>Сервис<|Бесплатно/.test(homeHtml + hubJs));
  });

  it('карточка клиента и полка остатка — внутри «Моих занятий»', () => {
    const mine = homeHtml.slice(homeHtml.indexOf('id="hubMine"'), homeHtml.indexOf('id="hubNearest"'));
    for (const id of ['nextBookingBlock', 'myTrainerBlock', 'hubPrimaryPanel']) assert.ok(mine.includes('id="' + id + '"'), id);
  });

  it('шапка держит высоту и грузит фото первым', () => {
    assert.match(homeHtml, /<img class="hh__photo" id="hubHeroPhoto"[^>]*fetchpriority="high"/);
    assert.match(hubCss, /\.hh \{[^}]*height: 300px/);
  });
});

describe('скорость (AC-P2…P5)', () => {
  it('ни одного шрифта и стиля с Google: свои Dela Gothic и Golos', () => {
    assert.ok(!homeHtml.includes('fonts.googleapis.com'));
    assert.ok(!homeHtml.includes('fonts.gstatic.com'));
    assert.match(homeHtml, /glide-public-fonts\.css/);
  });

  it('у своих ассетов одна версия, preload совпадает с тегом', () => {
    const versions = new Set([...homeHtml.matchAll(/\.(?:js|css)\?v=(\d+)/g)].map((m) => m[1]));
    assert.equal(versions.size, 1, 'разные ?v=: ' + [...versions].join(','));
    const pre = /<link rel="preload" href="(client-home-main\.js\?v=\d+)"/.exec(homeHtml);
    assert.ok(pre && homeHtml.includes('src="' + pre[1] + '"'));
  });

  it('модели старых зон и строка игры отдельными файлами не грузятся', () => {
    for (const f of ['hub-collections-model.js', 'hub-ice-today-model.js', 'hub-kto-kogo.js', 'hub-kto-kogo.css', 'kto-kogo-model.js']) {
      assert.ok(!homeHtml.includes(f), f);
    }
    assert.ok(homeHtml.indexOf('src="hub-home.js') < homeHtml.lastIndexOf('src="client-home-main.js'));
  });

  it('фото «Ближайшего льда» — лениво; битое фото не рисует значок', () => {
    assert.match(hubJs, /img\.loading = 'lazy'/);
    assert.match(hubJs, /img\.onerror = function \(\) \{ img\.remove\(\); \}/);
    // Шапка: битое фото — следующее фото города, кончились — тёмная плашка.
    assert.match(hubJs, /new global\.Image\(\)/);
    assert.match(hubJs, /if \(!showing\) \{\s+photo\.classList\.remove\('is-in'\);\s+photo\.hidden = true;\s+\}/);
    assert.match(hubJs, /city\.hero_photos/);
    // Не больше четырёх попыток, без размытой миниатюры; вкладки ждут обложку не дольше 1,5 с.
    assert.match(hubJs, /HERO_MAX_TRIES = 4/);
    assert.match(hubJs, /\[p\.card, p\.hero\]\.forEach/);
    assert.match(hubJs, /Promise\.race\(\[heroSettle/);
    // Кэш шапки — только после onload. Старый ключ v1 запоминал первый URL ещё до 404.
    assert.match(hubJs, /CACHE_KEY = 'glide\.hub\.hero\.v2'/);
    const apply = hubJs.slice(hubJs.indexOf('function apply('), hubJs.indexOf('function paintCached('));
    assert.ok(!/cacheWrite\(\{ city: hero\.city/.test(apply.replace(/hero\.onPhoto = function[\s\S]*?\};/, '')));
  });

  it('префетч других вкладок — после load, а не вместе с первым экраном', () => {
    const finish = fnBody('finishHubInitialLoading');
    assert.match(finish, /window\.HubHome\.ready\(\)/);
    assert.match(finish, /document\.readyState === 'complete'/);
    assert.match(finish, /addEventListener\('load', prefetch, \{ once: true \}\)/);
    assert.match(finish, /whenHeroSettled\(\)/);
    assert.ok(!homeCss.includes('hub-initial-reveal'), 'блоки главной не выезжают после скелетона');
  });

  it('префетч поиска качает те же версии, что открывает вкладка', () => {
    const iceHtml = fs.readFileSync(path.join(webapp, 'ice.html'), 'utf8');
    const shell = fs.readFileSync(path.join(webapp, 'mini-app-client-shell.js'), 'utf8');
    // Версию префетч берёт из адреса самого shell — вписанные руками ?v= не переживали бамп.
    assert.ok(!/\?v=\d+/.test(shell), 'в shell нет вписанных версий');
    assert.match(shell, /document\.currentScript/);
    const shellV = /mini-app-client-shell\.js\?v=(\d+)/.exec(homeHtml)[1];
    for (const file of ['ice-tab.js', 'ice-tab-model.js', 'ice-map-model.js', 'ice-map.js', 'ice-tab.css']) {
      const v = new RegExp(file.replace('.', '\\.') + '\\?v=(\\d+)').exec(iceHtml);
      assert.ok(v, file);
      assert.equal(v[1], shellV, file + ': вкладка и главная на одной версии');
      assert.ok(shell.includes("assetUrl(base, '" + file + "')"), file + ' прогревается');
    }
  });

  it('скелет снимается после bootstrap, не после окон тренера', () => {
    const load = fnBody('loadAll');
    assert.match(load, /\.then\(finishHubInitialLoading, finishHubInitialLoading\)/);
  });
});

describe('client-home-main.js раскладывает своё по новой главной', () => {
  it('HubHome рисует шапку и слот первым делом', () => {
    const apply = fnBody('applyHubState');
    assert.match(apply, /var slotKind = window\.HubHome \? window\.HubHome\.apply\(hubMeta\) : 'none'/);
    assert.ok(apply.indexOf('HubHome.apply') < apply.indexOf('findNextBooking'));
  });

  it('запись сегодня — в слот, будущая — в «Мои занятия»', () => {
    assert.match(fnBody('applyHubState'), /placeMeCard\(slotKind === 'booking' \? 'slot' : 'mine'\)/);
  });

  it('без города слот — тизер льда по стране; его модели грузятся только тогда', () => {
    assert.match(hubJs, /else if \(!city && hub && hub\.ice_teaser\)/);
    assert.match(hubJs, /NO_CITY_SCRIPTS = \['minsk-time\.js', 'schedule-staleness-model\.js', 'ice-teaser-model\.js', 'catalog-geo-model\.js'\]/);
    for (const f of ['ice-teaser-model.js', 'catalog-geo-model.js', 'minsk-time.js', 'schedule-staleness-model.js']) {
      assert.ok(!homeHtml.includes('src="' + f), f + ' не в критическом пути');
    }
    assert.match(fnBody('attemptHubGeoRefine'), /needNoCityModels\(\)\.then\(attemptHubGeoRefine/);
    assert.ok(!/paintMarketHero/.test(homeMain), 'карточка «лёд города» заменена слотом');
  });

  it('сбой и отсутствие initData — честная шапка, без старых зон', () => {
    const load = fnBody('loadAll');
    assert.equal((load.match(/window\.HubHome\.fail\(\)/g) || []).length, 2);
    assert.ok(!/renderIceTeaser|renderHubExplore|renderStreakRibbon|syncClientHubBookFab/.test(homeMain));
  });
});

describe('hub-home.js', () => {
  it('рисует только через textContent/createElement', () => {
    assert.ok(!/innerHTML|insertAdjacentHTML|outerHTML/.test(hubJs));
  });

  it('приветствие по часу и имени', () => {
    assert.equal(HubHome.greetingText(9, 'Макс'), 'Доброе утро, Макс');
    assert.equal(HubHome.greetingText(19, ''), 'Добрый вечер');
    assert.equal(HubHome.greetingText(2, null), 'Доброй ночи');
  });

  it('время матча — как в игре', () => {
    const now = new Date('2026-10-19T15:00:00Z');
    assert.equal(HubHome._whenLabel('2026-10-20T16:30:00Z', now), 'завтра, 19:30');
    assert.equal(HubHome._whenLabel('2026-10-19T16:30:00Z', now), 'сегодня, 19:30');
  });

  it('«через N минут» и короткий день недели', () => {
    assert.equal(HubHome._soonLabel(22), 'через 22 минуты');
    assert.equal(HubHome._soonLabel(75), 'через 1 ч 15 мин');
    assert.equal(HubHome._soonLabel(0), 'уже идёт');
    assert.equal(HubHome._shortKicker('понедельник, 19 октября'), 'пн, 19 октября');
  });
});
