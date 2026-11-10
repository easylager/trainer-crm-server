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
      var suffix = code === "RUB" ? "руб." : code;
      return String(amount) + (suffix ? " " + suffix : "");
    }

    /** Одна десятая, half-up — как trainer_rating_score в Python (4,25 → 4,3). */
    function trainerRatingScore(avg) {
      var a = Number(avg);
      if (!isFinite(a) || a <= 0) return null;
      return Math.floor(a * 10 + 0.5) / 10;
    }

    function trainerRatingParts(avg, count) {
      var n = Math.floor(Number(count) || 0);
      if (n < 1) return null;
      var value = trainerRatingScore(avg);
      if (value == null) return null;
      var score = value.toFixed(1).replace(".", ",");
      return { score: score, label: countRu(n, "оценка", "оценки", "оценок") };
    }

    /** «★ 5,0 · 2 оценки» с первой оценки. Нет оценок — пустая строка. */
    function trainerRatingCaption(avg, count) {
      var parts = trainerRatingParts(avg, count);
      if (!parts) return "";
      return "★ " + parts.score + " · " + parts.label;
    }

    return {
      pluralRu: pluralRu,
      countRu: countRu,
      genitiveCountRu: genitiveCountRu,
      formatPrice: formatPrice,
      trainerRatingScore: trainerRatingScore,
      trainerRatingCaption: trainerRatingCaption,
    };
  },
);
