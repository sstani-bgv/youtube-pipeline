---
name: shorts-cutter
description: "Оркестрировать production-партию Shorts из длинного видео: выбрать самостоятельные непересекающиеся моменты, подготовить hook/title/description/CTA, делегировать каждый Short отдельному make-reels-video agent и собрать manifest с QA receipts. Использовать внутри youtube-generation или для отдельной нарезки Shorts."
---

# Shorts Cutter

Владеть selection и общим manifest, но не выполнять монтаж самостоятельно.

## Вход

- локальный long-form video;
- `transcript/raw.words.json` или эквивалентные word timestamps;
- brief, язык и желаемое число Shorts;
- authority на upload/schedule, если она вообще дана.

## Процесс

1. Выбрать самостоятельные непересекающиеся моменты с ясным hook и payoff.
2. Для каждого зафиксировать `start`, `end`, hook, тезис, CTA и ограничения.
3. Создать `shorts/manifest.json`.
4. На каждый элемент запустить отдельный `$make-reels-video` agent с собственным
   рабочим каталогом.
5. Принять только storyboard + финальный MP4 + audio/visual QA pass.
6. Upload делегировать `$youtube-uploader`; без authority оставить локально.

Не принимать placeholder b-roll, оборванную речь, двойные субтитры или receipt без
реального output file. Root-agent один обновляет общий manifest.
