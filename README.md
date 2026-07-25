# YouTube Pipeline Skills

Два русскоязычных скилла для Codex и Claude Code в одном репозитории:

- `youtube-pipeline` — подготовка метаданных, проверка проекта и безопасная
  загрузка видео через официальный YouTube Data API;
- `groq-transcribe` — транскрибация аудио и видео через Groq Whisper с
  пословными таймкодами, SRT и контекстной очисткой текста.

Скиллы не содержат готовых API keys, OAuth tokens, channel IDs, cookies,
персональных путей или данных автора. Каждый пользователь подключает только свои
аккаунты.

## Установка

Нужны Python 3.10+ и Git.

```bash
git clone https://github.com/sstani-bgv/youtube-pipeline.git
cd youtube-pipeline
python3 install.py --target codex
```

На Windows вместо `python3` используйте `py`.

Для Claude Code:

```bash
python3 install.py --target claude
```

Для Codex и Claude Code одновременно:

```bash
python3 install.py --target both
```

По умолчанию устанавливаются оба скилла. Можно поставить один:

```bash
python3 install.py --target codex --skill youtube-pipeline
python3 install.py --target codex --skill groq-transcribe
```

Для обновления:

```bash
git pull --ff-only
python3 install.py --target both --force
```

Старые версии сохраняются рядом как `*.backup-ДАТА`.

## Быстрый старт: YouTube

После перезапуска агента:

```text
Используй $youtube-pipeline. Подготовь проект для видео:
/absolute/path/to/video.mp4
```

Скилл:

1. создаст переносимую папку проекта;
2. подготовит title, description, tags и концепции обложки;
3. проверит официальные лимиты YouTube;
4. покажет dry-run;
5. загрузит видео только после явного разрешения.

Безопасные дефолты:

- upload по умолчанию `private`;
- активный channel ID сверяется с ожидаемым;
- `public` требует отдельный `--allow-public`;
- повторный запуск проверяет receipt и не создаёт дубль.

### Одноразовое подключение YouTube API

Понадобятся `uv`, Google Cloud project, YouTube Data API v3 и Desktop OAuth
client. Полная инструкция:

[`skills/youtube-pipeline/references/SETUP.md`](skills/youtube-pipeline/references/SETUP.md)

## Быстрый старт: транскрибация

Понадобятся `uv`, `ffmpeg` и собственный Groq API key.

```text
Используй $groq-transcribe и транскрибируй
/absolute/path/to/audio.m4a на русском.
```

Результат:

```text
transcript/
├── raw.words.json
├── raw.srt
├── raw.txt
├── raw.json
└── clean.txt
```

Сам Python-скрипт создаёт `raw.*`; `clean.txt` формирует агент после
контекстной проверки. Полная настройка:

[`skills/groq-transcribe/references/SETUP.md`](skills/groq-transcribe/references/SETUP.md)

Аудио отправляется в Groq API. Для конфиденциальных материалов используйте
локальный транскрибатор.

## Опциональные функции YouTube Studio

Официальный YouTube Data API не предоставляет часть Studio-функций: native
A/B tests, cards, end screens и related video для Shorts.

Опциональный отдельный проект [`yt-studio`](https://github.com/sstani-bgv/yt-studio)
можно установить так:

```bash
python3 install_studio.py
```

Это неофициальный инструмент, который использует private YouTube Studio
endpoints. Они могут измениться, а автоматизация может нарушать правила
Google/YouTube. Начинайте с тестового канала, проверяйте каждый dry-run и не
публикуйте session-файлы.

## Структура

```text
youtube-pipeline/
├── install.py
├── install_studio.py
└── skills/
    ├── youtube-pipeline/
    │   ├── SKILL.md
    │   ├── agents/
    │   ├── assets/
    │   ├── references/
    │   └── scripts/
    └── groq-transcribe/
        ├── SKILL.md
        ├── agents/
        ├── references/
        └── scripts/
```

## Лицензия

Скиллы и их собственные скрипты распространяются по MIT.

Опциональный `yt-studio` — отдельный проект под GPL-3.0.
