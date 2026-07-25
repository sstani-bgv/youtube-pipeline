# Одноразовая настройка YouTube Data API

## Что понадобится

- Google-аккаунт с нужным YouTube-каналом;
- доступ к Google Cloud Console;
- Python 3.10+;
- `uv`;
- системный браузер для OAuth.

## 1. Создать проект Google Cloud

1. Открыть Google Cloud Console.
2. Создать новый проект или выбрать отдельный проект для uploader.
3. Открыть **APIs & Services → Library**.
4. Найти и включить **YouTube Data API v3**.

## 2. Настроить OAuth consent screen

1. Открыть **Google Auth Platform** / OAuth consent screen.
2. Для личного использования выбрать External, если Internal недоступен.
3. Заполнить обязательные поля приложения.
4. Если приложение остаётся в Testing, добавить свой Google-аккаунт в Test users.

Публично раздавать один общий client secret не нужно. Каждый пользователь создаёт
собственный Desktop OAuth client в своём Google Cloud project.

## 3. Создать Desktop OAuth client

1. Открыть **APIs & Services → Credentials**.
2. Нажать **Create credentials → OAuth client ID**.
3. Выбрать **Desktop app**.
4. Скачать JSON.
5. Положить его в:

```text
~/.config/youtube-pipeline/youtube_client_secret.json
```

На Windows `~` означает домашнюю папку пользователя.

Не переименовывать чужой token в client secret. Не коммитить этот JSON.

## 4. Пройти первую авторизацию

```bash
uv run --with google-api-python-client --with google-auth-oauthlib \
  "<skill-dir>/scripts/upload_youtube.py" --check-auth
```

Откроется браузер. Выбрать Google-аккаунт и нужный YouTube-канал. Скрипт покажет:

- channel title;
- channel ID;
- путь к локальному token.

Token хранится в:

```text
~/.config/youtube-pipeline/youtube_token.json
```

На macOS/Linux скрипт ставит права `0600`.

## 5. Зафиксировать канал в проекте

Скопировать показанный ID в `publish.json`:

```json
{
  "expected_channel_id": "UC_REPLACE_WITH_YOUR_CHANNEL_ID"
}
```

Перед каждой реальной загрузкой скрипт снова получает активный канал через API.
Если IDs не совпадают, загрузка прекращается до `videos.insert`.

## Частые ошибки

### Access blocked / app not verified

Проверить, что аккаунт добавлен в Test users. Для личного Desktop client обычно
не нужно публиковать приложение для всех.

### API has not been used / accessNotConfigured

Включить YouTube Data API v3 именно в том Cloud project, из которого скачан JSON.

### Scope changed

Удалить только локальный `youtube_token.json` и снова выполнить `--check-auth`.
Client secret удалять не нужно.

### Открылся не тот канал

Не продолжать загрузку. Удалить локальный token, повторить OAuth и сверить
`expected_channel_id`.

## Где сверять актуальные требования

- YouTube Data API: https://developers.google.com/youtube/v3/
- Installed-app OAuth: https://developers.google.com/youtube/v3/guides/auth/installed-apps
- Upload guide: https://developers.google.com/youtube/v3/guides/uploading_a_video
