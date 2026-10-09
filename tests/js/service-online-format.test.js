/**
 * Online format lives on the trainer offering (service), not a profile checkbox.
 */
const fs = require('fs');
const path = require('path');
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');

function read(name) {
  return fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'webapp', name), 'utf8');
}

describe('онлайн на уровне услуги', () => {
  const profileHtml = read('trainer-profile.html');
  const profileJs = read('trainer-profile-main.js');
  const onboardingHtml = read('trainer-onboarding.html');
  const onboardingJs = read('trainer-onboarding-main.js');
  const catalogJs = read('catalog-main.js');
  const bookHtml = read('book.html');

  it('профиль: нет галочки «Также онлайн», есть формат на услуге', () => {
    assert.doesNotMatch(profileHtml, /id="online_enabled"/);
    assert.doesNotMatch(profileHtml, /Также провожу занятия онлайн/);
    assert.match(profileHtml, /формат «На площадке» или «Онлайн»/);
    assert.match(profileHtml, /svcAddCustomBtn/);
    assert.match(profileJs, /Подробнее ▾/);
    assert.match(profileJs, /\/trainer\/services\/custom/);
    assert.doesNotMatch(profileJs, /Тарифы ▾/);
    assert.match(profileJs, /function getServiceIsOnline/);
    assert.match(profileJs, /function setServiceFormatOnline/);
    assert.match(profileJs, /function syncServiceOnlineDependentUi/);
    assert.match(profileJs, /svc_client_notice_wrap_/);
    assert.match(profileJs, /Online offer: keep tariffs\/prices/);
    assert.match(profileJs, /svc_group_price_wrap_/);
    assert.match(profileJs, /svc-format-seg/);
    assert.match(profileJs, /is_online: isOnlineSvc/);
    assert.match(profileJs, /function isServiceFormatLocked/);
    assert.match(profileJs, /service_ids_format_locked/);
    assert.match(profileJs, /svc-format-lock-hint/);
    assert.doesNotMatch(profileJs, /getElementById\('online_enabled'\)/);
  });

  it('онбординг: нет obOnlineEnabled, есть формат услуг в payload', () => {
    assert.doesNotMatch(onboardingHtml, /id="obOnlineEnabled"/);
    assert.match(onboardingHtml, /id="obServiceFormats"/);
    assert.match(onboardingJs, /function renderServiceFormats/);
    assert.match(onboardingJs, /custom_services:/);
    assert.match(onboardingJs, /is_online: !!state\.serviceOnlineById/);
    assert.doesNotMatch(onboardingJs, /online_enabled:\s*state\.onlineEnabled/);
    assert.match(onboardingJs, /function allSelectedOffersOnline/);
    assert.match(onboardingJs, /syncOnlineArenaWithServices/);
    assert.match(onboardingJs, /arenaMode === 'online'/);
  });

  it('каталог: блок Онлайн и фильтр услуг по слоту', () => {
    assert.match(catalogJs, /renderServiceSection\('Онлайн'/);
    assert.match(catalogJs, /function catalogServicesForSlot/);
    assert.match(catalogJs, /У тренера нет онлайн-услуг для этого слота/);
  });

  it('каталог: онлайн-услуга скрывает площадки и не шлёт arena_ids', () => {
    assert.match(catalogJs, /function catalogServiceIsOnline/);
    assert.match(catalogJs, /function catalogSelectedServiceIsOnline/);
    assert.match(catalogJs, /Online offering: drop venue chip filter/);
    assert.match(catalogJs, /Online offering: never auto-pin a venue chip/);
    assert.match(catalogJs, /!onlineSvc && state\.trainerSlotsArenaIds/);
    assert.match(catalogJs, /Онлайн-слоты/);
    assert.match(catalogJs, /Сейчас нет свободных онлайн-слотов/);
    // paintTrainerArenaSlotFilterBar early-return for online
    assert.match(
      catalogJs,
      /if \(catalogServiceIsOnline\(t, state\.serviceId\)\) \{\s*el\.innerHTML = '';\s*el\.style\.display = 'none'/
    );
  });

  it('book.html: фильтр услуг по is_online слота', () => {
    assert.match(bookHtml, /function bookServicesForSlot/);
    assert.match(bookHtml, /updateBookFormServiceUi\(effSid, .*selSlot\)/);
    assert.match(bookHtml, /У тренера нет онлайн-услуг для этого слота/);
  });

  it('book.html: онлайн-услуга не фильтрует слоты по arena_ids', () => {
    assert.match(bookHtml, /function bookServiceIsOnline/);
    assert.match(bookHtml, /!onlineSvc && Number\.isFinite\(Number\(sessionArenaId\)\)/);
  });
});
