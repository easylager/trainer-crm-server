---
task_id: TASK-083
title: BY-egress VPS для ledlife/junost — провижининг и подключение к скедулеру
status: READY
phase: plan
epic: EPIC3
depends_on: [TASK-071, TASK-072]
execution_mode: SUPERVISED
lane: INGEST
created_at: 2026-09-06
updated_at: 2026-09-06
---

# Task

## Objective

Дать воркеру `notification_service` реальный белорусский исходящий IP, чтобы можно было безопасно включить `ice_parser_jobs` для `ledlife` и `junost` (сейчас `requires_by_egress=true`, `is_enabled=false`; скедулер безусловно блокирует такие job — `src/ingestion/scheduler.py:72-83`, `error_code="requires_by_egress"`).

## Business Context

**PDEC-004** (`.ai/decisions.md`, ACCEPTED 2026-09-06 владельцем): небольшой VPS в Беларуси (hoster.by / A1 Cloud, ~$3–5/мес) + туннель (WireGuard/SSH) обратно к тому же Docker-образу, а не коммерческий BY-резидентный прокси и не ручной ввод. Globalping-проверка (см. EPIC3 «Открытые вопросы» / DESIGN-INGESTION-PARSERS-V1.md §6.2) уже показала: BY IP через прокси не спуфится, спуфинг заголовков запрещён спекой — нужен настоящий IP.

## Scope

### In Scope
- Завести VPS у белорусского хостера (hoster.by или A1 Cloud) — **ручное действие владельца** (оплата, аккаунт); эта задача не покупает инфраструктуру сама.
- Поднять туннель (WireGuard или SSH reverse tunnel) от прод-образа `notification_service` до VPS так, чтобы HTTP-запросы `ledlife`/`junost` парсеров шли через BY-исходящий узел.
- Механизм в коде, которым воркер узнаёт «сейчас исходящий трафик реально BY» — не полагаться на голое `is_enabled=true`; например явный конфиг/env (`BY_EGRESS_PROXY_URL` или аналог) плюс сохранение текущей безусловной блокировки как fallback, если конфиг пуст.
- Включить `is_enabled=true` и `requires_by_egress` остаётся `true` (флаг не снимается — он теперь просто удовлетворён) для job `ledlife` и `junost` в `.ai/data/minsk-parser-registry.yaml` / `ice_parser_jobs`.
- Один прогон каждого job на реальном сайте (`ledlife.by/massovye_kataniya/`, `junost.by/seansy_massovogo_kataniya_na_vyhodnyh/`) через новый egress; сверка результата с существующими спеками/фикстурами (парсер-код уже есть, если фикстуры валидны).

### Out of Scope
- Сами парсер-адаптеры `ledlife`/`junost`, если их ещё нет как класса — это TASK-061 lane, не эта задача (проверить фактическое состояние перед стартом).
- Header-spoofing или иные способы подделать geo — прямо запрещено (`DESIGN-INGESTION-PARSERS-V1.md` §6.2).
- Коммерческий резидентный прокси, ручной ввод админом — отклонённые альтернативы PDEC-004.
- PR в `master`.

## Acceptance Criteria

### AC-001
VPS в Беларуси поднят и туннель до `notification_service` работает; исходящий IP воркера для этих двух job подтверждён как BY (напр. через Globalping или запрос к сервису geo-IP с самого туннеля).
Status: OPEN
Verification: ручная проверка + запись IP/провайдера в Execution History (без секретов в git)

### AC-002
`ledlife` и `junost` jobs дают `ok`/`empty` прогон (не `blocked`/`error` из-за geo) минимум один раз на реальном сайте.
Status: OPEN
Verification: запись в `ice_scrape_runs`, скрин/лог прогона

### AC-003
Без настроенного BY-egress (конфиг пуст/недоступен) скедулер по-прежнему блокирует эти job с тем же `error_code="requires_by_egress"` — регресса безопасности нет.
Status: OPEN
Verification: unit-тест на fallback-ветку

## Technical Notes
- Точка входа блокировки: `src/ingestion/scheduler.py:69-83` (`config_requires_by_egress`).
- Секреты (VPS-доступ, ключи туннеля) — только в реальном `.env`/секрет-хранилище, никогда в `.env.example` или в git.
- Реестр парсеров: `.ai/data/minsk-parser-registry.yaml` (уже фиксирует, что оба сайта отдают BY-geo-block, спуфинг X-Forwarded-For не помог).

## Execution History
- **TASK_CREATED** (2026-09-06) — координатор: follow-up из PDEC-004 (`.ai/decisions.md`, PR #53) после подтверждения владельцем «свой VPS в Беларуси». Инфраструктура ещё не поднята — задача READY, не в работе.
- **RENUMBERED** (2026-09-06) — TASK-082 → TASK-083: номер TASK-082 занят параллельным PR #56 («Ice map loader and hide empty Группы chip»), коллизия обнаружена координатором до мержа.
