#!/usr/bin/env python3
"""Transcribe audio/video with Groq while preserving source-timeline timestamps."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_ENV_FILE = Path.home() / ".config" / "groq-transcribe" / ".env"
API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def read_env_value(path: Path, name: str) -> str:
    if not path.is_file():
        return ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip("\"'")
    return ""


def api_key(env_file: Path) -> str:
    return os.environ.get("GROQ_API_KEY", "") or read_env_value(
        env_file, "GROQ_API_KEY"
    )


def require_executables() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise SystemExit(
            "Не найдены команды: "
            + ", ".join(missing)
            + ". Установите ffmpeg по references/SETUP.md."
        )


def duration_seconds(source: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"ffprobe не смог прочитать файл: {source}")
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise SystemExit("ffprobe не вернул длительность") from exc
    if duration <= 0:
        raise SystemExit("Длительность файла должна быть больше нуля")
    return duration


def atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, payload: Any, indent: int = 2) -> None:
    atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=indent) + "\n",
    )


def cache_is_fresh(output: Path, source: Path) -> bool:
    required = [
        output / "raw.words.json",
        output / "raw.srt",
        output / "raw.txt",
        output / "raw.json",
    ]
    if any(
        not path.is_file()
        or path.stat().st_size == 0
        or path.stat().st_mtime < source.stat().st_mtime
        for path in required
    ):
        return False
    try:
        words = json.loads(required[0].read_text(encoding="utf-8"))
        metadata = json.loads(required[3].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(words, list)
        and bool(words)
        and isinstance(metadata, dict)
        and bool(metadata.get("segments"))
    )


def transcribe_chunk(
    source: Path,
    chunk_file: Path,
    start: float,
    length: float,
    track: str,
    key: str,
    model: str,
    language: str,
    prompt: str,
) -> dict[str, Any]:
    import requests

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{length:.3f}",
            "-i",
            str(source),
            "-map",
            track,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "64k",
            str(chunk_file),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    form: list[tuple[str, str]] = [
        ("model", model),
        ("response_format", "verbose_json"),
        ("timestamp_granularities[]", "word"),
        ("temperature", "0"),
    ]
    if language != "auto":
        form.append(("language", language))
    if prompt:
        form.append(("prompt", prompt))

    with chunk_file.open("rb") as handle:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {key}"},
            data=form,
            files={"file": (chunk_file.name, handle, "audio/mpeg")},
            timeout=600,
        )
    if not response.ok:
        try:
            detail = response.json().get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            detail = response.text[:300]
        raise RuntimeError(f"Groq HTTP {response.status_code}: {detail}")
    data = response.json()
    if not isinstance(data, dict):
        raise TypeError("Groq вернул неожиданный формат ответа")
    return data


def timestamp_srt(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def build_segments(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for index, word in enumerate(words):
        current.append(word)
        next_word = words[index + 1] if index + 1 < len(words) else None
        gap = (float(next_word["start"]) - float(word["end"])) if next_word else 99
        segment_duration = float(word["end"]) - float(current[0]["start"])
        ends_sentence = str(word["word"]).endswith((".", "?", "!", "…", ":"))
        if (
            (ends_sentence and len(current) >= 3)
            or segment_duration > 6.5
            or gap > 0.8
            or len(current) >= 14
        ):
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    segments: list[dict[str, Any]] = []
    for index, group in enumerate(groups, 1):
        segments.append(
            {
                "id": index,
                "start": round(float(group[0]["start"]), 3),
                "end": round(float(group[-1]["end"]), 3),
                "text": " ".join(str(item["word"]) for item in group).strip(),
            }
        )
    return segments


def paragraphs(words: list[dict[str, Any]]) -> str:
    output: list[str] = []
    buffer: list[str] = []
    for index, word in enumerate(words):
        buffer.append(str(word["word"]))
        next_word = words[index + 1] if index + 1 < len(words) else None
        gap = (float(next_word["start"]) - float(word["end"])) if next_word else 99
        if gap > 1.5:
            output.append(" ".join(buffer).strip())
            buffer = []
    if buffer:
        output.append(" ".join(buffer).strip())
    return "\n\n".join(output) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Groq Whisper transcription with word timestamps"
    )
    parser.add_argument("media", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--language", default="auto")
    parser.add_argument(
        "--model",
        choices=("whisper-large-v3", "whisper-large-v3-turbo"),
        default="whisper-large-v3",
    )
    parser.add_argument(
        "--chunk-seconds",
        type=float,
        default=900.0,
        help="Длина одного API-чанка; default 900 seconds",
    )
    parser.add_argument("--track", default="0:a:0")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    require_executables()
    source = args.media.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Файл не найден: {source}")
    if args.chunk_seconds < 10 or args.chunk_seconds > 1800:
        raise SystemExit("--chunk-seconds должен быть от 10 до 1800")

    output = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else source.parent / f"{source.stem}-transcript"
    )
    if not args.force and cache_is_fresh(output, source):
        print(f"Кэш актуален: {output} (для повтора добавьте --force)")
        return 0

    env_file = args.env_file.expanduser().resolve()
    key = api_key(env_file)
    if not key:
        raise SystemExit(
            "Не найден GROQ_API_KEY. "
            f"Задайте env или создайте {env_file}. См. references/SETUP.md."
        )
    output.mkdir(parents=True, exist_ok=True)
    raw_srt = output / "raw.srt"

    prompt = ""
    if args.prompt_file:
        prompt_path = args.prompt_file.expanduser().resolve()
        if not prompt_path.is_file():
            raise SystemExit(f"Prompt file не найден: {prompt_path}")
        prompt = prompt_path.read_text(encoding="utf-8").strip()

    duration = duration_seconds(source)
    words: list[dict[str, Any]] = []
    detected_languages: list[str] = []

    with tempfile.TemporaryDirectory(prefix="groq-transcribe-") as temp_dir:
        temp = Path(temp_dir)
        start = 0.0
        chunk_index = 0
        while start < duration - 0.01:
            length = min(args.chunk_seconds, duration - start)
            chunk_file = temp / f"chunk-{chunk_index:04d}.mp3"
            data = transcribe_chunk(
                source=source,
                chunk_file=chunk_file,
                start=start,
                length=length,
                track=args.track,
                key=key,
                model=args.model,
                language=args.language,
                prompt=prompt,
            )
            detected = data.get("language")
            if isinstance(detected, str):
                detected_languages.append(detected)
            chunk_words = data.get("words") or []
            if not isinstance(chunk_words, list):
                raise TypeError("Groq response.words не является списком")
            for item in chunk_words:
                if not isinstance(item, dict):
                    continue
                try:
                    word_start = float(item["start"]) + start
                    word_end = float(item["end"]) + start
                    text = str(item["word"])
                except (KeyError, TypeError, ValueError):
                    continue
                words.append(
                    {
                        "start": round(word_start, 3),
                        "end": round(word_end, 3),
                        "word": text,
                    }
                )
            print(
                f"chunk {chunk_index + 1}: "
                f"{start:.1f}-{start + length:.1f}s, words={len(chunk_words)}"
            )
            start += length
            chunk_index += 1

    if not words:
        raise SystemExit("Groq не вернул ни одного слова")

    segments = build_segments(words)
    srt_blocks = [
        (
            f"{segment['id']}\n"
            f"{timestamp_srt(float(segment['start']))} --> "
            f"{timestamp_srt(float(segment['end']))}\n"
            f"{segment['text']}\n"
        )
        for segment in segments
    ]
    language = (
        detected_languages[0]
        if detected_languages
        else (args.language if args.language != "auto" else "unknown")
    )

    atomic_json(output / "raw.words.json", words, indent=2)
    atomic_text(raw_srt, "\n".join(srt_blocks))
    atomic_text(output / "raw.txt", paragraphs(words))
    atomic_json(
        output / "raw.json",
        {
            "model": args.model,
            "language": language,
            "duration": round(duration, 3),
            "source_filename": source.name,
            "segments": segments,
        },
        indent=2,
    )

    print(f"\nГотово: {output}")
    print(f"duration={duration:.1f}s words={len(words)} segments={len(segments)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit("\nТранскрибация прервана.")
