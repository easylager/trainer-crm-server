/**
 * TASK-147: стаб Яндекс Карт JS API 2.1 для headless-проверки раскладки.
 * Живого ключа в локальной сессии нет; проверяем GEOMETRY интерфейса:
 * слои, шторку, карусель, FAB, копирайт. Тайлов и камер нет — стаб.
 *
 * Подключается через page.addInitScript ДО загрузки ice-map.js.
 */
export const YMAPS_STUB = `
(function () {
  'use strict';
  if (window.__ymapsStub) return;

  function fakeProps(initial) {
    var store = Object.assign({}, initial || {});
    return {
      get: function (k) { return store[k]; },
      set: function (k, v) { store[k] = v; },
      getAll: function () { return Object.assign({}, store); },
      unset: function (k) { delete store[k]; },
    };
  }

  function fakeEvents() {
    var map = {};
    return {
      add: function (type, fn) { (map[type] = map[type] || []).push(fn); },
      remove: function (type, fn) {
        var list = map[type] || [];
        var i = list.indexOf(fn);
        if (i >= 0) list.splice(i, 1);
      },
      fire: function (type, ev) { (map[type] || []).forEach(function (fn) { fn(ev); }); },
    };
  }

  function fakeGeometry(coords) {
    return { getCoordinates: function () { return coords; } };
  }

  function Placemark(coords, props, options) {
    this.geometry = fakeGeometry(coords);
    this.properties = fakeProps(props);
    this.options = fakeProps(options);
    this.events = fakeEvents();
  }

  function Clusterer(options) {
    this.options = fakeProps(Object.assign({}, options));
    this.events = fakeEvents();
    var geo = [];
    this.geoObjects = geo;
    this.add = function (marks) { marks.forEach(function (m) { geo.push(m); }); };
    this.removeAll = function () { geo.length = 0; };
    this.getGeoObjects = function () { return geo.slice(); };
  }

  function templateLayoutFactory.createClass(tpl, overrides) {
    function Base() {}
    Base.prototype = {
      build: function () {},
      getData: function () { return this._data; },
      getParentElement: function () { return this._parent; },
      destroy: function () {},
      onSetData: function () {},
    };
    function Layout(data, parent) {
      this._data = data;
      this._parent = parent;
    }
    Layout.prototype = Object.create(Base.prototype);
    Object.keys(overrides || {}).forEach(function (k) {
      Layout.prototype[k] = overrides[k];
    });
    Layout.superclass = Base.prototype;
    return Layout;
  }

  function Map(el, state, options) {
    var events = fakeEvents();
    var self = this;
    this.container = {
      getElement: function () { return el; },
      fitToViewport: function () {},
      setBounds: function () {},
    };
    this.options = fakeProps(Object.assign({}, options));
    this.geoObjects = {
      add: function () {},
      remove: function () {},
    };
    this.events = events;
    var bounds = [[53.80, 27.38], [53.99, 27.72]];
    this.getBounds = function () { return bounds; };
    this.getZoom = function () { return 11; };
    this.setZoom = function () {};
    this.setCenter = function () {};
    this.setBounds = function () { return Promise.resolve(); };
    this.__fire = events.fire;
  }

  window.ymaps = {
    ready: function (fn) { fn(); },
    Placemark: Placemark,
    Clusterer: Clusterer,
    Map: Map,
    templateLayoutFactory: { createClass: templateLayoutFactory.createClass },
  };
  window.__ymapsStub = true;
})();
`;
