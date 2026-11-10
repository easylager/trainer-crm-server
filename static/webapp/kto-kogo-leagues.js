/**
 * «Кто кого» — лиги (TASK-334 S5): новая лига (команды + срок + сводка), лига изнутри (месяц / весь срок,
 * «Продлить», «Позвать»), вход по ссылке, итоги месяца. Холст: LeagueNew, League.
 * Лига = название + команды + срок; ходить отдельно не нужно, считаются матчи после вступления.
 */
(function () {
  'use strict';

  var K = window.KK;
  var h = K.h;
  var M = K.M;
  var S = K.S;
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

  function seg(items, current, onPick, label) {
    return h('div', { class: 'kk-seg', role: 'group', 'aria-label': label }, items.map(function (it) {
      var on = it[0] === current;
      return h('button', { type: 'button', class: 'kk-seg__b' + (on ? ' is-on' : ''), 'aria-pressed': on ? 'true' : 'false', onclick: function () { onPick(it[0]); }, text: it[1] });
    }));
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
    var sub = (r.title && r.title.label ? r.title.label + (r.title.detail ? ' · ' + r.title.detail : '') + ' · ' : '') + S.rowSub(r);
    return h('div', { class: 'kk-r' + (r.is_me ? ' is-me' : '') }, [
      h('span', { class: 'kk-r__n' + (r.rank === 1 ? ' is-gold' : ''), text: String(r.rank) }),
      h('span', { class: 'kk-col kk-r__w' }, [h('span', { class: 'kk-r__name' }, [h('span', { class: 'kk-r__nm', text: r.display_name }), r.is_me ? h('span', { class: 'kk-me', text: 'ты' }) : null, K.crownTag(r.crowns)]), h('span', { class: 'kk-sub', text: sub })]),
      h('span', { class: 'kk-r__pt', text: String(r.points) }),
    ]);
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
      loadLeague(a, true).then(K.render, function (e) {
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
      var key = lkey(a);
      K.api('GET', base + (a.tab === 'month' ? '?period=month' : '')).then(function (d) {
        state.leagues = null;
        state.leagueTables = {};
        state.leagueTables[key] = d;
        K.render();
      }, function () {});
    });
  }

  K.register('league', {
    enter: function (a) {
      a.tab = a.tab || 'all';
      a.failed = false;
      Promise.all([loadLeague(a, true), K.loadClubs().catch(function () {})]).then(K.render, function (e) {
        K.fail(e);
        a.failed = true;
        K.render();
      });
    },
    render: function (a) {
      a.tab = a.tab || 'all';
      var l = state.leagueTables[lkey(a)];
      var monthName = S.periodLabel(S.monthKey(nowIso()));
      if (!l) return [h('main', { class: 'kk-main' }, [K.topbar('Лига', null), a.failed ? K.retryCard('Лига не загрузилась.', function () { a.failed = false; K.render(); K.replace('league', a); }) : K.loading()])];
      var items = l.items || [];
      var me = items.filter(function (r) { return r.is_me; })[0];
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
        seg([['month', monthName], ['all', 'Вся лига']], a.tab, function (id) {
          a.tab = id;
          a.failed = false;
          K.render();
          loadLeague(a).then(K.render, function (e) { K.fail(e); a.failed = true; K.render(); });
        }, 'Период таблицы'),
        h('div', { class: 'kk-crownbar' }, [K.crownIcon(18), h('span', { text: S.leagueCrownLine(l, a.tab, me, items[0] ? items[0].points : 0) })]),
        items.length > 1 ? h('div', { class: 'kk-tbl' }, items.map(leagueRow)) : h('span', { class: 'kk-sub', text: 'Пока в лиге только ты. Позови своих — таблица оживёт после первого матча.' }),
        a.tab === 'all' ? crownWall(l.wall) : null,
        h('div', { class: 'kk-two kk-two--cta' }, [
          h('button', { type: 'button', class: 'kk-btn kk-btn--gold', onclick: function () { K.shareCard({ card: 'league', league_id: l.id }, l.invite_url, S.inviteText(l.name, l)); }, text: 'Позвать в лигу' }),
          l.is_owner ? h('button', { type: 'button', class: 'kk-btn kk-btn--alt', onclick: function () { state.sheet = { kind: 'extend' }; K.render(); }, text: 'Продлить' }) : null,
        ]),
      ]);
      return [main];
    },
    sheet: function (s, a) {
      var l = state.leagueTables[lkey(a)] || {};
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
          won ? K.crownIcon(64) : h('span', { class: 'kk-big', text: res.rank ? String(res.rank) : '–' }),
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
