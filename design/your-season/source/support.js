/* Мини-рендер формата .dc.html для экспорта макетов в статичный HTML/PNG.
   Поддерживает то, что используют наши экраны: {{дырки}}, <sc-if>, <sc-for>, <dc-import>, <helmet>, data-props, state. */
(function () {
  'use strict';
  window.DCLogic = class {
    constructor(props) { this.props = props || {}; this.state = {}; }
    setState(p) { Object.assign(this.state, typeof p === 'function' ? p(this.state, this.props) : p); }
    forceUpdate() {}
  };
  var HOLE = /\{\{\s*([^}]+?)\s*\}\}/g;
  var WHOLE = /^\s*\{\{\s*([^}]+?)\s*\}\}\s*$/;
  var BOOL_ATTRS = { checked: 1, disabled: 1, selected: 1, hidden: 1, readonly: 1 };

  function lookup(scope, path) {
    path = path.trim();
    if (path === 'true') return true;
    if (path === 'false') return false;
    if (/^-?\d+(\.\d+)?$/.test(path)) return Number(path);
    var cur = scope;
    var parts = path.split('.');
    for (var i = 0; i < parts.length; i++) {
      if (cur == null) return undefined;
      cur = cur[parts[i]];
    }
    return cur;
  }
  function interp(str, scope) {
    return str.replace(HOLE, function (_, p) { var v = lookup(scope, p); return v == null ? '' : String(v); });
  }
  function camel(s) { return s.replace(/-([a-z])/g, function (_, c) { return c.toUpperCase(); }); }

  async function processChildren(src, scope, out) {
    for (var n of Array.from(src.childNodes)) {
      var r = await processNode(n, scope);
      if (r) out.appendChild(r);
    }
    return out;
  }

  async function processNode(node, scope) {
    if (node.nodeType === 3) return document.createTextNode(interp(node.textContent, scope));
    if (node.nodeType !== 1) return null;
    var tag = node.tagName.toLowerCase();
    if (tag === 'sc-if') {
      var m = WHOLE.exec(node.getAttribute('value') || '');
      var ok = m ? lookup(scope, m[1]) : false;
      if (!ok) return null;
      return processChildren(node, scope, document.createDocumentFragment());
    }
    if (tag === 'sc-for') {
      var lm = WHOLE.exec(node.getAttribute('list') || '');
      var list = (lm ? lookup(scope, lm[1]) : []) || [];
      var as = node.getAttribute('as') || 'item';
      var frag = document.createDocumentFragment();
      for (var i = 0; i < list.length; i++) {
        var s2 = Object.create(scope);
        s2[as] = list[i];
        s2.$index = i;
        await processChildren(node, s2, frag);
      }
      return frag;
    }
    if (tag === 'dc-import') {
      var props = {};
      for (var a of Array.from(node.attributes)) {
        if (a.name === 'name' || a.name.indexOf('hint-') === 0) continue;
        var wm = WHOLE.exec(a.value);
        props[camel(a.name)] = wm ? lookup(scope, wm[1]) : interp(a.value, scope);
      }
      var wrap = document.createElement('span');
      wrap.style.display = 'contents';
      await renderFile(node.getAttribute('name') + '.dc.html', props, null, wrap);
      return wrap;
    }
    var el = document.createElementNS(node.namespaceURI, node.localName);
    for (var at of Array.from(node.attributes)) {
      if (/^on[A-Z]/.test(at.name) || /^on[a-z]+$/.test(at.name)) continue;
      var whole = WHOLE.exec(at.value);
      if (BOOL_ATTRS[at.name]) {
        var bv = whole ? lookup(scope, whole[1]) : true;
        if (bv) el.setAttribute(at.name, '');
        continue;
      }
      if (at.name === 'value' && whole) { el.setAttribute('value', String(lookup(scope, whole[1]) ?? '')); continue; }
      el.setAttribute(at.name, interp(at.value, scope));
    }
    await processChildren(node, scope, el);
    return el;
  }

  async function renderFile(url, extraProps, stateOverride, mount) {
    var html = await (await fetch(url)).text();
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var xdc = doc.querySelector('x-dc');
    var script = doc.querySelector('script[data-dc-script]');
    var defs = JSON.parse(script.getAttribute('data-props') || '{}');
    var props = {};
    Object.keys(defs).forEach(function (k) { if (k[0] !== '$' && defs[k] && 'default' in defs[k]) props[k] = defs[k].default; });
    Object.assign(props, extraProps || {});
    var Component = new Function('DCLogic', script.textContent + '\n;return Component;')(window.DCLogic);
    var c = new Component(props);
    if (stateOverride) Object.assign(c.state, stateOverride);
    var vals = c.renderVals();
    var helmet = xdc.querySelector('helmet');
    if (helmet) {
      Array.from(helmet.children).forEach(function (n) {
        var key = n.outerHTML;
        if (!document.head.querySelector('[data-helmet="' + CSS.escape(key.length + ':' + key.slice(0, 80)) + '"]')) {
          var imp = document.importNode(n, true);
          imp.setAttribute('data-helmet', key.length + ':' + key.slice(0, 80));
          document.head.appendChild(imp);
        }
      });
      helmet.remove();
    }
    await processChildren(xdc, vals, mount);
  }

  window.__dcExport = async function () {
    var q = new URLSearchParams(location.search);
    var props = JSON.parse(q.get('props') || '{}');
    var state = JSON.parse(q.get('state') || 'null');
    var file = location.pathname.split('/').pop();
    var host = document.createElement('div');
    host.id = 'dc-root';
    document.body.innerHTML = '';
    document.body.appendChild(host);
    await renderFile(file, props, state, host);
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    return true;
  };
  window.__dcExportAuto = true;
})();
