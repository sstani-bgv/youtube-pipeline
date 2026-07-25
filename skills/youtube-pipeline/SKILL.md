---
name: youtube-pipeline
description: "Оркестрировать полный переносимый YouTube-конвейер от финального видео до упаковки, Shorts/Reels, проверки, безопасной загрузки и Studio-функций. Использовать для запросов «доведи видео до YouTube», «запусти весь YouTube pipeline», «сделай метаданные, обложки и Shorts», а также для возобновления частично завершённого проекта. Делегировать фазы установленным youtube-* скиллам и принимать их результаты через файлы и компактные receipts."
---

# YouTube Pipeline

Быть корневым оркестратором. Не выполнять все production-задачи в одном контексте.
Работать с переносимым каталогом проекта и не зависеть от имени пользователя,
конкретного канала или структуры чужих папок.

## Состав конвейера

1. **Brief и preflight** — проверить финальное видео, authority на удалённые действия
   и создать проект через `scripts/init_project.py`.
2. **Транскрибация** — вызвать `$groq-transcribe`, если transcript отсутствует.
3. **Generation** — вызвать `$youtube-generation`. Он параллельно делегирует:
   `$youtube-title-generator`, `$youtube-seo-tags`,
   `$youtube-description-writer`, `$youtube-thumbnail-text-generator`,
   `$youtube-thumbnail-image-generator`, `$shorts-cutter` и
   `$make-reels-video`.
4. **Validation и upload** — вызвать `$youtube-meta-validator`, затем
   `$youtube-uploader` либо установленный `ytstudio-safe`.
5. **Studio-only функции** — A/B/C, cards, end screen и related video выполнять
   через `ytstudio-safe`, всегда dry-run-first.
6. **Audit** — проверить файлы, receipts и live state; только после этого завершать.

## Структура проекта

```text
project/
├── brief.md
├── publish.json
├── transcript/
├── meta/
│   ├── titles.md
│   ├── tags.md
│   ├── description.md
│   └── thumbnails.md
├── thumbnails/
├── shorts/
└── receipts/
```

Видео и credentials не класть внутрь скилла или git-репозитория.

## Оркестрация

- Один root-agent владеет общим state.
- Каждой фазе назначать owned outputs; child-agent не меняет общий state.
- Независимые metadata-задачи и Shorts запускать параллельно.
- Повторный запуск пропускает уже валидные outputs и не создаёт дубли.
- Длинные логи держать в `/tmp`; root принимает компактный JSON receipt.
- Production-fail сначала исправляет owning agent и повторяет QA.

Минимальный receipt:

```json
{
  "task": "youtube-title-generator",
  "status": "done",
  "output_files": ["meta/titles.md"],
  "qa": {"verdict": "pass"},
  "mutation": {"applied": false},
  "error": null
}
```

## Безопасность

- До любой загрузки показывать dry-run.
- По умолчанию использовать `private`.
- `public`, schedule и внешняя публикация требуют явного разрешения пользователя.
- Перед мутацией сверять активный channel ID с ожидаемым.
- Не печатать и не коммитить Groq key, OAuth JSON/token, cookies или Studio session.
- Не продолжать после auth mismatch, validator error или неполного receipt.

## Два транспорта YouTube

**Login-only:** `ytstudio-safe` использует отдельный браузерный профиль. Пользователь
только входит в Google/YouTube и выбирает канал. Это неофициальный private API:
обязательно сообщить риск и использовать test channel для первого запуска.

**Official API:** `$youtube-uploader` использует YouTube Data API. Он стабильнее,
но Google требует один раз создать Desktop OAuth client. Полностью читать
`references/SETUP.md` перед настройкой.

## Completion gate

Не завершать, пока не подтверждены:

- metadata и `publish.json` прошли validator;
- long-form upload существует либо явно не был разрешён;
- все запрошенные thumbnails/Shorts имеют QA receipt;
- upload не продублирован;
- visibility соответствует authority;
- Studio-only операции либо применены, либо явно отмечены как необязательные/blocked.
