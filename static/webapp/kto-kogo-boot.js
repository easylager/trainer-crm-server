(function () {
  'use strict';
  function go() {
    window.KK.boot();
  }
  var WA = window.GlideWriteAccess;
  var tg = window.Telegram && window.Telegram.WebApp;
  if (WA && typeof WA.entryGate === 'function') {
    WA.entryGate(tg).then(go, go);
  } else {
    go();
  }
})();
