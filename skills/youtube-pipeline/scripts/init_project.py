#!/usr/bin/env python3
"""Create a portable YouTube project skeleton without overwriting user files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

BRIEF = """# Brief

## Тема

[О чём видео]

## Зритель

[Кому и в какой ситуации полезно видео]

## Проблема и обещание

[Что болит и что зритель получит]

## Ключевые факты

- [Факт, число или пример из видео]

## CTA и ссылки

[Только реальные ссылки и действия]

## Tone of voice

[Как должен звучать автор]

## Ограничения

[Что нельзя обещать, упоминать или публиковать]
"""


def write_if_missing(path: Path, text: str) -> bool:
    if path.exists():
        return False
    path.write_text(text, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Создать YouTube project skeleton")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--language", default="ru")
    args = parser.parse_args()

    project = args.project_dir.expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    (project / "transcript").mkdir(exist_ok=True)
    (project / "thumbnails").mkdir(exist_ok=True)

    video = str(args.video.expanduser().resolve()) if args.video else ""
    config = {
        "title": "",
        "description": "",
        "tags": [],
        "video": video,
        "thumbnail": "",
        "expected_channel_id": "",
        "privacy": "private",
        "category_id": "22",
        "default_language": args.language,
        "default_audio_language": args.language,
        "made_for_kids": None,
    }

    created: list[Path] = []
    if write_if_missing(project / "brief.md", BRIEF):
        created.append(project / "brief.md")
    if write_if_missing(
        project / "publish.json",
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
    ):
        created.append(project / "publish.json")

    if created:
        print("Создано:")
        for path in created:
            print(f"  {path}")
    else:
        print(f"Ничего не перезаписано: проект уже существует в {project}")


if __name__ == "__main__":
    main()
