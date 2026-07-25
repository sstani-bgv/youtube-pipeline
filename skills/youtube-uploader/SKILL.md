---
name: youtube-uploader
description: "Безопасно загружать валидированный YouTube-проект через официальный YouTube Data API: OAuth preflight, channel guard, dry-run, private-by-default upload, thumbnail и idempotent receipt. Использовать только после youtube-meta-validator."
---

# YouTube Uploader

До первого использования прочитать setup в соседнем `$youtube-pipeline`.

Dry-run:

```bash
python3 "<skill-dir>/scripts/upload_youtube.py" --project "<project-dir>"
```

OAuth check:

```bash
uv run --with google-api-python-client --with google-auth-oauthlib \
  "<skill-dir>/scripts/upload_youtube.py" --check-auth
```

Apply выполнять только после явного разрешения и точного confirm:

```bash
uv run --with google-api-python-client --with google-auth-oauthlib \
  "<skill-dir>/scripts/upload_youtube.py" --project "<project-dir>" \
  --apply --confirm "UPLOAD:<video-filename>"
```

Правила:

- default visibility `private`;
- `public` требует отдельного `--allow-public`;
- active channel обязан совпасть с `expected_channel_id`;
- существующий receipt проверять до нового upload;
- key/token/secret не печатать и не класть в проект.
