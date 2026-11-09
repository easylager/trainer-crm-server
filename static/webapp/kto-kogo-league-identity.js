/**
 * «Кто кого», лицо лиги (TASK-361): картинка и строка «На что играем». Чистая модель без DOM и сети —
 * её проверяет tests/js/kto-kogo-league-identity.test.js; экраны (kto-kogo-leagues.js) только рисуют.
 * Правила те же, что на сервере (src/application/hockey_leagues.py, hockey_league_images.py): сервер перепроверит.
 */
(function (global) {
  'use strict';

  var STAKE_MAX = 80;
  var NAME_MAX = 28;
  var IMAGE_MAX_BYTES = 5 * 1024 * 1024;
  var IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
  var LABEL = 'На что играем';

  /** Пробелы и переводы строк сжаты, края обрезаны — как `clean_stake` на сервере. */
  function cleanStake(value) {
    return String(value == null ? '' : value).replace(/[​‎‏‪-‮⁠-⁤﻿]/g, '').split(/\s+/).filter(Boolean).join(' ');
  }

  function stakeError(value) {
    return cleanStake(value).length > STAKE_MAX ? 'Строка до ' + STAKE_MAX + ' символов' : '';
  }

  /** «На что играем: Пицца» одной строкой разбора: подпись и текст отдельно, чтобы подпись можно было приглушить. */
  function stakeParts(league) {
    var text = cleanStake(league && league.stake_text);
    return text ? { label: LABEL, text: text } : null;
  }

  /** Только свои адреса и https: ничего, что браузер выполнит как скрипт, в `src` не попадает. */
  function safeSrc(url) {
    return typeof url === 'string' && /^(https?:\/\/|\/(?!\/))/i.test(url) ? url : null;
  }

  /** Картинка лиги для показа: основной и маленький кадр; нет картинки — `null` (прежний вид). */
  function faceOf(league) {
    var full = safeSrc(league && league.image_url);
    var thumb = safeSrc(league && league.image_thumb_url) || full;
    return full || thumb ? { src: full || thumb, thumb: thumb || full } : null;
  }

  /** Файл из галереи: тип и вес проверяем до отправки, чтобы не гонять пять мегабайт зря. Пустая строка — годится. */
  function imageError(file) {
    if (!file) return '';
    if (IMAGE_TYPES.indexOf(String(file.type || '').toLowerCase()) < 0) return 'Подходят только JPEG, PNG и WEBP';
    if (file.size > IMAGE_MAX_BYTES) return 'Фото больше 5 МБ. Выбери поменьше';
    return '';
  }

  /** Ошибка поля новой лиги, которое не про команды и время: строка «На что играем» и картинка. */
  function identityError(form) {
    return stakeError(form.stake) || imageError(form.image);
  }

  /** Что поменять в лиге: тело PATCH, нужна ли загрузка/удаление картинки. Нечего менять — `changed: false`. */
  function editPlan(league, draft) {
    var patch = {};
    var name = String(draft.name == null ? '' : draft.name).split(/\s+/).filter(Boolean).join(' ');
    var stake = cleanStake(draft.stake);
    if (name !== String(league.name || '')) patch.name = name;
    if (stake !== cleanStake(league.stake_text)) patch.stake_text = stake;
    var hasPatch = Object.keys(patch).length > 0;
    var image = draft.file ? 'upload' : draft.removeImage && faceOf(league) ? 'remove' : null;
    return { patch: hasPatch ? patch : null, image: image, changed: hasPatch || image !== null };
  }

  function editError(draft) {
    var name = String(draft.name == null ? '' : draft.name).split(/\s+/).filter(Boolean).join(' ');
    if (!name) return 'Назови лигу';
    if (name.length > NAME_MAX) return 'Название до ' + NAME_MAX + ' символов';
    return stakeError(draft.stake) || imageError(draft.file);
  }

  var api = {
    STAKE_MAX: STAKE_MAX,
    NAME_MAX: NAME_MAX,
    IMAGE_MAX_BYTES: IMAGE_MAX_BYTES,
    IMAGE_TYPES: IMAGE_TYPES,
    LABEL: LABEL,
    cleanStake: cleanStake,
    stakeError: stakeError,
    stakeParts: stakeParts,
    safeSrc: safeSrc,
    faceOf: faceOf,
    imageError: imageError,
    identityError: identityError,
    editPlan: editPlan,
    editError: editError,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.KtoKogoIdentity = api;
})(typeof window !== 'undefined' ? window : globalThis);
