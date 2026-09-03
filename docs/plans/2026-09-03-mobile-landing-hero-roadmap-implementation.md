# Мобильный лендинг: hero без 3D + roadmap-карусель — план реализации

**Goal:** на `≤860px` (тот же порог, что уже использует `isMobile()` в JS) hero переключает экраны кроссфейдом вместо 3D-выезда карточек, а roadmap-секция становится горизонтальной swipe-каруселью вместо scroll-jacking sticky-блока с багом пустого провала.

**Architecture:** только `static/landing/{index.html,landing-live-link.css,landing-live-link-demo.js}`. Backend/шаблоны/тесты не трогаем — файлы отдаются как статика (`src/api/routes/public.py`). Никакого нового тулинга: чистый CSS + vanilla JS, без сборки.

**Tech Stack:** HTML/CSS/vanilla JS, `scroll-snap-type` для карусели, playwright MCP для визуальной проверки (нет unit-тестов для статического лендинга — верификация каждого шага визуальная, на живом `127.0.0.1:8000`).

**Design doc:** [2026-09-03-mobile-landing-hero-roadmap-design.md](./2026-09-03-mobile-landing-hero-roadmap-design.md)

---

### Task 1: Hero — кроссфейд вместо 3D на `≤860px`

**Files:**
- Modify: `static/landing/landing-live-link.css:702-776` (существующий `@media (max-width:860px)` блок — добавить правила внутрь него, не создавать новый breakpoint)

**Step 1: Добавить в конец блока `@media (max-width:860px){...}` (после строки 775, перед закрывающей `}` на 776) правила, убирающие 3D и включающие кроссфейд**

```css
  /* Hero: кроссфейд вместо 3D-выезда — на телефоне перспектива/наклон не
     читаются, а перекрытие карточек выглядит как поломка вёрстки. */
  .hero{perspective:none}
  .hero--enter .col--trainer .col__stage{animation:none}
  .col__stage{transform:none!important}
  .surfaces{position:relative}
  .col--client,.col--trainer{
    position:absolute;inset:0;width:100%;
    transition:opacity .45s var(--slow),transform .45s var(--slow);
  }
  .col--trainer{opacity:1;transform:none;pointer-events:auto}
  .col--client{
    opacity:0;transform:translateY(8px);pointer-events:none;
    right:auto;left:0;
  }
  .hero.is-live .col--client{opacity:0;transform:translateY(8px);pointer-events:none}
  .hero[data-side="client"] .col--client{opacity:1;transform:none;pointer-events:auto}
  .hero[data-side="client"] .col--trainer{opacity:0;transform:translateY(8px);pointer-events:none}
  .hero[data-side="trainer"] .col--trainer{opacity:1;transform:none;pointer-events:auto}
  .hero[data-side="trainer"] .col--client{opacity:0;transform:translateY(8px);pointer-events:none}
  .col__stage::after{display:none}
```

Важно: это переопределяет (по каскаду, ниже в том же файле = выигрывает) правила `.col--client` из блока `@media (max-width:1180px)` (строки 670-691) — они остаются как есть для диапазона 861-1180px (планшет), где 3D ещё не ломается.

**Step 2: Проверить визуально на 390×844**

Через playwright MCP: `browser_navigate` на `http://127.0.0.1:8000/`, `browser_resize(390,844)`, дождаться срабатывания демки (авто-старт beat1 через ~4.6с бездействия, см. `armIdle` в JS) или кликнуть `#shareBtn`/`#confirmBtn` вручную, сделать `browser_snapshot` + один `browser_take_screenshot` в момент, когда `data-side="client"` — убедиться, что виден **только** клиентский экран на всю ширину, без обрезанной/перекрывающей тренерской карточки сзади.

Ожидаемо: `.col--trainer` полностью `opacity:0`, не видна.

**Step 3: Проверить, что десктоп (>1180px) не сломан**

`browser_resize(1440,900)`, screenshot hero в состоянии `data-side="trainer"` и `data-side="client"` — 3D-колода должна выглядеть как раньше (это код мы не трогали, только добавили правила под 860px).

**Step 4: Commit**

```bash
git add static/landing/landing-live-link.css
git commit -m "landing: кроссфейд вместо 3D-колоды в hero на мобильном"
```

---

### Task 2: Hero — pill-индикатор «Ученик / Тренер» на мобильном

**Files:**
- Modify: `static/landing/index.html` (внутри `<div class="surfaces" id="surfaces">`, перед `<div class="col col--client">`, около строки 71)
- Modify: `static/landing/landing-live-link.css` (новый класс `.side-pill`, добавить в конец мобильного блока `@media (max-width:860px)`)
- Modify: `static/landing/landing-live-link-demo.js` — функция `side(w)` (строки 44-55)

Без кроссфейда с движением карточек на 3D переключение точки зрения читалось «само»; с плоским кроссфейдом нужен явный маркер, что сцена сменилась.

**Step 1: HTML — добавить разметку пилюли**

В `index.html` перед `<div class="col col--client">` (строка ~73):

```html
  <div class="side-pill" id="sidePill" aria-hidden="true">
    <span class="side-pill__opt" data-role="client">Ученик</span>
    <span class="side-pill__opt" data-role="trainer">Тренер</span>
  </div>
```

**Step 2: CSS — стили пилюли (видна только на мобильном, скрыта на десктопе/планшете по умолчанию)**

В основной секции стилей (например, сразу после `.col__label` на строке 180) добавить базовое скрытое состояние:

```css
.side-pill{display:none}
```

В конец `@media (max-width:860px){...}` (после блока из Task 1):

```css
  .side-pill{
    display:flex;gap:4px;margin:0 auto 14px;padding:3px;width:max-content;
    background:var(--surface);border:1px solid var(--line);border-radius:999px;
  }
  .side-pill__opt{
    padding:6px 14px;border-radius:999px;font-size:12px;font-weight:600;
    color:var(--hint);transition:background .3s var(--ease),color .3s var(--ease);
  }
  .hero[data-side="client"] .side-pill__opt[data-role="client"],
  .hero[data-side="trainer"] .side-pill__opt[data-role="trainer"]{
    background:var(--teal-wash);color:var(--teal-ink);
  }
```

**Step 3: JS — не требует новой логики**, `side(w)` уже проставляет `hero.setAttribute('data-side', w)` для любого `w` (строка 45) — CSS-селекторы выше сработают сами. Правок в `landing-live-link-demo.js` не нужно; убрать этот файл из списка "Modify" после проверки (см. ниже).

**Step 4: Проверить на 390×844**

Playwright: снапшот в момент `data-side="client"` и в момент `data-side="trainer"` — активная пилюля должна подсвечиваться тилом.

**Step 5: Commit**

```bash
git add static/landing/index.html static/landing/landing-live-link.css
git commit -m "landing: pill-индикатор роли для мобильного кроссфейда hero"
```

---

### Task 3: Roadmap — отключить scroll-jacking на мобильном, подготовить данные для карусели

**Files:**
- Modify: `static/landing/landing-live-link-demo.js:429-511` (блок «Section 2 — real UI fragments»)

**Step 1: Собрать заголовки/описания шагов из уже существующего DOM, а не дублировать текст**

После строки, где определён `rmItems` (строка 436: `var rmItems = [].slice.call(document.querySelectorAll('.rm__item'));`), добавить:

```js
var STEPS = rmItems.map(function(it, i){
  return {
    name: it.querySelector('.rm__name').textContent,
    desc: it.querySelector('.rm__desc').textContent,
    frag: FRAGS[i]
  };
});
```

(Расположить эту строку физически ПОСЛЕ определения `FRAGS`/`fragNodes`, т.е. после строки 447, а не сразу после `rmItems` — `FRAGS` объявлен на строке 258, доступен раньше по порядку выполнения модуля, но для читаемости держим `STEPS` рядом с остальной roadmap-логикой, после `fragNodes`.)

**Step 2: Сделать desktop-only scroll-jacking**

Обернуть содержимое `onScroll()` (строки 478-488) условием — если мобильный, не считать `p`/`assembled` по вертикальному скроллу вообще:

```js
function onScroll(){
  if (isMobile()) return;
  var r = rm.getBoundingClientRect();
  var total = rm.offsetHeight - window.innerHeight;
  if (total <= 0) return;
  var p = Math.min(1, Math.max(0, -r.top / total));
  var assembled = p > 0.88;
  var idx = Math.min(COUNT - 1, Math.floor((p / 0.88) * COUNT));
  setStage(idx, assembled);
  rmFill.style.height = (assembled ? 100 : ((idx + 0.5) / COUNT) * 100) + '%';
}
```

**Step 3: `syncSpacer()` — на мобильном высота 0 (никакого зарезервированного скролла)**

Заменить строки 450-457:

```js
function syncSpacer(){
  if (!rmSpacer) return;
  if (isMobile()){ rmSpacer.hidden = true; rmSpacer.style.height = '0px'; return; }
  rmSpacer.hidden = false;
  rmSpacer.style.height = (COUNT * 58 + 55) + 'vh';
}
```

**Step 4: Проверить, что десктоп не сломан**

`browser_resize(1440,900)`, проскроллить страницу до roadmap — sticky-пиннинг и последовательная смена stage/fragment должны работать как раньше.

**Step 5: Проверить на 390×844, что вертикальный скролл страницы больше не «залипает» на roadmap**

Playwright: `browser_resize(390,844)`, программно проскроллить страницу вниз через секцию `#rm` (`window.scrollTo` до `document.querySelector('#soon').offsetTop`), убедиться, что путь до `#soon` короткий (не 2000+px), `document.querySelector('#rmSpacer').offsetHeight === 0`.

**Step 6: Commit**

```bash
git add static/landing/landing-live-link-demo.js
git commit -m "landing: roadmap scroll-jacking только на десктопе, spacer=0 на мобильном"
```

---

### Task 4: Roadmap — HTML/CSS каркас карусели, удаление мёртвого `#rmm`

**Files:**
- Modify: `static/landing/index.html:344-355` (весь блок `<section class="rmm" ...>`)
- Modify: `static/landing/index.html` (после `</section>` секции `#rm`, т.е. после строки 342)
- Modify: `static/landing/landing-live-link.css` (удалить строки 617 `.rmm{display:none}`, 773-775, 798 — мёртвые правила; добавить новые для `.rm-carousel`)

**Step 1: Удалить блок `#rmm` из `index.html` (строки 344-355) целиком** — это неиспользуемый, никогда не заполняемый JS'ом код (см. design doc п.1.3).

**Step 2: Добавить пустой контейнер карусели сразу после `</section>` секции `#rm` (была строка 342)**

```html
<!-- ══════════════════ ROADMAP — мобильная swipe-карусель ═══════════════════ -->
<section class="rmc" id="rmc" aria-hidden="true">
  <p class="rmc__eyebrow">Рабочее пространство</p>
  <h2 class="rmc__title">Всё рабочее пространство тренера — в одном месте</h2>
  <div class="rmc__progress">
    <span class="rmc__bar"><span class="rmc__fill" id="rmcFill"></span></span>
    <span class="rmc__label" id="rmcLabel">1/9 · Запись</span>
  </div>
  <div class="rmc__track" id="rmcTrack"></div>
</section>
```

Карточки внутрь `#rmcTrack` генерирует JS в Task 5 — здесь только каркас.

**Step 3: Удалить мёртвые CSS-правила `.rmm`**

В `landing-live-link.css`: удалить строку 617 (`.rmm{display:none}`), удалить строки 773-775 внутри блока `@media (max-width:860px)`, удалить строку 798 внутри блока `@media (prefers-reduced-motion:reduce)`.

**Step 4: Добавить CSS карусели**

По умолчанию (десктоп) секция скрыта; в конец `@media (max-width:860px){...}` добавить показ и стили. В основной секции стилей, рядом с `.rm` (после строки 617, на месте удалённого `.rmm{display:none}`):

```css
.rmc{display:none}
```

В конец `@media (max-width:860px){...}`:

```css
  .rm{display:none}
  #rmSpacer{display:none}
  .rmc{
    display:block;padding:32px 18px calc(48px + env(safe-area-inset-bottom, 0px));
    border-top:1px solid var(--line);
  }
  .rmc__eyebrow{margin:0 0 4px;font-size:11px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--hint)}
  .rmc__title{margin:0 0 16px;font-size:clamp(20px,5vw,26px);line-height:1.15;font-weight:700;letter-spacing:-.02em}
  .rmc__progress{display:flex;align-items:center;gap:10px;margin-bottom:14px}
  .rmc__bar{flex:1;height:3px;border-radius:2px;background:var(--line-strong);overflow:hidden}
  .rmc__fill{display:block;height:100%;width:0;background:var(--teal);border-radius:2px;transition:width .25s var(--ease)}
  .rmc__label{flex-shrink:0;font-size:11.5px;font-weight:600;color:var(--hint);white-space:nowrap}
  .rmc__track{
    display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x mandatory;
    -webkit-overflow-scrolling:touch;padding-bottom:4px;margin:0 -18px;padding-left:18px;padding-right:18px;
  }
  .rmc__track::-webkit-scrollbar{display:none}
  .rmc__card{
    flex:0 0 86%;scroll-snap-align:center;
    background:var(--surface);border:1px solid var(--line);border-radius:16px;
    padding:16px 16px 18px;
  }
  .rmc__cardName{margin:0 0 2px;font-size:15px;font-weight:700;letter-spacing:-.01em;color:var(--ink)}
  .rmc__cardDesc{margin:0 0 12px;font-size:12.5px;line-height:1.5;color:var(--hint)}
  .rmc__cardFrag{background:var(--p-bg);border:1px solid var(--p-line);border-radius:12px;padding:12px 14px 14px;overflow:hidden}
  .rmc__cardFrag .frag__cap{font-size:9.5px;margin-bottom:5px;letter-spacing:.08em}
  .rmc__cardFrag .frag__screen{font-size:14px;margin-bottom:8px}
  .rmc__final{
    flex:0 0 86%;scroll-snap-align:center;
    background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:20px 18px;
    display:flex;flex-direction:column;gap:12px;
  }
  .rmc__finalChips{display:flex;flex-wrap:wrap;gap:6px}
  .rmc__finalChip{font-size:11px;font-weight:600;padding:5px 11px;border-radius:999px;background:var(--teal-wash);color:var(--teal-ink)}
  .rmc__finalLine{margin:0;font-size:14px;line-height:1.5;font-weight:500;color:var(--ink)}
```

`.rmc__cardFrag` переиспользует уже существующие классы фрагментов (`.frag__cap`, `.frag__screen`, `.slot-card`, `.s-card`, `.chip` и т.д. — они стилизованы глобально в `:root`/`.frag` секции, поэтому автоматически подхватят вид).

**Step 5: Commit**

```bash
git add static/landing/index.html static/landing/landing-live-link.css
git commit -m "landing: удалить мёртвый #rmm, добавить каркас мобильной карусели roadmap"
```

---

### Task 5: Roadmap — JS-генерация карточек карусели и прогресс-бара

**Files:**
- Modify: `static/landing/landing-live-link-demo.js` (после блока Task 3, перед `var ticking = false;` строка 505)

**Step 1: Построение карточек из `STEPS` (из Task 3) при инициализации на мобильном**

```js
var rmc      = document.getElementById('rmc');
var rmcTrack = document.getElementById('rmcTrack');
var rmcFill  = document.getElementById('rmcFill');
var rmcLabel = document.getElementById('rmcLabel');
var rmcCards = [];

function buildCarousel(){
  if (rmcTrack.childElementCount) return; /* построить один раз */
  STEPS.forEach(function(s){
    var card = document.createElement('div');
    card.className = 'rmc__card';
    card.innerHTML =
      '<p class="rmc__cardName">' + s.name + '</p>' +
      '<p class="rmc__cardDesc">' + s.desc + '</p>' +
      '<div class="rmc__cardFrag"><p class="frag__cap">' + s.frag.cap + '</p>' + s.frag.html + '</div>';
    rmcTrack.appendChild(card);
    rmcCards.push(card);
  });
  var final = document.createElement('div');
  final.className = 'rmc__final';
  final.innerHTML =
    '<div class="rmc__finalChips">' +
      STEPS.map(function(s){ return '<span class="rmc__finalChip">' + s.name + '</span>'; }).join('') +
    '</div>' +
    '<p class="rmc__finalLine">Один бот в Telegram — без установки и настройки CRM.</p>';
  rmcTrack.appendChild(final);
  rmcCards.push(final);
}

function onRmcScroll(){
  var max = rmcTrack.scrollWidth - rmcTrack.clientWidth;
  var idx = max > 0
    ? Math.round((rmcTrack.scrollLeft / max) * (rmcCards.length - 1))
    : 0;
  idx = Math.max(0, Math.min(rmcCards.length - 1, idx));
  rmcFill.style.width = ((idx + 1) / rmcCards.length * 100) + '%';
  rmcLabel.textContent = (idx + 1) + '/' + rmcCards.length + ' · ' +
    (idx < STEPS.length ? STEPS[idx].name : 'Готово');
}

var rmcTicking = false;
rmcTrack.addEventListener('scroll', function(){
  if (rmcTicking) return;
  rmcTicking = true;
  requestAnimationFrame(function(){ onRmcScroll(); rmcTicking = false; });
}, { passive:true });
```

**Step 2: Вызывать `buildCarousel()`/`onRmcScroll()` из `syncMode()` на мобильном**

Заменить тело `syncMode()` (строки 492-503):

```js
function syncMode(){
  syncSpacer();
  if (isMobile()){
    buildCarousel();
    onRmcScroll();
  } else {
    onScroll();
  }
}
```

**Step 3: Проверить на 390×844**

Playwright: `browser_resize(390,844)`, прокрутить страницу до `#rmc`, сделать `browser_snapshot` — убедиться, что видна первая карточка «Запись» с превью слотов. Затем через `browser_evaluate` эмулировать свайп (`rmcTrack.scrollTo({left: rmcTrack.clientWidth * 0.86 * 3})`) и проверить, что `#rmcLabel` обновился на 4-й пункт, `#rmcFill` вырос. Один финальный `browser_take_screenshot` на первой карточке для визуальной проверки.

**Step 4: Проверить последнюю (9-ю) карточку — payoff-момент**

`rmcTrack.scrollTo({left: rmcTrack.scrollWidth})`, снапшот — должны быть видны все 8 чипов + строка «Один бот в Telegram...».

**Step 5: Commit**

```bash
git add static/landing/landing-live-link-demo.js
git commit -m "landing: JS-генерация мобильной карусели roadmap из STEPS/FRAGS"
```

---

### Task 6: Финальный регрессионный проход

**Files:** нет изменений — только проверка.

**Step 1: Desktop full-page (1440×900)** — screenshot hero (оба состояния) и roadmap (sticky-скролл на середине последовательности) — сверить, что ничего визуально не изменилось относительно состояния до правок.

**Step 2: Mobile full-page (390×844)** — проскроллить всю страницу сверху донизу (`hero → roadmap-карусель → soon → close → footer`), делая по одному снапшоту/скриншоту на секцию — убедиться, что нет пустых провалов, нет горизонтального переполнения (`document.documentElement.scrollWidth === document.documentElement.clientWidth`).

**Step 3: Проверить консоль браузера** (`browser_console_messages`, `onlyErrors:true`) на обоих размерах — 0 ошибок.

**Step 4: Проверить планшетный диапазон (768×1024, портрет)** — здесь всё ещё должна работать 3D stacked-deck версия hero (мы не трогали `@media (max-width:1180px)` правила для 861-1180px) и — важно — `isMobile()` в JS триггерится на `≤860px`, то есть на 768px ширины сработает **мобильная карусель** для roadmap, а hero останется в 3D-режиме (860px — это порог и для hero-кроссфейда, и для карусели, но `isCompactHero()` для 3D-деки — порог 1180px). Явно проверить, что на 768px это сочетание не выглядит нелогично; при необходимости — точечная правка ширины `.side-pill`/`.rmc__card` под этот диапазон, без выхода за рамки Task 1-5.

**Step 5: Ничего не коммитить** (это верификационный таск) — если найден баг, завести его как правку в соответствующем Task выше и переисполнить commit того таска.
