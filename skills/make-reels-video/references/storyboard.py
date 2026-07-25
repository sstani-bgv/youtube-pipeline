#!/usr/bin/env python3
"""Сториборд-план монтажа: РЕАЛЬНЫЕ кадры из видео + аннотации → одна картинка.

Идея шага: ПЕРЕД нарезкой/рендером пользователь должен увидеть план монтажа.
План (plan.json) составляет Codex/агент из транскрипта, style guide и brief
(см. SKILL.md). Этот скрипт — «руки»: НЕ генерирует изображения и НЕ придумывает план.
Он берёт ГОТОВЫЙ plan.json, тянет ffmpeg'ом по 1 репрезентативному кадру на каждый бит
(середина диапазона start/end; для CTA без таймкода — последний кадр видео), раскладывает
вертикальные 9:16 кадры строкой/сеткой и подписывает каждый: label + тайм-код + overlay-заметка.
Сверху — баннер с хуком. Кадры РЕАЛЬНЫЕ из его видео, не концепт-арт.

Только ffmpeg + PIL (Pillow). NumPy не тащим.

Схема plan.json (составляет Codex, описана в SKILL.md):

  {
    "source": "work.mp4",
    "hook": "текст хука (первая секунда)",
    "subtitles": true,
    "beats": [
      {"start": 0.0, "end": 2.5, "label": "HOOK",
       "overlay": "крупный заголовок, акцент на 1 слове", "note": "..."},
      {"start": 3.2, "end": 8.9, "label": "B-ROLL",
       "overlay": "плавающая карточка в углу над плечом", "note": "..."},
      {"label": "CTA", "overlay": "пилюля 'сохрани' + 'подпишись'", "note": "конец"}
    ]
  }

Бит без start/end (типично CTA) → берём последний кадр видео.

Использование:
  python3 storyboard.py plan.json video.mp4 -o storyboard.png
  python3 storyboard.py plan.json video.mp4               # -o рядом с plan.json
  python3 storyboard.py plan.json video.mp4 --per-row 5   # кадров в ряду (default 4)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# -------- Шрифты (DejaVu из репо, без маковой специфики) ---------------------

def _find_fonts_dir() -> Path | None:
    """Найти hermes/skills/producing/guide/fonts/, идя вверх от этого файла."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "guide" / "fonts"
        if (cand / "DejaVuSans.ttf").exists():
            return cand
        cand = parent / "hermes" / "skills" / "producing" / "guide" / "fonts"
        if (cand / "DejaVuSans.ttf").exists():
            return cand
    return None


_FONTS_DIR = _find_fonts_dir()


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """DejaVu из репо (кириллица ок); фолбэк — PIL.ImageFont.load_default()."""
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    if _FONTS_DIR is not None:
        fp = _FONTS_DIR / name
        if fp.exists():
            try:
                return ImageFont.truetype(str(fp), size)
            except OSError:
                pass
    try:
        return ImageFont.load_default(size)  # Pillow ≥10 принимает size
    except TypeError:
        return ImageFont.load_default()


# -------- Цвета (созвучны стиль-системе скилла) ------------------------------

BG = (14, 15, 18)           # Ink Black
PANEL = (24, 25, 30)
FG = (255, 255, 255)        # Ink White
DIM = (160, 160, 170)
ACCENT = (255, 31, 142)     # Magenta — баннер/акценты
CORAL = (255, 106, 61)      # Coral — лейблы битов

# цвет рамки/лейбла по типу бита (по label, регистронезависимо)
LABEL_COLORS = {
    "HOOK": (244, 200, 75),     # Yellow
    "SUB": (255, 255, 255),
    "SUBTITLES": (255, 255, 255),
    "B-ROLL": (255, 106, 61),   # Coral
    "BROLL": (255, 106, 61),
    "PIP": (255, 106, 61),
    "SPLIT": (255, 31, 142),    # Magenta
    "CTA": (255, 31, 142),
}


def label_color(label: str) -> tuple[int, int, int]:
    return LABEL_COLORS.get((label or "").strip().upper(), CORAL)


# -------- ffmpeg: извлечение кадров ------------------------------------------

def probe_duration(video: Path) -> float:
    if shutil.which("ffprobe") is None:
        return 0.0
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True,
    )
    try:
        return round(float(res.stdout.strip()), 3)
    except (ValueError, AttributeError):
        return 0.0


def beat_time(beat: dict, duration: float) -> float | None:
    """Репрезентативный таймкод бита: середина [start,end]; без таймкода → конец видео."""
    start = beat.get("start")
    end = beat.get("end")
    if start is not None and end is not None:
        try:
            return (float(start) + float(end)) / 2.0
        except (TypeError, ValueError):
            pass
    if start is not None:
        try:
            return float(start)
        except (TypeError, ValueError):
            pass
    # бит без таймкода (CTA) → последний кадр
    if duration > 0:
        return max(0.0, duration - 0.1)
    return None


def extract_frame(video: Path, t: float, dest: Path) -> bool:
    """Один кадр в момент t, масштаб по ширине 360 (вертикаль 9:16 ок). True при успехе."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, t):.3f}", "-i", str(video),
        "-frames:v", "1", "-q:v", "3",
        "-vf", "scale=360:-2",
        str(dest),
    ]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0 and dest.exists() and dest.stat().st_size > 0


# -------- Перенос текста по ширине -------------------------------------------

def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont,
              max_w: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fmt_tc(beat: dict, duration: float) -> str:
    start = beat.get("start")
    end = beat.get("end")
    if start is not None and end is not None:
        return f"{float(start):.1f}–{float(end):.1f}s"
    if start is not None:
        return f"{float(start):.1f}s →"
    return "конец" if duration <= 0 else f"~{max(0.0, duration - 0.1):.1f}s"


# -------- Раскладка ----------------------------------------------------------

# геометрия одной ячейки
FRAME_W = 240
FRAME_H = int(FRAME_W * 16 / 9)   # 9:16 → 426
CELL_PAD = 16
CAPTION_H = 150                   # место под подписи под кадром
COL_GAP = 24
ROW_GAP = 28
MARGIN = 40
BANNER_H = 150


def render_storyboard(plan: dict, video: Path, out_path: Path, per_row: int) -> None:
    beats = plan.get("beats") or []
    if not beats:
        sys.exit("В plan.json пустой список beats — нечего рисовать.")

    duration = probe_duration(video)
    hook = (plan.get("hook") or "").strip()
    subtitles = bool(plan.get("subtitles"))

    cell_w = FRAME_W + 2 * CELL_PAD
    cell_h = FRAME_H + CAPTION_H + 2 * CELL_PAD
    n = len(beats)
    per_row = max(1, per_row)
    cols = min(per_row, n)
    rows = (n + cols - 1) // cols

    canvas_w = MARGIN * 2 + cols * cell_w + (cols - 1) * COL_GAP
    canvas_h = MARGIN + BANNER_H + 20 + rows * cell_h + (rows - 1) * ROW_GAP + MARGIN

    canvas = Image.new("RGB", (canvas_w, canvas_h), BG)
    draw = ImageDraw.Draw(canvas)

    f_banner = load_font(34, bold=True)
    f_sub = load_font(18)
    f_label = load_font(20, bold=True)
    f_tc = load_font(16, bold=True)
    f_note = load_font(15)

    # ---- баннер с хуком ----
    draw.rectangle((MARGIN, MARGIN, canvas_w - MARGIN, MARGIN + BANNER_H), fill=PANEL)
    draw.rectangle((MARGIN, MARGIN, MARGIN + 8, MARGIN + BANNER_H), fill=ACCENT)
    title = "ПЛАН МОНТАЖА (сториборд)"
    draw.text((MARGIN + 26, MARGIN + 16), title, fill=ACCENT, font=f_label)
    hook_lines = wrap_text(draw, hook or "(хук не задан)", f_banner, canvas_w - 2 * MARGIN - 52)
    y = MARGIN + 46
    for ln in hook_lines[:2]:
        draw.text((MARGIN + 26, y), ln, fill=FG, font=f_banner)
        y += 38
    meta = f"{video.name}   •   битов: {n}   •   субтитры: {'да' if subtitles else 'нет'}"
    if duration:
        meta += f"   •   длит.: {duration:.1f}s"
    draw.text((MARGIN + 26, MARGIN + BANNER_H - 26), meta, fill=DIM, font=f_sub)

    grid_top = MARGIN + BANNER_H + 20

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for i, beat in enumerate(beats):
            r, c = divmod(i, cols)
            x0 = MARGIN + c * (cell_w + COL_GAP)
            y0 = grid_top + r * (cell_h + ROW_GAP)
            lbl = (beat.get("label") or f"BEAT {i + 1}").strip()
            col = label_color(lbl)

            # рамка ячейки
            draw.rectangle((x0, y0, x0 + cell_w, y0 + cell_h), fill=PANEL)

            # кадр
            fx = x0 + CELL_PAD
            fy = y0 + CELL_PAD
            t = beat_time(beat, duration)
            placed = False
            if t is not None:
                print(f"  кадр {i + 1}/{n}: {lbl} @ {t:.2f}s")
                fp = tmp_dir / f"frame_{i:03d}.jpg"
                if extract_frame(video, t, fp):
                    try:
                        img = Image.open(fp).convert("RGB")
                        img = img.resize((FRAME_W, FRAME_H), Image.Resampling.LANCZOS)
                        canvas.paste(img, (fx, fy))
                        placed = True
                    except OSError:
                        placed = False
            if not placed:
                print(f"  кадр {i + 1}/{n}: {lbl} — кадр не извлечён, рисую заглушку")
                draw.rectangle((fx, fy, fx + FRAME_W, fy + FRAME_H), fill=(40, 40, 48))
                draw.text((fx + 12, fy + FRAME_H // 2 - 10), "нет кадра", fill=DIM, font=f_note)

            # цветная рамка кадра по типу бита
            draw.rectangle((fx, fy, fx + FRAME_W, fy + FRAME_H), outline=col, width=3)

            # лейбл-плашка поверх верхней кромки кадра
            lbl_w = draw.textlength(lbl, font=f_label) + 18
            draw.rectangle((fx, fy, fx + lbl_w, fy + 30), fill=col)
            draw.text((fx + 9, fy + 5), lbl, fill=BG, font=f_label)

            # подписи под кадром
            cy = fy + FRAME_H + 12
            draw.text((fx, cy), fmt_tc(beat, duration), fill=col, font=f_tc)
            cy += 24
            overlay = (beat.get("overlay") or "").strip()
            if overlay:
                for ln in wrap_text(draw, overlay, f_note, FRAME_W)[:3]:
                    draw.text((fx, cy), ln, fill=FG, font=f_note)
                    cy += 19
            note = (beat.get("note") or "").strip()
            if note:
                for ln in wrap_text(draw, note, f_note, FRAME_W)[:2]:
                    draw.text((fx, cy), ln, fill=DIM, font=f_note)
                    cy += 19

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "PNG", optimize=True)
    print(f"  готово: сториборд → {out_path}  ({out_path.stat().st_size // 1024} кБ)")
    print("  дальше: покажи storyboard пользователю до нарезки и рендера.")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Сториборд-план монтажа: реальные кадры из видео + аннотации → PNG.")
    ap.add_argument("plan", type=Path, help="plan.json (составляет Codex/агент)")
    ap.add_argument("video", type=Path, help="исходное видео")
    ap.add_argument("-o", "--output", type=Path, default=None,
                    help="куда писать PNG (default: storyboard.png рядом с plan.json)")
    ap.add_argument("--per-row", type=int, default=4, help="кадров в ряду (default: 4)")
    args = ap.parse_args()

    if shutil.which("ffmpeg") is None:
        sys.exit("Нет ffmpeg в PATH. Установите ffmpeg пакетным менеджером вашей ОС.")

    if not args.plan.exists():
        sys.exit(f"Нет plan.json: {args.plan}")
    video = args.video.resolve()
    if not video.exists():
        sys.exit(f"Нет видео: {video}")

    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"plan.json не парсится: {exc}")

    out_path = args.output or (args.plan.resolve().parent / "storyboard.png")
    print(f"Рисую сториборд: {args.plan} + {video.name}")
    render_storyboard(plan, video, out_path, args.per_row)


if __name__ == "__main__":
    main()
