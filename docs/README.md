# Знания о продукте

`docs/` отвечает на вопрос **«что верно про продукт»**. Живое состояние работы
(задачи, решения, прогресс) здесь не хранится — оно в `.ai/`, см. `AGENTS.md`.

Читать выборочно по этому индексу. Целиком дерево не читать — оно для этого не нужно.

## Правила

1. **Один документ = один вопрос.** Папка выбирается по типу вопроса, а не по эпику.
2. **Нет строки в этом индексе — файла не существует.** Новый документ добавляется сюда же, одной строкой.
3. **Актуальный документ всегда один.** Устаревшее уезжает в `archive/`, а не остаётся рядом с заменой.
4. **Ничего личного.** Резюме, cover letters, LinkedIn-контент — в `~/Projects/personal-career/`.

## Куда что кладём

| Папка | Вопрос, на который отвечает |
|---|---|
| `product-knowledge/` | Как устроен продукт и для кого он |
| `strategy/` | Куда идём и на чём зарабатываем |
| `research/` | Что мы выяснили (разово, с датой) |
| `adr/` | Какое решение приняли и почему (необратимое) |
| `plans/` | Как делаем конкретную инициативу |
| `epics/` | Полное описание крупной линии работ |
| `reviews/` | Аудит существующего поведения по подсистемам |
| `ops/` | Как эксплуатировать и восстанавливать |
| `agents/` | Системные промпты ревьюеров и агентов |
| `release-comms/` | Что говорим пользователям на релизе |
| `archive/` | Устаревшее, но удалять жалко |

Дизайн и прототипы — в `design/` в корне репозитория, не здесь.

## product-knowledge — как устроен продукт

| Документ | О чём |
|---|---|
| [architecture.md](product-knowledge/architecture.md) | Архитектура продукта ICING целиком: домен, сущности, границы |
| [icp.md](product-knowledge/icp.md) | Идеальный клиент продукта |
| [jtbd.md](product-knowledge/jtbd.md) | Работы, ради которых продукт «нанимают» |
| [wedge.md](product-knowledge/wedge.md) | Клин — ядро продукта |
| [activation.md](product-knowledge/activation.md) | Лестница ценности от первой записи |
| [retention.md](product-knowledge/retention.md) · [retention_loop.md](product-knowledge/retention_loop.md) | Удержание и его циклы |
| [growth_loop.md](product-knowledge/growth_loop.md) | Циклы роста под ICP |
| [client-booking-url-contract.md](product-knowledge/client-booking-url-contract.md) | Контракт ссылок записи клиента |
| [organization-role-surfaces.md](product-knowledge/organization-role-surfaces.md) | Организации: что видит каждая роль |

## strategy — куда идём

| Документ | О чём |
|---|---|
| [business-plan-2026.md](strategy/business-plan-2026.md) | Основной бизнес-план ICING |
| [business-plan-by-ru-detailed.md](strategy/business-plan-by-ru-detailed.md) · [-short](strategy/business-plan-by-ru-short.md) | План продаж в Беларуси и России |
| [client-growth-2026.md](strategy/client-growth-2026.md) | Клиентское ядро и инфраструктура роста |
| [partner-commerce-2026.md](strategy/partner-commerce-2026.md) | Третий двигатель выручки: экипировка и сервис |
| [onboarding-2026-roadmap.md](strategy/onboarding-2026-roadmap.md) · [executive-summary.md](strategy/executive-summary.md) | Переделка онбординга тренера |
| [sales-pitches-2026-09.md](strategy/sales-pitches-2026-09.md) | Скрипты трёх разговоров с клиентом |
| [advice-2026-success.md](strategy/advice-2026-success.md) | Принципы: как сделать успешный продукт в 2026 |

## research — что выяснили

| Документ | О чём |
|---|---|
| [activation-2026-09-02.md](research/activation-2026-09-02.md) | Как система ведёт тренера от первой записи к полному использованию |
| [arenas-scale-2026-09-02.md](research/arenas-scale-2026-09-02.md) | Что будет с системой на 90 аренах и многих городах |
| [onboarding-multi-arena.md](research/onboarding-multi-arena.md) | Мультиарена и нестандартные сетки в онбординге |
| [trainer-profile-ux-friction.md](research/trainer-profile-ux-friction.md) | Почему профиль тренера неприятно заполнять |

## adr — принятые решения

| Документ | Решение |
|---|---|
| [001-collective-overlay.md](adr/001-collective-overlay.md) | Collective overlay как основа white-label |
| [003-studio-schedule-modes-and-center-commerce.md](adr/003-studio-schedule-modes-and-center-commerce.md) · [приложение](adr/003-appendix-organization-format-ux.md) | Режимы расписания студии, коммерция центра, мульти-коллектив |
| [004-multi-profile-clients.md](adr/004-multi-profile-clients.md) | Несколько детей и взрослых под одним клиентским аккаунтом |
| [005-go-no-go-90d.md](adr/005-go-no-go-90d.md) | Go / no-go по продукту — замер 6 декабря 2026 |

## epics — крупные линии работ

| Документ | О чём |
|---|---|
| [ice-discovery/epic.md](epics/ice-discovery/epic.md) | EPIC3: арена как экран — лёд и тренеры в одном приложении |
| [ice-discovery/agent-start.md](epics/ice-discovery/agent-start.md) · [git](epics/ice-discovery/agent-git.md) · [lanes](epics/ice-discovery/agent-lanes.md) | Как агенту входить в эпик, вести ветки и параллельные дорожки |
| [client-multi-profile.md](epics/client-multi-profile.md) | EPIC1: несколько профилей под одним клиентским аккаунтом |
| [subscription-retention.md](epics/subscription-retention.md) | EPIC2: утечка в продлении подписки |

## plans — как делаем инициативы

| Документ | О чём |
|---|---|
| [collectives-enablement.md](plans/collectives-enablement.md) | Коллективы как ось выручки R2a: гейты и риски включения |
| [subscription-model-reverse-trial.md](plans/subscription-model-reverse-trial.md) | Reverse trial + тарифы Starter / Pro |
| [telegram-paywall-daily-digest-monetization.md](plans/telegram-paywall-daily-digest-monetization.md) | Paywall и daily digest как ядро монетизации |
| [lead-mode-revenue-retention.md](plans/lead-mode-revenue-retention.md) | Удержание выручки после триала |
| [organizations-completion-backlog.md](plans/organizations-completion-backlog.md) | Что осталось достроить в организациях |
| [2026-09-04-epic3-arenas-sdd-release-plan.md](plans/2026-09-04-epic3-arenas-sdd-release-plan.md) · [r1](plans/2026-09-04-epic3-r1-foundation.md) | Релизный план EPIC3 для агентов |
| [2026-09-09-merge-epics-to-master.md](plans/2026-09-09-merge-epics-to-master.md) | Кат двух эпиков (premium + региональные парсеры) в master/прод |
| [2026-09-04-client-multi-profile-booking.md](plans/2026-09-04-client-multi-profile-booking.md) · [design](plans/2026-09-04-client-multi-profile-booking-design.md) | Запись ребёнка и раздельная статистика |
| [2026-09-03-mobile-landing-hero-roadmap-design.md](plans/2026-09-03-mobile-landing-hero-roadmap-design.md) · [impl](plans/2026-09-03-mobile-landing-hero-roadmap-implementation.md) | Мобильный лендинг: hero и roadmap |
| [2026-09-05-trainer-profile-s1-s2-data-guards.md](plans/2026-09-05-trainer-profile-s1-s2-data-guards.md) | Гарды данных профиля тренера |

## ops — эксплуатация

| Документ | О чём |
|---|---|
| [BACKUPS.md](ops/BACKUPS.md) | Off-site резервные копии Postgres |
| [DISASTER_RECOVERY.md](ops/DISASTER_RECOVERY.md) | Восстановление после аварии |
| [onboard-collective-formats.md](ops/onboard-collective-formats.md) | Runbook подключения коллектива |
| [platform-processes-for-legal-by-v1.md](ops/platform-processes-for-legal-by-v1.md) | Описание процессов платформы для юристов (BY) |

## Остальное

- `reviews/` — 18 аудитов подсистем (запись, платежи, боты, абонементы и т.д.), плюс [продуктовое ревью клиньев](reviews/notes/product_review_wedges_activation.md).
- `agents/` — системные промпты ревьюеров (backend, product, QA, refactor, security, UX) и агентов эпика (`prompt-*`).
- `release-comms/` — сообщения релизов по аудиториям, есть [шаблон](release-comms/TEMPLATE.md).
- `archive/` — [legacy-индекс задач](archive/legacy-tasks-index.md), [sprintq-backlog](archive/sprintq-backlog.md), [RFQ по локерам](archive/rfq-smart-sports-locker-v1.md).
