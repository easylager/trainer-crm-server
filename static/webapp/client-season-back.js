/**
 * TASK-375: «назад» со страниц из «Ещё» при новой навигации (season_ui).
 * Чистая логика, без DOM. Оболочку не грузит: флаг читается из ClientShell.uiFlags(), если оболочка
 * уже на странице, иначе из кэша localStorage['cw_ui_flags_v1'] (тот же ключ и правила, что в оболочке).
 * Любая неопределённость = флаг выключен.
 */
(function (global) {
  'use strict';

  var UI_FLAGS_KEY = 'cw_ui_flags_v1';
  /* Тот же TTL и то же правило, что в оболочке (UI_FLAGS_TTL_MS) и в гейте kto-kogo.html. */
  var UI_FLAGS_TTL_MS = 24 * 60 * 60 * 1000;

  /** id пользователя Telegram из initDataUnsafe.user.id; пусто, если нет. */
  function telegramUserId(tg) {
    try {
      var u = tg && tg.initDataUnsafe && tg.initDataUnsafe.user;
      return u && u.id != null ? String(u.id) : '';
    } catch (e) {
      return '';
    }
  }

  /** season_ui из кэша: только если кэш этого пользователя, свежий (at моложе суток) и season_ui === true. */
  function readCachedSeasonUi(storage, uid) {
    try {
      if (!uid || !storage) return false;
      var c = JSON.parse(storage.getItem(UI_FLAGS_KEY) || 'null');
      if (!c || String(c.u) !== String(uid) || c.season_ui !== true) return false;
      var age = Date.now() - c.at;
      return typeof c.at === 'number' && age >= 0 && age < UI_FLAGS_TTL_MS;
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

  /** Есть ли куда вернуться: та же проверка, что в mini-app-client-home.js. */
  function canGoBack(env) {
    try {
      if (env.navigation && typeof env.navigation.canGoBack === 'function') return !!env.navigation.canGoBack();
    } catch (e) { /* старые WebView */ }
    try {
      return !!env.history && env.history.length > 1;
    } catch (e) {
      return false;
    }
  }

  /** Адрес client-me рядом с текущей страницей, init_data как у остальных переходов Mini App. */
  function meUrl(env) {
    var p = (env.location && env.location.pathname) || '';
    var url = (p.replace(/[^/]+$/, '') || '/webapp/') + 'client-me';
    var tg = env.Telegram && env.Telegram.WebApp;
    var initData = tg && tg.initData ? tg.initData : '';
    return initData ? url + '?init_data=' + encodeURIComponent(initData) : url;
  }

  /**
   * Выполнить «назад» при включённом флаге. Возвращает 'history' | 'me' | 'legacy';
   * при 'legacy' ничего не делает (вызывающий оставляет прежнее поведение страницы).
   */
  function goBack(env) {
    var action = backAction(isSeasonUi(env), canGoBack(env));
    if (action === 'history') env.history.back();
    else if (action === 'me') env.location.href = meUrl(env);
    return action;
  }

  var api = {
    canGoBack: canGoBack,
    meUrl: meUrl,
    goBack: goBack,
    UI_FLAGS_KEY: UI_FLAGS_KEY,
    UI_FLAGS_TTL_MS: UI_FLAGS_TTL_MS,
    telegramUserId: telegramUserId,
    readCachedSeasonUi: readCachedSeasonUi,
    isSeasonUi: isSeasonUi,
    backAction: backAction,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.ClientSeasonBack = api;
})(typeof window !== 'undefined' ? window : globalThis);
