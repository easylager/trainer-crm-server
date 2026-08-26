(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    if (typeof tg.ready === 'function') tg.ready();
    if (typeof tg.expand === 'function') tg.expand();
  }
  var initData = tg && tg.initData ? tg.initData : '';

  function apiUrl(path) {
    var url = '/api/webapp' + path;
    if (initData) url += (url.indexOf('?') >= 0 ? '&' : '?') + 'init_data=' + encodeURIComponent(initData);
    return url;
  }

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function initialsFromLabel(label) {
    if (!label) return '?';
    var parts = String(label).trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return parts[0].slice(0, 2).toUpperCase();
  }

  /** Shorter role line: avoids «владелец» next to the child’s name (profile is the child; Telegram is the parent’s). */
  function roleCaption(role, isViewer) {
    if (role === 'owner') {
      return isViewer
        ? 'Основной Telegram — приглашения и отзыв доступа'
        : 'Основной Telegram — к нему привязаны имя и телефон в профиле';
    }
    return isViewer
      ? 'Ваш Telegram — доступ по приглашению'
      : 'Дополнительный Telegram — общие записи и абонементы';
  }

  function childProfileName(members) {
    var m = (members || []).filter(function (x) {
      return x.role === 'owner';
    })[0];
    var label = (m && m.display_label) || '';
    return String(label).trim();
  }

  function setIntro(data) {
    var introEl = document.getElementById('cfaIntro');
    var maxExtra = Number(data.max_extra_members) || 0;
    var extraN = Number(data.extra_members_count) || 0;
    var canManage = !!data.can_manage;
    var child = childProfileName(data.members);
    if (canManage) {
      if (extraN >= maxExtra) {
        introEl.textContent =
          'Лимит приглашённых исчерпан (' +
          maxExtra +
          '). Чтобы отправить ссылку другому человеку, сначала отзовите доступ у участника ниже.';
      } else {
        introEl.textContent =
          'Пригласите близкого по ссылке — один профиль на семью: общие записи и абонементы с разных Telegram.';
      }
    } else {
      introEl.textContent = child
        ? 'Профиль «' +
          child +
          '»: вы вошли с дополнительного Telegram. Записи и абонементы общие; приглашать близких может только основной Telegram выше.'
        : 'Вы подключены к семейному аккаунту с дополнительного Telegram. Записи и абонементы общие; пригласить близкого может только основной Telegram в списке.';
    }
  }

  function showState(el, text, isErr) {
    el.style.display = 'block';
    el.textContent = text;
    el.className = 'cfa-state' + (isErr ? ' err' : '');
  }

  function render(data) {
    var listEl = document.getElementById('cfaList');
    var limitEl = document.getElementById('cfaLimit');
    var actionsEl = document.getElementById('cfaActions');
    var stateEl = document.getElementById('cfaState');
    stateEl.style.display = 'none';
    var maxExtra = Number(data.max_extra_members) || 0;
    var extraN = Number(data.extra_members_count) || 0;
    var canManage = !!data.can_manage;
    var rawVid = data.viewer_telegram_id;
    var viewerTid = rawVid == null || rawVid === '' ? NaN : Number(rawVid);

    setIntro(data);

    limitEl.style.display = 'block';
    limitEl.textContent = canManage
      ? 'Приглашённых по ссылке: ' +
        extraN +
        ' из ' +
        maxExtra +
        '. Телефон в профиле один — привязан к основному Telegram.'
      : 'Дополнительных Telegram: ' +
        extraN +
        ' из ' +
        maxExtra +
        '. Номер телефона в профиле тот же, что у основного входа.';

    var members = data.members || [];
    listEl.innerHTML = members
      .map(function (m) {
        var tid = m.telegram_id;
        var isYou = !isNaN(viewerTid) && Number(tid) === viewerTid;
        var revoke =
          canManage &&
          m.role === 'member'
            ? '<button type="button" class="cfa-btn cfa-btn--danger" data-revoke="' +
              String(tid) +
              '">Отозвать</button>'
            : '';
        return (
          '<div class="cfa-member">' +
          '<div class="cfa-member__avatar">' +
          esc(initialsFromLabel(m.display_label)) +
          '</div>' +
          '<div class="cfa-member__meta">' +
          '<div class="cfa-member__label">' +
          esc(m.display_label || 'Telegram') +
          '</div>' +
          '<div class="cfa-member__role">' +
          esc(roleCaption(m.role, isYou)) +
          '</div>' +
          '</div>' +
          revoke +
          '</div>'
        );
      })
      .join('');

    actionsEl.style.display = canManage && extraN < maxExtra ? 'flex' : 'none';

    listEl.querySelectorAll('[data-revoke]').forEach(function (btn) {
      btn.onclick = function () {
        var id = Number(btn.getAttribute('data-revoke'));
        if (!id || !window.confirm('Отозвать доступ у этого Telegram?')) return;
        fetch(apiUrl('/client/family-access/revoke'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ member_telegram_id: id }),
        })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail || r.status); });
            return load();
          })
          .catch(function (e) {
            showState(stateEl, String(e.message || e), true);
          });
      };
    });
  }

  function load() {
    var stateEl = document.getElementById('cfaState');
    return fetch(apiUrl('/client/family-access'))
      .then(function (r) {
        if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail || 'Ошибка'); });
        return r.json();
      })
      .then(render)
      .catch(function (e) {
        showState(stateEl, String(e.message || e), true);
      });
  }

  document.getElementById('btnInvite').onclick = function () {
    var stateEl = document.getElementById('cfaState');
    stateEl.style.display = 'none';
    fetch(apiUrl('/client/family-access/invite'), { method: 'POST' })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail || r.status); });
        return r.json();
      })
      .then(function (o) {
        var link = (o && o.invite_url) || '';
        if (!link) throw new Error('Нет ссылки');
        var msg =
          'Привет! Подключайся к нашему семейному доступу в приложении Glide — общие записи и абонементы:\n' +
          link;
        if (typeof window.openTelegramShareUrlFromMiniApp === 'function') {
          window.openTelegramShareUrlFromMiniApp({ fullMessage: msg });
        } else {
          try {
            if (tg && typeof tg.openTelegramLink === 'function') {
              tg.openTelegramLink(
                'https://t.me/share/url?url=' + encodeURIComponent(link) + '&text=' + encodeURIComponent(msg)
              );
            }
          } catch (e2) {
            showState(stateEl, 'Не удалось открыть шаринг. Скопируйте ссылку вручную:\n' + link, true);
          }
        }
      })
      .catch(function (e) {
        showState(stateEl, String(e.message || e), true);
      });
  };

  load();
})();
