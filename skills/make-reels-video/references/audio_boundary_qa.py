#!/usr/bin/env python3
"""Проверка монтажных границ по PCM-энергии + waveform-контактный лист.

Exit code 0: все границы безопасны. Exit code 2: хотя бы одна граница режет
активное аудио или оставляет меньше --min-handle-ms тишины.
"""
from __future__ import annotations

import argparse
import array
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SAMPLE_RATE = 16_000
FRAME_MS = 10
BG = (14, 15, 18)
PANEL = (25, 27, 32)
FG = (255, 253, 247)
DIM = (150, 153, 163)
ACCENT = (244, 200, 75)
SAFE = (73, 190, 118)
UNSAFE = (255, 106, 61)


def parse_range(value: str) -> tuple[float, float]:
    try:
        start_raw, end_raw = value.split(":", 1)
        start, end = float(start_raw), float(end_raw)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("диапазон должен быть START:END") from exc
    if start < 0 or end <= start:
        raise argparse.ArgumentTypeError("нужен диапазон 0 <= START < END")
    return start, end


def load_ranges(path: Path | None, inline: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ranges = list(inline)
    if path is not None:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("ranges", []) if isinstance(data, dict) else data
        for item in items:
            if isinstance(item, dict):
                ranges.append((float(item["start"]), float(item["end"])))
            else:
                ranges.append((float(item[0]), float(item[1])))
    if not ranges:
        raise SystemExit("Передай --range START:END или --ranges edl.json")
    return ranges


def extract_pcm(media: Path) -> array.array:
    if shutil.which("ffmpeg") is None:
        raise SystemExit("Нет ffmpeg в PATH")
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-acodec", "pcm_s16le", "-f", "s16le", "-"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.decode("utf-8", errors="replace").strip())
    samples = array.array("h")
    samples.frombytes(result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        raise SystemExit("Пустая аудиодорожка")
    return samples


def rms_frames(samples: array.array) -> list[float]:
    frame_size = max(1, round(SAMPLE_RATE * FRAME_MS / 1000))
    values: list[float] = []
    for offset in range(0, len(samples), frame_size):
        frame = samples[offset:offset + frame_size]
        if not frame:
            continue
        rms = math.sqrt(sum(sample * sample for sample in frame) / len(frame))
        values.append(20 * math.log10(rms / 32768) if rms else -90.0)
    return values


def measure_boundary(
    frames_db: list[float], time_s: float, kind: str, threshold_db: float,
    min_handle_ms: int, window_ms: int, duration_s: float,
) -> tuple[float, str]:
    hop = FRAME_MS / 1000
    radius = max(1, round(window_ms / FRAME_MS))
    boundary_frame = time_s / hop

    if kind == "start" and time_s <= hop:
        return 0.0, "edge"
    if kind == "end" and duration_s - time_s <= hop:
        return 0.0, "edge"

    if kind == "start":
        first = max(0, math.floor(boundary_frame))
        last = min(len(frames_db), first + radius)
        active_index = next((index for index in range(first, last) if frames_db[index] >= threshold_db), None)
        handle_s = window_ms / 1000 if active_index is None else active_index * hop - time_s
    else:
        last = min(len(frames_db) - 1, math.ceil(boundary_frame) - 1)
        first = max(-1, last - radius)
        active_index = next((index for index in range(last, first, -1) if frames_db[index] >= threshold_db), None)
        handle_s = window_ms / 1000 if active_index is None else time_s - (active_index + 1) * hop

    handle_ms = round(handle_s * 1000, 1)
    return handle_ms, "safe" if handle_ms >= min_handle_ms else "unsafe"


def render_waveform(
    samples: array.array, time_s: float, result: dict, out_path: Path,
    window_ms: int, min_handle_ms: int,
) -> None:
    width, height = 1000, 250
    image = Image.new("RGB", (width, height), PANEL)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=18)
    small = ImageFont.load_default(size=15)
    half_window = window_ms / 1000
    start_s = max(0.0, time_s - half_window)
    end_s = min(len(samples) / SAMPLE_RATE, time_s + half_window)
    start_sample = int(start_s * SAMPLE_RATE)
    end_sample = max(start_sample + 1, int(end_s * SAMPLE_RATE))
    center_y = 142
    amplitude_h = 78

    draw.line((0, center_y, width, center_y), fill=(65, 68, 77), width=1)
    for x in range(width):
        left = start_sample + int((end_sample - start_sample) * x / width)
        right = start_sample + int((end_sample - start_sample) * (x + 1) / width)
        peak = max((abs(value) for value in samples[left:max(left + 1, right)]), default=0) / 32768
        level = max(1, round(peak * amplitude_h))
        draw.line((x, center_y - level, x, center_y + level), fill=ACCENT, width=1)

    cut_x = round((time_s - start_s) / max(0.001, end_s - start_s) * width)
    handle_px = round((min_handle_ms / 1000) / max(0.001, end_s - start_s) * width)
    if result["kind"] == "start":
        draw.rectangle((cut_x, 48, min(width - 1, cut_x + handle_px), height - 18), outline=DIM, width=1)
    else:
        draw.rectangle((max(0, cut_x - handle_px), 48, cut_x, height - 18), outline=DIM, width=1)
    color = SAFE if result["status"] in {"safe", "edge"} else UNSAFE
    draw.line((cut_x, 42, cut_x, height - 12), fill=color, width=4)
    title = f"{result['kind'].upper()} #{result['range_index'] + 1}  t={time_s:.3f}s"
    verdict = f"{result['status'].upper()}  handle={result['handle_ms']:.1f}ms  need={min_handle_ms}ms"
    draw.text((16, 12), title, fill=FG, font=font)
    draw.text((16, 216), verdict, fill=color, font=small)
    image.save(out_path, "PNG", optimize=True)


def contact_sheet(images: list[Path], output: Path) -> None:
    opened = [Image.open(path).convert("RGB") for path in images]
    cell_w, cell_h, gap = 1000, 250, 16
    cols = 2 if len(opened) > 1 else 1
    rows = math.ceil(len(opened) / cols)
    sheet = Image.new("RGB", (cols * cell_w + (cols + 1) * gap, rows * cell_h + (rows + 1) * gap), BG)
    for index, image in enumerate(opened):
        x = gap + (index % cols) * (cell_w + gap)
        y = gap + (index // cols) * (cell_h + gap)
        sheet.paste(image, (x, y))
    sheet.save(output, "PNG", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="QA монтажных границ по аудиограмме")
    parser.add_argument("media", type=Path)
    parser.add_argument("--range", dest="inline_ranges", action="append", type=parse_range, default=[])
    parser.add_argument("--ranges", type=Path, help="JSON/EDL с ranges[].start/end")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-handle-ms", type=int, default=100)
    parser.add_argument("--window-ms", type=int, default=800)
    parser.add_argument("--threshold-db", type=float, default=-30.0)
    args = parser.parse_args()

    if not args.media.exists():
        raise SystemExit(f"Нет media: {args.media}")
    ranges = load_ranges(args.ranges, args.inline_ranges)
    samples = extract_pcm(args.media)
    frames_db = rms_frames(samples)
    duration_s = len(samples) / SAMPLE_RATE
    args.out.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    images: list[Path] = []
    for range_index, (start, end) in enumerate(ranges):
        if end > duration_s + 0.02:
            raise SystemExit(f"Диапазон {start}:{end} выходит за duration={duration_s:.3f}")
        for kind, time_s in (("start", start), ("end", end)):
            handle_ms, status = measure_boundary(
                frames_db, time_s, kind, args.threshold_db,
                args.min_handle_ms, args.window_ms, duration_s,
            )
            image_name = f"boundary-{range_index + 1:02d}-{kind}.png"
            item = {
                "range_index": range_index,
                "kind": kind,
                "time_s": round(time_s, 3),
                "handle_ms": handle_ms,
                "status": status,
                "image": image_name,
            }
            render_waveform(samples, time_s, item, args.out / image_name, args.window_ms, args.min_handle_ms)
            results.append(item)
            images.append(args.out / image_name)

    ok = all(item["status"] != "unsafe" for item in results)
    report = {
        "media": str(args.media.resolve()),
        "duration_s": round(duration_s, 3),
        "threshold_db": args.threshold_db,
        "min_handle_ms": args.min_handle_ms,
        "ok": ok,
        "boundaries": results,
    }
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    contact_sheet(images, args.out / "contact-sheet.png")

    for item in results:
        print(f"{item['status'].upper():6} range={item['range_index'] + 1} {item['kind']} "
              f"t={item['time_s']:.3f}s handle={item['handle_ms']:.1f}ms")
    print(f"report: {args.out / 'report.json'}")
    print(f"waveform: {args.out / 'contact-sheet.png'}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
