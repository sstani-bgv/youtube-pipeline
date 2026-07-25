#!/usr/bin/env python3
"""Авто-субтитры для нарезки рилсов через Groq Whisper.

Вход:  путь к видео ИЛИ аудио ролика (уже кадрированного 9:16 — неважно, берём только звук).
Поток: ffmpeg извлекает моно-аудио → Groq whisper-large-v3 (verbose_json + word-level
       таймштампы) → пословные тайминги режутся на короткие читаемые фразы (1 фраза =
       1 субтитр-кадр, русский) → JSON, который ложится в HyperFrames-композицию
       karaoke-субтитров (см. references/template/index.html).
Выход: JSON-файл со списком субтитр-фраз. Формат описан ниже.

Зависимости: ТОЛЬКО stdlib + ffmpeg/ffprobe в PATH. Никаких pip install groq/requests —
multipart-запрос к Groq собирается руками (как в watch-скилле, на котором основан этот код).

Ключ: `GROQ_API_KEY` из окружения, `.env` проекта или
`~/.config/groq-transcribe/.env`.

--------------------------------------------------------------------------------------------
ФОРМАТ ВЫХОДА (под template/index.html)

{
  "meta": { "source": "...", "language": "ru", "backend": "groq",
            "model": "whisper-large-v3", "phrase_count": 12, "duration": 16.4 },
  "subs": [
    {
      "index": 1,
      "start": 0.55,          # сек — кладётся в data-start субтитр-div
      "end": 2.30,            # сек
      "duration": 1.75,       # сек — кладётся в data-duration
      "text": "смотри что он делает сам",
      "hl": "сам",            # ключевое слово фразы → оборачивается в <span class="hl">
      "words": [              # пословные тайминги (опц.) — для пер-словного karaoke
        { "word": "смотри", "start": 0.55, "end": 0.92 },
        ...
      ]
    },
    ...
  ]
}

Как это ложится в template/index.html: каждый объект subs[i] = один блок
  <div class="sub clip" data-start="{start}" data-duration="{duration}" data-track-index="9">
    текст до hl <span class="hl">{hl}</span> текст после
  </div>
плюс снаппи-поп в таймлайне на {start}. Пословные words[] нужны, только если делаешь
пер-словную подсветку (а не одну .hl на фразу) — для базового шаблона достаточно text + hl.

ДОПУЩЕНИЕ про формат ответа Groq: ответ verbose_json содержит "segments" (start/end/text)
и, при timestamp_granularities[]=word, плоский список "words" ({word,start,end}). Это
совпадает с OpenAI-совместимым контрактом Groq. Если в ответе нет "words" (модель/эндпоинт
их не вернул), скрипт деградирует к посегментной разбивке — фразы будут грубее, но валидны.
--------------------------------------------------------------------------------------------
ИСПОЛЬЗОВАНИЕ

  python3 transcribe_subs.py <video|audio> -o subs.json [--language ru]
                                                   [--max-chars 32] [--max-words 6]
                                                   [--max-gap 0.6]

  --max-chars / --max-words : предел длины одной субтитр-фразы (читаемость на 9:16).
  --max-gap                 : пауза (сек) между словами, которая принудительно рвёт фразу.
"""
from __future__ import annotations

import argparse
import io
import json
import mimetypes
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3"

# слова, которые НЕ стоит делать акцентным (.hl) — служебные/связки
RU_STOPWORDS = {
    "и", "а", "но", "да", "не", "ни", "же", "бы", "ли", "то", "что", "как", "так",
    "это", "этот", "эта", "эти", "вот", "уже", "ещё", "еще", "или", "за", "по", "на",
    "в", "во", "к", "ко", "с", "со", "о", "об", "от", "до", "у", "из", "при", "про",
    "для", "без", "над", "под", "я", "ты", "он", "она", "оно", "мы", "вы", "они",
    "его", "её", "ее", "их", "мне", "тебе", "нам", "вам", "им", "был", "была", "было",
    "были", "есть", "будет", "если", "когда", "чтобы", "там", "тут", "здесь",
}

# пунктуация, на которой логично закрывать фразу
PHRASE_END_RE = re.compile(r"[.!?…]+$")
CLAUSE_END_RE = re.compile(r"[,;:—–-]+$")


# ----------------------------------------------------------------------------- ключ
def load_api_key() -> str:
    """GROQ_API_KEY из env → .env в cwd/родителях → user config."""
    val = (os.environ.get("GROQ_API_KEY") or "").strip()
    if val:
        return val

    def _from_dotenv(path: Path) -> str | None:
        if not path.exists():
            return None
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, raw = line.partition("=")
                if key.strip() != "GROQ_API_KEY":
                    continue
                raw = raw.strip()
                if len(raw) >= 2 and raw[0] in ("'", '"') and raw[-1] == raw[0]:
                    raw = raw[1:-1]
                return raw or None
        except OSError:
            return None
        return None

    candidates = [Path.cwd(), *Path.cwd().parents]
    for d in candidates:
        v = _from_dotenv(d / ".env")
        if v:
            return v
    v = _from_dotenv(Path.home() / ".config" / "groq-transcribe" / ".env")
    if v:
        return v

    raise SystemExit(
        "Нет GROQ_API_KEY. Задайте переменную окружения или сохраните ключ в "
        "~/.config/groq-transcribe/.env."
    )


# ----------------------------------------------------------------------------- аудио
def extract_audio(src: str, out_path: Path) -> Path:
    """Извлечь моно 16kHz mp3 (~0.5 МБ/мин — влезает в лимит Groq)."""
    if shutil.which("ffmpeg") is None:
        raise SystemExit(
            "Нет ffmpeg в PATH. Установите ffmpeg пакетным менеджером вашей ОС."
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(Path(src).resolve()),
        "-vn", "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-b:a", "64k",
        str(out_path.resolve()),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"ffmpeg не извлёк аудио: {res.stderr.strip()}")
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise SystemExit("ffmpeg вернул пустое аудио — у ролика нет звуковой дорожки?")
    return out_path


def probe_duration(src: str) -> float:
    if shutil.which("ffprobe") is None:
        return 0.0
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(Path(src).resolve())],
        capture_output=True, text=True,
    )
    try:
        return round(float(res.stdout.strip()), 2)
    except (ValueError, AttributeError):
        return 0.0


# ----------------------------------------------------------------------------- Groq
def _build_multipart(fields: dict, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----ReelsSubs{uuid.uuid4().hex}"
    eol = b"\r\n"
    buf = io.BytesIO()
    for name, value in fields.items():
        values = value if isinstance(value, (list, tuple)) else [value]
        for v in values:
            buf.write(f"--{boundary}".encode()); buf.write(eol)
            buf.write(f'Content-Disposition: form-data; name="{name}"'.encode()); buf.write(eol)
            buf.write(eol)
            buf.write(str(v).encode()); buf.write(eol)
    mimetype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    buf.write(f"--{boundary}".encode()); buf.write(eol)
    buf.write(f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"'.encode()); buf.write(eol)
    buf.write(f"Content-Type: {mimetype}".encode()); buf.write(eol)
    buf.write(eol)
    buf.write(file_path.read_bytes()); buf.write(eol)
    buf.write(f"--{boundary}--".encode()); buf.write(eol)
    return buf.getvalue(), boundary


MAX_ATTEMPTS = 4
MAX_429_RETRIES = 2
RETRY_BASE_DELAY = 2.0


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read()
    except Exception:
        return ""
    if not body:
        return ""
    try:
        return f" — {body.decode('utf-8', errors='replace')[:400]}"
    except Exception:
        return ""


def _retry_after(exc: urllib.error.HTTPError) -> float | None:
    header = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
    if not header:
        return None
    try:
        return float(header)
    except ValueError:
        return None


def groq_transcribe(audio_path: Path, api_key: str, language: str) -> dict:
    fields: dict = {
        "model": GROQ_MODEL,
        "response_format": "verbose_json",
        "temperature": "0",
        "timestamp_granularities[]": ["word", "segment"],
    }
    if language:
        fields["language"] = language
    body, boundary = _build_multipart(fields, audio_path)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        # Groq за Cloudflare: дефолтный Python-urllib UA ловит WAF 403 до auth.
        "User-Agent": "reels-motion-graphics/1.0 (+hermes; python-urllib)",
    }
    ctx = ssl.create_default_context()
    rate_hits = 0
    last_exc: Exception | None = None
    last_detail = ""
    for attempt in range(MAX_ATTEMPTS):
        req = Request(GROQ_ENDPOINT, data=body, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=300, context=ctx) as resp:
                payload = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = _read_error_body(exc)
            last_exc, last_detail = exc, detail
            if 400 <= exc.code < 500 and exc.code != 429:
                raise SystemExit(f"Groq отклонил запрос: {exc}{detail}")
            if exc.code == 429:
                rate_hits += 1
                if rate_hits >= MAX_429_RETRIES:
                    raise SystemExit(f"Groq rate limit: {exc}{detail}")
                delay = _retry_after(exc) or RETRY_BASE_DELAY * (2 ** attempt) + 1
            else:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
            if attempt < MAX_ATTEMPTS - 1:
                print(f"  Groq HTTP {exc.code} — повтор через {delay:.1f}с "
                      f"(попытка {attempt + 2}/{MAX_ATTEMPTS})", file=sys.stderr)
                time.sleep(delay)
            continue
        except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as exc:
            last_exc, last_detail = exc, ""
            if attempt < MAX_ATTEMPTS - 1:
                delay = RETRY_BASE_DELAY * (attempt + 1)
                print(f"  сеть ({type(exc).__name__}) — повтор через {delay:.1f}с "
                      f"(попытка {attempt + 2}/{MAX_ATTEMPTS})", file=sys.stderr)
                time.sleep(delay)
            continue
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Groq вернул не-JSON: {exc}: {payload[:200]}")
    raise SystemExit(f"Groq не ответил за {MAX_ATTEMPTS} попыток: {last_exc}{last_detail}")


# ----------------------------------------------------------------------------- разбивка
def _words_from_response(data: dict) -> list[dict]:
    """Плоский список слов {word,start,end} из verbose_json."""
    out: list[dict] = []
    for w in data.get("words") or []:
        text = (w.get("word") or "").strip()
        if not text:
            continue
        out.append({
            "word": text,
            "start": round(float(w.get("start") or 0.0), 3),
            "end": round(float(w.get("end") or 0.0), 3),
        })
    return out


def _segments_from_response(data: dict) -> list[dict]:
    out: list[dict] = []
    for seg in data.get("segments") or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        out.append({
            "start": round(float(seg.get("start") or 0.0), 3),
            "end": round(float(seg.get("end") or 0.0), 3),
            "text": text,
        })
    return out


def _pick_highlight(words: list[str]) -> str:
    """Выбрать акцентное слово фразы: самое длинное не-стоп-слово (последнее при равенстве)."""
    best = ""
    best_len = 0
    for raw in words:
        clean = re.sub(r"[^\wа-яёА-ЯЁ-]", "", raw, flags=re.UNICODE)
        if not clean:
            continue
        if clean.lower() in RU_STOPWORDS:
            continue
        if len(clean) >= best_len:
            best = clean
            best_len = len(clean)
    return best


def _flush_phrase(buf: list[dict], index: int) -> dict:
    text = " ".join(w["word"] for w in buf).strip()
    text = re.sub(r"\s+([,.!?;:…])", r"\1", text)  # убрать пробел перед пунктуацией
    start = round(buf[0]["start"], 2)
    end = round(buf[-1]["end"], 2)
    hl = _pick_highlight([w["word"] for w in buf])
    return {
        "index": index,
        "start": start,
        "end": end,
        "duration": round(max(0.1, end - start), 2),
        "text": text,
        "hl": hl,
        "words": [{"word": w["word"], "start": round(w["start"], 3),
                   "end": round(w["end"], 3)} for w in buf],
    }


def phrases_from_words(words: list[dict], max_chars: int, max_words: int,
                       max_gap: float) -> list[dict]:
    """Разбить поток слов на короткие читаемые фразы (1 фраза = 1 субтитр-кадр)."""
    subs: list[dict] = []
    buf: list[dict] = []
    cur_chars = 0
    idx = 1
    for i, w in enumerate(words):
        word_text = w["word"].strip()
        if not word_text:
            continue
        # пауза перед текущим словом
        gap = (w["start"] - buf[-1]["end"]) if buf else 0.0
        if buf and gap >= max_gap:
            subs.append(_flush_phrase(buf, idx)); idx += 1
            buf, cur_chars = [], 0
        buf.append(w)
        cur_chars += len(word_text) + 1
        end_clause = bool(PHRASE_END_RE.search(word_text)) or bool(CLAUSE_END_RE.search(word_text))
        over_budget = cur_chars >= max_chars or len(buf) >= max_words
        if end_clause or over_budget:
            subs.append(_flush_phrase(buf, idx)); idx += 1
            buf, cur_chars = [], 0
    if buf:
        subs.append(_flush_phrase(buf, idx))
    return subs


def phrases_from_segments(segments: list[dict], max_chars: int) -> list[dict]:
    """Фолбэк, если Groq не вернул пословные тайминги: режем сегменты по знакам/длине."""
    subs: list[dict] = []
    idx = 1
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        chunks = re.split(r"(?<=[.!?…])\s+", text)
        span = max(0.1, seg["end"] - seg["start"])
        total_chars = max(1, sum(len(c) for c in chunks))
        t = seg["start"]
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            # длинный кусок без пунктуации — режем по словам под max_chars
            pieces = _split_long(chunk, max_chars)
            for piece in pieces:
                dur = round(span * (len(piece) / total_chars), 2)
                dur = max(0.4, dur)
                start = round(t, 2)
                end = round(min(seg["end"], start + dur), 2)
                subs.append({
                    "index": idx,
                    "start": start,
                    "end": end,
                    "duration": round(max(0.1, end - start), 2),
                    "text": piece,
                    "hl": _pick_highlight(piece.split()),
                    "words": [],
                })
                idx += 1
                t = end
    return subs


def _split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    out, cur = [], []
    n = 0
    for word in text.split():
        if n + len(word) + 1 > max_chars and cur:
            out.append(" ".join(cur)); cur, n = [], 0
        cur.append(word); n += len(word) + 1
    if cur:
        out.append(" ".join(cur))
    return out


# ----------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description="Авто-субтитры для рилсов через Groq Whisper.")
    ap.add_argument("src", help="путь к видео или аудио ролика")
    ap.add_argument("-o", "--out", default="subs.json", help="куда писать JSON (default: subs.json)")
    ap.add_argument("--language", default="ru", help="язык распознавания (default: ru)")
    ap.add_argument("--max-chars", type=int, default=32, help="макс. символов на фразу (default: 32)")
    ap.add_argument("--max-words", type=int, default=6, help="макс. слов на фразу (default: 6)")
    ap.add_argument("--max-gap", type=float, default=0.6, help="пауза (с), рвущая фразу (default: 0.6)")
    ap.add_argument("--keep-audio", action="store_true", help="не удалять извлечённое аудио")
    args = ap.parse_args()

    src = args.src
    if not Path(src).exists():
        raise SystemExit(f"Нет файла: {src}")

    print(f"Субтитры для: {src}")
    api_key = load_api_key()

    # 1) аудио
    audio_path = Path(src)
    audio_exts = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
    extracted = False
    if Path(src).suffix.lower() not in audio_exts:
        print("  извлекаю аудио (ffmpeg, моно 16kHz)…")
        audio_path = extract_audio(src, Path(src).with_suffix(".reels_audio.mp3"))
        extracted = True
    size_kb = audio_path.stat().st_size / 1024
    print(f"  аудио {size_kb:.0f} кБ → Groq {GROQ_MODEL}…")

    # 2) Groq
    data = groq_transcribe(audio_path, api_key, args.language)
    words = _words_from_response(data)
    segments = _segments_from_response(data)

    # 3) фразы
    if words:
        print(f"  получено {len(words)} слов с таймингами → режу на фразы…")
        subs = phrases_from_words(words, args.max_chars, args.max_words, args.max_gap)
    elif segments:
        print(f"  пословных таймингов нет, фолбэк по {len(segments)} сегментам…")
        subs = phrases_from_segments(segments, args.max_chars)
    else:
        raise SystemExit("Groq не вернул ни слов, ни сегментов — пустая транскрипция.")

    if not subs:
        raise SystemExit("Не удалось собрать ни одной субтитр-фразы.")

    duration = probe_duration(src)
    out = {
        "meta": {
            "source": str(Path(src).resolve()),
            "language": args.language,
            "backend": "groq",
            "model": GROQ_MODEL,
            "phrase_count": len(subs),
            "duration": duration,
        },
        "subs": subs,
    }
    out_path = Path(args.out)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if extracted and not args.keep_audio:
        try:
            audio_path.unlink()
        except OSError:
            pass

    print(f"  готово: {len(subs)} субтитр-фраз → {out_path}")
    print("  дальше: разложи subs[] в .sub-блоки template/index.html "
          "(data-start / data-duration / .hl) и прогони QA.")


if __name__ == "__main__":
    main()
