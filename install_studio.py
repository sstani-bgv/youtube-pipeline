#!/usr/bin/env python3
"""Install the optional unofficial yt-studio adapter from its public repository."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

DEFAULT_REPO = "https://github.com/sstani-bgv/yt-studio.git"
DEFAULT_DIR = Path.home() / ".local" / "share" / "youtube-pipeline" / "yt-studio"


def run(command: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Установить опциональный адаптер yt-studio"
    )
    parser.add_argument("--repo-url", default=DEFAULT_REPO)
    parser.add_argument("--install-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Обновить уже скачанный репозиторий через git pull --ff-only",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="Не скачивать Playwright Chromium (для CI/повторной установки)",
    )
    args = parser.parse_args()

    for executable in ("git", "uv"):
        if not shutil.which(executable):
            raise SystemExit(
                f"Не найден {executable}. Установите его по инструкции в README.md."
            )

    destination = args.install_dir.expanduser().resolve()
    if destination.exists():
        if not (destination / ".git").is_dir():
            raise SystemExit(
                f"Папка уже существует, но это не git-репозиторий: {destination}"
            )
        if args.update:
            run(["git", "pull", "--ff-only"], cwd=destination)
        else:
            print(f"Репозиторий уже скачан: {destination}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--depth", "1", args.repo_url, str(destination)])

    run(
        [
            "uv",
            "tool",
            "install",
            "--force",
            "--with",
            "playwright>=1.45",
            "--editable",
            str(destination),
        ]
    )
    if not args.skip_browser:
        run(
            [
                "uv",
                "run",
                "--with",
                "playwright>=1.45",
                "python",
                "-m",
                "playwright",
                "install",
                "chromium",
            ]
        )
    print("\nГотово. Проверка: ytstudio-safe --help")
    print(
        "Важно: это неофициальный private-API инструмент. "
        "Сначала используйте тестовый канал и dry-run."
    )


if __name__ == "__main__":
    main()
