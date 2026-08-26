(function(){
'use strict';

var reduce   = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
var isMobile = function(){ return window.matchMedia('(max-width: 860px)').matches; };

/* ══════════════════════════ HERO ═══════════════════════════════════════ */
var mini       = document.getElementById('mini');
var chatBody   = document.getElementById('chatBody');
var notif      = document.getElementById('notif');
var inbox      = document.getElementById('inbox');
var hero       = document.getElementById('hero');
var replay     = document.getElementById('replay');
var confirmBtn = document.getElementById('confirmBtn');
var shareBtn    = document.getElementById('shareBtn');
var inviteSheet = document.getElementById('inviteSheet');
var inviteCopy  = document.getElementById('inviteCopy');
var beats      = [].slice.call(document.querySelectorAll('.beat'));

var targetSlot   = document.getElementById('targetSlot');
var targetName   = document.getElementById('targetName');
var targetStatus = document.getElementById('targetStatus');
var freeCount    = document.getElementById('freeCount');
var bookedCount  = document.getElementById('bookedCount');

var timers = [], idleTimer = null, engaged = false, state = 0;

function after(ms, fn){ var t = setTimeout(fn, reduce ? Math.min(ms,40) : ms); timers.push(t); return t; }
function clearTimers(){ timers.forEach(clearTimeout); timers = []; }
function setBeat(n){
  hero.classList.toggle('is-running', n > 0);
  beats.forEach(function(b,i){
    b.classList.toggle('is-done', i < n-1);
    b.classList.toggle('is-on',  i === n-1);
  });
}
var colClient     = document.querySelector('.col--client');
var colTrainer    = document.querySelector('.col--trainer');
var surfClientEl  = document.getElementById('surfClient');
var surfTrainerEl = document.getElementById('surfTrainer');

/* Directs the eye: `w` leads, the other recedes. 'none' returns both to rest. */
function side(w){
  hero.setAttribute('data-side', w);           /* only has effect at <=860px */
  if (isMobile()){
    colClient.classList.remove('col--lead','col--rest');
    colTrainer.classList.remove('col--lead','col--rest');
    return;
  }
  var lead = w === 'trainer' ? colTrainer : (w === 'client' ? colClient : null);
  var rest = w === 'trainer' ? colClient  : (w === 'client' ? colTrainer : null);
  [colClient, colTrainer].forEach(function(c){ c.classList.remove('col--lead','col--rest'); });
  if (lead){ lead.classList.add('col--lead'); rest.classList.add('col--rest'); }
}

function bubble(html, meta, ok){
  var el = document.createElement('div');
  el.className = 'bubble enterable' + (ok ? ' bubble--ok' : '');
  el.innerHTML = html + (meta ? '<span class="bubble__meta">' + meta + '</span>' : '');
  chatBody.appendChild(el);
  requestAnimationFrame(function(){ requestAnimationFrame(function(){
    el.classList.add('is-in');
    chatBody.scrollTop = chatBody.scrollHeight;
  });});
}
function divider(text){
  var el = document.createElement('span');
  el.className = 'divider enterable';
  el.textContent = text;
  chatBody.appendChild(el);
  requestAnimationFrame(function(){ requestAnimationFrame(function(){ el.classList.add('is-in'); });});
}
function tick(el, val){
  el.textContent = val;
  el.classList.add('is-tick');
  after(1500, function(){ el.classList.remove('is-tick'); });
}

/* Beat 1 — you send the link. The client does not exist in the story yet;
   this is the beat that brings them in. Real sheet: trainer-home.html:732. */
function beat1(){
  state = 1; setBeat(1);
  side('trainer');
  inviteSheet.classList.add('is-up');
  /* Deliberately unhurried: the sheet has to be read, not glimpsed. */
  after(reduce ? 20 : 1150, function(){
    inviteCopy.classList.add('is-done');
    after(reduce ? 20 : 780, function(){
      inviteSheet.classList.remove('is-up');
      /* the client's screen is drawn out from behind the trainer's */
      after(reduce ? 20 : 260, function(){
        hero.classList.add('is-live');
        side('client');
        after(reduce ? 20 : 1350, beat2);
      });
    });
  });
}

/* Beat 2 — the client picks a time. Deliberately automatic: the whole promise
   is that this happens without you. booking-client.js:217 */
function beat2(){
  state = 2; setBeat(2);
  var pick = document.getElementById('slotPick');
  /* the client's choice registers before the sheet closes */
  pick.classList.add('slot-card--taken');
  after(reduce ? 20 : 620, function(){ mini.classList.add('is-closed'); });
  after(reduce ? 20 : 980, function(){
    bubble('✅ <b>Вы записаны</b>.<br><br>Ожидайте подтверждения от тренера в боте.', '18:42', true);
    /* The slot is blocked immediately — this is what the real notification
       means by «Слот занят». schedule.html statusLabel: booked → «занят».
       The lead moves to the trainer on the same frame the row fills; this is
       the beat that has to land, so it gets its own breathing room. */
    after(reduce ? 20 : 1050, function(){
      side('trainer');
      targetSlot.classList.remove('s-card--free');
      targetSlot.classList.add('s-card--new','s-card--sweep');
      targetName.textContent = 'Анна К.';
      targetName.classList.remove('s-client--muted');
      targetStatus.textContent = 'занят';
      targetStatus.classList.remove('s-status--free');
      tick(freeCount, '3');
      tick(bookedCount, '14 из 17');
      after(1400, function(){ targetSlot.classList.remove('s-card--sweep'); });
    });
    after(reduce ? 20 : (isMobile() ? 2200 : 1900), beat3);
  });
}

/* Beat 3 — the request reaches you. messages.py:2815 + trainer-home-main.js:2354 */
function beat3(){
  state = 3; setBeat(3);
  side('trainer');
  if (isMobile()){ notif.classList.add('notif--mobile'); document.body.appendChild(notif); }
  notif.classList.add('is-in');
  after(reduce ? 20 : 2600, function(){
    notif.classList.remove('is-in');
    inbox.classList.add('is-shown');
    if (!engaged) after(reduce ? 20 : 1600, beat4);
  });
}

/* Beat 4 — one tap. */
function beat4(){
  if (state >= 4) return;
  state = 4; setBeat(4);
  inbox.classList.remove('is-shown');
  after(reduce ? 20 : 500, beat5);
}

/* Beat 5 — both sides settle, then the reminder. messages.py:1119 / :1372 */
function beat5(){
  state = 5; setBeat(5);
  targetSlot.classList.remove('s-card--new');
  after(reduce ? 20 : 560, function(){
    side('client');
    bubble('✅ <b>Ваша запись подтверждена!</b>' +
           '<div class="bubble__rows">' +
           '📅 <b>18 июня (ср) 18:00</b> — 60 мин.<br>' +
           '🎯 Фигурное катание<br>' +
           '📍 Минск · 🏟 Minsk Arena' +
           '</div>', '18:44', true);
    after(reduce ? 20 : 1800, reminder);
  });
}

/* Tail of beat 5 — later, on its own. messages.py:1372 CLIENT_REMINDER_24H */
function reminder(){
  divider('накануне');
  after(reduce ? 20 : 440, function(){
    bubble('⏰ <b>Напоминание о занятии</b>' +
           '<div class="bubble__rows">' +
           '📅 <b>18 июня</b> (ср) · 18:00<br>' +
           '⏱ Длительность: 60 мин.' +
           '</div>' +
           'Адрес и детали — в <b>«Мои записи»</b> (меню бота).', '17:00');
    replay.classList.add('is-shown');
  });
}

function reset(){
  clearTimers();
  state = 0; setBeat(0);
  /* back to one surface: the client is not in the story yet */
  hero.classList.remove('is-live');
  inviteSheet.classList.remove('is-up');
  inviteCopy.classList.remove('is-done');
  document.getElementById('slotPick').classList.remove('slot-card--taken');
  mini.classList.remove('is-closed');
  notif.classList.remove('is-in');
  inbox.classList.remove('is-shown');
  targetSlot.classList.add('s-card--free');
  targetSlot.classList.remove('s-card--new');
  targetName.textContent = 'Свободно';
  targetName.classList.add('s-client--muted');
  targetStatus.textContent = 'свободен';
  targetStatus.classList.add('s-status--free');
  freeCount.textContent = '4';          freeCount.classList.remove('is-tick');
  bookedCount.textContent = '13 из 17'; bookedCount.classList.remove('is-tick');
  /* prior history — messages.py:20 CLIENT_START_WELCOME, verbatim */
  chatBody.innerHTML =
    '<span class="divider is-in">сегодня</span>' +
    '<div class="bubble enterable is-in">👋 Привет! Здесь можно найти тренера и записаться на занятие. ' +
    'Нажмите кнопку <b>Главная</b> слева от поля ввода — там каталог, записи и заявки. Помощь: /guide' +
    '<span class="bubble__meta">18:39</span></div>';
  replay.classList.remove('is-shown');
  side('none');   /* at rest neither surface leads — the page is calm */
}

function engage(){ engaged = true; clearTimeout(idleTimer); }

/* Tap 1 — send the link. */
[shareBtn, inviteCopy].forEach(function(el){
  el.addEventListener('click', function(){
    if (state !== 0) return;
    engage(); clearTimers(); beat1();
  });
});
/* Tap 2 — confirm. */
confirmBtn.addEventListener('click', function(){ engage(); clearTimers(); beat4(); });
notif.addEventListener('click', function(){
  if (!isMobile() || state !== 3) return;
  engage(); clearTimers();
  notif.classList.remove('is-in');
  side('trainer');
  inbox.classList.add('is-shown');
});
replay.addEventListener('click', function(){ reset(); after(280, beat1); });

function armIdle(){
  clearTimeout(idleTimer);
  idleTimer = setTimeout(function(){
    if (engaged || state !== 0) return;
    beat1();
  }, 4600);
}
if ('IntersectionObserver' in window){
  var io = new IntersectionObserver(function(en){
    en.forEach(function(e){ if (e.isIntersecting){ armIdle(); io.disconnect(); } });
  }, { threshold:.4 });
  io.observe(document.getElementById('surfClient'));
} else { armIdle(); }

document.getElementById('logoImg').addEventListener('error', function(){
  var box = document.getElementById('logoBox');
  box.classList.add('logo--fallback');
  box.textContent = '';
});

reset();

/* ══════════════════ SECTION 2 — real UI fragments ══════════════════════ */
/* Each fragment is a small piece of a real screen — real markup, real labels,
   real field names. Nothing here is a capability the product doesn't have. */
var FRAGS = [
  /* 0 — Запись · book.html */
  { cap:'Экран клиента · запись',
    html:
      '<p class="frag__screen">Выберите время</p>' +
      '<div class="day-title">Среда, 18 июня</div>' +
      '<div class="slot-card" style="cursor:default">' +
        '<span class="slot-card-body"><span class="slot-time">18:00–19:00</span>' +
        '<span class="slot-venue-pill">Minsk Arena</span></span>' +
        '<span class="slot-arrow">›</span></div>' +
      '<div class="slot-card" style="cursor:default">' +
        '<span class="slot-card-body"><span class="slot-time">19:00–20:00</span>' +
        '<span class="slot-venue-pill">Minsk Arena</span></span>' +
        '<span class="slot-arrow">›</span></div>' +
      '<div class="day-title">Четверг, 19 июня</div>' +
      '<div class="slot-card" style="cursor:default">' +
        '<span class="slot-card-body"><span class="slot-time">07:30–08:30</span>' +
        '<span class="slot-venue-pill">Чижовка-Арена</span></span>' +
        '<span class="slot-arrow">›</span></div>'
  },
  /* 1 — Расписание · schedule.html */
  { cap:'Экран тренера · расписание',
    html:
      '<p class="frag__screen">Моё расписание</p>' +
      '<div class="sched__chips" style="margin-bottom:12px">' +
        '<span class="chip chip--on">Все</span><span class="chip">Свободны</span><span class="chip">Заняты</span></div>' +
      '<div class="day-title">Среда, 18 июня</div>' +
      '<div class="s-card s-card--a"><div class="s-main">' +
        '<div class="s-time">16:00–17:00</div><div class="s-client">Максим</div>' +
        '<div class="s-venue">Фигурное катание · 📍 Minsk Arena</div></div>' +
        '<span class="s-status">занят</span></div>' +
      '<div class="s-card s-card--free"><div class="s-main">' +
        '<div class="s-time">18:00–19:00</div><div class="s-client s-client--muted">Свободно</div>' +
        '<div class="s-venue">Фигурное катание · 📍 Minsk Arena</div></div>' +
        '<span class="s-status s-status--free">свободен</span></div>' +
      '<div class="s-card"><div class="s-main">' +
        '<div class="s-time">19:00–20:00</div><div class="s-client">Дарья</div>' +
        '<div class="s-venue">Фигурное катание · 📍 Minsk Arena</div></div>' +
        '<span class="s-status">занят</span></div>'
  },
  /* 2 — Клиенты · trainer-clients.html */
  { cap:'Экран тренера · клиенты',
    html:
      '<p class="frag__screen">Мои клиенты</p>' +
      '<div class="sched__chips" style="margin-bottom:12px">' +
        '<span class="chip chip--on">Все</span><span class="chip">Постоянные</span>' +
        '<span class="chip">С абонементом</span></div>' +
      '<div class="c-card"><span class="c-av">АК</span><div class="c-main">' +
        '<div class="c-nameRow"><span class="c-name">Анна К.</span>' +
        '<span class="c-pill">Постоянный</span></div>' +
        '<div class="c-meta">+375 29 ··· 41 07</div>' +
        '<div class="c-meta">Последнее занятие: 11 июня</div></div>' +
        '<span class="c-arrow">→</span></div>' +
      '<div class="c-card"><span class="c-av">МД</span><div class="c-main">' +
        '<div class="c-nameRow"><span class="c-name">Максим Д.</span>' +
        '<span class="c-pill">Абонемент · 6</span></div>' +
        '<div class="c-meta">+375 33 ··· 12 88</div>' +
        '<div class="c-meta">Последнее занятие: вчера</div></div>' +
        '<span class="c-arrow">→</span></div>' +
      '<div class="c-card"><span class="c-av">ДС</span><div class="c-main">' +
        '<div class="c-nameRow"><span class="c-name">Дарья С.</span>' +
        '<span class="c-pill c-pill--gray">Нет в боте</span></div>' +
        '<div class="c-meta">+375 44 ··· 90 33</div>' +
        '<div class="c-meta">Последнее занятие: 3 июня</div></div>' +
        '<span class="c-arrow">→</span></div>'
  },
  /* 3 — Заметки · dossier (trainer-clients-main.js:2321) */
  { cap:'Досье клиента · Анна К.',
    html:
      '<p class="frag__screen">Профиль клиента</p>' +
      '<div class="d-sec">' +
        '<div class="d-field"><p class="d-label">Цель сезона</p>' +
          '<p class="d-val">Чисто откатать короткую программу к декабрю</p></div>' +
        '<div class="d-field"><p class="d-label">Цели</p>' +
          '<p class="d-val">Стабильный двойной аксель</p></div>' +
        '<div class="d-field"><p class="d-label">Ограничения / Травмы</p>' +
          '<p class="d-val d-val--empty">Нажмите, чтобы добавить</p></div>' +
      '</div>' +
      '<div class="d-sec"><p class="d-secTitle">Метки</p>' +
        '<div class="d-tags">' +
          '<span class="d-tag">2-й разряд</span><span class="d-tag">Соревнования</span>' +
          '<span class="d-tag">Утро</span><span class="d-tag">Прыжки</span></div></div>'
  },
  /* 4 — Абонементы и сертификаты · trainer-pass-products.html + client-passes.html.
         Backed by real tables: TrainerPassProduct / PassInstance / PassRedemption /
         TrainerCertificateProduct (src/infrastructure/db/models.py). */
  { cap:'Экран тренера · продажи',
    html:
      '<p class="frag__screen">Абонементы и сертификаты</p>' +
      '<div class="sched__chips" style="margin-bottom:12px">' +
        '<span class="chip chip--on">Абонементы</span><span class="chip">Сертификаты</span>' +
        '<span class="chip">Выданы</span></div>' +
      '<div class="p-card">' +
        '<div class="p-head"><span class="p-name">Абонемент · 8 занятий</span>' +
        '<span class="p-tag">Активен</span></div>' +
        '<p class="p-meta">🎯 Фигурное катание · срок действия 60 дней</p>' +
        '<div class="p-left"><span class="p-leftNum">5</span>' +
        '<span class="p-leftLbl">осталось занятий из 8</span></div>' +
        '<span class="p-bar"><span class="p-barFill" style="width:62%"></span></span>' +
      '</div>' +
      '<div class="p-card">' +
        '<div class="p-head"><span class="p-name">Подарочный сертификат</span>' +
        '<span class="p-tag">Выдан</span></div>' +
        '<p class="p-meta">Активируется кодом в боте</p>' +
        '<p class="p-nom">Номинал: 120 BYN</p>' +
      '</div>'
  },
  /* 5 — Каталог Glide · catalog.html */
  { cap:'Каталог Glide · как вас видят',
    html:
      '<p class="frag__screen">Найдите тренера</p>' +
      '<div class="sched__chips" style="margin-bottom:12px">' +
        '<span class="chip chip--on">Минск</span><span class="chip">Фигурное катание</span></div>' +
      '<div class="t-card"><span class="t-photo"></span><div class="t-info">' +
        '<div class="t-name">Алексей</div>' +
        '<div class="t-meta">Минск · фигурное катание</div>' +
        '<div class="t-meta">Minsk Arena, Чижовка-Арена</div>' +
        '<span class="t-badge">Набор в группу</span></div>' +
        '<span class="c-arrow">→</span></div>' +
      '<div class="t-card"><span class="t-photo"></span><div class="t-info">' +
        '<div class="t-name">Ирина</div>' +
        '<div class="t-meta">Минск · фигурное катание</div>' +
        '<div class="t-meta">Чижовка-Арена</div></div>' +
        '<span class="c-arrow">→</span></div>'
  },
  /* 6 — Реферальная программа · trainer-referral.html (labels verbatim) */
  { cap:'Экран тренера · рефералы',
    html:
      '<p class="frag__screen">Пригласи коллегу</p>' +
      '<div class="r-link"><span class="r-linkVal">t.me/glide_bot?start=ref_a4f2</span>' +
        '<span class="r-copy">Копировать</span></div>' +
      '<div class="r-grid">' +
        '<div class="r-tile"><span class="r-val r-val--accent">14</span>' +
          '<span class="r-lbl">Бонусных дней</span></div>' +
        '<div class="r-tile"><span class="r-val">6</span>' +
          '<span class="r-lbl">Приглашено</span></div>' +
        '<div class="r-tile"><span class="r-val">3</span>' +
          '<span class="r-lbl">Оплатили</span></div>' +
      '</div>' +
      '<div class="r-rules">' +
        '<div class="r-rule"><span class="r-ruleN">+2</span>' +
          '<span>дня — коллега заполнил базовый профиль</span></div>' +
        '<div class="r-rule"><span class="r-ruleN">+3</span>' +
          '<span>дня — первая подтверждённая или проведённая запись</span></div>' +
        '<div class="r-rule"><span class="r-ruleN">+7</span>' +
          '<span>дней — первая оплата подписки</span></div>' +
      '</div>'
  },
  /* 7 — Аналитика · trainer-stats.html */
  { cap:'Экран тренера · аналитика',
    html:
      '<p class="frag__screen">Статистика и выручка</p>' +
      '<p class="a-title">6 недель · занятия</p>' +
      '<div class="a-card"><div class="a-bars">' +
        '<div class="a-barWrap"><div class="a-barTrack"><div class="a-bar" style="height:44%"></div></div><div class="a-barLbl">12.05</div></div>' +
        '<div class="a-barWrap"><div class="a-barTrack"><div class="a-bar" style="height:58%"></div></div><div class="a-barLbl">19.05</div></div>' +
        '<div class="a-barWrap"><div class="a-barTrack"><div class="a-bar" style="height:38%"></div></div><div class="a-barLbl">26.05</div></div>' +
        '<div class="a-barWrap"><div class="a-barTrack"><div class="a-bar" style="height:66%"></div></div><div class="a-barLbl">02.06</div></div>' +
        '<div class="a-barWrap"><div class="a-barTrack"><div class="a-bar" style="height:72%"></div></div><div class="a-barLbl">09.06</div></div>' +
        '<div class="a-barWrap"><div class="a-barTrack"><div class="a-bar is-active" style="height:88%"></div></div><div class="a-barLbl">16.06</div></div>' +
      '</div><p class="a-foot">Последний столбец — текущая неделя</p></div>' +
      '<p class="a-title">Загрузка слотов</p>' +
      '<div class="a-card"><div class="a-load">' +
        '<div class="a-ring" style="--pct:76"><div class="a-ringIn">76%</div></div>' +
        '<div class="a-loadCopy"><p class="a-kLabel">Эта неделя</p>' +
        '<p class="a-kVal">13 из 17</p>' +
        '<p class="a-kSub">Свободно слотов: <strong>4</strong></p></div>' +
      '</div></div>'
  }
];

var COUNT = FRAGS.length;

/* ── Desktop: sticky, scroll-driven ─────────────────────────────────────── */
var rm       = document.getElementById('rm');
var rmSpacer = document.getElementById('rmSpacer');
var rmStage  = document.getElementById('rmStage');
var rmFill   = document.getElementById('rmFill');
var rmItems  = [].slice.call(document.querySelectorAll('.rm__item'));
var rmDone   = document.getElementById('rmDone');
var rmDoneLn = document.getElementById('rmDoneLine');

/* build fragment nodes once */
var fragNodes = FRAGS.map(function(f){
  var d = document.createElement('div');
  d.className = 'frag';
  d.innerHTML = '<p class="frag__cap">' + f.cap + '</p>' + f.html;
  rmStage.appendChild(d);
  return d;
});

/* scroll distance: one screen per stage + a tail for the assembly */
rmSpacer.style.height = (COUNT * 58 + 55) + 'vh';

var current = -1, currentAsm = null;
function setStage(i, assembled){
  /* Both index and assembled-ness gate the update — keying on index alone
     left the last item stuck "active" once the chain assembled. */
  if (i === current && assembled === currentAsm) return;
  current = i; currentAsm = assembled;
  fragNodes.forEach(function(n,k){ n.classList.toggle('is-on', k === i); });
  rmItems.forEach(function(it,k){
    it.classList.toggle('is-on',   k === i && !assembled);
    it.classList.toggle('is-past', assembled || k < i);
  });
  rmDone.classList.toggle('is-on', !!assembled);
  rmDoneLn.classList.toggle('is-on', !!assembled);
}

function onScroll(){
  if (isMobile()) return;
  var r = rm.getBoundingClientRect();
  var total = rm.offsetHeight - window.innerHeight;
  if (total <= 0) return;
  var p = Math.min(1, Math.max(0, -r.top / total));
  /* reserve the last 12% for the assembled state */
  var assembled = p > 0.88;
  var idx = Math.min(COUNT - 1, Math.floor((p / 0.88) * COUNT));
  setStage(idx, assembled);
  rmFill.style.height = (assembled ? 100 : ((idx + 0.5) / COUNT) * 100) + '%';
}

/* ── Mobile: linear story, scroll reveals but never hides ───────────────── */
var rmmList  = document.getElementById('rmmList');
var rmmFill  = document.getElementById('rmmFill');
var rmmChips = document.getElementById('rmmChips');
var NAMES = ['Запись','Расписание','Клиенты','Заметки',
             'Абонементы и сертификаты','Каталог Glide','Реферальная программа','Аналитика'];

function buildMobile(){
  if (rmmList.dataset.built) return;
  rmmList.dataset.built = '1';
  rmItems.forEach(function(src, i){
    var li = document.createElement('li');
    li.className = 'rmm__item';
    li.innerHTML =
      '<span class="rmm__dot"></span>' +
      '<p class="rmm__name">' + NAMES[i] + '</p>' +
      '<p class="rmm__desc">' + src.querySelector('.rm__desc').textContent + '</p>' +
      '<div class="rmm__stage"><div class="frag is-on">' +
        '<p class="frag__cap">' + FRAGS[i].cap + '</p>' + FRAGS[i].html +
      '</div></div>';
    rmmList.appendChild(li);
  });
  NAMES.forEach(function(n){
    var s = document.createElement('span');
    s.className = 'rm__doneChip';
    s.textContent = n;
    rmmChips.appendChild(s);
  });

  var items = [].slice.call(rmmList.querySelectorAll('.rmm__item'));
  if ('IntersectionObserver' in window && !reduce){
    var mo = new IntersectionObserver(function(entries){
      entries.forEach(function(e){
        if (e.isIntersecting){
          e.target.classList.add('is-in');
          var seen = items.filter(function(x){ return x.classList.contains('is-in'); }).length;
          rmmFill.style.height = (seen / items.length) * 100 + '%';
        }
      });
    }, { threshold:.25, rootMargin:'0px 0px -12% 0px' });
    items.forEach(function(it){ mo.observe(it); });
  } else {
    /* no observer / reduced motion — everything visible, rail full */
    items.forEach(function(it){ it.classList.add('is-in'); });
    rmmFill.style.height = '100%';
  }
}

function syncMode(){
  if (isMobile()){
    buildMobile();
    document.getElementById('rmm').setAttribute('aria-hidden','false');
  } else {
    onScroll();
  }
}

var ticking = false;
window.addEventListener('scroll', function(){
  if (ticking) return;
  ticking = true;
  requestAnimationFrame(function(){ onScroll(); ticking = false; });
}, { passive:true });
window.addEventListener('resize', syncMode);

/* ══ THE PHYSICAL LAYER ══════════════════════════════════════════════════
   Arrival plays once. Then a weighted pointer parallax keeps the surfaces
   feeling like objects under a light, rather than pictures on a page.
   Both are desktop-only and both are off under reduced motion.
   ═════════════════════════════════════════════════════════════════════════ */
var canPhysical = !reduce && window.matchMedia('(hover: hover) and (pointer: fine)').matches;

/* Arrival — added before first paint, removed once done so it never replays
   and never competes with the pointer transform. */
if (!reduce){
  hero.classList.add('hero--enter');
  var ENTER_MS = 1500 + 260 + 60;
  setTimeout(function(){ hero.classList.remove('hero--enter'); }, ENTER_MS);
}

if (canPhysical){
  var pTargetX = 0, pTargetY = 0, pX = 0, pY = 0, pRaf = null;
  var MAX_RY = 1.9, MAX_RX = 1.2;   /* degrees — deliberately tiny */
  var stages = [].slice.call(document.querySelectorAll('.col__stage'));

  function pFrame(){
    /* lerp: the surfaces carry momentum instead of snapping to the cursor */
    pX += (pTargetX - pX) * 0.075;
    pY += (pTargetY - pY) * 0.075;
    var ry = (pX * MAX_RY).toFixed(3) + 'deg';
    var rx = (-pY * MAX_RX).toFixed(3) + 'deg';
    /* light moves opposite the tilt, as a fixed source would */
    var lx = (30 + pX * 26).toFixed(1) + '%';
    var ly = (8 + pY * 14).toFixed(1) + '%';
    stages.forEach(function(c){
      c.style.setProperty('--ry', ry);
      c.style.setProperty('--rx', rx);
    });
    [surfClientEl, surfTrainerEl].forEach(function(s){
      s.style.setProperty('--lx', lx);
      s.style.setProperty('--ly', ly);
    });
    if (Math.abs(pTargetX - pX) > 0.001 || Math.abs(pTargetY - pY) > 0.001){
      pRaf = requestAnimationFrame(pFrame);
    } else { pRaf = null; }
  }
  function pWake(){ if (!pRaf) pRaf = requestAnimationFrame(pFrame); }

  hero.addEventListener('pointermove', function(e){
    var r = hero.getBoundingClientRect();
    pTargetX = ((e.clientX - r.left) / r.width  - 0.5) * 2;   /* -1 … 1 */
    pTargetY = ((e.clientY - r.top ) / r.height - 0.5) * 2;
    pWake();
  }, { passive:true });

  hero.addEventListener('pointerleave', function(){
    pTargetX = 0; pTargetY = 0; pWake();
  }, { passive:true });
}

/* Planned-updates band reveals once, quietly. */
if ('IntersectionObserver' in window && !reduce){
  var soonEl = document.getElementById('soon');
  var so = new IntersectionObserver(function(en){
    en.forEach(function(e){ if (e.isIntersecting){ soonEl.classList.add('is-in'); so.disconnect(); } });
  }, { threshold:.2 });
  so.observe(soonEl);
} else {
  document.getElementById('soon').classList.add('is-in');
}

setStage(0, false);
syncMode();
})();
