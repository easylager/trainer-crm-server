/**
 * «Кто кого» — лиги (TASK-334 S5): новая лига (команды + срок + сводка), лига изнутри (вечер / месяц / весь срок,
 * «Продлить», «Позвать»), вход по ссылке, итоги месяца. Холст: LeagueNew, League.
 * «Вечер» лиги — кто как сходил за игровой день, кепка дня и жесты (TASK-431, design/kto-kogo-league-evening).
 * Лига = название + команды + срок; ходить отдельно не нужно, считаются матчи после вступления.
 */
(function () {
  'use strict';

  var K = window.KK;
  var h = K.h;
  var M = K.M;
  var S = K.S;
  var NBSP = '\u00a0';
  var I = K.I;
  var state = K.state;
  var icon = K.icon;

  // Лицо лиги (TASK-361): модель — в kto-kogo-league-identity.js, он грузится после этого файла, поэтому берём её в момент вызова.
  function Id() {
    return window.KtoKogoIdentity;
  }
  var PHOTO_ICON = ['M4 6.5h16v11H4z', 'M4 15.5l4.5-4.5 4 4 3-3 4.5 4.5', 'M9 10h.01'];

  /** Картинка лиги. Не загрузилась — убираем, под ней остаётся фон, как без картинки. Текст пользователя сюда не попадает. */
  function photo(src, cls, alt) {
    return h('img', { class: cls, src: src, alt: alt || '', decoding: 'async', onerror: function (e) { e.target.remove(); } });
  }

  /** Миниатюра для строки лиги на хабе; нет картинки — ничего (прежний вид). */
  function leagueThumb(l) {
    var face = Id().faceOf(l);
    return face ? h('span', { class: 'kk-lface', 'aria-hidden': 'true' }, [photo(face.thumb, 'kk-lface__img')]) : null;
  }
  K.leagueThumb = leagueThumb;

  /** «На что играем: …» — подпись приглушена, текст пользователя только через textContent. */
  function stakeEl(l, cls) {
    var parts = Id().stakeParts(l);
    return parts ? h('p', { class: cls }, [h('span', { class: 'kk-stake__k', text: parts.label + ': ' }), h('span', { class: 'kk-stake__v', text: parts.text })]) : null;
  }

  /** Загрузка файла в лигу: multipart, ответ — лига с адресами картинки. */
  function uploadImage(id, file) {
    var fd = new FormData();
    fd.append('file', file, file.name || 'photo');
    return K.api('POST', '/client/hockey/leagues/' + id + '/image', fd);
  }

  /**
   * Поле «Картинка»: настоящий label + input[type=file] (камера и галерея), превью и «Убрать».
   * o: id, src (что показать), alt, error, onFile(file), onRemove (null — убирать нечего).
   */
  function photoField(o) {
    var has = !!o.src;
    return h('div', { class: 'kk-fld' }, [
      h('span', { class: 'kk-lbl' }, ['КАРТИНКА ', h('span', { class: 'kk-mute', text: '· необязательно' })]),
      h('div', { class: 'kk-pick' }, [
        has ? photo(o.src, 'kk-pick__img', o.alt) : h('span', { class: 'kk-pick__ph', 'aria-hidden': 'true' }, [icon(PHOTO_ICON, 26)]),
        h('div', { class: 'kk-pick__a' }, [
          h('label', { class: 'kk-filebtn', for: o.id }, [
            h('input', {
              id: o.id,
              class: 'kk-vh',
              type: 'file',
              accept: 'image/jpeg,image/png,image/webp',
              onchange: function (e) {
                var file = e.target.files && e.target.files[0];
                e.target.value = '';
                if (file) o.onFile(file);
              },
            }),
            has ? 'Заменить фото' : 'Выбрать фото',
          ]),
          has && o.onRemove ? h('button', { type: 'button', class: 'kk-linkbtn kk-pick__rm', onclick: o.onRemove, 'aria-label': 'Убрать картинку лиги', text: 'Убрать' }) : null,
        ]),
      ]),
      o.error ? h('span', { class: 'kk-tx kk-tx--err', role: 'alert', text: o.error }) : h('span', { class: 'kk-sub', text: 'JPEG, PNG или WEBP до 5\u00a0МБ' }),
    ]);
  }

  /** Поле «На что играем»: обычный input без примера внутри. */
  function stakeField(id, value, oninput) {
    return h('div', { class: 'kk-fld' }, [
      h('label', { for: id, class: 'kk-lbl' }, ['НА ЧТО ИГРАЕМ ', h('span', { class: 'kk-mute', text: '· необязательно' })]),
      h('input', { id: id, class: 'kk-input', maxlength: String(Id().STAKE_MAX), autocomplete: 'off', value: value, placeholder: 'Свободный текст', oninput: function (e) { oninput(e.target.value); } }),
    ]);
  }

  /**
   * Кнопка «Создать» перечитывает форму на каждый символ: полная перерисовка на вводе уронила бы клавиатуру,
   * а без этого кнопка висела на «Назови лигу» до следующего тапа по вариантам.
   */
  function syncCta(f) {
    var btn = document.querySelector('.kk-cta .kk-btn');
    if (!btn) return;
    var err = S.formError(f) || Id().stakeError(f.stake);
    if (err || state.busy) btn.setAttribute('disabled', 'true');
    else btn.removeAttribute('disabled');
    btn.setAttribute('aria-disabled', err ? 'true' : 'false');
    btn.textContent = err || (state.busy ? 'Создаём…' : 'Создать и позвать своих');
  }

  var IDEAS = ['Раздевалка', 'Офис', 'Двор', 'Семья'];
  var SCOPES = [
    ['dinamo', 'Динамо-Минск', 'КХЛ, дома и на выезде'],
    ['extraliga', 'Вся Экстралига', 'Чемпионат Беларуси'],
    ['all', 'Всё сразу', 'Динамо-Минск (КХЛ) и вся Экстралига'],
    ['pick', 'Свои команды', 'Одна или несколько — например, Юность и Динамо'],
  ];

  function nowIso() {
    return new Date().toISOString();
  }

  /** «Чемпионат Беларуси, 15 клубов»: число клубов — из списка клубов, а не из головы. */
  function scopeSub(it, clubs) {
    if (it[0] !== 'extraliga') return it[2];
    var n = clubs.filter(function (c) { return c.league === 'extraliga'; }).length;
    return n ? it[2] + ', ' + n + '\u00a0' + M.plural(n, 'клуб', 'клуба', 'клубов') : it[2];
  }

  // ---------- Новая лига ----------

  function newForm(a) {
    if (!a.form) {
      a.form = { name: '', scope: a.club ? 'pick' : 'dinamo', clubs: a.club ? [a.club] : [], term: 'season', startsOn: '', endsOn: '', stake: '', image: null, imageUrl: null, imageError: '' };
    }
    return a.form;
  }

  var previewTimer = null;
  /** Окно дат и число матчей: спрашиваем у сервера, когда форма меняется. */
  function refreshPreview(a) {
    var f = newForm(a);
    a.preview = null;
    clearTimeout(previewTimer);
    if (S.termsError(f)) return;
    var seq = (a.previewSeq = (a.previewSeq || 0) + 1);
    previewTimer = setTimeout(function () {
      var body = S.termsBody(f, nowIso());
      K.api('POST', '/client/hockey/leagues/terms-preview', body)
        .then(function (p) {
          // Ответы могут прийти не по порядку: применяем только последний запрос.
          if (a.previewSeq === seq) {
            a.preview = p;
            a.previewError = '';
            K.render();
          }
        })
        .catch(function (e) {
          if (a.previewSeq === seq) {
            a.preview = null;
            a.previewError = e.message;
            K.render();
          }
        });
    }, 250);
  }

  function change(a, patch) {
    Object.keys(patch).forEach(function (k) { newForm(a)[k] = patch[k]; });
    a.previewError = '';
    K.render();
    refreshPreview(a);
  }

  /** Выбранный файл: тип и вес проверяем сразу, превью — из памяти телефона. */
  function pickFile(holder, file, fileKey, urlKey, errKey) {
    if (holder[urlKey]) URL.revokeObjectURL(holder[urlKey]);
    var err = Id().imageError(file);
    holder[errKey] = err;
    holder[fileKey] = err ? null : file;
    holder[urlKey] = err ? null : URL.createObjectURL(file);
  }

  function dropFile(holder, fileKey, urlKey, errKey) {
    if (holder[urlKey]) URL.revokeObjectURL(holder[urlKey]);
    holder[fileKey] = null;
    holder[urlKey] = null;
    holder[errKey] = '';
  }

  function createLeague(a) {
    var f = newForm(a);
    var err = S.formError(f) || Id().stakeError(f.stake);
    if (err) return K.toast(err);
    state.busy = true;
    K.render();
    var owner = K.current();
    var body = { name: f.name.trim(), terms: S.termsBody(f, nowIso()) };
    var stake = Id().cleanStake(f.stake);
    if (stake) body.stake_text = stake;
    var file = f.image;
    K.api('POST', '/client/hockey/leagues', body)
      .then(function (l) {
        state.created = l;
        state.createdNote = '';
        state.leagues = null;
        if (!file) return l;
        // Лига уже есть: не вышло с фото — это не повод терять лигу, картинку можно добавить в меню лиги.
        return uploadImage(l.id, file).then(
          function (withImage) {
            state.created = Object.assign({}, l, withImage);
            return state.created;
          },
          function (e) {
            state.createdNote = 'Лигу собрали, а фото не загрузилось: ' + e.message + '. Добавить его можно в меню лиги.';
            return l;
          }
        );
      })
      .then(function (l) {
        state.busy = false;
        dropFile(f, 'image', 'imageUrl', 'imageError');
        K.haptic('success');
        // Лига создана, но игрок успел уйти с формы: чужой экран не подменяем.
        if (K.current() === owner) K.replace('created', {});
        else K.toast('Лига «' + l.name + '» создана');
      })
      .catch(function (e) {
        state.busy = false;
        K.toast(e.message);
      });
  }

  /** Строка-вариант: иконка, название, подстрока, кружок выбора справа. */
  function opt(icon_, label, sub, on, onclick) {
    return h('button', { type: 'button', class: 'kk-opt' + (on ? ' is-on' : ''), 'aria-pressed': on ? 'true' : 'false', onclick: onclick }, [
      icon_,
      h('span', { class: 'kk-opt__t' }, [h('b', { class: 'kk-opt__n', text: label }), sub ? h('span', { class: 'kk-opt__s', text: sub }) : null]),
      h('span', { class: 'kk-opt__ck' + (on ? ' is-on' : ''), 'aria-hidden': 'true' }, on ? [icon(I.check, 14)] : null),
    ]);
  }

  /** Иконка набора команд: Динамо — одна шайба клуба, Экстралига и «всё» — веер логотипов, свои — квадрат из четырёх. */
  function scopeFace(scope, clubs) {
    var dinamo = clubs.filter(function (c) { return c.league === 'khl'; });
    var extra = clubs.filter(function (c) { return c.league === 'extraliga'; });
    if (scope === 'dinamo') return h('span', { class: 'kk-logos', 'aria-hidden': 'true' }, dinamo[0] ? [K.logoDisc(dinamo[0], 40)] : [K.worldDisc(40)]);
    if (scope === 'extraliga') return h('span', { class: 'kk-logos', 'aria-hidden': 'true' }, extra.slice(0, 3).map(function (c) { return K.logoDisc(c, 40); }));
    if (scope === 'all') return h('span', { class: 'kk-logos', 'aria-hidden': 'true' }, dinamo.slice(0, 1).concat(extra.slice(0, 3)).map(function (c) { return K.logoDisc(c, 40); }));
    return h('span', { class: 'kk-pick4', 'aria-hidden': 'true' }, clubs.slice(0, 4).map(function (c) { return K.logoDisc(c, 18); }));
  }

  K.register('leagueNew', {
    enter: function (a) {
      Promise.all([K.loadClubs(), K.loadTermOptions()]).then(function () { K.render(); refreshPreview(a); }, K.fail);
    },
    render: function (a) {
      var f = newForm(a);
      var clubs = state.clubs || [];
      var maxClubs = (state.termOptions && state.termOptions.max_clubs) || state.maxClubs || null;
      var err = S.formError(f) || Id().stakeError(f.stake);
      var sum = S.termsSummary(f, a.preview);
      var choices = S.termChoices(state.termOptions);
      // Выбранное окно ушло из списка (плей-офф прошёл): откатываемся на первый открытый.
      f.term = S.settleTerm(f.term, state.termOptions);
      var today = S.dayKey(nowIso());
      var lastDay = state.termOptions && state.termOptions.season_ends_at ? S.dayKey(new Date(new Date(state.termOptions.season_ends_at).getTime() - 1).toISOString()) : null;

      function toggleClub(name) {
        var on = f.clubs.indexOf(name) >= 0;
        if (!on && maxClubs && f.clubs.length >= maxClubs) return K.toast('Не больше ' + maxClubs + ' команд');
        change(a, { clubs: on ? f.clubs.filter(function (x) { return x !== name; }) : f.clubs.concat([name]) });
      }

      var main = h('main', { class: 'kk-main' }, [
        K.topbar('Новая лига', null),
        h('p', { class: 'kk-sub kk-sub--tight', text: 'Своя таблица для своих. Ходы те же, что в общей игре, — отдельно ходить не нужно.' }),
        h('div', { class: 'kk-fld' }, [
          h('label', { for: 'kk-lname', class: 'kk-lbl', text: 'КАК НАЗОВЁМ' }),
          h('input', { id: 'kk-lname', class: 'kk-input', maxlength: '28', autocomplete: 'off', value: f.name, placeholder: 'Например, Офис', oninput: function (e) { f.name = e.target.value; syncCta(f); } }),
          h('div', { class: 'kk-chips' }, IDEAS.map(function (n) { return h('button', { type: 'button', class: 'kk-ch kk-ch--sm', onclick: function () { f.name = n; K.render(); refreshPreview(a); }, text: n }); })),
        ]),
        photoField({
          id: 'kk-limg',
          src: f.imageUrl,
          alt: 'Выбранная картинка лиги',
          error: f.imageError,
          onFile: function (file) { pickFile(f, file, 'image', 'imageUrl', 'imageError'); K.render(); },
          onRemove: f.image ? function () { dropFile(f, 'image', 'imageUrl', 'imageError'); K.render(); } : null,
        }),
        stakeField('kk-lstake', f.stake, function (v) { f.stake = v; syncCta(f); }),
        h('div', { class: 'kk-sec' }, [
          h('span', { class: 'kk-lbl', text: 'КАКИЕ МАТЧИ' }),
          h('div', { class: 'kk-opts', role: 'group', 'aria-label': 'Матчи' }, SCOPES.map(function (it) {
            return opt(scopeFace(it[0], clubs), it[1], scopeSub(it, clubs), f.scope === it[0], function () { change(a, { scope: it[0] }); });
          })),
          f.scope === 'pick'
            ? h('div', { class: 'kk-clubgrid' }, clubs.map(function (c) {
                var on = f.clubs.indexOf(c.name) >= 0;
                return h('button', {
                  type: 'button',
                  class: 'kk-club' + (on ? ' is-on' : ''),
                  'aria-pressed': on ? 'true' : 'false',
                  onclick: function () { toggleClub(c.name); },
                }, [K.logoDisc(c, 34), h('span', { class: 'kk-club__n', text: S.clubShort(c.name) }), on ? h('span', { class: 'kk-ok', 'aria-hidden': 'true' }, [icon(I.check, 12)]) : null]);
              }))
            : null,
        ]),
        h('div', { class: 'kk-sec' }, [
          h('span', { class: 'kk-lbl', text: 'КАК ДОЛГО' }),
          h('div', { class: 'kk-opts', role: 'group', 'aria-label': 'Время лиги' }, choices.map(function (c) {
            return opt(null, c.label, c.sub, f.term === c.term, function () { change(a, { term: c.term }); });
          })),
          f.term === 'dates'
            ? h('div', { class: 'kk-two' }, [
                h('div', { class: 'kk-fld' }, [h('label', { for: 'kk-d1', class: 'kk-lbl', text: 'С' }), h('input', { id: 'kk-d1', class: 'kk-input', type: 'date', min: today, max: lastDay, value: f.startsOn, onchange: function (e) { change(a, { startsOn: e.target.value }); } })]),
                h('div', { class: 'kk-fld' }, [h('label', { for: 'kk-d2', class: 'kk-lbl', text: 'ПО' }), h('input', { id: 'kk-d2', class: 'kk-input', type: 'date', min: today, max: lastDay, value: f.endsOn, onchange: function (e) { change(a, { endsOn: e.target.value }); } })]),
              ])
            : null,
        ]),
        h('section', { class: 'kk-card kk-sum kk-sum--future' }, [
          h('span', { class: 'kk-lbl kk-lbl--gold', text: 'КАК БУДЕТ' }),
          sum.title ? h('b', { class: 'kk-hd', text: sum.title }) : null,
          h('span', { class: 'kk-tx', text: sum.what }),
          sum.when ? h('span', { class: 'kk-tx', text: sum.when }) : null,
          sum.crowns ? h('span', { class: 'kk-tx', text: sum.crowns }) : null,
          a.previewError ? h('span', { class: 'kk-tx kk-tx--err', text: a.previewError }) : null,
          sum.few ? h('span', { class: 'kk-tx kk-tx--warn', text: sum.few }) : null,
          h('span', { class: 'kk-sub', text: sum.note }),
        ]),
      ]);
      return [main, h('div', { class: 'kk-cta' }, [
        h('button', { type: 'button', class: 'kk-btn kk-btn--gold kk-btn--lg', disabled: err || state.busy ? 'true' : null, 'aria-disabled': err ? 'true' : 'false', onclick: function () { createLeague(a); }, text: err || (state.busy ? 'Создаём…' : 'Создать и позвать своих') }),
      ])];
    },
  });

  K.register('created', {
    render: function () {
      var l = state.created;
      if (!l) return [h('main', { class: 'kk-main' }, [K.loading()])];
      var face = Id().faceOf(l);
      return [
        h('main', { class: 'kk-main kk-center' }, [
          face
            ? h('span', { class: 'kk-badge-big kk-badge-big--img', 'aria-hidden': 'true' }, [photo(face.src, 'kk-badge-big__img')])
            : h('span', { class: 'kk-badge-big', 'aria-hidden': 'true', text: M.firstChars(l.name, 2).toUpperCase() }),
          h('h2', { class: 'kk-h2 kk-h2--xl', text: 'Лига «' + l.name + '» готова' }),
          stakeEl(l, 'kk-stake kk-stake--c'),
          h('span', { class: 'kk-sub', text: S.leagueSub(l) + '. Пока в лиге только ты — позови своих, очки за матчи пойдут и сюда, и в общую таблицу.' }),
          state.createdNote ? h('span', { class: 'kk-tx kk-tx--warn', role: 'status', text: state.createdNote }) : null,
          l.few_matches ? h('span', { class: 'kk-tx kk-tx--warn', text: 'Матчей до конца лиги мало — таблица будет почти пустой.' }) : null,
          h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { K.shareCard({ card: 'league', league_id: l.id }, l.invite_url, S.inviteText(l.name, l)); }, text: 'Позвать в Telegram' }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.copy(l.invite_url); }, text: 'Скопировать ссылку' }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.reset('hub', {}); }, text: 'К игре' }),
        ]),
      ];
    },
  });

  // ---------- Лига изнутри ----------

  function lkey(a) {
    return a.id + '|' + a.tab;
  }

  function loadLeague(a, force) {
    var key = lkey(a);
    if (state.leagueTables[key] && !force) return Promise.resolve();
    return K.api('GET', '/client/hockey/leagues/' + a.id + (a.tab === 'month' ? '?period=month' : '')).then(function (d) { state.leagueTables[key] = d; });
  }

  function clubLogos(l) {
    var clubs = state.clubs || [];
    if (l.scope !== 'clubs') return [K.worldDisc(26)];
    return l.clubs.slice(0, 4).map(function (n) {
      var c = clubs.filter(function (x) { return x.name === n; })[0] || { name: n };
      return K.logoDisc(c, 26);
    });
  }

  function crownWall(wall) {
    if (!wall || !wall.length) return null;
    var LABEL = { running: 'идёт', counting: 'считаем', empty: 'без короны', ahead: '' };
    return h('section', { class: 'kk-sec', 'aria-label': 'Короны лиги' }, [
      h('span', { class: 'kk-lbl', text: 'КОРОНЫ ЛИГИ' }),
      h('div', { class: 'kk-wall' }, wall.map(function (w) {
        var who = (w.winners || []).map(function (x) { return x.display_name; }).join(', ');
        return h('div', { class: 'kk-wall__t kk-wall__t--' + w.state }, [
          h('span', { class: 'kk-wall__mo', text: w.title.toUpperCase() }),
          w.state === 'crowned' ? h('span', { class: 'kk-wall__who' }, [K.crownIcon(14), who]) : LABEL[w.state] ? h('span', { class: 'kk-sub', text: LABEL[w.state] }) : null,
        ]);
      })),
    ]);
  }

  function leagueRow(r) {
    var mark = S.titleMark(r.title);
    var marks = S.leagueMarks(r);
    var sub = (r.title && r.title.label ? (mark ? mark + NBSP : '') + r.title.label + (r.title.detail ? ' · ' + r.title.detail : '') + ' · ' : '') + S.rowSub(r) + (marks ? ' · ' + marks : '');
    return h('div', { class: 'kk-r' + (r.is_me ? ' is-me' : '') }, [
      h('span', { class: 'kk-r__n' + (r.rank === 1 ? ' is-gold' : ''), text: String(r.rank) }),
      h('span', { class: 'kk-col kk-r__w' }, [h('span', { class: 'kk-r__name' }, [h('span', { class: 'kk-r__nm', text: r.display_name }), r.is_me ? h('span', { class: 'kk-me', text: 'ты' }) : null, K.crownTag(r.crowns)]), h('span', { class: 'kk-sub', text: sub })]),
      h('span', { class: 'kk-r__pt', text: String(r.points) }),
    ]);
  }

  /** Аватарка со значком звания: кепка на макушке, шарф на шее. Без звания — просто аватарка. */
  function avatarWithMark(r, size) {
    var a = K.ava(r.display_name, size);
    var mark = S.titleMark(r.title);
    if (!mark) return a;
    return h('span', { class: 'kk-capwrap' }, [a, h('span', { class: 'kk-cap kk-cap--' + r.title.id, 'aria-hidden': 'true', text: mark })]);
  }

  /** Пьедестал лиги из первой версии игры: трое лучших колонками, звание (шарф, кепка) под именем. */
  function leaguePodium(items) {
    var order = S.podiumOrder(items);
    if (!order) return null;
    return h('div', { class: 'kk-podium', role: 'group', 'aria-label': 'Первая тройка лиги' }, order.map(function (r, i) {
      var place = i === 1 ? 1 : i === 0 ? 2 : 3;
      return h('div', { class: 'kk-podium__col' }, [
        avatarWithMark(r, place === 1 ? 60 : 48),
        h('span', { class: 'kk-podium__name' }, [h('span', { class: 'kk-podium__nm', text: r.display_name }), r.is_me ? h('span', { class: 'kk-me', text: 'ты' }) : null]),
        r.title && r.title.label ? h('span', { class: 'kk-podium__title', text: r.title.label }) : h('span', { class: 'kk-podium__title' }),
        h('div', { class: 'kk-podium__block kk-podium__block--' + place }, [
          h('span', { class: 'kk-podium__rank', text: String(r.rank) }),
          h('span', { class: 'kk-podium__pt', text: String(r.points) }),
        ]),
      ]);
    }));
  }

  /** Черновик «Изменить лигу»: название, строка, выбранный файл и «убрать картинку». */
  function editDraft(l) {
    return { kind: 'edit', name: l.name || '', stake: l.stake_text || '', file: null, previewUrl: null, imageError: '', removeImage: false, error: '', busy: false };
  }

  function closeDraft(s) {
    if (s.previewUrl) URL.revokeObjectURL(s.previewUrl);
    s.previewUrl = null;
  }

  function editSheet(s, a, l) {
    var face = Id().faceOf(l);
    var shown = s.previewUrl || (!s.removeImage && face ? face.thumb : null);
    return K.sheet('Изменить лигу', 'Друзья увидят всё сразу', [
      h('label', { for: 'kk-ename', class: 'kk-lbl', text: 'НАЗВАНИЕ' }),
      h('input', { id: 'kk-ename', class: 'kk-input', maxlength: String(Id().NAME_MAX), autocomplete: 'off', value: s.name, oninput: function (e) { s.name = e.target.value; } }),
      photoField({
        id: 'kk-eimg',
        src: shown,
        alt: s.previewUrl ? 'Выбранная картинка лиги' : 'Картинка лиги',
        error: s.imageError,
        onFile: function (file) { pickFile(s, file, 'file', 'previewUrl', 'imageError'); s.removeImage = false; K.render(); },
        onRemove: shown
          ? function () {
              // Выбранный, но ещё не отправленный файл просто отменяем (возвращается прежняя картинка); прежнюю — убираем.
              if (s.file) dropFile(s, 'file', 'previewUrl', 'imageError');
              else s.removeImage = true;
              K.render();
            }
          : null,
      }),
      stakeField('kk-estake', s.stake, function (v) { s.stake = v; }),
      s.error ? h('span', { class: 'kk-tx kk-tx--err', role: 'alert', text: s.error }) : null,
      h('button', { type: 'button', class: 'kk-btn kk-btn--gold', disabled: s.busy ? 'true' : null, text: s.busy ? 'Сохраняем…' : 'Сохранить', onclick: function () { saveEdit(s, a, l); } }),
    ]);
  }

  /** Сохранить по шагам: тексты, потом картинка. Сбой на втором шаге не откатывает первый — лига перечитывается как есть. */
  function saveEdit(s, a, l) {
    var err = Id().editError(s);
    if (err) {
      s.error = err;
      return K.render();
    }
    var plan = Id().editPlan(l, s);
    if (!plan.changed) return K.closeSheet();
    s.busy = true;
    s.error = '';
    K.render();
    var base = '/client/hockey/leagues/' + a.id;
    var touched = false;
    var chain = Promise.resolve();
    if (plan.patch) chain = chain.then(function () { return K.api('PATCH', base, plan.patch); }).then(function () { touched = true; });
    if (plan.image === 'upload') chain = chain.then(function () { return uploadImage(a.id, s.file); }).then(function () { touched = true; });
    if (plan.image === 'remove') chain = chain.then(function () { return K.api('DELETE', base + '/image'); }).then(function () { touched = true; });
    chain.then(function () {
      closeDraft(s);
      state.sheet = null;
      state.leagues = null;
      state.leagueTables = {};
      a.failed = false;
      // Всё сохранено: сбой перезагрузки таблицы показываем на экране с «Повторить», а не в закрытой шторке.
      loadLeague(headArgs(a), true).then(K.render, function (e) {
        a.failed = true;
        K.render();
        K.fail(e);
      });
      K.render();
    }, function (e) {
      s.busy = false;
      s.error = e.message;
      K.render();
      if (!touched) return;
      // Часть уже сохранена: перечитываем лигу, чтобы повторное «Сохранить» отправило только оставшееся.
      var key = lkey(headArgs(a));
      K.api('GET', base + (a.tab === 'month' ? '?period=month' : '')).then(function (d) {
        state.leagues = null;
        state.leagueTables = {};
        state.leagueTables[key] = d;
        K.render();
      }, function () {});
    });
  }

  // ---------- Вечер лиги (TASK-431) ----------

  var TABS_ID = 'kk-ltabs';

  function ekey(a) {
    return a.id + '|' + (a.day || '');
  }

  /** «Вечер» лиги за a.day (пусто — сегодня или последний день с матчами). Ответ кладём и под его день. */
  function loadEvening(a, force) {
    var key = ekey(a);
    if (state.evenings[key] && !force) return Promise.resolve();
    return K.api('GET', '/client/hockey/leagues/' + a.id + '/evening' + (a.day ? '?day=' + encodeURIComponent(a.day) : '')).then(function (d) {
      state.evenings[key] = d;
      if (d && d.day) state.evenings[a.id + '|' + d.day] = d;
    });
  }

  /** Переключатель вверху: Вечер · <Месяц> · Вся лига. */
  function leagueTabs(a, monthName, onPick) {
    var items = [['evening', 'Вечер'], ['month', monthName], ['all', 'Вся лига']];
    return h('div', { class: 'kk-ltabs', role: 'tablist', 'aria-label': 'Лига', id: TABS_ID }, items.map(function (it) {
      var on = a.tab === it[0];
      return h('button', { type: 'button', role: 'tab', class: 'kk-ltabs__b', 'aria-selected': on ? 'true' : 'false', onclick: function () { if (!on) onPick(it[0]); }, text: it[1] });
    }));
  }

  var SVG_NS = 'http://www.w3.org/2000/svg';

  /** Кепка из макета (viewBox 64×44): купол и козырёк; band — белая полоса, как в шторке правил. */
  function capSvg(w, hgt, fill, band) {
    var s = document.createElementNS(SVG_NS, 'svg');
    s.setAttribute('width', w);
    s.setAttribute('height', hgt);
    s.setAttribute('viewBox', '0 0 64 44');
    s.setAttribute('aria-hidden', 'true');
    ['M10 32 C10 14 20 6 32 6 C44 6 52 14 52 32 Z', 'M30 32 H61 C62 36 58 39 51 39 H30 Z'].forEach(function (d) {
      var p = document.createElementNS(SVG_NS, 'path');
      p.setAttribute('d', d);
      p.setAttribute('fill', fill);
      s.appendChild(p);
    });
    if (band) {
      var r = document.createElementNS(SVG_NS, 'rect');
      r.setAttribute('x', '10');
      r.setAttribute('y', '28');
      r.setAttribute('width', '42');
      r.setAttribute('height', '4');
      r.setAttribute('fill', band);
      s.appendChild(r);
    }
    return s;
  }
  K.capSvg = capSvg;

  var STICK_ICON = ['M7 2l7 15h7', 'M3 21h8'];
  var PEN_ICON = ['M12 7a7 7 0 1 0 0 14a7 7 0 0 0 0-14z', 'M12 14V10', 'M10 3h4'];

  /** Анимация живёт окном времени: экран перерисовывается целиком, и класс, оставленный дольше, проиграл бы её снова. */
  var MOTION_MS = 1100;

  function fresh(at) {
    return !!at && Date.now() - at < MOTION_MS;
  }

  /** Прилетевшие мне жесты анимируем один раз на набор: что уже видел — помнит браузер (только удобство, не состояние игры). */
  function revealAt(a, ev, r) {
    a.reveal = a.reveal || {};
    if (a.reveal[ev.day] !== undefined) return a.reveal[ev.day];
    var sig = S.gestureSeenKey(r);
    var key = 'kk-ev-seen:' + a.id + ':' + ev.day;
    var seen = null;
    try { seen = window.localStorage.getItem(key); } catch (e) { seen = sig; }
    a.reveal[ev.day] = sig && seen !== sig ? Date.now() : 0;
    if (a.reveal[ev.day]) {
      try { window.localStorage.setItem(key, sig); } catch (e) { /* без хранилища — просто покажем снова */ }
    }
    return a.reveal[ev.day];
  }

  function gestureButtons(a, ev, r) {
    return h('div', { class: 'kk-ev__acts', role: 'group', 'aria-label': 'Жест: ' + r.display_name }, S.GESTURES.map(function (g) {
      var on = r.my_gesture === g[0];
      var just = on && a.gave && a.gave.pid === r.pid && fresh(a.gave.at);
      var skin = S.gestureSkin(g[0], 'base');
      return h('button', {
        type: 'button', id: 'kk-g-' + r.pid + '-' + g[0], 'data-keep': '',
        class: 'kk-gest kk-gest--' + g[0] + (just ? ' is-' + skin.motion : ''),
        'aria-pressed': on ? 'true' : 'false', 'aria-label': g[1], disabled: r.busy ? 'true' : null,
        onclick: function () { sendGesture(a, ev, r, g[0]); },
      }, [g[0] === 'pen' ? penIcon() : icon(STICK_ICON, 20)]);
    }));
  }

  /** Секундомер с кольцом, которое «сбегает» при нажатии. */
  function penIcon() {
    var s = icon(PEN_ICON, 20);
    var ring = document.createElementNS(SVG_NS, 'circle');
    ring.setAttribute('class', 'kk-gest__drain');
    ring.setAttribute('cx', '12');
    ring.setAttribute('cy', '14');
    ring.setAttribute('r', '7');
    ring.setAttribute('transform', 'rotate(-90 12 14)');
    s.appendChild(ring);
    return s;
  }

  function gestureHaptic(kind) {
    var hp = S.gestureSkin(kind, 'base').haptic;
    try {
      var hf = window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.HapticFeedback;
      if (!hf) return;
      if (hp[0] === 'notification') hf.notificationOccurred(hp[1]);
      else hf.impactOccurred(hp[1]);
    } catch (e) { /* старые клиенты */ }
  }

  /** Жест — без пушей: ответ сервера и есть новый «Вечер» этого дня. */
  function sendGesture(a, ev, r, kind) {
    if (r.busy) return;
    var next = S.gestureNext(r.my_gesture, kind);
    if (next) gestureHaptic(next);
    r.busy = true;
    K.render();
    K.api('PUT', '/client/hockey/leagues/' + a.id + '/evening/' + ev.day + '/gesture', { to: r.pid, kind: next })
      .then(function (d) {
        state.evenings[a.id + '|' + d.day] = d;
        if (!a.day) state.evenings[a.id + '|'] = d;
        // Минуты штрафа в таблице месяца изменились: таблицы перечитаются при переключении вкладки.
        delete state.leagueTables[a.id + '|month'];
        a.gave = next ? { pid: r.pid, at: Date.now() } : null;
        K.render();
        if (next) setTimeout(K.render, MOTION_MS);
      }, function (e) {
        r.busy = false;
        K.render();
        K.toast(e.message);
      });
  }

  /** Аватар со следом жестов вечера: стуки — значок ×N сверху, скамейка — табличка «2:00» снизу. */
  function eveningAvatar(a, ev, r) {
    var st = S.gestureStamps(r);
    var motion = r.is_me ? fresh(revealAt(a, ev, r)) : a.gave && a.gave.pid === r.pid && fresh(a.gave.at);
    return h('div', { class: 'kk-ev__av' + (st.pens ? ' is-bench' : '') }, [
      K.ava(r.display_name, 44, r.is_me ? '' : 'kk-ava--soft'),
      st.sticks ? h('span', { class: 'kk-stamp kk-stamp--stick' + (motion ? ' is-new' : ''), 'aria-hidden': 'true' }, [icon(STICK_ICON, 11), st.stickLabel]) : null,
      st.pens ? h('span', { class: 'kk-stamp kk-stamp--pen' + (motion ? ' is-new' : ''), 'aria-hidden': 'true', text: st.penLabel }) : null,
      st.say ? h('span', { class: 'kk-vh', text: st.say }) : null,
    ]);
  }

  function eveningPerson(a, ev, r) {
    var pts = S.eveningPoints(r, ev);
    var notes = S.eveningNotes(r, ev);
    return h('div', { class: 'kk-ev__p' + (r.is_me ? ' is-me' : '') }, [
      eveningAvatar(a, ev, r),
      h('div', { class: 'kk-ev__w' }, [
        h('div', { class: 'kk-ev__name' }, [
          h('span', { class: 'kk-ev__nm', text: r.is_me ? 'Ты' : r.display_name }),
          r.cap ? h('span', { class: 'kk-ev__cap' }, [capSvg(18, 12, 'currentColor'), 'кепка']) : null,
          r.scarf ? h('span', { class: 'kk-ev__scarf', text: 'в чужом шарфе' }) : null,
        ]),
        h('div', { class: 'kk-ev__dots' }, [
          h('span', { class: 'kk-evd-row', 'aria-hidden': 'true' }, (r.marks || []).map(function (x) { return h('span', { class: 'kk-evd kk-evd--' + x.state }); })),
          h('span', { class: 'kk-ev__mv', text: S.eveningMoves(r, ev) }),
        ]),
      ]),
      h('div', { class: 'kk-ev__side' }, [
        pts ? h('span', { class: 'kk-ev__pt' + (r.points ? '' : ' is-zero'), text: pts }) : null,
        r.can_gesture ? gestureButtons(a, ev, r) : null,
      ]),
      notes.length ? h('div', { class: 'kk-ev__notes' }, notes.map(function (n) { return h('span', { class: 'kk-ev__note' + (n.tone ? ' kk-ev__note--' + n.tone : ''), text: n.text }); })) : null,
    ]);
  }

  /** Итог вечера над строками: звезда и кепка. Вечер не сыгран — блока нет. */
  function eveningVerdict(ev) {
    var v = S.eveningVerdict(ev);
    if (!v) return null;
    return h('div', { class: 'kk-ev__verdict' }, [
      v.star ? h('div', { class: 'kk-ev__vd kk-ev__vd--star' }, [
        icon(['M4 8l4 4 4-7 4 7 4-4-2 11H6z'], 26),
        h('span', { class: 'kk-ev__vl', text: v.star.label }),
        h('span', { class: 'kk-ev__vt', text: v.star.name }),
        h('span', { class: 'kk-ev__vs', text: v.star.sub }),
      ]) : null,
      v.cap ? h('div', { class: 'kk-ev__vd kk-ev__vd--cap' }, [
        capSvg(34, 24, 'currentColor'),
        h('span', { class: 'kk-ev__vl', text: v.cap.label }),
        h('span', { class: 'kk-ev__vt', text: v.cap.name }),
        h('span', { class: 'kk-ev__vs', text: v.cap.sub }),
      ]) : null,
    ]);
  }

  function eveningBlock(a) {
    var ev = state.evenings[ekey(a)];
    if (!ev) return [a.eveningFailed ? K.retryCard('Вечер не загрузился.', function () { a.eveningFailed = false; openEvening(a, a.day); }) : K.loading()];
    if (!ev.day) return [h('span', { class: 'kk-sub', text: 'У лиги ещё не было матчей. Первый вечер появится в день матча.' })];
    function go(day) { openEvening(a, day); }
    return [
      h('div', { class: 'kk-ev__nav' }, [
        h('button', { type: 'button', class: 'kk-ev__arrow', 'aria-label': 'Предыдущий вечер', disabled: ev.prev ? null : 'true', onclick: function () { go(ev.prev); } }, [icon(I.back)]),
        h('div', { class: 'kk-ev__day' }, [h('h2', { class: 'kk-ev__t', text: S.eveningTitle(ev.day) }), h('span', { class: 'kk-ev__s', text: S.eveningSummary(ev) })]),
        h('button', { type: 'button', class: 'kk-ev__arrow', 'aria-label': 'Следующий вечер', disabled: ev.next ? null : 'true', onclick: function () { go(ev.next); } }, [icon(I.chev)]),
      ]),
      eveningVerdict(ev),
      h('div', { class: 'kk-ev__people' }, (ev.items || []).map(function (r) { return eveningPerson(a, ev, r); })),
      h('div', { class: 'kk-ev__matches' }, (ev.matches || []).map(function (m, i) {
        return h('div', { class: 'kk-ev__m' }, [
          h('span', { class: 'kk-ev__n', text: String(i + 1) }),
          h('span', { class: 'kk-ev__mt', text: S.eveningMatchTitle(m) }),
          h('span', { class: 'kk-ev__sc', text: S.eveningScore(m) }),
        ]);
      })),
      h('p', { class: 'kk-ev__foot' }, [
        S.eveningFoot(ev) + ' ',
        h('button', { type: 'button', class: 'kk-ev__link', id: 'kk-ev-rules', 'aria-haspopup': 'dialog', onclick: function () { state.sheet = { kind: 'points', tab: 'cap', returnId: 'kk-ev-rules' }; K.render(); }, text: 'Как считаем' }),
      ]),
    ];
  }

  /** Перейти на день (стрелки): данные дня — свой запрос; пока он идёт, на экране прежний вечер. */
  function openEvening(a, day) {
    a.day = day || '';
    a.eveningFailed = false;
    K.render();
    loadEvening(a).then(K.render, function (e) { a.eveningFailed = true; K.render(); K.fail(e); });
  }

  /** Шапке лиги (название, лицо, кто владелец) нужна таблица: на «Вечере» берём таблицу всей лиги. */
  function headArgs(a) {
    return a.tab === 'evening' ? { id: a.id, tab: 'all' } : a;
  }

  /** Вкладки месяца и всей лиги: пьедестал, таблица (с минутами штрафа и кепками), стена корон. */
  function tableBlock(a, l) {
    var items = l.items || [];
    var me = items.filter(function (r) { return r.is_me; })[0];
    return [
      h('div', { class: 'kk-crownbar' + (S.leagueCrownMuted(l) ? ' kk-crownbar--muted' : '') }, [K.crownIcon(18), h('span', { text: S.leagueCrownLine(l, a.tab, me, items[0] ? items[0].points : 0) })]),
      S.podiumOrder(items) ? leaguePodium(items) : null,
      items.length > 1 ? h('div', { class: 'kk-tbl' }, (S.podiumOrder(items) ? items.slice(3) : items).map(leagueRow)) : h('span', { class: 'kk-sub', text: 'Пока в лиге только ты. Позови своих — таблица оживёт после первого матча.' }),
      S.titlesNote(items) ? h('span', { class: 'kk-sub', text: S.titlesNote(items) }) : null,
      a.tab === 'all' ? crownWall(l.wall) : null,
    ];
  }

  K.register('league', {
    enter: function (a) {
      // Тап по лиге открывает «Вечер» (TASK-431); шапке лиги нужна её таблица — для вечера берём «Вся лига».
      a.tab = a.tab || 'evening';
      a.failed = false;
      a.eveningFailed = false;
      var head = loadLeague(headArgs(a), true);
      if (a.tab === 'evening') loadEvening(a, true).then(K.render, function (e) { a.eveningFailed = true; K.render(); K.fail(e); });
      Promise.all([head, K.loadClubs().catch(function () {})]).then(K.render, function (e) {
        K.fail(e);
        a.failed = true;
        K.render();
      });
    },
    render: function (a) {
      a.tab = a.tab || 'evening';
      var l = state.leagueTables[lkey(headArgs(a))];
      var monthName = S.periodLabel(S.monthKey(nowIso()));
      if (!l) return [h('main', { class: 'kk-main' }, [K.topbar('Лига', null), a.failed ? K.retryCard('Лига не загрузилась.', function () { a.failed = false; K.render(); K.replace('league', a); }) : K.loading()])];
      var items = l.items || [];
      var face = Id().faceOf(l);
      var main = h('main', { class: 'kk-main' }, [
        h('header', { class: 'kk-lhead' + (face ? ' kk-lhead--img' : '') }, [
          face ? photo(face.src, 'kk-lhead__bg') : null,
          h('div', { class: 'kk-hero__bar' }, [
            h('button', { type: 'button', class: 'kk-round kk-round--glass', 'aria-label': 'Назад', onclick: K.back }, [icon(I.back)]),
            h('button', { type: 'button', class: 'kk-round kk-round--glass', 'aria-label': 'Настройки лиги', onclick: function () { state.sheet = { kind: 'menu' }; K.render(); } }, [icon(I.more)]),
          ]),
          h('h1', { class: 'kk-h1 kk-h1--xl', text: l.name }),
          stakeEl(l, 'kk-lstake'),
          h('div', { class: 'kk-lmeta' }, [h('span', { class: 'kk-logos' }, clubLogos(l)), h('span', { text: S.leagueMeta(l, items.length) + (l.active ? '' : ' · закончилась') })]),
        ]),
        leagueTabs(a, monthName, function (id) {
          a.tab = id;
          a.failed = false;
          K.render();
          if (id === 'evening') return openEvening(a, a.day);
          loadLeague(a).then(K.render, function (e) { K.fail(e); a.failed = true; K.render(); });
        }),
      ].concat(a.tab === 'evening' ? eveningBlock(a) : tableBlock(a, l)).concat([
        h('div', { class: 'kk-two kk-two--cta' }, [
          h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { K.shareCard({ card: 'league', league_id: l.id }, l.invite_url, S.inviteText(l.name, l)); }, text: 'Позвать в лигу' }),
          l.is_owner ? h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { state.sheet = { kind: 'extend' }; K.render(); }, text: 'Продлить' }) : null,
        ]),
      ]));
      return [main];
    },
    sheet: function (s, a) {
      var l = state.leagueTables[lkey(headArgs(a))] || {};
      if (s.kind === 'points') return K.hubCards.pointsSheet();
      if (s.kind === 'menu') {
        return K.sheet('Лига', null, [
          l.is_owner ? h('button', { type: 'button', class: 'kk-pr', onclick: function () { state.sheet = editDraft(l); K.render(); } }, [h('span', { text: 'Изменить лигу' })]) : null,
          h('button', { type: 'button', class: 'kk-pr', onclick: function () { state.sheet = null; K.render(); K.copy(l.invite_url); } }, [h('span', { text: 'Скопировать ссылку' })]),
          !l.is_owner ? h('button', { type: 'button', class: 'kk-pr', onclick: function () { state.sheet = { kind: 'report', error: '', busy: false }; K.render(); } }, [h('span', { text: 'Пожаловаться на лигу' })]) : null,
          h('button', { type: 'button', class: 'kk-pr kk-pr--danger', onclick: function () { state.sheet = { kind: 'leave' }; K.render(); } }, [h('span', { text: 'Выйти из лиги' })]),
        ]);
      }
      if (s.kind === 'edit') return editSheet(s, a, l);
      if (s.kind === 'report') {
        return K.sheet('Пожаловаться на лигу?', null, [
          h('span', { class: 'kk-tx', text: 'Мы посмотрим картинку и текст этой лиги и уберём то, что не подходит. Владелец не узнает, что жалоба от тебя.' }),
          s.error ? h('span', { class: 'kk-tx kk-tx--err', role: 'alert', text: s.error }) : null,
          h('button', { type: 'button', class: 'kk-btn kk-btn--alt', text: 'Не надо', onclick: K.closeSheet }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--danger', disabled: s.busy ? 'true' : null, text: s.busy ? 'Отправляем…' : 'Пожаловаться', onclick: function () {
            s.busy = true;
            s.error = '';
            K.render();
            K.api('POST', '/client/hockey/leagues/' + a.id + '/report')
              .then(function () {
                K.haptic('success');
                K.closeSheet();
                K.toast('Спасибо, мы посмотрим');
              }, function (e) {
                s.busy = false;
                s.error = e.message;
                K.render();
              });
          } }),
        ]);
      }
      if (s.kind === 'leave') {
        var others = (l.items || []).filter(function (r) { return !r.is_me; });
        var text = 'Твои очки останутся в общей таблице. Вернуться можно по той же ссылке.';
        if (l.is_owner && others.length) text = 'Твои очки останутся в общей таблице. Лига перейдёт тому, кто здесь дольше всех. Вернуться можно по той же ссылке.';
        if (!others.length) text = 'В лиге больше никого — она исчезнет. Твои очки останутся в общей таблице.';
        return K.sheet('Выйти из «' + (l.name || '') + '»?', null, [
          h('span', { class: 'kk-tx', text: text }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--alt', text: 'Остаться', onclick: K.closeSheet }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--danger', text: 'Выйти', onclick: function () {
            var owner = K.current();
            K.api('DELETE', '/client/hockey/leagues/' + a.id + '/membership')
              .then(function () {
                state.leagueTables = {};
                state.leagues = null;
                if (K.current() !== owner) return;
                state.sheet = null;
                K.reset('hub', {});
              })
              .catch(K.fail);
          } }),
        ]);
      }
      if (s.kind === 'extend') {
        return K.sheet('Продлить «' + (l.name || '') + '»', null, [
          h('span', { class: 'kk-tx', text: 'Появится новая лига с теми же людьми и теми же командами — на следующий круг. Участникам придёт сообщение, выйти можно в один тап. Старая лига и её короны остаются.' }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--gold', text: 'Продлить', onclick: function () {
            var owner = K.current();
            K.api('POST', '/client/hockey/leagues/' + a.id + '/extend', {})
              .then(function (next) {
                state.leagues = null;
                K.haptic('success');
                if (K.current() !== owner) return K.toast(next.created ? 'Лига продлена: все уже внутри' : 'У лиги уже есть продолжение');
                state.sheet = null;
                K.replace('league', { id: next.id });
                K.toast(next.created ? 'Лига продлена: все уже внутри' : 'У лиги уже есть продолжение');
              })
              .catch(function (e) { if (K.current() === owner) K.closeSheet(); K.toast(e.message); });
          } }),
        ]);
      }
      return null;
    },
  });

  // ---------- Своя лига в один тап (TASK-431, макет Ready.dc.html) ----------

  function readyForm(a) {
    if (!a.form) a.form = { scope: 'all', clubs: [], stake: '' };
    return a.form;
  }

  /** «Позвать друзей»: лига создаётся только здесь (не при открытии экрана), потом — приглашение в чат. */
  function quickCreate(a) {
    var f = readyForm(a);
    var err = S.readyError(f) || Id().stakeError(f.stake);
    if (err) return K.toast(err);
    if (state.busy) return;
    state.busy = true;
    K.render();
    var owner = K.current();
    K.api('POST', '/client/hockey/leagues/quick', S.readyBody(f, Id().cleanStake(f.stake), state.src))
      .then(function (l) {
        state.busy = false;
        state.leagues = null;
        state.created = l;
        K.haptic('success');
        // Назад с лиги — не на «Лига готова»: повторный тап создал бы вопрос «а лига уже есть?».
        if (K.current() === owner) K.replace('league', { id: l.id, tab: 'evening' });
        K.shareCard({ card: 'league', league_id: l.id }, l.invite_url, S.inviteText(l.name, l));
      }, function (e) {
        state.busy = false;
        K.render();
        K.toast(e.message);
      });
  }

  function readyClubs(f) {
    var clubs = state.clubs || [];
    var maxClubs = state.maxClubs || null;
    return h('div', { class: 'kk-clubgrid' }, clubs.map(function (c) {
      var on = f.clubs.indexOf(c.name) >= 0;
      return h('button', {
        type: 'button', class: 'kk-club' + (on ? ' is-on' : ''), 'aria-pressed': on ? 'true' : 'false',
        onclick: function () {
          if (!on && maxClubs && f.clubs.length >= maxClubs) return K.toast('Не больше ' + maxClubs + ' команд');
          f.clubs = on ? f.clubs.filter(function (x) { return x !== c.name; }) : f.clubs.concat([c.name]);
          K.render();
        },
      }, [K.logoDisc(c, 34), h('span', { class: 'kk-club__n', text: S.clubShort(c.name) }), on ? h('span', { class: 'kk-ok', 'aria-hidden': 'true' }, [icon(I.check, 12)]) : null]);
    }));
  }

  K.register('ready', {
    enter: function (a) {
      var me = K.current();
      readyForm(a);
      a.info = null;
      a.failed = false;
      K.api('GET', '/client/hockey/leagues/quick').then(function (d) {
        // Своя действующая лига уже есть — вторую не собираем, открываем её «Вечер».
        if (d.league_id) {
          if (K.current() === me) K.replace('league', { id: d.league_id, tab: 'evening' });
          return;
        }
        a.info = d;
        K.render();
      }, function (e) {
        a.failed = true;
        K.render();
        K.fail(e);
      });
      K.loadClubs().then(K.render, function () {});
    },
    render: function (a) {
      var f = readyForm(a);
      var back = h('div', { class: 'kk-ready__top' }, [h('button', { type: 'button', class: 'kk-round', 'aria-label': 'Назад', onclick: K.back }, [icon(I.back)])]);
      if (!a.info) {
        return [h('main', { class: 'kk-main kk-ready' }, [back, a.failed ? K.retryCard('Не загрузилось.', function () { K.replace('ready', {}); }) : K.loading()])];
      }
      var err = S.readyError(f);
      return [h('main', { class: 'kk-main kk-ready' }, [
        back,
        h('div', { class: 'kk-ready__body' }, [
          h('span', { class: 'kk-ready__tag', 'aria-hidden': 'true', text: 'ТВОЯ ЛИГА ГОТОВА' }),
          h('h1', { class: 'kk-ready__name', text: a.info.name }),
          h('p', { class: 'kk-ready__tx', text: S.readyLine(f.scope, f.clubs) }),
          h('div', { class: 'kk-fld' }, [
            h('label', { for: 'kk-rstake', class: 'kk-ready__lbl', text: 'На что играем' }),
            h('input', { id: 'kk-rstake', class: 'kk-ready__input', type: 'text', maxlength: String(Id().STAKE_MAX), autocomplete: 'off', value: f.stake, oninput: function (e) { f.stake = e.target.value; } }),
          ]),
          h('div', { class: 'kk-fld' }, [
            h('span', { class: 'kk-ready__lbl', id: 'kk-rscope', text: 'Какие матчи' }),
            h('div', { class: 'kk-seg', role: 'group', 'aria-labelledby': 'kk-rscope' }, S.READY_SCOPES.map(function (it) {
              var on = f.scope === it[0];
              return h('button', { type: 'button', class: 'kk-seg__b' + (on ? ' is-on' : ''), 'aria-pressed': on ? 'true' : 'false', onclick: function () { f.scope = it[0]; K.render(); }, text: it[1] });
            })),
            f.scope === 'clubs' ? readyClubs(f) : null,
          ]),
          h('div', { class: 'kk-ready__list' }, [
            h('div', { class: 'kk-ready__row' }, [K.ava(state.profile && state.profile.display_name ? state.profile.display_name : a.info.name.replace(/^Лига\s+/, ''), 36), h('span', { class: 'kk-ready__who', text: 'Ты' }), h('span', { class: 'kk-ready__in', text: 'уже в лиге' })]),
            h('div', { class: 'kk-ready__row' }, [h('span', { class: 'kk-ready__ph', 'aria-hidden': 'true' }), h('span', { class: 'kk-ready__who is-empty', text: 'Здесь будет твой друг' })]),
            h('div', { class: 'kk-ready__row' }, [h('span', { class: 'kk-ready__ph', 'aria-hidden': 'true' }), h('span', { class: 'kk-ready__who is-empty', text: 'И ещё один' })]),
          ]),
          h('p', { class: 'kk-ready__note', text: 'Кепка дня разыгрывается, когда в лиге трое' }),
        ]),
        h('div', { class: 'kk-ready__cta' }, [
          h('button', { type: 'button', class: 'kk-btn kk-btn--gold kk-btn--lg kk-ready__go', disabled: err || state.busy ? 'true' : null, 'aria-disabled': err ? 'true' : 'false', onclick: function () { quickCreate(a); }, text: err || (state.busy ? 'Собираем…' : 'Позвать друзей') }),
          h('button', { type: 'button', class: 'kk-ready__alt', onclick: function () { K.go('leagueNew', {}); }, text: 'Изменить лигу' }),
        ]),
      ])];
    },
  });

  // ---------- Вход по ссылке ----------

  K.register('join', {
    enter: function (a) {
      state.joinCode = a.code;
      state.joinPreview = null;
      state.joinError = '';
      K.api('GET', '/hockey/leagues/' + encodeURIComponent(a.code), undefined, true)
        .then(function (p) { state.joinPreview = p; K.render(); })
        .catch(function (e) { state.joinError = e.status === 404 ? 'gone' : e.message; K.render(); });
    },
    render: function () {
      if (state.joinError === 'gone') {
        return [h('main', { class: 'kk-main kk-center' }, [
          h('h2', { class: 'kk-h2 kk-h2--xl', text: 'Этой лиги больше нет' }),
          h('span', { class: 'kk-sub', text: 'Все из неё вышли. Можно собрать свою или играть без лиги.' }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { K.replace('leagueNew', {}); }, text: 'Создать свою лигу' }),
          h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.reset('hub', {}); }, text: 'Играть без лиги' }),
        ])];
      }
      var p = state.joinPreview;
      var next = S.nextMatch(state.matches, { id: 0, home_team: '', away_team: '' });
      var face = p ? Id().faceOf(p) : null;
      return [h('main', { class: 'kk-main' }, [
        h('span', { class: 'kk-lbl', text: 'КТО КОГО?' }),
        p ? h('div', { class: 'kk-sec' }, [
          face ? h('div', { class: 'kk-joinimg', 'aria-hidden': 'true' }, [photo(face.src, 'kk-joinimg__img')]) : null,
          h('div', { class: 'kk-faces', 'aria-hidden': 'true' }, (p.names || []).slice(0, 5).map(function (n) { return K.ava(n, 48); })),
          h('span', { class: 'kk-tx', text: p.names && p.names[0] ? p.names[0] + ' зовёт тебя в лигу' : 'Тебя зовут в лигу' }),
          h('h2', { class: 'kk-h2 kk-h2--xl', text: p.name }),
          stakeEl(p, 'kk-stake'),
          h('span', { class: 'kk-tx', text: p.members + ' ' + M.plural(p.members, 'человек', 'человека', 'человек') + ' уже ' + M.plural(p.members, 'угадывает', 'угадывают', 'угадывают') }),
          next ? h('div', { class: 'kk-card kk-note' }, [h('span', { class: 'kk-lbl', text: 'БЛИЖАЙШИЙ МАТЧ' }), h('b', { class: 'kk-hd', text: S.clubName(next.home.name) + ' — ' + S.clubName(next.away.name) }), h('span', { class: 'kk-sub', text: M.whenLabel(next.starts_at, new Date()) })]) : null,
          h('span', { class: 'kk-sub', text: 'Тапаешь за команду или угадываешь счёт. После матча очки приходят сами. ' + M.RULES }),
        ]) : state.joinError ? h('span', { class: 'kk-tx', text: state.joinError }) : K.loading(),
        h('button', { type: 'button', class: 'kk-btn kk-btn--gold', disabled: !p || state.busy ? 'true' : null, onclick: joinLeague, text: 'Вступить в лигу' }),
        h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.reset('hub', {}); }, text: 'Посмотреть матчи' }),
      ])];
    },
  });

  function joinLeague() {
    state.busy = true;
    K.render();
    var owner = K.current();
    K.api('POST', '/client/hockey/leagues/join', { code: state.joinCode, from_card: state.fromCard || null })
      .then(function (l) {
        state.busy = false;
        state.created = l;
        state.leagues = null;
        K.haptic('success');
        if (K.current() === owner) K.replace('joined', {});
        else K.toast('Ты в лиге «' + l.name + '»');
      })
      .catch(function (e) {
        state.busy = false;
        K.toast(e.message);
      });
  }

  K.register('joined', {
    render: function () {
      var l = state.created;
      var next = S.nextMatch(state.matches, { id: 0, home_team: '', away_team: '' });
      if (!l) return [h('main', { class: 'kk-main' }, [K.loading()])];
      var face = Id().faceOf(l);
      return [h('main', { class: 'kk-main kk-center' }, [
        K.sticker('ТЫ В ЛИГЕ'),
        face ? h('span', { class: 'kk-badge-big kk-badge-big--img', 'aria-hidden': 'true' }, [photo(face.src, 'kk-badge-big__img')]) : null,
        h('h2', { class: 'kk-h2 kk-h2--xl', text: l.name }),
        stakeEl(l, 'kk-stake kk-stake--c'),
        h('span', { class: 'kk-sub', text: S.leagueSub(l) + '. Очки в лиге — за матчи после вступления.' }),
        next ? h('span', { class: 'kk-tx', text: 'Первый ход — ' + M.whenLabel(next.starts_at, new Date()).split(',')[0] + ': ' + S.clubName(next.home.name) + ' или ' + S.clubName(next.away.name) + '?' }) : h('span', { class: 'kk-tx', text: 'Как только матчи появятся в календаре, тапни за команду.' }),
        h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { K.reset('hub', {}); }, text: 'Тапнуть за команду' }),
      ])];
    },
  });

  // ---------- Итоги месяца ----------

  K.register('month', {
    render: function () {
      var res = state.month;
      if (!res) return [h('main', { class: 'kk-main' }, [K.loading()])];
      var won = res.won;
      return [h('main', { class: 'kk-main' }, [
        K.topbar('Итоги: ' + res.title, res.league ? '«' + res.league.name + '»' : 'общая таблица'),
        h('section', { class: 'kk-card kk-card--hero kk-center' }, [
          won ? (K.stand ? K.stand.moment() : K.crownIcon(64)) : h('span', { class: 'kk-big', text: res.rank ? String(res.rank) : '–' }),
          h('h2', { class: 'kk-h2 kk-h2--xl', text: M.monthHead(res) }),
          h('span', { class: 'kk-hero-tx', text: M.monthLine(res) }),
        ]),
        res.podium && res.podium.length ? h('div', { class: 'kk-tbl' }, res.podium.map(function (p) {
          return h('div', { class: 'kk-r' + (p.is_me ? ' is-me' : '') }, [
            h('span', { class: 'kk-r__n', text: String(p.rank) }),
            h('span', { class: 'kk-col kk-r__w' }, [h('span', { class: 'kk-r__name' }, [p.is_me ? 'Ты' : p.display_name, p.crown ? K.crownIcon(14) : null])]),
            h('span', { class: 'kk-r__pt', text: String(p.points) }),
          ]);
        })) : null,
        h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { brag(res); } }, [icon(I.send), won ? 'Похвастаться в чате' : res.winners && res.winners.length ? 'Поздравить в чате' : 'Позвать в новый месяц']),
        h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { K.reset('hub', {}); }, text: 'К матчам месяца' }),
      ])];
    },
  });

  function brag(res) {
    var leagues = state.leagues || [];
    var league = (res.league && leagues.filter(function (l) { return l.id === res.league.id; })[0]) || leagues[0];
    var where = res.league ? ' в «' + res.league.name + '»' : '';
    var who = (res.winners || []).join(' и ');
    var text = res.won
      ? 'Корона «Кто кого» за ' + res.title + where + ' — моя. Новый месяц, все с нуля: попробуй забрать.'
      : who
        ? 'Корона «Кто кого» за ' + res.title + where + ' досталась: ' + who + '. В новом месяце — реванш.'
        : '«Кто кого» за ' + res.title + where + ' — без короны. Новый месяц, все с нуля: играем?';
    K.shareCard({ card: 'crown', race_id: res.race_id }, league ? league.invite_url : null, text);
  }
})();
