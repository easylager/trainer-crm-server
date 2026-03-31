# Data Model: 005-trainer-profile-details

## Entity: TrainerProfileExtended

Расширение существующего профиля тренера.

- `education` (option)
- `specialization` (option/list)
- `training_format` (option/list)
- `about_short` (text, limited)
- `achievements` (text, limited)

## Entity: ProfileFieldOption

Справочник вариантов для полей выбора.

- `field_name`
- `value`
- `label`
- `is_active`

## Notes

Фактический перечень полей утверждается в tasks/implementation на основе приоритета P1.
