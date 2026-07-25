---
name: youtube-generation
description: "Оркестрировать отдельную генеративную фазу YouTube-проекта: параллельно создать title A/B/C, tags, description, thumbnail concepts/images и при необходимости Shorts/Reels с QA. Использовать когда brief и видео уже готовы, но packaging assets ещё не созданы, либо когда пользователь просит поставить или запустить только фазу generation."
---

# YouTube Generation

Владеть только генеративной фазой. Не выполнять upload и не менять YouTube.

## Вход

- `brief.md`;
- финальное видео;
- transcript, если он есть;
- язык, аудитория и CTA;
- пользовательские ссылки и brand assets, если предоставлены.

Не выдумывать ссылки, продукты, факты, channel IDs или лицо автора.

## Параллельные ветки

Запустить независимо:

- `$youtube-title-generator` → `meta/titles.md`;
- `$youtube-seo-tags` → `meta/tags.md`;
- `$youtube-description-writer` → `meta/description.md`;
- `$youtube-thumbnail-text-generator` → `meta/thumbnails.md`;
- `$youtube-thumbnail-image-generator` → `thumbnails/`;
- `$shorts-cutter` → `shorts/manifest.json`, затем отдельный
  `$make-reels-video` agent на каждый выбранный Short.

Thumbnail-image ветка ждёт только готовые concepts. Shorts могут стартовать после
transcript и локального video path, не дожидаясь остальных metadata.

## Acceptance

- три действительно разные title-гипотезы;
- thumbnail concepts не повторяют titles дословно;
- description основан на фактическом содержании;
- tags укладываются в YouTube budget;
- изображения существуют и визуально различаются либо честно отмечен text-only режим;
- каждый Short имеет storyboard, финальный MP4 и QA receipt;
- никаких удалённых мутаций.

Вернуть root-agent только компактные receipts и список output files.
