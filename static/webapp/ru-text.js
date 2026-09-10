/**
 * Small, context-free helpers for Russian UI text.
 * Browser: window.RuText. Node tests: module.exports.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.RuText = api;
  }
})(
  typeof window !== "undefined"
    ? window
    : typeof globalThis !== "undefined"
      ? globalThis
      : this,
  function () {
    "use strict";

    function pluralRu(number, one, few, many) {
      var absolute = Math.abs(Number(number));
      var lastTwo = absolute % 100;
      var last = absolute % 10;
      if (lastTwo >= 11 && lastTwo <= 14) return many;
      if (last === 1) return one;
      if (last >= 2 && last <= 4) return few;
      return many;
    }

    function countRu(number, one, few, many) {
      return String(number) + " " + pluralRu(number, one, few, many);
    }

    function genitiveCountRu(number, one, many) {
      return String(number) + " " + pluralRu(number, one, many, many);
    }

    function formatPrice(amount, currency) {
      var code = String(currency || "")
        .trim()
        .toUpperCase();
      var suffix = code === "RUB" ? "₽" : code;
      return String(amount) + (suffix ? " " + suffix : "");
    }

    return {
      pluralRu: pluralRu,
      countRu: countRu,
      genitiveCountRu: genitiveCountRu,
      formatPrice: formatPrice,
    };
  },
);
