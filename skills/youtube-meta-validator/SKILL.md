---
name: youtube-meta-validator
description: "Валидировать переносимый YouTube publish.json и локальные media assets перед dry-run или upload: title, description, tags, thumbnail, audience, visibility, channel guard и пути. Использовать после generation-фазы и всегда непосредственно перед удалённой мутацией."
---

# YouTube Meta Validator

Запустить:

```bash
python3 "<skill-dir>/scripts/validate_project.py" "<project-dir>"
```

Перед реальным upload дополнительно:

```bash
python3 "<skill-dir>/scripts/validate_project.py" \
  "<project-dir>" --require-channel-id
```

Exit 0 означает валидную конфигурацию. Warning не скрывать. Ошибки исправить в
owning generation skill и повторить validator; не обходить проверку вручную.
