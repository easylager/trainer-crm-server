/**
 * Вкладка «Я» (TASK-370): разводка страницы и поведение контроллера на поддельном DOM —
 * тёплый кэш, ошибка, шторки, перерисовка только изменённого блока.
 * Run: node --test tests/js/client-me-page.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.resolve(__dirname, '../..');
const webapp = path.join(ROOT, 'static/webapp');
const html = fs.readFileSync(path.join(webapp, 'client-me.html'), 'utf8');
const pageSrc = fs.readFileSync(path.join(webapp, 'client-me.js'), 'utf8');
const ruText = fs.readFileSync(path.join(webapp, 'ru-text.js'), 'utf8');
const appPy = fs.readFileSync(path.join(ROOT, 'src/api/app.py'), 'utf8');

function scripts() {
  const out = [];
  const re = /<script([^>]*)><\/script>/g;
  let m;
  while ((m = re.exec(html))) {
    const src = (/src="([^"?]+)/.exec(m[1]) || [])[1];
    if (src) out.push({ src: src.split('/').pop(), defer: /\bdefer\b/.test(m[1]), async: /\basync\b/.test(m[1]) });
  }
  return out;
}

describe('разметка и маршрут', () => {
  it('<body data-client-shell="tabs">, оболочка синхронно после SDK и темы', () => {
    assert.match(html, /<body class="cm-body" data-client-shell="tabs">/);
    const list = scripts();
    const at = (name) => list.findIndex((s) => s.src === name);
    const shell = list[at('mini-app-client-shell.js')];
    assert.ok(shell && !shell.defer && !shell.async);
    assert.ok(at('telegram-web-app.js') < at('client-mini-app-theme.js'));
    assert.ok(at('client-mini-app-theme.js') < at('mini-app-client-shell.js'));
  });

  it('шрифты, токены и компоненты — как на главной; preload Dela Gothic и Golos с __FONT_V__', () => {
    assert.match(html, /dela-gothic-one-cyr-lat\.woff2\?v=__FONT_V__/);
    assert.match(html, /golos-text-cyr-lat\.woff2\?v=__FONT_V__/);
    for (const css of ['glide-public-fonts.css', 'glide-tokens.css', 'glide-components.css', 'client-sheet.css', 'client-me.css']) {
      assert.ok(html.includes(css), css);
    }
  });

  it('шторки: база раньше шторок, шторки раньше client-me.js, без async/defer', () => {
    const list = scripts();
    const order = [
      'ru-text.js', 'client-sheet.js', 'client-club-sheet.js', 'client-name-sheet.js',
      'minsk-time.js', 'opening-hours.js', 'glide-copy.js', 'public-display-model.js', 'ice-tab-model.js',
      'write-access.js', 'bell-follow.js', 'client-rink-sheet.js', 'client-me.js',
    ];
    const idx = order.map((name) => list.findIndex((s) => s.src === name));
    idx.forEach((i, k) => assert.ok(i >= 0, order[k] + ' подключён'));
    assert.deepEqual(idx.slice().sort((a, b) => a - b), idx);
    for (const name of order) {
      const s = list.find((x) => x.src === name);
      assert.ok(!s.defer && !s.async, name + ' без defer/async');
    }
    assert.ok(list.findIndex((s) => s.src === 'client-profile-switcher.js') < list.findIndex((s) => s.src === 'client-me.js'));
  });

  it('маршрут /webapp/client-me — как у главной: __FONT_V__ и no-cache; ассеты отдаются по /webapp/', () => {
    const block = appPy.slice(appPy.indexOf('@app.get("/webapp/client-me")'));
    const route = block.slice(0, block.indexOf('\n\n\n'));
    assert.match(route, /client-me\.html/);
    assert.match(route, /FONT_V_PLACEHOLDER, PUBLIC_FONTS_ASSET_VERSION/);
    assert.match(route, /stamp_html/);
    assert.match(route, /_WEBAPP_NO_CACHE_HEADERS/);
    assert.ok(appPy.includes('"/webapp/client-me.js"'));
    assert.ok(appPy.includes('"/webapp/client-me.css"'));
  });
});

/* ── Поддельный DOM ─────────────────────────────────────────────────── */

function makeNode(markup) {
  return {
    markup,
    replaced: null,
    replaceWith(next) {
      this.replaced = next;
    },
    remove() {},
    after() {},
  };
}

function boot(opts) {
  const o = opts || {};
  const calls = { fetch: [], nav: [], name: [], club: [], rink: [], haptic: 0, replaced: [] };
  const listeners = {};
  const session = new Map();
  if (o.warm !== undefined) session.set('cw_me_warm_v1', typeof o.warm === 'string' ? o.warm : JSON.stringify(o.warm));
  let responses = (o.responses || []).slice();
  const blocks = {};

  const mount = {
    innerHTML: '<div class="cm-skel cm-skel--head"></div>',
    attrs: { 'aria-busy': 'true' },
    setAttribute(k, v) {
      this.attrs[k] = v;
    },
    removeAttribute(k) {
      delete this.attrs[k];
    },
    addEventListener(t, fn) {
      (listeners['mount:' + t] = listeners['mount:' + t] || []).push(fn);
    },
    contains: () => true,
    querySelector(sel) {
      const m = /data-block="(\w+)"/.exec(sel);
      if (!m) return null;
      if (!blocks[m[1]]) {
        blocks[m[1]] = makeNode('old:' + m[1]);
        const node = blocks[m[1]];
        node.replaceWith = (next) => calls.replaced.push([m[1], next.markup]);
      }
      return blocks[m[1]];
    },
    prepend() {},
  };

  const document = {
    getElementById: (id) => (id === 'meRoot' ? mount : null),
    createElement() {
      return {
        set innerHTML(v) {
          this._h = v;
        },
        get firstElementChild() {
          return this._h ? makeNode(this._h) : null;
        },
      };
    },
    fonts: o.fonts || null,
  };

  const win = {
    document,
    location: { search: '', href: '' },
    sessionStorage: {
      getItem: (k) => (session.has(k) ? session.get(k) : null),
      setItem: (k, v) => session.set(k, v),
    },
    getComputedStyle: () => ({ lineHeight: '26.4px' }),
    Telegram: { WebApp: { initData: 'a=1' } },
    ClientShell: {
      uiFlags: () => ({ season_ui: true, bookings_tab: !!o.bookingsTab }),
      navigate: (p) => calls.nav.push(p),
      hapticSelection: () => {
        calls.haptic += 1;
      },
    },
    ClientProfileSwitcher: {
      getStoredActiveProfileId: () => (o.activeId === undefined ? null : o.activeId),
      getCachedDefaultProfileId: () => null,
      init: () => Promise.resolve(),
    },
    ClientNameSheet: { open: (a) => calls.name.push(a) },
    ClientClubSheet: { open: (a) => calls.club.push(a) },
    addEventListener(t, fn) {
      (listeners[t] = listeners[t] || []).push(fn);
    },
    fetch(url, init) {
      calls.fetch.push({ url, headers: init.headers });
      const next = responses.length ? responses.shift() : { ok: false, status: 500 };
      const res = { ok: next.ok !== false, status: next.status || 200, json: () => Promise.resolve(next.body) };
      return next.delayMs ? new Promise((r) => setTimeout(() => r(res), next.delayMs)) : Promise.resolve(res);
    },
    Promise,
    setTimeout,
    Intl,
    Date,
    JSON,
    URLSearchParams,
  };
  if (o.rinkSheet) win.ClientRinkSheet = { open: (a) => calls.rink.push(a) };
  win.window = win;
  const ctx = vm.createContext(win);
  vm.runInContext(ruText, ctx);
  vm.runInContext(pageSrc.replace("typeof window !== 'undefined' ? window : globalThis", 'window'), ctx);

  function click(attrs) {
    const target = { getAttribute: (k) => (k in attrs ? attrs[k] : null) };
    const ev = { target: { closest: () => target }, prevented: false, preventDefault() { this.prevented = true; } };
    (listeners['mount:click'] || []).forEach((fn) => fn(ev));
    return ev;
  }
  function setResponses(list) {
    responses = list.slice();
  }
  return { mount, calls, session, click, setResponses, win };
}

const settle = () => new Promise((r) => setTimeout(r, 0));

function data(over) {
  return Object.assign(
    {
      name: 'Максим',
      initial: 'М',
      city: 'Минск',
      club: null,
      home_arena: null,
      stats: { trainings: null, streak_weeks: null, kk_points: null, kk_place: null },
      rows: {
        bookings: { next_starts_at: null },
        passes: null,
        saved: null,
        family: { people: [{ profile_id: 15, name: 'Максим', is_you: true, active: true }] },
        requests: null,
      },
      profile_name: null,
    },
    over || {}
  );
}

describe('загрузка', () => {
  it('свежий кэш — рисует сразу, до ответа сервера; потом обновляет и пишет кэш', async () => {
    const t = boot({ warm: { ts: Date.now() - 5000, data: data({ name: 'Из кэша' }) }, responses: [{ body: data(), delayMs: 30 }] });
    await settle();
    assert.match(t.mount.innerHTML, /Из кэша/);
    assert.equal(t.mount.attrs['aria-busy'], undefined);
    assert.equal(t.calls.replaced.length, 0);
    await new Promise((r) => setTimeout(r, 60));
    assert.deepEqual(t.calls.replaced.map((r) => r[0]), ['header']);
    assert.match(JSON.parse(t.session.get('cw_me_warm_v1')).data.name, /Максим/);
  });

  it('кэш старше 60 с или старой схемы — скелетон, без исключения', () => {
    const stale = boot({ warm: { ts: Date.now() - 61000, data: data() } });
    assert.match(stale.mount.innerHTML, /cm-skel/);
    const old = data();
    old.rows.family = { profiles: 1 };
    const oldSchema = boot({ warm: { ts: Date.now(), data: old } });
    assert.match(oldSchema.mount.innerHTML, /cm-skel/);
    const broken = boot({ warm: '{oops' });
    assert.match(broken.mount.innerHTML, /cm-skel/);
  });

  it('ошибка запроса → «Не загрузилось» и «Повторить»; повтор снова спрашивает сервер', async () => {
    const t = boot({ responses: [{ ok: false, status: 500 }] });
    await settle();
    await settle();
    assert.match(t.mount.innerHTML, /Не загрузилось/);
    assert.match(t.mount.innerHTML, /Повторить/);
    t.setResponses([{ body: data() }]);
    t.click({ 'data-act': 'retry' });
    assert.match(t.mount.innerHTML, /cm-skel/);
    await settle();
    await settle();
    assert.match(t.mount.innerHTML, /Максим/);
    assert.equal(t.calls.fetch.length, 2);
  });

  it('ответ без rows.family.people — тоже «Не загрузилось», не пустой экран', async () => {
    const bad = data();
    bad.rows.family = { profiles: 1 };
    const t = boot({ responses: [{ body: bad }] });
    await settle();
    await settle();
    assert.match(t.mount.innerHTML, /Не загрузилось/);
  });

  it('выбранный на главной человек уходит в X-Profile-Id', async () => {
    const t = boot({ activeId: 16, responses: [{ body: data() }] });
    await settle();
    assert.equal(t.calls.fetch[0].headers['X-Profile-Id'], '16');
    assert.equal(t.calls.fetch[0].headers['X-Telegram-Init-Data'], 'a=1');
  });

  it('«Мои записи» нет на экране, если в баре вкладка «Записи»', async () => {
    const t = boot({ bookingsTab: true, responses: [{ body: data() }] });
    await settle();
    await settle();
    assert.doesNotMatch(t.mount.innerHTML, /Мои записи/);
    const u = boot({ responses: [{ body: data() }] });
    await settle();
    await settle();
    assert.match(u.mount.innerHTML, /Мои записи/);
  });
});

describe('TASK-381: фокус с клавиатуры', () => {
  const css = fs.readFileSync(path.join(webapp, 'client-me.css'), 'utf8');
  const tokens = fs.readFileSync(path.join(ROOT, 'static/shared/glide-tokens.css'), 'utf8');
  it('кнопки (карандаш катка, «Изменить», плитки) и ссылки-строки в .cm получают видимый контур токеном обеих тем', () => {
    assert.match(css, /\.cm a:focus-visible,\s*\.cm button:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--g-accent-ink\)/);
    assert.doesNotMatch(css, /outline:\s*(none|0)/);
    assert.match(html, /id="meRoot"[^>]*class="cm|class="cm[^"]*"[^>]*id="meRoot"/);
    assert.match(tokens, /--g-accent-ink:\s*var\(--glide-700\)/);
    assert.match(tokens, /body\.tg-dark \{[\s\S]*?--g-accent-ink:\s*#7FD7D8/);
  });
});

describe('TASK-381: гонка сохранения и порядок отрисовки', () => {
  async function ready() {
    const t = boot({ responses: [{ body: data() }] });
    await settle();
    await settle();
    return t;
  }

  it('сохранение, пока запрос уже летит, перезапрашивает ПОСЛЕ него, а не отдаёт старый ответ', async () => {
    const t = await ready();
    assert.equal(t.calls.fetch.length, 1);
    t.click({ 'data-act': 'name' });
    t.setResponses([{ body: data({ name: 'Старое' }), delayMs: 40 }, { body: data({ name: 'Новое' }) }]);
    t.calls.name[0].onSaved('A');
    await settle();
    assert.equal(t.calls.fetch.length, 2, 'первый перезапрос летит');
    t.calls.name[0].onSaved('B');
    t.calls.name[0].onSaved('C');
    await settle();
    assert.equal(t.calls.fetch.length, 2, 'пока летит — новый запрос не стартует');
    await new Promise((r) => setTimeout(r, 80));
    await settle();
    await settle();
    assert.equal(t.calls.fetch.length, 3, 'ровно один повторный запрос, после ответа первого');
    assert.match(t.calls.replaced.map((r) => r[1]).join(''), /Новое/);
  });

  it('тёплый кэш не рисуется поверх «Не загрузилось», если шрифты пришли позже ошибки', async () => {
    const warm = { ts: Date.now(), data: data({ name: 'Кэш' }) };
    const fonts = { load: () => new Promise((r) => setTimeout(r, 40)) };
    const t = boot({ warm, fonts, responses: [{ ok: false, status: 500 }] });
    await new Promise((r) => setTimeout(r, 100));
    await settle();
    assert.match(t.mount.innerHTML, /Не загрузилось/);
    assert.doesNotMatch(t.mount.innerHTML, /Кэш/);
  });
});

describe('тапы и шторки', () => {
  async function ready(over, opts) {
    const t = boot(Object.assign({ responses: [{ body: data(over) }] }, opts));
    await settle();
    await settle();
    return t;
  }

  it('строка ведёт на свою страницу через ClientShell.navigate', async () => {
    const t = await ready();
    const ev = t.click({ 'data-nav': 'client-family-access' });
    assert.ok(ev.prevented);
    assert.deepEqual(t.calls.nav, ['client-family-access']);
  });

  it('«Изменить» → шторка имени с текущим именем; сохранение → перезапрос и перерисовка только шапки', async () => {
    const t = await ready();
    t.click({ 'data-act': 'name' });
    assert.equal(t.calls.haptic, 1);
    assert.equal(t.calls.name[0].current, 'Максим');
    t.setResponses([{ body: data({ name: 'Макс' }) }]);
    t.calls.name[0].onSaved('Макс');
    await settle();
    await settle();
    assert.equal(t.calls.fetch.length, 2);
    assert.deepEqual(t.calls.replaced.map((r) => r[0]), ['header']);
    assert.match(t.calls.replaced[0][1], /Макс/);
  });

  it('«Болею за» → шторка клуба с текущим клубом; сохранение перерисовывает шапку и плитки', async () => {
    const club = { name: 'Шахтер', short: 'Ш', color: '#E07000', logo: null, label_ink: '#0D1B26', next_match: null };
    const t = await ready({ club });
    t.click({ 'data-act': 'club' });
    assert.equal(t.calls.club[0].current, 'Шахтер');
    t.setResponses([{ body: data({ club: null }) }]);
    t.calls.club[0].onSaved(null);
    await settle();
    await settle();
    assert.deepEqual(t.calls.replaced.map((r) => r[0]).sort(), ['header', 'tiles']);
  });

  it('карандаш катка → ClientRinkSheet с currentId; модуля нет — «Поиск», без исключения', async () => {
    const home = { id: 12, name: 'Лёд', href: '/webapp/arena?id=12', sessions_left_today: 0, tomorrow_first: null, subscribed: false };
    const t = await ready({ home_arena: home }, { rinkSheet: true });
    t.click({ 'data-act': 'rink' });
    assert.equal(t.calls.rink[0].currentId, 12);
    const u = await ready({ home_arena: home });
    assert.doesNotThrow(() => u.click({ 'data-act': 'rink' }));
    assert.deepEqual(u.calls.nav, ['ice']);
  });
});
