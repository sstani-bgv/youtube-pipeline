#!/usr/bin/env python3
"""Store a Groq API key without echoing it or putting it in shell history."""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

DEFAULT_PATH = Path.home() / ".config" / "groq-transcribe" / ".env"


def main() -> None:
    parser = argparse.ArgumentParser(description="Безопасно сохранить GROQ_API_KEY")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    destination = args.path.expanduser().resolve()
    if destination.exists() and not args.force:
        raise SystemExit(
            f"Файл уже существует: {destination}\n"
            "Для осознанной замены добавьте --force."
        )

    key = getpass.getpass("Вставьте Groq API key (ввод скрыт): ").strip()
    if not key or any(character in key for character in "\r\n"):
        raise SystemExit("Пустой или некорректный key; файл не создан.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(f"GROQ_API_KEY={key}\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, destination)
    os.chmod(destination, 0o600)
    print(f"Groq key сохранён: {destination}")
    print("Значение ключа не выводилось.")


if __name__ == "__main__":
    main()
