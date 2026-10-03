/**
 * TASK-147: стаб Яндекс Карт JS API 2.1 для headless-проверки раскладки.
 * Живого ключа и сети в CI нет; проверяем GEOMETRY интерфейса: слои, шторку,
 * карусель, FAB, копирайт, пины и кластеры. Тайлов нет — стаб.
 *
 * Что стаб делает по-настоящему (иначе он «удобнее реальности»):
 *  - template-layout: разметка шаблона кладётся в родителя, build() ice-map.js
 *    красит классы пина/кластера; properties.set перестраивает слой, как в 2.1;
 *  - кластеризация сеткой gridSize (px) по линейной проекции фиксированных границ;
 *  - клики по пину и кластеру приходят в events с ev.get('target').
 * Чего не делает: тайлы, зум/пан, balloon, реальную проекцию. Поэтому дополнительно
 * есть прогон на настоящем API (YMAPS_REAL=1, нужна сеть), см. ice-map-fullscreen.check.mjs.
 *
 * Подключается через page.addInitScript ДО загрузки ice-map.js. Внимание: ошибка
 * синтаксиса в строке ниже addInitScript глотает молча — поэтому e2e обязательно
 * проверяет window.__ymapsStub === true.
 */
export const YMAPS_STUB = `
(function () {
  'use strict';
  if (window.__ymapsStub) return;

  /* Фиксированные границы «камеры»: линейная проекция lat/lon → px контейнера. */
  var BOUNDS = [[53.78, 27.34], [54.00, 27.74]];

  function fakeProps(initial, onChange) {
    var store = Object.assign({}, initial || {});
    return {
      get: function (k) { return store[k]; },
      set: function (k, v) {
        if (typeof k === 'object') { Object.assign(store, k); } else { store[k] = v; }
        if (onChange) onChange();
      },
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
      fire: function (type, ev) { (map[type] || []).slice().forEach(function (fn) { fn(ev); }); },
    };
  }

  function fakeGeometry(coords) {
    return { getCoordinates: function () { return coords; } };
  }

  function Placemark(coords, props, options) {
    var self = this;
    this.geometry = fakeGeometry(coords);
    this.options = fakeProps(options);
    this.events = fakeEvents();
    this.properties = fakeProps(props, function () {
      if (self.__owner) self.__owner.__render();
    });
  }

  function Clusterer(options) {
    var self = this;
    var geo = [];
    this.options = fakeProps(Object.assign({}, options));
    this.events = fakeEvents();
    this.geoObjects = geo;
    this.__map = null;
    this.__layer = null;
    this.add = function (marks) {
      marks.forEach(function (m) { m.__owner = self; geo.push(m); });
      self.__render();
    };
    this.removeAll = function () { geo.forEach(function (m) { m.__owner = null; }); geo.length = 0; self.__render(); };
    this.getGeoObjects = function () { return geo.slice(); };

    this.__attach = function (map) {
      self.__map = map;
      var layer = document.createElement('div');
      layer.className = 'ymaps-stub-objects';
      layer.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden';
      map.__root.appendChild(layer);
      self.__layer = layer;
      self.__render();
    };

    function project(coords, w, h) {
      var latSpan = BOUNDS[1][0] - BOUNDS[0][0];
      var lonSpan = BOUNDS[1][1] - BOUNDS[0][1];
      return {
        x: (coords[1] - BOUNDS[0][1]) / lonSpan * w,
        y: (BOUNDS[1][0] - coords[0]) / latSpan * h,
      };
    }

    function mount(layoutClass, data, x, y, onClick) {
      var wrap = document.createElement('div');
      wrap.style.cssText = 'position:absolute;left:' + x + 'px;top:' + y + 'px;pointer-events:auto;cursor:pointer';
      self.__layer.appendChild(wrap);
      var layout = new layoutClass(data, wrap);
      layout.build();
      wrap.addEventListener('click', onClick);
      return wrap;
    }

    this.__render = function () {
      if (!self.__layer || !self.__map) return;
      var layer = self.__layer;
      layer.innerHTML = '';
      var rect = self.__map.__root.getBoundingClientRect();
      var w = rect.width || 390;
      var h = rect.height || 700;
      var grid = Number(self.options.get('gridSize')) || 64;
      var minSize = Number(self.options.get('minClusterSize')) || 2;
      var buckets = {};
      var order = [];
      geo.forEach(function (m) {
        var p = project(m.geometry.getCoordinates(), w, h);
        m.__px = p;
        var key = Math.floor(p.x / grid) + ':' + Math.floor(p.y / grid);
        if (!buckets[key]) { buckets[key] = []; order.push(key); }
        buckets[key].push(m);
      });
      order.forEach(function (key) {
        var group = buckets[key];
        if (group.length < minSize) {
          group.forEach(function (m) {
            var layoutClass = m.options.get('iconLayout');
            if (!layoutClass) return;
            mount(layoutClass, { properties: m.properties }, m.__px.x, m.__px.y, function (e) {
              m.events.fire('click', { preventDefault: function () {}, get: function () { return m; } });
              e.stopPropagation();
            });
          });
          return;
        }
        var cx = 0, cy = 0;
        group.forEach(function (m) { cx += m.__px.x; cy += m.__px.y; });
        var cluster = {
          getGeoObjects: function () { return group.slice(); },
          properties: fakeProps({ geoObjects: group.slice() }),
        };
        var clusterLayout = self.options.get('clusterIconLayout');
        if (!clusterLayout) return;
        mount(clusterLayout, { properties: cluster.properties }, cx / group.length, cy / group.length, function (e) {
          self.events.fire('click', { get: function (k) { return k === 'target' ? cluster : undefined; } });
          e.stopPropagation();
        });
      });
    };
  }

  /* Реальный синтаксис: переменная, а не «function a.b()» (из-за этого прежний стаб не загружался). */
  var templateLayoutFactory = {
    createClass: function (tpl, overrides) {
      function Base() {}
      Base.prototype = {
        build: function () { if (this._parent) this._parent.innerHTML = tpl; },
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
    },
  };

  function Map(el, state, options) {
    var events = fakeEvents();
    var root = document.createElement('ymaps');
    root.className = 'ymaps-2-1-stub-map';
    root.style.cssText = 'position:absolute;inset:0;display:block;overflow:hidden';
    /* Слой-«тайлы»: на него в тёмной теме вешается фильтр (html.client-mini-dark [class*="ground-pane"]). */
    var ground = document.createElement('ymaps');
    ground.className = 'ymaps-2-1-stub-ground-pane';
    ground.style.cssText = 'position:absolute;inset:0;display:block;background:#E8ECEA';
    root.appendChild(ground);
    el.appendChild(root);
    this.__root = root;
    this.container = {
      getElement: function () { return el; },
      fitToViewport: function () {},
    };
    this.options = fakeProps(Object.assign({}, options));
    var self = this;
    this.geoObjects = {
      add: function (obj) { if (obj && typeof obj.__attach === 'function') obj.__attach(self); },
      remove: function () {},
    };
    this.events = events;
    this.getBounds = function () { return BOUNDS; };
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
    templateLayoutFactory: templateLayoutFactory,
  };
  window.__ymapsStub = true;
})();
`;
