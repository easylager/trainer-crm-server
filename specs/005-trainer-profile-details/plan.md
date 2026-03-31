# Implementation Plan: Расширенный профиль тренера

**Branch**: `005-trainer-profile-details` | **Date**: 2026-03-24 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/005-trainer-profile-details/spec.md`

## Summary

Расширить профиль тренера новыми атрибутами самопрезентации, полезными клиенту при выборе (FR-001/FR-004), с безопасным редактированием для тренера (FR-002/FR-006) и обратной совместимостью (FR-005).

## Technical Context

**Language/Version**: Python 3.x  
**Primary Dependencies**: FastAPI, Pydantic, SQLAlchemy async  
**Storage**: PostgreSQL (`trainer_profiles`, связанные справочники/опции)  
**Testing**: pytest (`tests/api/test_trainers_api.py`)  
**Target Platform**: API + Mini App карточка тренера + сайт/админка профиля  
**Project Type**: монолит (api/application/repository + static webapp)  
**Performance Goals**: без заметной деградации GET карточки и PATCH профиля  
**Constraints**: обратная совместимость, человеко-понятные ошибки, русский UX-копирайт  
**Scale/Scope**: профиль тренера и связанные контракты API

## Constitution Check

*GATE: Passed. Перепроверить после дизайна полей.*

- [x] I — слойность сохраняется (`api -> application -> infrastructure`)
- [x] II — доменные термины профиля тренера
- [x] III — тесты API на новые поля и валидацию
- [x] IV — без секретов/PII в артефактах
- [x] V — UX и понятные формулировки
- [x] VI — без тяжелых вычислений
- [x] VII — если трогаем бот, копирайт/разметка по правилам
- [x] VIII — если трогаем Mini App, единые токены/паттерны

## Project Structure

### Documentation (this feature)

```text
specs/005-trainer-profile-details/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── trainer-profile-fields.md
└── tasks.md
```

### Source Code (repository root)

```text
src/api/schemas.py
src/api/routes/trainers.py
src/application/trainer_use_cases.py
src/infrastructure/repositories/trainer_repository.py
src/infrastructure/db/models.py
static/webapp/catalog.html
tests/api/test_trainers_api.py
```

**Structure Decision**: расширяем существующую модель профиля инкрементально и отдаём поля через существующие endpoints `POST/PATCH/GET /api/trainers*`.

## Phases (execution)

### Phase 0 — Research

Выход: `research.md` — финальный перечень новых полей, обязательность, ограничения и fallback-логика для старых профилей.

### Phase 1 — Design & contracts

- `data-model.md` — схема расширенного профиля.
- `contracts/trainer-profile-fields.md` — контракт payload/response и справочников опций.
- `quickstart.md` — проверка create/patch/get сценариев.

### Phase 2 — Tasks

Следующий шаг: `/speckit.tasks`.

## Complexity Tracking

Нарушений конституции не запланировано.
