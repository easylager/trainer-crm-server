'use strict';
/**
 * TASK-437: настоящий компонент «Нет связи / Не загрузилось · Повторить» из mini-app-telegram-chrome.js
 * (блок между маркерами miniapp-load-error:begin/end) для тестов экранов, которые грузятся в vm без chrome.
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SRC = fs.readFileSync(path.resolve(__dirname, '../../../static/webapp/mini-app-telegram-chrome.js'), 'utf8');
const BLOCK = SRC.slice(SRC.indexOf('/* miniapp-load-error:begin'), SRC.indexOf('/* miniapp-load-error:end */'));

/** document — заглушка страницы (нужны getElementById, createElement, head); navigator — { onLine }. */
function loadErrorUi(document, navigator) {
  const sandbox = { document, global: { navigator: navigator || { onLine: true } }, Object, String };
  vm.runInNewContext(
    BLOCK +
      '\nthis.ui = { LOAD_ERROR_COPY: LOAD_ERROR_COPY, isOffline: isOffline, loadErrorTitle: loadErrorTitle,' +
      ' loadErrorHtml: loadErrorHtml, loadErrorNode: loadErrorNode, renderLoadError: renderLoadError };',
    sandbox
  );
  return sandbox.ui;
}

module.exports = { BLOCK, loadErrorUi };
