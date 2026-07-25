#!/usr/bin/env python3
"""Install YouTube Pipeline skill bundles and optionally prepare runtimes."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent

CORE_SKILLS = (
    "youtube-pipeline",
    "groq-transcribe",
)
GENERATION_SKILLS = (
    "youtube-generation",
    "youtube-title-generator",
    "youtube-seo-tags",
    "youtube-description-writer",
    "youtube-thumbnail-text-generator",
    "youtube-thumbnail-image-generator",
    "shorts-cutter",
    "make-reels-video",
)
PUBLISH_SKILLS = (
    "youtube-meta-validator",
    "youtube-uploader",
)
SKILL_NAMES = tuple(dict.fromkeys((*CORE_SKILLS, *GENERATION_SKILLS, *PUBLISH_SKILLS)))
BUNDLES = {
    "core": CORE_SKILLS,
    "generation": GENERATION_SKILLS,
    "publish": PUBLISH_SKILLS,
    "all": SKILL_NAMES,
}
TARGETS = {
    "codex": Path.home() / ".codex" / "skills",
    "claude": Path.home() / ".claude" / "skills",
}
RUNTIME_PACKAGES = (
    "requests==2.34.2",
    "google-api-python-client",
    "google-auth-oauthlib",
    "Pillow>=10",
    "gdown>=5",
    "yt-dlp",
)


def run(command: list[str]) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True)


def install_one(skill_name: str, target_root: Path, force: bool) -> None:
    source = PACKAGE_ROOT / "skills" / skill_name
    destination = target_root / skill_name
    if not source.is_dir():
        raise SystemExit(f"Не найдена папка скилла: {source}")

    target_root.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not force:
            raise SystemExit(
                f"Уже существует: {destination}\n"
                "Для обновления добавьте --force. "
                "Старая версия будет сохранена рядом."
            )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup = destination.with_name(f"{skill_name}.backup-{stamp}")
        destination.rename(backup)
        print(f"Резервная копия: {backup}")

    shutil.copytree(source, destination)
    print(f"Установлено: {destination}")


def prepare_runtime() -> None:
    missing = [name for name in ("uv", "ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise SystemExit(
            "Не найдены системные зависимости: "
            + ", ".join(missing)
            + ". Попросите агента установить их пакетным менеджером ОС и повторить команду."
        )

    command = ["uv", "run"]
    for package in RUNTIME_PACKAGES:
        command.extend(("--with", package))
    command.extend(
        (
            "python",
            "-c",
            (
                "import requests, googleapiclient, google_auth_oauthlib, PIL, "
                "gdown, yt_dlp; print('Python runtime dependencies: OK')"
            ),
        )
    )
    run(command)

    if not shutil.which("hyperframes"):
        if shutil.which("bun"):
            run(["bun", "add", "-g", "hyperframes"])
        elif shutil.which("npm"):
            run(["npm", "install", "-g", "hyperframes"])
        else:
            raise SystemExit(
                "Не найдены hyperframes, bun или npm. "
                "Попросите агента установить Node.js/npm, затем повторить команду."
            )
    run(["hyperframes", "--version"])


def install_studio(skip_browser: bool) -> None:
    command = [sys.executable, str(PACKAGE_ROOT / "install_studio.py")]
    if skip_browser:
        command.append("--skip-browser")
    run(command)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Установить полный YouTube Pipeline или отдельный bundle"
    )
    parser.add_argument(
        "--target",
        choices=("codex", "claude", "both"),
        default="codex",
        help="Куда установить (по умолчанию: codex)",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--bundle",
        choices=tuple(BUNDLES),
        default="all",
        help="Контур скиллов: core, generation, publish или all",
    )
    selection.add_argument(
        "--skill",
        choices=("all", *SKILL_NAMES),
        help="Установить только один скилл",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        help="Установить в указанный каталог skills (для CI/теста)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Обновить существующие установки с резервными копиями",
    )
    parser.add_argument(
        "--prepare-runtime",
        action="store_true",
        help="Скачать Python dependencies и установить HyperFrames CLI",
    )
    parser.add_argument(
        "--with-studio",
        action="store_true",
        help="Установить login-only yt-studio adapter и браузер Playwright",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="С --with-studio не скачивать Playwright Chromium",
    )
    args = parser.parse_args()

    selected_skills = (
        SKILL_NAMES
        if args.skill == "all"
        else (args.skill,)
        if args.skill
        else BUNDLES[args.bundle]
    )
    if args.target_dir:
        selected_targets = {"custom": args.target_dir.expanduser().resolve()}
    else:
        selected_targets = (
            TARGETS
            if args.target == "both"
            else {args.target: TARGETS[args.target]}
        )

    for target_name, target_root in selected_targets.items():
        print(f"\n{target_name}:")
        for skill_name in selected_skills:
            install_one(skill_name, target_root, args.force)

    if args.prepare_runtime:
        print("\nruntime:")
        prepare_runtime()
    if args.with_studio:
        print("\nyt-studio:")
        install_studio(args.skip_browser)

    installed = ", ".join(f"${name}" for name in selected_skills)
    print(f"\nГотово. Перезапустите агента. Установлено: {installed}.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nУстановка отменена.")
