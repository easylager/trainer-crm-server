# Шрифты для PDF-сертификатов

Для корректного отображения кириллицы в PDF-сертификатах используется шрифт **Inter** (SIL Open Font License).

## Файлы в этом каталоге

- `Inter-Regular.ttf` — основной текст
- `Inter-Bold.ttf` — заголовки, код сертификата
- `Inter-SemiBold.ttf` — промежуточные акценты

Шрифты скачаны из [github.com/rsms/inter](https://github.com/rsms/inter/releases).

## Карточки «Кто кого» (TASK-300)

- `Unbounded-wght.ttf` — игровой заголовочный шрифт, вариативный (жирность 800 выставляет код)
- `GolosText-wght.ttf` — текст карточек, вариативный, как шрифт Mini App

Оба — SIL Open Font License, из [github.com/google/fonts](https://github.com/google/fonts/tree/main/ofl).

## Fallback (Linux / Docker)

Если Inter отсутствует, код попробует:
- `DejaVuSans.ttf` / `DejaVuSans-Bold.ttf` из этого каталога или системных путей
- Системные шрифты macOS (Arial Unicode)

Скачать DejaVu: https://dejavu-fonts.github.io/Download.html

## Устаревшие файлы

- `DMSans-Regular.ttf` — можно удалить (variable font без кириллицы, не используется)
