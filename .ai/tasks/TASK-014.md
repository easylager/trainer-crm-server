---
task_id: TASK-014
title: Шаг «Расскажите о себе» закрывается галочкой без единого слова о себе
status: READY
phase: new
created_at: 2026-08-31
updated_at: 2026-08-31
---

# Task

## Objective

Согласовать название шага онбординга с тем, что он реально закрывает, и сделать три планки полноты профиля понятными тренеру. Сейчас шаг «Расскажите о себе» получает «Готово ✓» без фото, описания и образования, а потом тренер отдельно узнаёт, что анкета не отправлена и в каталоге его нет.

## Business Context

Галочка на незавершённом деле обесценивает следующий разговор о том же профиле: продукт уже сказал «готово», а теперь просит доделать. Три разные планки полноты (5 / 8 / 11 критериев) обоснованы инженерно, но наружу вылезают как противоречивые сигналы.

## Scope

### In Scope

- Название и подпись шага 1 (`static/webapp/trainer-home.html`, ветки `hintP` в `trainer-home-main.js`)
- Как показывать разницу «минимум для работы» vs «готово к проверке» vs «полная карточка»
- Тексты статуса профиля (вкладка «Статус профиля», `modHint` / `modMissingList`)

### Out of Scope

- Сами пороги критериев в `trainer_profile_completeness.py` — менять не предлагается
- Исчезновение полосы онбординга — TASK-007

## Comprehension Tips

### Facts

- Три планки в `src/application/trainer_profile_completeness.py`: **C — TTV минимум** (5 критериев: имя+фамилия, телефон, город, услуги, арены), **A — submission** (8 = полная минус description/education/experience_years, **фото обязательно**), **B — full** (11, каталожное доверие). `MODERATION_CRITERIA_TOTAL = 11`, `MODERATION_SUBMISSION_CRITERIA_TOTAL = 8`, `TT_MINIMAL_CRITERIA_TOTAL = 5`.
- Визард шага 1 идёт только по TTV: `PROFILE_TT_MINIMAL_WIZARD_ORDER = ['anketa_main', 'phone', 'services', 'arenas']` (`static/webapp/trainer-profile-main.js:161`). Ни фото, ни описания там нет.
- `static/webapp/trainer-home-main.js:3052-3082` — `stage1Done = active ? pc : ttOk`. Для не-active тренера галочка ставится по TTV, кнопка становится «Готово» и `disabled`.
- Название шага — «Расскажите о себе» (`static/webapp/trainer-home.html:378`), подпись «Откроет расписание и онлайн-запись.»
- `moderation_readiness_dict` уже отдаёт все три среза с русскими лейблами: `missing_labels_ru`, `full_profile_missing_labels_ru`, `tt_minimal_missing_labels_ru`, плюс `already_submitted_for_moderation`.
- `session_duration_minutes` и `min_hours_before_booking` формально входят в планку A, но имеют server_default (`45` и `3` в `src/infrastructure/db/models.py:201-204`) — то есть закрываются сами и тренера не блокируют. Это нормально, не баг.

### Implications

- Переименование шага — минимальная правка с наибольшим эффектом: «Настройте рабочий минимум» честнее, чем «Расскажите о себе», раз о себе там ничего нет.
- Альтернатива: оставить название и добавить фото в TTV-визард — но это удлиняет путь до первой ценности, что противоречит смыслу TTV-планки.
- «Готово ✓» + `disabled` на кнопке лучше заменить на состояние вида «Минимум готов · осталось для каталога: фотография» — данные для этого уже в ответе чеклиста.

## Acceptance Criteria

## Execution History

- **TASK_CREATED** — заведена по результатам ревью онбординга тренера от 2026-08-31
