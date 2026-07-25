#!/usr/bin/env python3
"""Install the bundled skills into Codex, Claude Code, or a custom directory."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_NAMES = ("youtube-pipeline", "groq-transcribe")
PACKAGE_ROOT = Path(__file__).resolve().parent
TARGETS = {
    "codex": Path.home() / ".codex" / "skills",
    "claude": Path.home() / ".claude" / "skills",
}


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Установить YouTube Pipeline и Groq Transcribe"
    )
    parser.add_argument(
        "--target",
        choices=("codex", "claude", "both"),
        default="codex",
        help="Куда установить (по умолчанию: codex)",
    )
    parser.add_argument(
        "--skill",
        choices=("all", *SKILL_NAMES),
        default="all",
        help="Какой скилл установить (по умолчанию: оба)",
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
    args = parser.parse_args()

    selected_skills = SKILL_NAMES if args.skill == "all" else (args.skill,)
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

    installed = ", ".join(f"${name}" for name in selected_skills)
    print(f"\nГотово. Перезапустите Codex/Claude Code. Установлено: {installed}.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nУстановка отменена.")
