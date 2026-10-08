/**
 * Trainer profile venues block: section title «Где занимаюсь» + combobox picker + default venue.
 */
const fs = require('fs');
const path = require('path');
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

function read(name) {
  return fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'webapp', name), 'utf8');
}

describe('профиль тренера: раздел «Где занимаюсь»', () => {
  const html = read('trainer-profile.html');
  const src = read('trainer-profile-main.js');
  const css = read('mini-app-trainer-profile.css');

  it('чип и заголовок секции — «Где занимаюсь», не «Арены»', () => {
    assert.match(html, /data-profile-scroll="profileNavArenas">Где занимаюсь</);
    assert.match(html, /profile-collapse__title">Где занимаюсь</);
    assert.doesNotMatch(
      html,
      /data-profile-scroll="profileNavArenas">Арены</,
      'nav chip must not say Арены'
    );
    assert.doesNotMatch(html, /profile-collapse__title">Арены</);
  });

  it('стат и checklist говорят «площадки»', () => {
    assert.match(src, /stat2\.textContent = 'Площадки: ' \+ arenasCount/);
    assert.match(src, /subtitle: 'Выберите площадки из списка/);
    assert.match(src, /arenas: 'площадки'/);
  });

  it('площадка по умолчанию — label + select + hint, без старой фразы', () => {
    const start = src.indexOf('function renderArenaDefaultLine');
    assert.ok(start > 0);
    const body = src.slice(start, src.indexOf('function updateArenaChips'));
    assert.match(body, /Площадка по умолчанию/);
    assert.match(body, /arena-default-field/);
    assert.match(body, /Подставится, если при создании слота площадку не выбрать/);
    assert.doesNotMatch(body, /Если при создании слота не выбрать площадку/);
    assert.doesNotMatch(body, /Точном времени/);
    assert.match(css, /\.arena-default-field__/);
    assert.doesNotMatch(css, /\.arena-default-line\s*\{/);
  });

  it('выбранные площадки — плоские строки без свитчей витрины', () => {
    const start = src.indexOf('function updateArenaChips');
    const body = src.slice(start, src.indexOf('function arenaThumbUrl'));
    assert.doesNotMatch(body, /arenaRowOpenId|data-arena-toggle|arena-row__panel|arena-row__chev/);
    assert.doesNotMatch(body, /data-arena-public|arena-sw|arenaIsPublic/);
    assert.match(body, /data-arena-remove/);
    assert.doesNotMatch(src, /var arenaRowOpenId/);
    assert.doesNotMatch(css, /\.arena-sw\s*\{/);
  });

  it('площадку с записями нельзя убрать — lock по arena_ids_locked', () => {
    assert.match(src, /function lockedArenaIds/);
    assert.match(src, /function isArenaLockedByBookings/);
    assert.match(src, /function applyTrainerFromApi/);
    assert.match(src, /arena_ids_locked/);
    assert.match(src, /есть записи или слоты сейчас или в будущем/);
    const start = src.indexOf('function updateArenaChips');
    const body = src.slice(start, src.indexOf('function arenaThumbUrl'));
    assert.match(body, /arena-row--locked/);
    assert.match(body, /disabled/);
    assert.match(css, /\.arena-row__remove:disabled/);
  });

  it('пикер — комбобокс как в онбординге: список сразу + мини-фото', () => {
    assert.match(html, /class="arena-combo"/);
    assert.match(html, /Площадка из списка/);
    assert.match(html, /arena-combo__list/);
    assert.match(src, /function buildArenaComboThumb/);
    assert.match(src, /function arenasForProfilePicker/);
    assert.match(src, /ARENA_BROWSE_CAP/);
    assert.match(src, /thumb_url/);
    assert.match(src, /Выберите из списка ниже/);
    assert.doesNotMatch(src, /Начните вводить название или адрес/);
    assert.match(css, /\.arena-combo__thumb/);
    assert.match(css, /\.arena-combo__row/);
  });

  it('online_enabled рядом с площадками; exclusive online — только без арен', () => {
    assert.match(src, /Также провожу занятия онлайн|online_enabled/);
    assert.doesNotMatch(src, /В «Лёд»/);
    assert.match(src, /mode: 'clear'|mode === 'clear'|"clear"|'clear'/);
    assert.match(src, /Убрать режим «только онлайн»/);
    assert.match(src, /Только онлайн — площадок в профиле нет/);
    const entry = src.slice(
      src.indexOf('function renderArenaAddEntryPoint'),
      src.indexOf('function submitArenaWorkFormat')
    );
    assert.match(entry, /hasArenas/);
    assert.match(entry, /Только онлайн \(без площадки\)/);
    assert.match(entry, /online_enabled/);
  });
});
