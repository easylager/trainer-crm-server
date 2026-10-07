# Parser spec: Каток ХК «Юность»

- arena_id: 8
- arena_slug: katok-khk-yunost
- city: Минск
- parser_key: junost_instagram_caption_v1
- cadence: weekly
- requires_by_egress: false

Оператор публикует расписание массовых катаний в **Instagram** [`@junost.by`](https://www.instagram.com/junost.by/) (подпись + афиша). Сайт `junost.by` / `junost.hockey.by` **не** считаем SoT: страница расписания устарела, с не-BY IP — 403.

**Не** скрапим Instagram API/CDN. Обновление: копипаст подписи → `scripts/ingest_junost_from_caption.py` (см. `docs/instructions/ice-ingest-junost-instagram.md`).

Старый адаптер `junost_origin_html_v1` остаётся в коде для регрессии, в seed больше не используется.

## Sources

- schedule + prices: текст поста IG (ручной ввод)
- widget/api: нет
- job.config JSON:

```json
{
  "caption_file": "data/fixtures/minsk-junost/instagram-caption-latest.txt",
  "timezone": "Europe/Minsk",
  "kind": "public_skate",
  "requires_by_egress": false,
  "source_label": "instagram_caption_manual"
}
```

## How to extract

1. Прочитать `caption_file` из репозитория **или** `caption_text` из job.config (one-shot ingest).
2. Дата: `4 октября` (опционально с днём недели `Воскресенье | 4 октября`).
3. Времена: все интервалы `HH:MM - HH:MM` в тексте → слоты на эту дату.
4. Цены: `взрослый - N р.`, `детский - N р.`, `прокат коньков - N р.` → на все слоты.
5. `pivot_year` в config при необходимости (иначе текущий год).
6. Прошедшие слоты отбрасывает `IceSessionNormalizer` — в прод попадают только будущие сеансы.

## Fixture

`data/fixtures/minsk-junost/`

| файл | смысл |
|---|---|
| `instagram-caption-2026-10-04.txt` | эталон поста 04.10.2026 |
| `instagram-caption-latest.txt` | последняя подпись для коммита / планировщика |
| `expected.json` | golden для seed + тестов |
| `junost-origin*.html` | legacy BY-egress (не SoT) |
