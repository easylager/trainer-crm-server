/**
 * Лента каталога: заглушки до ответа и отклик на касание (как b-press.js на сайте).
 * Run: TZ=UTC node --test tests/js/ice-tab-skeleton-press.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const webapp = path.join(root, 'static/webapp');
const modelPath = path.join(webapp, 'ice-tab-model.js');
const tabSource = fs.readFileSync(path.join(webapp, 'ice-tab.js'), 'utf8');
const iceHtml = fs.readFileSync(path.join(webapp, 'ice.html'), 'utf8');
const pressSource = fs.readFileSync(path.join(root, 'static/share/b-press.js'), 'utf8');

function makeElement(id) {
  const listeners = {};
  return {
    id,
    hidden: false,
    innerHTML: '',
    textContent: '',
    style: {},
    dataset: {},
    children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    querySelector: () => null,
    querySelectorAll: () => [],
    setAttribute() {},
    getAttribute: () => null,
    insertBefore() {},
    appendChild() {},
    addEventListener(type, fn) {
      (listeners[type] || (listeners[type] = [])).push(fn);
    },
  };
}

const IDS = [
  'iceListSkate', 'iceListCoach', 'iceCaption', 'iceList', 'iceShopFilters', 'iceCatalogTools',
  'iceModeSeg', 'iceSearchInput', 'iceShareBtn', 'iceNearestBtn', 'iceViewSwitch',
];

async function flush() {
  for (let i = 0; i < 80; i += 1) await Promise.resolve();
}

/** Каталог с «висящим» запросом ленты: resolve() отдаёт ответ сервера. */
function boot(arenas) {
  delete require.cache[require.resolve(modelPath)];
  const model = require(modelPath);
  const elements = {};
  IDS.forEach((id) => {
    elements[id] = makeElement(id);
  });
  let release;
  const pending = new Promise((resolve) => {
    release = resolve;
  });
  const fetchImpl = (url) => {
    const u = String(url);
    if (u.includes('/ice/cities')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ items: [{ id: 1, name: 'Минск', skate_count: 4, trainer_count: 1 }] }),
      });
    }
    if (u.includes('/ice/arenas')) {
      return pending.then(() => ({ ok: true, json: () => Promise.resolve(arenas) }));
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ items: [] }) });
  };
  const sandbox = {
    IceTabModel: model,
    GlideShareSheet: { open() {} },
    IceMap: { mount: () => ({ setListItems() {}, start: () => Promise.resolve(), refresh() {}, resize() {} }) },
    location: { search: '?city_id=1' },
    sessionStorage: { getItem: () => null, setItem() {} },
    localStorage: { getItem: () => null, setItem() {} },
    addEventListener() {},
    setTimeout: (fn, ms) => {
      if (ms > 1000) return 0;
      fn();
      return 0;
    },
    clearTimeout() {},
    scrollTo() {},
    scrollY: 0,
    navigator: {},
  };
  const ctx = vm.createContext({
    window: sandbox,
    document: {
      readyState: 'complete',
      body: makeElement('body'),
      getElementById: (id) => elements[id] || null,
      querySelectorAll: () => [],
      querySelector: () => null,
      visibilityState: 'visible',
      addEventListener() {},
    },
    fetch: fetchImpl,
    URLSearchParams,
    Promise,
    console,
  });
  vm.runInContext(tabSource, ctx);
  return flush().then(() => ({
    elements,
    respond: async () => {
      release();
      await flush();
    },
  }));
}

const ARENAS = {
  items: [
    {
      id: 3,
      name: 'ТЦ Замок',
      venue_type: 'ice',
      card: '/photos/3_card.jpg',
      thumb: '/photos/3_thumb.jpg',
      live: { kind: 'session', local_date: '2026-10-07', starts_at_local: '18:00', session_id: 11 },
    },
    { id: 4, name: 'Чижовка', venue_type: 'ice', thumb: '/photos/4_thumb.jpg' },
  ],
  total: 2,
  window: { key: 'any', label: '' },
};

function count(html, re) {
  return (String(html).match(re) || []).length;
}

describe('лента: заглушки до ответа', () => {
  it('пока лента грузится — три карточки-заглушки без текста и полоса вместо подписи', async () => {
    const { elements } = await boot(ARENAS);
    const html = elements.iceListSkate.innerHTML;
    assert.equal(count(html, /class="ice-board ice-board--skel"/g), 3);
    assert.match(html, /ice-board__photo ice-skel/);
    assert.match(html, /ice-board__name"><span class="ice-skel/);
    assert.match(html, /aria-hidden="true"/);
    assert.equal(html.replace(/<[^>]*>/g, '').trim(), '', 'в заглушке нет текста');
    assert.match(elements.iceCaption.innerHTML, /ice-skel--cap/);
  });

  it('ответ сервера заменяет заглушки настоящими карточками', async () => {
    const { elements, respond } = await boot(ARENAS);
    await respond();
    const html = elements.iceListSkate.innerHTML;
    assert.doesNotMatch(html, /ice-board--skel/);
    assert.match(html, /ТЦ Замок/);
    assert.match(html, /Чижовка/);
  });

  it('уже загруженная лента при перезапросе не мигает заглушками', () => {
    delete require.cache[require.resolve(modelPath)];
    const M = require(modelPath);
    assert.equal(
      M.listPaintMode({ intent: 'skate', loadedIntent: 'skate', items: ARENAS.items, loading: true }),
      'items'
    );
  });

  it('статичные заглушки в ice.html совпадают с boardSkeletons() — первый кадр не пустой', () => {
    const one = /'(<div class="ice-board-wrap ice-board-wrap--skel"[\s\S]*?)';\n\s*return new Array/.exec(tabSource);
    assert.ok(one, 'boardSkeletons найден');
    const markup = one[1].replace(/'\s*\+\s*'/g, '');
    const list = /<div class="ice-list" id="iceListSkate">([\s\S]*?)<\/div>\n/.exec(iceHtml);
    assert.ok(list);
    assert.equal(count(iceHtml, /class="ice-board ice-board--skel"/g), 3);
    assert.ok(iceHtml.includes(markup), 'разметка та же, что у JS-заглушки');
    assert.doesNotMatch(iceHtml, /id="iceCaption">Ищем катки…/);
  });
});

describe('лента: отклик на касание', () => {
  it('press-класс на карточках и «Позвать»', async () => {
    const { elements, respond } = await boot(ARENAS);
    await respond();
    const html = elements.iceListSkate.innerHTML;
    assert.equal(count(html, /class="ice-board ga-press /g), 2);
    assert.match(tabSource, /'<button type="button" class="ice-board__invite ga-press" data-invite-arena=/);
  });

  it('чипы и вкладки шапки нажимаются и вибрируют выбором', () => {
    assert.doesNotMatch(tabSource, /class="ice-chip" /);
    assert.doesNotMatch(tabSource, /class="hdr-folder" /);
    assert.match(tabSource, /class="hdr-folder ga-press" data-haptic="select"/);
    assert.match(tabSource, /class="ice-chip ga-press" data-haptic="select" data-when-chip=/);
    assert.match(tabSource, /class="ice-acard ga-press"/);
  });

  it('один модуль отклика с сайтом: b-press.js знает .ga-press и подключён в каталоге', () => {
    assert.match(pressSource, /PRESS_SEL\s*=\s*\n?\s*'\.ga-press,/);
    assert.match(iceHtml, /<script defer src="\/static\/share\/b-press\.js\?v=\d+"><\/script>/);
    assert.doesNotMatch(tabSource, /b-press/, 'второго обработчика нажатия в ice-tab.js нет');
  });
});
