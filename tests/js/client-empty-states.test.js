/**
 * TASK-096 AC-002: пустое состояние клиентского приложения обязано показывать выход.
 * Гейт, а не разовая проверка: «ничего не найдено» без кнопки не должно вернуться.
 *
 * Run: node --test tests/js/client-empty-states.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');

function read(name) {
  return fs.readFileSync(path.join(webapp, name), 'utf8');
}

/** Экраны, которые вообще могут показать пустое состояние. */
const CLIENT_SCREENS = [
  'client-home.html',
  'client-bookings.html',
  'client-requests.html',
  'client-passes.html',
  'client-passes-certificates.html',
  'client-certificates.html',
  'client-buy-pass.html',
  'catalog.html',
  'ice.html',
  'arena.html',
  'book.html',
];

/**
 * Формулировки-тупики, вычищенные в TASK-096. Каждая говорила, чего нет, и молчала о том,
 * что делать. Список точечный намеренно: широкий запрет на строку «empty» ловил бы
 * лоадеры и подписи хвоста списка и быстро отключился бы кем-нибудь как ложное срабатывание.
 */
const BANNED = [
  { file: 'ice-tab.js', text: '<div class="ice-state">Ничего не найдено</div>' },
  { file: 'client-passes.html', text: '<div class="empty">Пока нет абонементов.</div>\n' },
  { file: 'catalog-main.js', text: '<div class="empty">Нет городов</div>' },
  { file: 'catalog-main.js', text: 'В этом городе арены пока не добавлены</div>' },
];

/** Минимальный DOM: компоненту нужны только innerHTML, querySelector и addEventListener. */
function fakeElement() {
  const el = {
    innerHTML: '',
    _listeners: {},
    querySelector(sel) {
      // Кнопка существует в модели ровно тогда, когда компонент её отрисовал.
      const cls = sel.replace(/^\./, '');
      if (!el.innerHTML.includes(cls)) return null;
      return {
        addEventListener(type, fn) {
          el._listeners[cls] = fn;
        },
      };
    },
  };
  return el;
}

function loadComponent() {
  const code = read('mini-app-empty-state.js');
  const errors = [];
  const sandbox = {
    console: { error: (...a) => errors.push(a.join(' ')) },
    location: { pathname: '/webapp/client-passes.html', href: '' },
    Telegram: undefined,
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return { api: sandbox.MiniAppEmptyState, errors, sandbox };
}

function loadIceModel() {
  const p = path.join(webapp, 'ice-tab-model.js');
  delete require.cache[require.resolve(p)];
  return require(p);
}

describe('общий компонент пустого состояния (TASK-096 AC-002)', () => {
  it('рисует заголовок, подсказку и кнопку', () => {
    const { api } = loadComponent();
    const el = fakeElement();
    const ok = api.render(el, {
      title: 'Пока нет абонементов',
      hint: 'Абонемент оформляет тренер',
      ctaLabel: 'Найти тренера',
      ctaPath: 'ice?intent=coach',
    });
    assert.equal(ok, true);
    assert.match(el.innerHTML, /client-empty-state__title/);
    assert.match(el.innerHTML, /Пока нет абонементов/);
    assert.match(el.innerHTML, /client-empty-state__cta/);
    assert.match(el.innerHTML, /Найти тренера/);
  });

  it('отказывается рисовать состояние без выхода и говорит об этом в консоль', () => {
    const { api, errors } = loadComponent();
    const el = fakeElement();
    const ok = api.render(el, { title: 'Ничего не найдено' });
    assert.equal(ok, false);
    assert.equal(el.innerHTML, '', 'тупик не должен попасть на экран вообще');
    assert.equal(errors.length, 1);
    assert.match(errors[0], /ctaPath|ctaHref|onCta/);
  });

  it('без выхода не спасает даже наличие ctaLabel', () => {
    const { api } = loadComponent();
    const el = fakeElement();
    assert.equal(api.render(el, { title: 'Пусто', ctaLabel: 'Дальше' }), false);
  });

  it('onCta годится как выход не хуже ctaPath — внутриэкранное действие тоже выход', () => {
    const { api } = loadComponent();
    const el = fakeElement();
    assert.equal(
      api.render(el, { title: 'Пусто', ctaLabel: 'Повторить', onCta: () => {} }),
      true
    );
  });

  it('экранирует пользовательский текст в заголовке', () => {
    const { api } = loadComponent();
    const el = fakeElement();
    api.render(el, {
      title: 'По запросу «<img src=x onerror=alert(1)>» ничего нет',
      ctaLabel: 'Сбросить',
      onCta: () => {},
    });
    assert.ok(!el.innerHTML.includes('<img'), 'разметка из запроса не должна исполняться');
    assert.match(el.innerHTML, /&lt;img/);
  });

  it('renderOrFallback оставляет текст, если состояние собрано неправильно', () => {
    const { api } = loadComponent();
    const el = fakeElement();
    const ok = api.renderOrFallback(el, { title: 'Пусто', fallbackText: 'Пока нет абонементов.' });
    assert.equal(ok, false);
    assert.match(el.innerHTML, /Пока нет абонементов\./);
  });
});

describe('пустые состояния «Льда» несут действие (TASK-096 AC-002)', () => {
  it('каждый intent даёт кнопку', () => {
    const { formatEmptyList } = loadIceModel();
    for (const intent of ['skate', 'coach', 'group', 'unknown']) {
      const shape = formatEmptyList(intent, {});
      assert.ok(shape.action, `intent=${intent} без action`);
      assert.ok(shape.action.label, `intent=${intent} без подписи кнопки`);
      assert.ok(shape.action.kind, `intent=${intent} без вида действия`);
    }
  });

  it('фильтр по услуге предлагает снять именно фильтр, а не сменить город', () => {
    const { formatEmptyList } = loadIceModel();
    const shape = formatEmptyList('coach', { serviceName: 'Хоккей' });
    assert.equal(shape.action.kind, 'clear-service');
    assert.equal(shape.secondary.kind, 'city');
  });

  it('пустой поиск предлагает открыть весь лёд города', () => {
    const { formatEmptySearch } = loadIceModel();
    const shape = formatEmptySearch('нету такого катка');
    assert.equal(shape.action.kind, 'clear-search');
    assert.match(shape.title, /нету такого катка/);
    assert.ok(shape.body);
  });

  it('пустой запрос не выдумывает кавычки вокруг пустоты', () => {
    const { formatEmptySearch } = loadIceModel();
    assert.equal(formatEmptySearch('').title, 'Ничего не найдено');
    assert.ok(formatEmptySearch('').action);
  });
});

describe('подключение и отсутствие рецидивов (TASK-096 AC-002)', () => {
  for (const screen of CLIENT_SCREENS) {
    it(`${screen} загружает mini-app-empty-state.js`, () => {
      assert.match(read(screen), /mini-app-empty-state\.js/);
    });
  }

  for (const { file, text } of BANNED) {
    it(`${file} больше не содержит тупик: ${text.slice(0, 42)}…`, () => {
      assert.ok(!read(file).includes(text), `вернулся тупик в ${file}`);
    });
  }

  it('стили пустого состояния лежат в общем файле, а не только в оболочке', () => {
    // Экраны без таб-бара не загружают mini-app-client-shell.css, но пустые состояния им нужны.
    assert.match(read('mini-app-components.css'), /\.client-empty-state\s*\{/);
    assert.ok(!/\.client-empty-state\s*\{/.test(read('mini-app-client-shell.css')));
  });

  it('оболочка не держит вторую реализацию рендера', () => {
    const shell = read('mini-app-client-shell.js');
    assert.match(shell, /MiniAppEmptyState/);
    // Разметку теперь собирает компонент; в оболочке её быть не должно.
    assert.ok(!shell.includes('client-empty-state__title'));
  });

  it('оболочка снимает скелетон, если mini-app-empty-state.js не загрузился', () => {
    const shell = read('mini-app-client-shell.js');
    const idx = shell.indexOf('mini-app-empty-state.js is not loaded');
    assert.ok(idx >= 0, 'ожидали лог про незагруженный компонент');
    assert.match(shell.slice(idx, idx + 500), /container\.innerHTML/);
  });
});
