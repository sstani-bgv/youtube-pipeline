#!/usr/bin/env python3
"""Validate a portable publish.json against current YouTube Data API limits."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{20,}$")
ALLOWED_PRIVACY = {"private", "unlisted", "public"}
ALLOWED_THUMBNAIL_SUFFIXES = {".png", ".jpg", ".jpeg"}


def resolve_media_path(project: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (project / path).resolve()


def tags_budget(tags: list[str]) -> int:
    total = 0
    for index, tag in enumerate(tags):
        if index:
            total += 1
        total += len(tag) + (2 if " " in tag else 0)
    return total


def validate(
    project: Path,
    require_channel_id: bool = False,
) -> tuple[dict[str, Any], list[str], list[str]]:
    config_path = project / "publish.json"
    if not config_path.is_file():
        return {}, [f"Не найден {config_path}"], []

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"Не удалось прочитать publish.json: {exc}"], []

    if not isinstance(config, dict):
        return {}, ["Корень publish.json должен быть JSON object"], []

    errors: list[str] = []
    warnings: list[str] = []

    title = config.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("title обязателен")
    elif len(title) > 100:
        errors.append(f"title: {len(title)} символов, максимум 100")
    elif "<" in title or ">" in title:
        errors.append("title не может содержать < или >")

    description = config.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("description обязателен")
    else:
        description_bytes = len(description.encode("utf-8"))
        if description_bytes > 5000:
            errors.append(
                f"description: {description_bytes} UTF-8 байт, максимум 5000"
            )
        if "<" in description or ">" in description:
            errors.append("description не может содержать < или >")

    tags = config.get("tags")
    if not isinstance(tags, list) or not all(
        isinstance(tag, str) and tag.strip() for tag in tags
    ):
        errors.append("tags должен быть списком непустых строк")
    else:
        budget = tags_budget(tags)
        if budget > 500:
            errors.append(f"tags: расчётный бюджет {budget}, максимум 500")
        if any("<" in tag or ">" in tag for tag in tags):
            errors.append("tags не могут содержать < или >")
        if len(tags) > 30:
            warnings.append("Тегов больше 30; обычно это не даёт дополнительной пользы")

    video = resolve_media_path(project, config.get("video"))
    if video is None:
        errors.append("video обязателен")
    elif not video.is_file():
        errors.append(f"Видео не найдено: {video}")

    thumbnail = resolve_media_path(project, config.get("thumbnail"))
    if thumbnail is not None:
        if not thumbnail.is_file():
            errors.append(f"Обложка не найдена: {thumbnail}")
        else:
            if thumbnail.suffix.lower() not in ALLOWED_THUMBNAIL_SUFFIXES:
                errors.append("Обложка для API должна быть PNG или JPEG")
            if thumbnail.stat().st_size > 2 * 1024 * 1024:
                errors.append("Обложка больше лимита YouTube Data API 2 MB")

    channel_id = config.get("expected_channel_id")
    if not isinstance(channel_id, str) or not channel_id.strip():
        message = (
            "expected_channel_id пока пуст; получите его через "
            "upload_youtube.py --check-auth"
        )
        (errors if require_channel_id else warnings).append(message)
    elif not CHANNEL_ID_RE.fullmatch(channel_id):
        errors.append("expected_channel_id имеет неверный формат")

    privacy = config.get("privacy")
    if privacy not in ALLOWED_PRIVACY:
        errors.append("privacy: допустимы private, unlisted, public")
    elif privacy == "public":
        warnings.append("Запрошен public: uploader потребует отдельный --allow-public")

    if not isinstance(config.get("made_for_kids"), bool):
        errors.append("made_for_kids должен быть true или false")

    for key in ("category_id", "default_language", "default_audio_language"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            errors.append(f"{key} должен быть непустой строкой")

    return config, errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверить YouTube project")
    parser.add_argument("project_dir", type=Path)
    parser.add_argument(
        "--require-channel-id",
        action="store_true",
        help="Считать пустой expected_channel_id ошибкой",
    )
    args = parser.parse_args()

    project = args.project_dir.expanduser().resolve()
    _, errors, warnings = validate(
        project,
        require_channel_id=args.require_channel_id,
    )

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")

    if errors:
        print(f"\nFAIL: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 2
    print(f"OK: publish.json валиден, warnings={len(warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
