/**
 * Публичный вход через /start: кнопка бота открывает Mini App адресом с ?startapp=<параметр>
 * (src/bot/start_entry.py). Здесь — что приложение делает с параметром из адреса, без
 * start_param от Telegram (у web_app-кнопки его нет).
 * Run: node --test tests/js/start-entry-button.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const webapp = path.resolve(__dirname, '../../static/webapp');

function load() {
  const modPath = path.join(webapp, 'glide-deeplink.js');
  delete require.cache[require.resolve(modPath)];
  return require(modPath);
}

function memStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
  };
}

/** Кнопка бота: /webapp/client-home?startapp=<sp>, Telegram есть (initData), start_param — нет. */
function openFromButton(G, sp, { storage = memStorage(), page = '/webapp/client-home' } = {}) {
  let replaced = '';
  const search = '?startapp=' + encodeURIComponent(sp);
  const loc = {
    href: 'https://app.test' + page + search + '#tgWebAppData=signed',
    pathname: page,
    search,
    hash: '#tgWebAppData=signed',
    replace(u) {
      replaced = u;
    },
  };
  const ok = G.maybeEarlyRedirect({
    location: loc,
    sessionStorage: storage,
    Telegram: { WebApp: { initData: 'signed', initDataUnsafe: {} } },
  });
  return { ok, replaced, storage };
}

describe('Кнопка бота на главную с ?startapp= открывает нужный экран', () => {
  const G = load();

  it('readStartParam берёт параметр из адреса, когда Telegram его не дал', () => {
    assert.equal(
      G.readStartParam({ location: { search: '?startapp=trainer_7_s_55', hash: '' }, Telegram: { WebApp: { initDataUnsafe: {} } } }),
      'trainer_7_s_55'
    );
  });

  it('тренер со слотом и меткой места → запись на это время, параметр едет дальше', () => {
    const r = openFromButton(G, 'trainer_7_s_55_v_p3');
    assert.equal(r.ok, true);
    assert.equal(
      r.replaced,
      '/webapp/trainers?trainer_id=7&slot_id=55&via=p3&startapp=trainer_7_s_55_v_p3#tgWebAppData=signed'
    );
  });

  it('тренер без слота с меткой места: метка не теряется на редиректе', () => {
    const r = openFromButton(G, 'trainer_7_v_p3');
    assert.equal(r.replaced, '/webapp/trainers?trainer_id=7&startapp=trainer_7_v_p3#tgWebAppData=signed');
  });

  it('каталог города с окном', () => {
    const r = openFromButton(G, 'catalog_12_skate_weekend');
    assert.equal(
      r.replaced,
      '/webapp/ice?city_id=12&intent=skate&when=weekend&startapp=catalog_12_skate_weekend#tgWebAppData=signed'
    );
  });

  it('матч (kkm_) → страница матча', () => {
    const r = openFromButton(G, 'kkm_5_k3x9abcd');
    assert.equal(r.replaced, '/webapp/client-match?id=5&c=k3x9abcd&startapp=kkm_5_k3x9abcd#tgWebAppData=signed');
  });

  it('игра: ход из напоминания (kkn_) → игра на матче', () => {
    const r = openFromButton(G, 'kkn_42_h');
    assert.equal(r.replaced, '/webapp/kto-kogo?pick=42&side=home&startapp=kkn_42_h#tgWebAppData=signed');
  });

  it('компания на лёд (company_) → экран компании', () => {
    const r = openFromButton(G, 'company_9');
    assert.equal(r.replaced, '/webapp/ice-company?s=9&startapp=company_9#tgWebAppData=signed');
  });

  it('место (arena_) не уходит из head — его открывает шелл после /client/session', () => {
    const r = openFromButton(G, 'arena_42_s_7');
    assert.equal(r.ok, false);
    assert.deepEqual(G.deepLinkTarget('arena_42_s_7'), { key: 'arena', path: 'arena?ref=42&s=7' });
  });

  it('незнакомый параметр остаётся на главной', () => {
    const r = openFromButton(G, 'something_new');
    assert.equal(r.ok, false);
    assert.equal(r.replaced, '');
  });

  it('на экране назначения второго редиректа нет — даже без sessionStorage', () => {
    const first = openFromButton(G, 'trainer_7_v_p3');
    const target = new URL(first.replaced, 'https://app.test');
    let again = '';
    const ok = G.maybeEarlyRedirect({
      location: {
        href: target.href,
        pathname: target.pathname,
        search: target.search,
        hash: target.hash,
        replace(u) {
          again = u;
        },
      },
      sessionStorage: null,
      Telegram: { WebApp: { initData: 'signed', initDataUnsafe: {} } },
    });
    assert.equal(ok, false);
    assert.equal(again, '');
  });

  it('start_param от Telegram (вход по startapp-ссылке) — адрес как раньше, без добавок', () => {
    assert.equal(
      G.carryStartParam('/webapp/trainers?trainer_id=7', 'trainer_7_v_p3', {
        Telegram: { WebApp: { initDataUnsafe: { start_param: 'trainer_7_v_p3' } } },
      }),
      '/webapp/trainers?trainer_id=7'
    );
  });
});

describe('Метка места доезжает до источника записи после редиректа', () => {
  it('booking-source на странице тренеров читает ?startapp= через GlideDeepLink', () => {
    const win = {
      location: { search: '?trainer_id=7&startapp=trainer_7_v_p3', hash: '', pathname: '/webapp/trainers' },
      sessionStorage: memStorage(),
      Telegram: { WebApp: { initDataUnsafe: {} } },
      URLSearchParams,
      URL,
    };
    win.window = win;
    vm.createContext(win);
    const dl = fs.readFileSync(path.join(webapp, 'glide-deeplink.js'), 'utf8');
    const bs = fs.readFileSync(path.join(webapp, 'booking-source.js'), 'utf8');
    // Хвост glide-deeplink.js сам пробует редирект: на целевой странице его быть не должно.
    win.location.replace = () => assert.fail('лишний редирект');
    win.document = { addEventListener() {} };
    win.addEventListener = () => {};
    vm.runInContext(dl, win);
    vm.runInContext(bs, win);
    const got = JSON.parse(JSON.stringify(win.GlideBookingSource.capture(win)));
    assert.deepEqual(got, { source: 'site_place', source_arena_id: 3 });
  });
});

describe('Страница игры читает параметр кнопки из адреса (kto-kogo.js)', () => {
  const M = require(path.join(webapp, 'kto-kogo-model.js'));
  const gameJs = fs.readFileSync(path.join(webapp, 'kto-kogo.js'), 'utf8');

  it('startParam(): Telegram, затем tgWebAppStartParam, затем ?startapp=', () => {
    assert.match(gameJs, /params\.get\('tgWebAppStartParam'\) \|\| params\.get\('startapp'\)/);
  });

  it('kks_<метка> → метка входа и POST /client/hockey/entry', () => {
    assert.equal(M.promoSrc('kks_insta', null), 'insta');
    assert.match(gameJs, /\/\^kks_\/\.test\(startParam\(\)\)/);
    assert.match(gameJs, /api\('POST', '\/client\/hockey\/entry'/);
  });

  it('kk_<КОД> / kkl_<КОД> → приглашение в лигу, kkr → итог', () => {
    assert.equal(M.inviteCode('kk_ab12'), 'AB12');
    assert.equal(M.inviteCode('kkl_ab12'), 'AB12');
    assert.equal(M.cardFrom('kkl_ab12', null), 'league');
    assert.equal(M.cardFrom('kkr', null), 'result');
  });
});
