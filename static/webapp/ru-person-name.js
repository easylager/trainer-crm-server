/**
 * Russian person-name display: split glued parts, title-case, genitive/dative.
 * Browser: window.RuPersonName. Node tests: module.exports.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.RuPersonName = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

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
    return 'гкхжчшщ'.indexOf(String(ch || '').toLowerCase()) >= 0;
  }

  function splitGluedCyrillic(s) {
    return String(s || '')
      .replace(/[\u00a0\u202f]/g, ' ')
      .replace(/([а-яё])([А-ЯЁ])/g, '$1 $2')
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function titleCaseToken(token) {
    var raw = String(token || '').trim();
    if (!raw) return '';
    var m = raw.match(/^([\p{L}]+)(.*)$/u);
    if (!m) return raw;
    var letters = m[1];
    var rest = m[2] || '';
    var bits = letters.split('-').map(function (p) {
      if (!p) return p;
      return p.charAt(0).toUpperCase() + p.slice(1).toLowerCase();
    });
    return bits.join('-') + rest;
  }

  function formatPersonName(first, last) {
    var f = splitGluedCyrillic(first);
    var l = splitGluedCyrillic(last);
    if (f && l) {
      var fl = f.toLowerCase();
      var ll = l.toLowerCase();
      if (fl === ll || fl.endsWith(' ' + ll) || fl.endsWith(ll)) {
        l = '';
      }
    }
    var joined = [f, l].filter(Boolean).join(' ');
    if (!joined) return '';
    return joined
      .split(' ')
      .map(titleCaseToken)
      .join(' ');
  }

  function formatPersonNameFromTrainer(t) {
    var p = t && t.profile ? t.profile : t || {};
    var fromParts = formatPersonName(p.first_name, p.last_name);
    if (fromParts) return fromParts;
    if (t && t.name) return formatPersonName(t.name, '');
    return '';
  }

  function guessGender(firstNom) {
    var n = String(firstNom || '')
      .replace(/[^\p{L}-]/gu, '')
      .toLowerCase();
    if (!n) return 'm';
    if (FEMALE_SOFT[n]) return 'f';
    if (MALE_YA_A[n]) return 'm';
    if (/ия$/.test(n) || /ья$/.test(n) || /ая$/.test(n)) return 'f';
    if (/а$/.test(n) || /я$/.test(n)) return 'f';
    return 'm';
  }

  function inflectGiven(name, gender, cas) {
    var m = String(name || '').match(/^([\p{L}]+)(.*)$/u);
    if (!m) return name;
    var n = m[1];
    var suf = m[2] || '';
    var low = n.toLowerCase();
    var out;

    if (/[оеэуи]$/i.test(n)) {
      return n + suf;
    }

    if (gender === 'f') {
      if (/[иь]я$/i.test(n) || /я$/i.test(n)) {
        out = n.slice(0, -1) + 'и';
      } else if (/а$/i.test(n)) {
        if (cas === 'dat') out = n.slice(0, -1) + 'е';
        else {
          var prev = n.charAt(n.length - 2);
          out = n.slice(0, -1) + (velarHush(prev) ? 'и' : 'ы');
        }
      } else if (/ь$/i.test(n)) {
        out = n.slice(0, -1) + 'и';
      } else {
        out = n;
      }
      return titleCaseToken(out) + suf;
    }

    if (/ий$/i.test(n) && n.length > 3) {
      out = n.slice(0, -2) + (cas === 'dat' ? 'ию' : 'ия');
    } else if (/ей$/i.test(n) || /ай$/i.test(n) || /ой$/i.test(n) || /й$/i.test(n)) {
      out = n.slice(0, -1) + (cas === 'dat' ? 'ю' : 'я');
    } else if (/ь$/i.test(n)) {
      out = n.slice(0, -1) + (cas === 'dat' ? 'ю' : 'я');
    } else if (/а$/i.test(n)) {
      if (cas === 'dat') out = n.slice(0, -1) + 'е';
      else {
        var prevM = n.charAt(n.length - 2);
        out = n.slice(0, -1) + (velarHush(prevM) ? 'и' : 'ы');
      }
    } else if (/я$/i.test(n)) {
      out = n.slice(0, -1) + (cas === 'dat' ? 'е' : 'и');
    } else {
      out = n + (cas === 'dat' ? 'у' : 'а');
    }
    return titleCaseToken(out) + suf;
  }

  function inflectSurname(name, gender, cas) {
    var m = String(name || '').match(/^([\p{L}]+)(.*)$/u);
    if (!m) return name;
    var n = m[1];
    var suf = m[2] || '';
    var out = n;

    if (/енко$/i.test(n) || /ко$/i.test(n) || /ых$/i.test(n) || /их$/i.test(n)) {
      return titleCaseToken(n) + suf;
    }

    if (gender === 'f') {
      if (/ская$/i.test(n) || /цкая$/i.test(n) || /ая$/i.test(n)) {
        out = n.slice(0, -2) + 'ой';
      } else if (/(ова|ева|ёва|ина|ына)$/i.test(n)) {
        out = n.slice(0, -1) + 'ой';
      } else if (/а$/i.test(n)) {
        if (cas === 'dat') out = n.slice(0, -1) + 'е';
        else {
          var prev = n.charAt(n.length - 2);
          out = n.slice(0, -1) + (velarHush(prev) ? 'и' : 'ы');
        }
      }
      return titleCaseToken(out) + suf;
    }

    if (/ский$/i.test(n) || /цкий$/i.test(n) || /ной$/i.test(n) || (/ой$/i.test(n) && n.length > 3)) {
      out = n.slice(0, -2) + (cas === 'dat' ? 'ому' : 'ого');
    } else if (/(ов|ев|ёв|ин|ын)$/i.test(n)) {
      out = n + (cas === 'dat' ? 'у' : 'а');
    } else if (/ь$/i.test(n)) {
      out = n.slice(0, -1) + (cas === 'dat' ? 'ю' : 'я');
    }
    return titleCaseToken(out) + suf;
  }

  function inflectPersonName(first, last, cas) {
    var nom = formatPersonName(first, last);
    if (!nom) return '';
    var parts = nom.split(' ');
    var gender = guessGender(parts[0]);
    if (parts.length === 1) {
      return inflectGiven(parts[0], gender, cas);
    }
    var given = inflectGiven(parts[0], gender, cas);
    var family = parts
      .slice(1)
      .map(function (p) {
        return inflectSurname(p, gender, cas);
      })
      .join(' ');
    return (given + ' ' + family).trim();
  }

  function requestHeading(first, last) {
    var nom = formatPersonName(first, last);
    if (!nom) return '';
    var gen = inflectPersonName(first, last, 'gen');
    if (gen && gen !== nom) return 'Для ' + gen;
    return nom;
  }

  function dativeLine(first, last) {
    var nom = formatPersonName(first, last);
    if (!nom) return '';
    var dat = inflectPersonName(first, last, 'dat');
    if (dat && dat !== nom) return dat;
    return nom;
  }

  return {
    splitGluedCyrillic: splitGluedCyrillic,
    formatPersonName: formatPersonName,
    formatPersonNameFromTrainer: formatPersonNameFromTrainer,
    guessGender: guessGender,
    inflectPersonName: inflectPersonName,
    requestHeading: requestHeading,
    dativeLine: dativeLine,
  };
});
