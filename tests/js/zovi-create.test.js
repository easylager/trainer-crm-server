/**
 * TASK-234: текст превью, день по умолчанию, проверка имени как на сервере.
 * Run: node --test tests/js/zovi-create.test.js
 */
'use strict';

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modelPath = path.resolve(__dirname, '../../static/shared/zovi-create.js');

function loadModel() {
  const resolved = require.resolve(modelPath);
  delete require.cache[resolved];
  return require(modelPath);
}

describe('превью открытки', () => {
  const { previewQuestion, previewMeta } = loadModel();

  it('имя и массовое катание', () => {
    assert.equal(previewQuestion('Лера', 'public_skate'), 'Лера, пойдёшь со мной на каток?');
  });

  it('ОХМ спрашивает про хоккей', () => {
    assert.equal(previewQuestion('Лера', 'hockey_practice'), 'Лера, пойдёшь со мной на хоккей?');
  });

  it('без имени — открытка для компании', () => {
    assert.equal(previewQuestion('', 'public_skate'), 'Пойдёшь со мной на каток?');
    assert.equal(previewQuestion('   ', 'open_ice'), 'Пойдёшь со мной на каток?');
  });

  it('ОХМ без имени всё равно про хоккей', () => {
    assert.equal(previewQuestion('', 'hockey_practice'), 'Пойдёшь со мной на хоккей?');
  });

  it('строка сеанса как в чате', () => {
    assert.equal(
      previewMeta('2026-10-17', '19:15', 'Ледовый дворец'),
      'Сб, 17 окт · 19:15 · Ледовый дворец'
    );
  });
});

describe('день по умолчанию', () => {
  const { defaultInviteDate, chooseDefaultDate, dayChips } = loadModel();

  it('ближайшая суббота, если до неё не больше 6 дней', () => {
    assert.equal(defaultInviteDate('2026-10-11'), '2026-10-17');
    assert.equal(defaultInviteDate('2026-10-12'), '2026-10-17');
    assert.equal(defaultInviteDate('2026-10-16'), '2026-10-17');
    assert.equal(defaultInviteDate('2026-10-17'), '2026-10-17');
  });

  it('дальше 6 дней — сегодня', () => {
    assert.equal(chooseDefaultDate('2026-10-11', '2026-10-18', 6), '2026-10-11');
  });

  it('в воскресенье чип «Вс» не переключается на «Сегодня»', () => {
    const { rememberedChipKey } = loadModel();
    assert.equal(rememberedChipKey('sun', '2026-10-11', '2026-10-11'), 'sun');
    assert.equal(rememberedChipKey('today', '2026-10-11', '2026-10-11'), 'today');
    assert.equal(rememberedChipKey(null, '2026-10-17', '2026-10-11'), 'sat');
  });

  it('чипы: сегодня, завтра, суббота, воскресенье, дата', () => {
    const chips = dayChips('2026-10-12');
    assert.deepEqual(
      chips.map((chip) => chip.label),
      ['Сегодня', 'Завтра', 'Сб', 'Вс', 'Дата']
    );
    assert.equal(chips[2].date, '2026-10-17');
    assert.equal(chips[3].date, '2026-10-18');
  });
});

describe('имя как на сервере', () => {
  const { validateInviteName, inviteRequestBody } = loadModel();

  it('пустое имя получателя можно, отправителя — нет', () => {
    assert.deepEqual(validateInviteName('   ', 'to_name', false), { ok: true, value: null, error: '' });
    const missing = validateInviteName('', 'from_name', true);
    assert.equal(missing.ok, false);
    assert.equal(missing.error, 'from_name: укажите имя — от 1 до 20 символов.');
  });

  it('схлопывает пробелы и приводит тире к дефису', () => {
    assert.equal(validateInviteName('  Аня   Мария  ', 'to_name', false).value, 'Аня Мария');
    assert.equal(validateInviteName('Анна–Мария', 'from_name', true).value, 'Анна-Мария');
  });

  it('длина, буквы и стоп-слова', () => {
    assert.match(validateInviteName('А'.repeat(21), 'from_name', true).error, /не длиннее 20/);
    assert.equal(validateInviteName('А'.repeat(20), 'from_name', true).ok, true);
    assert.match(validateInviteName('Макс1', 'from_name', true).error, /только буквы/);
    assert.match(validateInviteName('хуй', 'to_name', false).error, /нельзя использовать/);
    assert.equal(validateInviteName('Nazim', 'to_name', false).ok, true);
    assert.equal(validateInviteName('nazi', 'to_name', false).ok, false);
  });

  it('?from= уходит как parent_code, цена по умолчанию выключена', () => {
    const built = inviteRequestBody({
      toName: '',
      fromName: 'Макс',
      sessionId: 15,
      showPrice: false,
      parentCode: 'abcd2345',
    });
    assert.equal(built.ok, true);
    assert.deepEqual(built.body, {
      session_id: 15,
      to_name: null,
      from_name: 'Макс',
      show_price: false,
      parent_code: 'abcd2345',
    });
  });
});

describe('воронка (TASK-237): токен устройства, канал ссылки, вход', () => {
  const { ensureDeviceToken, linkWithSrc, inviteRequestBody, readQuery } = loadModel();

  function memoryStorage(initial) {
    const data = new Map(Object.entries(initial || {}));
    return {
      getItem: (k) => (data.has(k) ? data.get(k) : null),
      setItem: (k, v) => data.set(k, v),
      data,
    };
  }

  it('берёт zovi_device, который уже есть (его пишет открытка)', () => {
    const store = memoryStorage({ zovi_device: '0123456789abcdef0123456789abcdef' });
    assert.equal(ensureDeviceToken(store), '0123456789abcdef0123456789abcdef');
  });

  it('создаёт 32 hex и кладёт в то же поле', () => {
    const store = memoryStorage();
    const token = ensureDeviceToken(store, () => 171);
    assert.equal(token, 'ab'.repeat(16));
    assert.equal(store.data.get('zovi_device'), token);
  });

  it('битое значение заменяет, а без хранилища токен всё равно есть', () => {
    assert.match(ensureDeviceToken(memoryStorage({ zovi_device: 'x' })), /^[0-9a-f]{32}$/);
    assert.match(ensureDeviceToken(null), /^[0-9a-f]{32}$/);
  });

  it('ссылка получает src канала, чужие части адреса не трогает', () => {
    assert.equal(linkWithSrc('https://x.by/zovi/abcd2345', 'sys'), 'https://x.by/zovi/abcd2345?src=sys');
    assert.equal(linkWithSrc('https://x.by/zovi/abcd2345?a=1', 'copy'), 'https://x.by/zovi/abcd2345?a=1&src=copy');
    assert.equal(linkWithSrc('https://x.by/zovi/abcd2345', ''), 'https://x.by/zovi/abcd2345');
  });

  it('тело создания несёт токен, src и via только когда они есть', () => {
    const base = { toName: '', fromName: 'Макс', sessionId: 15, showPrice: false, parentCode: null };
    assert.deepEqual(Object.keys(inviteRequestBody(base).body).sort(), [
      'from_name', 'parent_code', 'session_id', 'show_price', 'to_name',
    ]);
    const full = inviteRequestBody({ ...base, deviceToken: 'a'.repeat(32), src: 'sys', via: 'arena_card' }).body;
    assert.equal(full.device_token, 'a'.repeat(32));
    assert.equal(full.src, 'sys');
    assert.equal(full.via, 'arena_card');
  });

  it('via и src читаются из адреса, мусор отбрасывается', () => {
    assert.equal(readQuery('?via=arena_card&src=sys').via, 'arena_card');
    assert.equal(readQuery('?via=arena_card&src=sys').src, 'sys');
    assert.equal(readQuery('?via=<b>&src=1').via, null);
    assert.equal(readQuery('').src, null);
  });
});

describe('вход из каталога', () => {
  const { inviteRequestHeaders, readTelegramInitData, openedWithVia, returnToSchedule } = loadModel();

  it('креденшл из sessionStorage уходит заголовком, пустой — нет', () => {
    assert.deepEqual(inviteRequestHeaders(''), {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    });
    assert.equal(inviteRequestHeaders('  signed  ')['X-Telegram-Init-Data'], 'signed');
    assert.equal(readTelegramInitData({ getItem: () => 'init' }), 'init');
    assert.equal(readTelegramInitData(null), '');
    assert.equal(
      readTelegramInitData({
        getItem() {
          throw new Error('blocked');
        },
      }),
      ''
    );
  });

  it('via включает возврат: назад, если история есть, иначе на главную', () => {
    assert.equal(openedWithVia(''), false);
    assert.equal(openedWithVia('?s=15'), false);
    assert.equal(openedWithVia('?s=15&via=place'), true);
    assert.equal(openedWithVia('?via=%20'), false);

    const backed = { history: { length: 2, back() { this.went = true; } }, location: { href: '' } };
    assert.equal(returnToSchedule(backed), 'back');
    assert.equal(backed.history.went, true);
    assert.equal(backed.location.href, '');

    const fresh = { history: { length: 1, back() { throw new Error('no'); } }, location: { href: '' } };
    assert.equal(returnToSchedule(fresh), 'home');
    assert.equal(fresh.location.href, '/');
  });
});
