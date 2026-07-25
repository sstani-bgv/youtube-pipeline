#!/usr/bin/env python3
"""Dry-run-first, channel-guarded, idempotent YouTube Data API uploader."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_project import resolve_media_path, validate

CONFIG_DIR = Path.home() / ".config" / "youtube-pipeline"
DEFAULT_CLIENT_SECRET = CONFIG_DIR / "youtube_client_secret.json"
DEFAULT_TOKEN = CONFIG_DIR / "youtube_token.json"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def credentials(client_secret: Path, token_path: Path):
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore

    creds = None
    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not client_secret.is_file():
            raise SystemExit(
                f"Не найден OAuth client secret: {client_secret}\n"
                "См. references/SETUP.md."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass
    return creds


def service_for(creds):
    from googleapiclient.discovery import build  # type: ignore

    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def active_channel(service) -> dict[str, str]:
    response = service.channels().list(part="id,snippet", mine=True).execute()
    items = response.get("items") or []
    if len(items) != 1:
        raise SystemExit(
            f"Ожидался один активный канал, API вернул: {len(items)}. "
            "Проверьте выбранный аккаунт."
        )
    item = items[0]
    return {
        "id": str(item.get("id", "")),
        "title": str((item.get("snippet") or {}).get("title", "")),
    }


def get_video(service, video_id: str) -> dict[str, Any] | None:
    response = service.videos().list(
        part="id,snippet,status",
        id=video_id,
    ).execute()
    items = response.get("items") or []
    return items[0] if items else None


def resumable_upload(service, video: Path, config: dict[str, Any]) -> str:
    from googleapiclient.errors import HttpError  # type: ignore
    from googleapiclient.http import MediaFileUpload  # type: ignore

    body = {
        "snippet": {
            "title": config["title"],
            "description": config["description"],
            "tags": config["tags"],
            "categoryId": config["category_id"],
            "defaultLanguage": config["default_language"],
            "defaultAudioLanguage": config["default_audio_language"],
        },
        "status": {
            "privacyStatus": config["privacy"],
            "selfDeclaredMadeForKids": config["made_for_kids"],
            "embeddable": True,
        },
    }
    media = MediaFileUpload(
        str(video),
        chunksize=8 * 1024 * 1024,
        resumable=True,
        mimetype="video/*",
    )
    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
        notifySubscribers=False,
    )

    response = None
    retries = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status is not None:
                print(f"upload: {int(status.progress() * 100)}%", flush=True)
        except HttpError as exc:
            if exc.resp.status not in RETRIABLE_STATUS_CODES or retries >= 5:
                raise
            delay = 2**retries
            retries += 1
            print(f"Временная ошибка HTTP {exc.resp.status}; retry через {delay}s")
            time.sleep(delay)

    video_id = response.get("id") if isinstance(response, dict) else None
    if not video_id:
        raise SystemExit("YouTube API не вернул video ID")
    return str(video_id)


def set_thumbnail(service, video_id: str, thumbnail: Path) -> None:
    from googleapiclient.http import MediaFileUpload  # type: ignore

    mimetype = "image/png" if thumbnail.suffix.lower() == ".png" else "image/jpeg"
    service.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(str(thumbnail), mimetype=mimetype),
    ).execute()


def receipt_from_live(
    video_id: str,
    live: dict[str, Any],
    channel: dict[str, str],
    thumbnail_applied: bool,
) -> dict[str, Any]:
    snippet = live.get("snippet") or {}
    status = live.get("status") or {}
    return {
        "schema_version": 1,
        "video_id": video_id,
        "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
        "watch_url": f"https://www.youtube.com/watch?v={video_id}",
        "channel_id": channel["id"],
        "channel_title": channel["title"],
        "privacy": status.get("privacyStatus"),
        "title": snippet.get("title"),
        "thumbnail_applied": thumbnail_applied,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def print_plan(project: Path, config: dict[str, Any]) -> str:
    video = resolve_media_path(project, config["video"])
    thumbnail = resolve_media_path(project, config.get("thumbnail"))
    confirmation = f"UPLOAD:{video.name if video else '<video>'}"
    print("DRY RUN — YouTube не изменён")
    print(f"  project: {project}")
    print(f"  video: {video}")
    print(f"  title: {config['title']}")
    print(f"  tags: {len(config['tags'])}")
    print(f"  thumbnail: {thumbnail or '(нет)'}")
    print(f"  expected channel: {config['expected_channel_id'] or '(не задан)'}")
    print(f"  privacy: {config['privacy']}")
    print(f"  made for kids: {config['made_for_kids']}")
    print(f"  exact confirm: {confirmation}")
    return confirmation


def main() -> int:
    parser = argparse.ArgumentParser(description="Безопасная загрузка на YouTube")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--check-auth", action="store_true")
    parser.add_argument("--client-secret", type=Path, default=DEFAULT_CLIENT_SECRET)
    parser.add_argument("--token", type=Path, default=DEFAULT_TOKEN)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--allow-public", action="store_true")
    parser.add_argument(
        "--force-new-upload",
        action="store_true",
        help="Создать новое видео, даже если receipt уже существует",
    )
    args = parser.parse_args()

    client_secret = args.client_secret.expanduser().resolve()
    token_path = args.token.expanduser().resolve()

    if args.check_auth:
        service = service_for(credentials(client_secret, token_path))
        channel = active_channel(service)
        print(f"Канал: {channel['title']}")
        print(f"Channel ID: {channel['id']}")
        print(f"Token: {token_path}")
        return 0

    if args.project is None:
        parser.error("нужен --project или --check-auth")

    project = args.project.expanduser().resolve()
    config, errors, warnings = validate(
        project,
        require_channel_id=args.apply,
    )
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 2

    expected_confirmation = print_plan(project, config)
    if not args.apply:
        if not config["expected_channel_id"]:
            print(
                "\nДо реальной загрузки выполните --check-auth, "
                "запишите channel ID в publish.json и повторите dry-run."
            )
        else:
            print("\nДля реальной загрузки добавьте:")
            print(f'  --apply --confirm "{expected_confirmation}"')
            if config["privacy"] == "public":
                print("  и --allow-public")
        return 0

    if args.confirm != expected_confirmation:
        raise SystemExit(
            f"Неверный --confirm. Ожидалось: {expected_confirmation}"
        )
    if config["privacy"] == "public" and not args.allow_public:
        raise SystemExit("Для public требуется отдельный флаг --allow-public")

    service = service_for(credentials(client_secret, token_path))
    channel = active_channel(service)
    if channel["id"] != config["expected_channel_id"]:
        raise SystemExit(
            "Активный канал не совпал с expected_channel_id; "
            "загрузка остановлена до videos.insert."
        )

    receipt_path = project / "upload_receipt.json"
    existing: dict[str, Any] | None = None
    if receipt_path.is_file():
        try:
            existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise SystemExit(f"Повреждён receipt: {receipt_path}")

    if existing and not args.force_new_upload:
        video_id = str(existing.get("video_id", ""))
        live = get_video(service, video_id) if video_id else None
        if not live:
            raise SystemExit(
                "Receipt существует, но видео не найдено. "
                "Проверьте аккаунт/удаление. Для нового upload нужен "
                "--force-new-upload."
            )
        live_channel = str((live.get("snippet") or {}).get("channelId", ""))
        if live_channel != channel["id"]:
            raise SystemExit("Receipt указывает на видео другого канала")

        thumbnail = resolve_media_path(project, config.get("thumbnail"))
        thumbnail_applied = bool(existing.get("thumbnail_applied"))
        if thumbnail and not thumbnail_applied:
            print("Продолжаю незавершённый шаг: thumbnail")
            set_thumbnail(service, video_id, thumbnail)
            thumbnail_applied = True
            live = get_video(service, video_id) or live

        receipt = receipt_from_live(
            video_id, live, channel, thumbnail_applied=thumbnail_applied
        )
        atomic_json(receipt_path, receipt)
        print(f"Видео уже существует; дубль не создан: {receipt['studio_url']}")
        return 0

    if existing and args.force_new_upload:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = receipt_path.with_name(f"upload_receipt.backup-{stamp}.json")
        receipt_path.rename(backup)
        print(f"Старый receipt сохранён: {backup}")

    video = resolve_media_path(project, config["video"])
    thumbnail = resolve_media_path(project, config.get("thumbnail"))
    assert video is not None

    started = time.monotonic()
    video_id = resumable_upload(service, video, config)
    minimal_receipt = {
        "schema_version": 1,
        "video_id": video_id,
        "channel_id": channel["id"],
        "privacy": config["privacy"],
        "thumbnail_applied": False,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "upload_seconds": round(time.monotonic() - started, 1),
    }
    atomic_json(receipt_path, minimal_receipt)

    thumbnail_applied = False
    if thumbnail:
        set_thumbnail(service, video_id, thumbnail)
        thumbnail_applied = True

    live = get_video(service, video_id)
    if not live:
        raise SystemExit(
            f"Upload вернул {video_id}, но read-after-write не нашёл видео. "
            f"Receipt сохранён: {receipt_path}"
        )
    live_channel = str((live.get("snippet") or {}).get("channelId", ""))
    if live_channel != channel["id"]:
        raise SystemExit("Live video принадлежит неожиданному каналу")

    receipt = receipt_from_live(
        video_id, live, channel, thumbnail_applied=thumbnail_applied
    )
    receipt["upload_seconds"] = minimal_receipt["upload_seconds"]
    atomic_json(receipt_path, receipt)

    print("\nЗагрузка подтверждена:")
    print(f"  Studio: {receipt['studio_url']}")
    print(f"  Watch: {receipt['watch_url']}")
    print(f"  Privacy: {receipt['privacy']}")
    print(f"  Receipt: {receipt_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.exit("\nОперация прервана. Перед повтором проверьте upload_receipt.json.")
