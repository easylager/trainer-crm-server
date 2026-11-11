/**
 * TASK-375: «назад» со страниц из «Ещё» при новой навигации (season_ui).
 * Чистая логика, без DOM. Оболочку не грузит: флаг читается из ClientShell.uiFlags(), если оболочка
 * уже на странице, иначе из кэша localStorage['cw_ui_flags_v1'] (тот же ключ и правила, что в оболочке).
 * Любая неопределённость = флаг выключен.
 */
(function (global) {
  'use strict';

  var UI_FLAGS_KEY = 'cw_ui_flags_v1';

  /** id пользователя Telegram из initDataUnsafe.user.id; пусто, если нет. */
  function telegramUserId(tg) {
    try {
      var u = tg && tg.initDataUnsafe && tg.initDataUnsafe.user;
      return u && u.id != null ? String(u.id) : '';
    } catch (e) {
      return '';
    }
  }

  /** season_ui из кэша: только если кэш чей-то этого пользователя и season_ui === true. */
  function readCachedSeasonUi(storage, uid) {
    try {
      if (!uid || !storage) return false;
      var c = JSON.parse(storage.getItem(UI_FLAGS_KEY) || 'null');
      return !!c && String(c.u) === String(uid) && c.season_ui === true;
    } catch (e) {
      return false;
    }
  }

  /** Флаг по окружению: оболочка, если загружена, иначе кэш. */
  function isSeasonUi(env) {
    try {
      var shell = env && env.ClientShell;
      if (shell && typeof shell.uiFlags === 'function') return shell.uiFlags().season_ui === true;
    } catch (e) { /* падаем на кэш */ }
    try {
      return readCachedSeasonUi(env && env.localStorage, telegramUserId(env && env.Telegram && env.Telegram.WebApp));
    } catch (e) {
      return false;
    }
  }

  /**
   * Что делать по «назад».
   * 'legacy'  — флаг выключен: страница ведёт себя как раньше, хелпер ничего не решает;
   * 'history' — флаг включён, есть история: history.back();
   * 'me'      — флаг включён, истории нет: перейти на client-me.
   */
  function backAction(seasonOn, canGoBack) {
    if (seasonOn !== true) return 'legacy';
    return canGoBack ? 'history' : 'me';
  }

  var api = {
    UI_FLAGS_KEY: UI_FLAGS_KEY,
    telegramUserId: telegramUserId,
    readCachedSeasonUi: readCachedSeasonUi,
    isSeasonUi: isSeasonUi,
    backAction: backAction,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.ClientSeasonBack = api;
})(typeof window !== 'undefined' ? window : globalThis);
