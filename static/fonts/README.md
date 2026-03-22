# Шрифты для PDF-сертификатов

Чтобы кириллица в сертификатах отображалась (а не квадратики), в PDF подставляется шрифт с поддержкой кириллицы.

- **macOS:** используются системные шрифты (Arial Unicode, Arial Bold из `/System/Library/Fonts/Supplemental/`).
- **Linux / Docker:** положите сюда:
  - `DejaVuSans.ttf` и `DejaVuSans-Bold.ttf` — основной текст;
  - `DejaVuSerif-Bold.ttf` — заголовок и имя получателя (более «подарочный» вид).
  Скачать: https://dejavu-fonts.github.io/Download.html

Без подходящего шрифта в PDF будет использоваться Helvetica — кириллица отобразится как квадраты.
