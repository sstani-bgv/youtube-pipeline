---
name: make-reels-video
description: "Производить один финальный вертикальный Reels/Shorts/TikTok из выбранного фрагмента: безопасные границы монтажа, karaoke captions, b-roll/PiP, CTA, HyperFrames composition и обязательный audio/visual QA. Использовать после shorts-cutter для одного изолированного Short; не использовать для отбора моментов или YouTube upload."
---

# Make Reels Video

Один вызов — один Short. Работать в изолированном каталоге; промежуточные файлы
держать в `/tmp`.

## Обязательный процесс

1. Получить source, `start/end`, hook, тезис, CTA и brief.
2. Проверить аудиограницы через `references/audio_boundary_qa.py`.
3. Получить word timestamps через готовый transcript или
   `references/transcribe_subs.py`.
4. Создать `plan.json`: HOOK, TALKING_HEAD, B-ROLL/PIP, CTA и subtitle beats.
5. Создать storyboard через `references/storyboard.py` и визуально проверить.
6. Собрать вертикальную HyperFrames-композицию из
   `references/template/index.html`.
7. Выполнить `hyperframes lint`, `hyperframes check`, snapshots и render.
8. Просмотреть начало, середину, конец и все склейки; проверить финальный MP4
   через `ffprobe`.

## Негативные требования

- не использовать случайный stock как доказательство;
- не превращать B-ROLL placeholder в текстовую карточку;
- не допускать двух слоёв субтитров;
- не обрезать слова на монтажных границах;
- не имитировать лицо/бренд пользователя без references;
- не загружать ролик автоматически.

## Acceptance receipt

```json
{
  "status": "done",
  "output": "short-final.mp4",
  "storyboard": "storyboard.png",
  "qa": {
    "audio_boundaries": "pass",
    "captions": "pass",
    "visual_review": "pass",
    "hyperframes": "pass"
  }
}
```

Подробные команды — в `references/PRODUCTION.md`; QA contract — в
`references/QA.md`.
