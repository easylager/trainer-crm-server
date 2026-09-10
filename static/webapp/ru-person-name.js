/**
 * Russian person-name display helpers.
 * Browser: window.RuPersonName. Node tests: module.exports.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.RuPersonName = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var MALE_YA_A = {
    никита: 1,
    илья: 1,
    илия: 1,
    савва: 1,
    фома: 1,
    кузьма: 1,
    данила: 1,
    добрыня: 1,
    лука: 1,
  };
  var FEMALE_SOFT = { любовь: 1, радость: 1 };

  function velarHush(ch) {
    return "гкхжчшщ".indexOf(String(ch || "").toLowerCase()) >= 0;
  }

  function splitGluedCyrillic(s) {
    return String(s || "")
      .replace(/[\u00a0\u202f]/g, " ")
      .replace(/([а-яё])([А-ЯЁ])/g, "$1 $2")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/\s+/g, " ")
      .trim();
  }

  function titleCaseToken(token) {
    var raw = String(token || "").trim();
    if (!raw) return "";
    var m = raw.match(/^([\p{L}]+)(.*)$/u);
    if (!m) return raw;
    return (
      m[1]
        .split("-")
        .map(function (part) {
          return part
            ? part.charAt(0).toUpperCase() + part.slice(1).toLowerCase()
            : part;
        })
        .join("-") + (m[2] || "")
    );
  }

  function formatPersonName(first, last) {
    var f = splitGluedCyrillic(first);
    var l = splitGluedCyrillic(last);
    if (f && l) {
      var fl = f.toLowerCase();
      var ll = l.toLowerCase();
      if (fl === ll || fl.endsWith(" " + ll) || fl.endsWith(ll)) l = "";
    }
    var joined = [f, l].filter(Boolean).join(" ");
    return joined ? joined.split(" ").map(titleCaseToken).join(" ") : "";
  }

  function formatPersonNameFromTrainer(t) {
    var p = t && t.profile ? t.profile : t || {};
    var fromParts = formatPersonName(p.first_name, p.last_name);
    if (fromParts) return fromParts;
    return t && t.name ? formatPersonName(t.name, "") : "";
  }

  function guessGender(firstNom) {
    var n = String(firstNom || "")
      .replace(/[^\p{L}-]/gu, "")
      .toLowerCase();
    if (!n) return "m";
    if (FEMALE_SOFT[n]) return "f";
    if (MALE_YA_A[n]) return "m";
    if (
      /ия$/.test(n) ||
      /ья$/.test(n) ||
      /ая$/.test(n) ||
      /а$/.test(n) ||
      /я$/.test(n)
    )
      return "f";
    return "m";
  }

  function inflectGiven(name, gender, cas) {
    var m = String(name || "").match(/^([\p{L}]+)(.*)$/u);
    if (!m) return name;
    var n = m[1];
    var suf = m[2] || "";
    var out;
    if (/[оеэуи]$/i.test(n)) return n + suf;
    if (gender === "f") {
      if (/[иь]я$/i.test(n) || /я$/i.test(n)) out = n.slice(0, -1) + "и";
      else if (/а$/i.test(n))
        out =
          n.slice(0, -1) +
          (cas === "dat" ? "е" : velarHush(n.charAt(n.length - 2)) ? "и" : "ы");
      else if (/ь$/i.test(n)) out = n.slice(0, -1) + "и";
      else out = n;
      return titleCaseToken(out) + suf;
    }
    if (/ий$/i.test(n) && n.length > 3)
      out = n.slice(0, -2) + (cas === "dat" ? "ию" : "ия");
    else if (/ей$|ай$|ой$|й$/i.test(n))
      out = n.slice(0, -1) + (cas === "dat" ? "ю" : "я");
    else if (/ь$/i.test(n)) out = n.slice(0, -1) + (cas === "dat" ? "ю" : "я");
    else if (/а$/i.test(n))
      out =
        n.slice(0, -1) +
        (cas === "dat" ? "е" : velarHush(n.charAt(n.length - 2)) ? "и" : "ы");
    else if (/я$/i.test(n)) out = n.slice(0, -1) + (cas === "dat" ? "е" : "и");
    else out = n + (cas === "dat" ? "у" : "а");
    return titleCaseToken(out) + suf;
  }

  function inflectSurname(name, gender, cas) {
    var m = String(name || "").match(/^([\p{L}]+)(.*)$/u);
    if (!m) return name;
    var n = m[1];
    var suf = m[2] || "";
    var out = n;
    if (/енко$|ко$|ых$|их$/i.test(n)) return titleCaseToken(n) + suf;
    if (gender === "f") {
      if (/ская$|цкая$|ая$/i.test(n)) out = n.slice(0, -2) + "ой";
      else if (/(ова|ева|ёва|ина|ына)$/i.test(n)) out = n.slice(0, -1) + "ой";
      else if (/а$/i.test(n))
        out =
          n.slice(0, -1) +
          (cas === "dat" ? "е" : velarHush(n.charAt(n.length - 2)) ? "и" : "ы");
      return titleCaseToken(out) + suf;
    }
    if (/ский$|цкий$|ной$/i.test(n) || (/ой$/i.test(n) && n.length > 3))
      out = n.slice(0, -2) + (cas === "dat" ? "ому" : "ого");
    else if (/(ов|ев|ёв|ин|ын)$/i.test(n))
      out = n + (cas === "dat" ? "у" : "а");
    else if (/ь$/i.test(n)) out = n.slice(0, -1) + (cas === "dat" ? "ю" : "я");
    return titleCaseToken(out) + suf;
  }

  function inflectPersonName(first, last, cas) {
    var nom = formatPersonName(first, last);
    if (!nom) return "";
    var parts = nom.split(" ");
    var gender = guessGender(parts[0]);
    var given = inflectGiven(parts[0], gender, cas);
    if (parts.length === 1) return given;
    return (
      given +
      " " +
      parts
        .slice(1)
        .map(function (part) {
          return inflectSurname(part, gender, cas);
        })
        .join(" ")
    ).trim();
  }

  function requestHeading(first, last) {
    var nom = formatPersonName(first, last);
    if (!nom) return "";
    var gen = inflectPersonName(first, last, "gen");
    return gen && gen !== nom ? "Для " + gen : nom;
  }

  function dativeLine(first, last) {
    return (
      inflectPersonName(first, last, "dat") || formatPersonName(first, last)
    );
  }
  function accusativeLine(first, last) {
    return (
      inflectPersonName(first, last, "acc") || formatPersonName(first, last)
    );
  }

  return {
    splitGluedCyrillic: splitGluedCyrillic,
    formatPersonName: formatPersonName,
    formatPersonNameFromTrainer: formatPersonNameFromTrainer,
    guessGender: guessGender,
    inflectPersonName: inflectPersonName,
    requestHeading: requestHeading,
    dativeLine: dativeLine,
    accusativeLine: accusativeLine,
  };
});
