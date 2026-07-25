# Настройка Groq Transcribe

## Требования

- Python 3.10+;
- `uv`;
- `ffmpeg` и `ffprobe`;
- собственный Groq API key;
- интернет для обращения к Groq API.

## Установить uv

macOS с Homebrew:

```bash
brew install uv
```

macOS/Linux через официальный standalone installer:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Если не хотите сразу выполнять скачанный shell-скрипт, сначала сохраните и
прочитайте его либо установите `uv` через пакетный менеджер ОС.

Windows PowerShell:

```powershell
winget install --id=astral-sh.uv -e
```

## Установить ffmpeg

macOS:

```bash
brew install ffmpeg
```

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install ffmpeg
```

Windows PowerShell:

```powershell
winget install --id=Gyan.FFmpeg -e
```

После установки перезапустить Терминал:

```bash
uv --version
ffmpeg -version
ffprobe -version
```

## Создать API key

1. Открыть Groq Console.
2. Создать собственный API key.
3. Не пересылать его автору скилла и не вставлять в публичный issue.

## Сохранить key

macOS/Linux:

```bash
mkdir -p ~/.config/groq-transcribe
```

Создать `~/.config/groq-transcribe/.env`:

```text
GROQ_API_KEY=YOUR_GROQ_API_KEY
```

Ограничить доступ:

```bash
chmod 600 ~/.config/groq-transcribe/.env
```

На Windows можно создать тот же файл в:

```text
%USERPROFILE%\.config\groq-transcribe\.env
```

Либо задать `GROQ_API_KEY` только в окружении текущего процесса.

## Проверка без отправки файла

```bash
python3 "<skill-dir>/scripts/transcribe_groq.py" --help
```

Эта команда не требует сети. При первом реальном запуске `uv` скачает закреплённую
версию `requests`, поэтому интернет понадобится до обращения к Groq.

## Где сверять актуальные лимиты

Groq Speech to Text:

```text
https://console.groq.com/docs/speech-to-text
```

Скилл заранее сжимает и режет длинные файлы, но фактические rate limits и
стоимость зависят от аккаунта Groq.
