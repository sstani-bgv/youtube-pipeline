# Опциональный yt-studio adapter

## Зачем он нужен

Официальный YouTube Data API подходит для upload, metadata, thumbnail и
visibility, но не предоставляет публичных методов для части Studio-функций:

- native title/thumbnail A/B test;
- info cards;
- end screen;
- related video у Shorts.

Для них можно использовать отдельный CLI:

```text
https://github.com/sstani-bgv/yt-studio
```

## Риск

Это неофициальный инструмент на private YouTube Studio endpoints. Endpoints могут
измениться без предупреждения. Использование может нарушать правила
Google/YouTube или привести к ограничениям аккаунта.

Обязательные правила:

- сначала тестовый канал;
- отдельный browser profile;
- dry-run перед каждой мутацией;
- проверка exact channel ID;
- никакого автоматического browser fallback;
- session/cookie/security files считать паролями;
- `public` только после отдельного разрешения.

## Установка из публичного репозитория

Из корня публичного пакета:

```bash
python3 install_studio.py
```

Установщик:

1. клонирует репозиторий в
   `~/.local/share/youtube-pipeline/yt-studio`;
2. ставит CLI через `uv tool`;
3. устанавливает отдельный Playwright Chromium.

Проверка:

```bash
ytstudio-safe --help
```

## Подключение тестового канала

Открыть выделенный профиль:

```bash
ytstudio-safe auth-open \
  --session-name youtube-sandbox \
  --browser-channel chrome
```

Войти, выбрать тестовый канал, дождаться Studio dashboard и полностью закрыть
выделенное окно.

Захватить только отфильтрованную session и зафиксировать канал:

```bash
ytstudio-safe auth-capture \
  --session-name youtube-sandbox \
  --browser-channel chrome \
  --expected-channel-id UC_REPLACE_WITH_YOUR_CHANNEL_ID
```

Перед Studio-only мутациями:

```bash
ytstudio-safe security-capture --session-name youtube-sandbox
```

## Применение

Каждую команду сначала запускать без `--apply`. После проверки dry-run добавить:

```text
--apply --confirm <TARGET_ID>
```

Не переносить session между людьми и не включать её в ZIP публичного скилла.
