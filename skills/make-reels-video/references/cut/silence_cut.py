#!/usr/bin/env python3
"""Базовый резак: убираем паузы + предфразовые вдохи из ОДНОЙ записи.

Порт из montage_v2 (video-use/helpers/silence_cut.py), адаптирован под рилсы.

Точки реза берутся из ЭНЕРГИИ звука (ffmpeg silencedetect), а НЕ из ASR-таймкодов
слов: онсеты ASR плывут (whisper рано, Deepgram поздно) и срезают реальные слова.
Транскрипт используется только как лёгкая страховка (не выкинуть сегмент, в котором
есть произнесённое слово).

Де-вдох (--debreath) подрезает ведущий вдох в начале каждого сегмента по RMS-энергии:
порог `thr = min(peak − DROP, ABS_SPEECH)` (относительно пика речи И абсолютный пол).

--------------------------------------------------------------------------------
ИСТОЧНИК СЛОВ (страховка)

В этом скилле уже есть references/transcribe_subs.py (Groq, word-level). Чтобы не
дублировать транскрипцию, silence_cut читает ОБА формата words.json (авто-детект):

  A) плоский список (формат montage):   [{"start","end","word"}, ...]
  B) выход transcribe_subs.py:           {"meta":..., "subs":[{...,"words":[...]}]}
     — слова собираются из subs[].words[]; если у фраз пустые words[] (фолбэк по
       сегментам), берутся пофразовые тайминги subs[].{start,end}.

Если --words не передан или файла нет — резак работает чисто по энергии (страховки
по словам нет, короткие слепки-сливеры режутся только по длительности).

--------------------------------------------------------------------------------
ИСПОЛЬЗОВАНИЕ

    python3 silence_cut.py <piece_dir> [--debreath] [флаги]
    python3 silence_cut.py --work in.mp4 --words subs.json --out edl.json [--debreath]

<piece_dir> (позиционный) — папка, где лежат work.mp4 и words.json и куда писать edl.json.
Либо задай пути явно через --work / --words / --out (тогда позиционный не нужен).

Выход: edl.json (потребляется render_cut.py). С --audio — ещё и preview_audio.m4a.

Флаги:
    --debreath        подрезать ведущий вдох в начале каждого сегмента
    --d FLOAT         silencedetect: мин. длина тишины (default 0.16) — туже паузы
    --keep FLOAT      остаточная пауза на стыке (default 0.20 = по 100мс с каждой стороны)
    --noise STR       порог тишины (default -30dB)
    --drop FLOAT      вдох на >= DROP дБ ниже пика речи сегмента (default 9)
    --absdb FLOAT     громче этого — всегда речь, не вдох (default -24.5)
    --no-snap CSV     индексы сегментов, исключённые из де-вдоха (напр. 13,27)
    --tag STR         имена выходов edl_<tag>.json / preview_audio_<tag>.m4a
    --work PATH       путь к видео (default <piece_dir>/work.mp4)
    --words PATH      путь к words.json/subs.json (default <piece_dir>/words.json)
    --out PATH        путь к выходному edl.json (default <piece_dir>/edl[_tag].json)
    --audio           собрать ещё и аудио-превью

Зависимости: ТОЛЬКО stdlib + ffmpeg/ffprobe в PATH. NumPy не нужен — RMS считается
на stdlib (array/math) по 16 kHz mono WAV-окнам.
"""
import array
import json
import math
import re
import subprocess
import sys
import wave
from pathlib import Path


def argval(flag, default):
    if flag in sys.argv:
        return type(default)(sys.argv[sys.argv.index(flag) + 1])
    return default


def positional():
    """Первый аргумент, не являющийся флагом и не значением флага."""
    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a.startswith("--"):
            i += 2  # пропускаем флаг и его значение
            continue
        return a
    return None


def load_words(path: Path):
    """Адаптер форматов → плоский список (start, end) спанов слов.

    Принимает montage-формат [{start,end,word}] И выход transcribe_subs.py
    ({meta, subs:[{start,end,words:[{word,start,end}]}]}). Возвращает [] если
    файла нет или формат пуст.
    """
    if not path or not path.exists():
        return []
    data = json.load(open(path, encoding="utf-8"))

    # A) плоский список слов (montage)
    if isinstance(data, list):
        return sorted((float(w["start"]), float(w["end"]))
                      for w in data
                      if w.get("start") is not None and w.get("end") is not None)

    # B) выход transcribe_subs.py
    if isinstance(data, dict) and "subs" in data:
        spans = []
        for s in data["subs"]:
            ws = s.get("words") or []
            if ws:
                for w in ws:
                    if w.get("start") is not None and w.get("end") is not None:
                        spans.append((float(w["start"]), float(w["end"])))
            else:
                # фолбэк по фразе (когда пословных таймингов нет)
                if s.get("start") is not None and s.get("end") is not None:
                    spans.append((float(s["start"]), float(s["end"])))
        return sorted(spans)

    return []


def main():
    pos = positional()
    PIECE = Path(pos).resolve() if pos else Path.cwd()
    WORK = Path(argval("--work", str(PIECE / "work.mp4")))
    WORDS = Path(argval("--words", str(PIECE / "words.json")))
    TAG = argval("--tag", "")
    NOISE = argval("--noise", "-30dB")
    DET_D = argval("--d", 0.16)
    KEEP_SIL = argval("--keep", 0.20)
    EDGE = 0.12
    MIN_SEG = 0.20

    if not WORK.exists():
        sys.exit(f"Нет видео: {WORK} (задай --work PATH)")

    WI = load_words(WORDS)
    WORK_DIR = Path(argval("--out", "")).parent if "--out" in sys.argv else PIECE

    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(WORK)],
        capture_output=True, text=True).stdout.strip())

    # ---- энергия: спаны тишины ----
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(WORK),
         "-af", f"silencedetect=noise={NOISE}:d={DET_D}", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    spans = [(s, ends[i] if i < len(ends) else dur) for i, s in enumerate(starts)]

    # ---- keep-диапазоны = дополнение, каждая тишина схлопнута до KEEP_SIL ----
    ranges = []
    cursor = 0.0
    for s, e in spans:
        keep_to = s + KEEP_SIL / 2 if s > 0 else 0.0
        nxt = e - KEEP_SIL / 2 if e < dur else dur
        if s <= 0:
            cursor = max(0.0, e - EDGE)
            continue
        if min(keep_to, dur) - cursor > 0.05:
            ranges.append([cursor, min(keep_to, dur)])
        cursor = max(nxt, 0.0)
    tail_end = dur
    if spans and spans[-1][1] >= dur:
        tail_end = min(spans[-1][0] + EDGE, dur)
    if tail_end - cursor > 0.05:
        ranges.append([cursor, tail_end])

    # ---- выкидываем шумовые сливеры: короткий спан (<0.30с), не перекрывающий слово ----
    def has_word(a, b):
        return any(min(b, e) - max(a, s) > 0 for s, e in WI)
    # если слов нет (страховки нет) — оставляем только по длительности
    if WI:
        ranges = [(a, b) for a, b in ranges
                  if (b - a) >= MIN_SEG and ((b - a) >= 0.30 or has_word(a, b))]
    else:
        ranges = [(a, b) for a, b in ranges if (b - a) >= 0.30]

    # ---- де-вдох (энергия): подрезаем ведущий вдох в начале сегмента ----
    snapped = 0
    if "--debreath" in sys.argv:
        DROP = float(argval("--drop", 9.0))
        ABS_SPEECH = float(argval("--absdb", -24.5))
        PAD, BREATH_MIN, MAX_TRIM, HOP = 0.05, 0.08, 0.6, 0.02
        NO_SNAP = set(int(x) for x in str(argval("--no-snap", "")).split(",") if x.strip())
        tmp = WORK_DIR / "_db.wav"

        def rms_db(start, length):
            subprocess.run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(WORK),
                            "-t", f"{length:.3f}", "-ac", "1", "-ar", "16000", "-f", "wav", str(tmp)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            w = wave.open(str(tmp)); sr = w.getframerate(); raw = w.readframes(w.getnframes()); w.close()
            step = int(HOP * sr) * 2
            res = []
            for i in range(0, len(raw) - step, step):
                a = array.array("h"); a.frombytes(raw[i:i + step])
                ms = math.sqrt(sum(x * x for x in a) / len(a)) if a else 0
                res.append(20 * math.log10(ms / 32768) if ms > 0 else -90.0)
            return res

        def speech_onset(start, seg_dur):
            db = rms_db(start, min(0.8, seg_dur))
            if not db:
                return start
            peak = max(db)
            if peak < -30:
                return start
            thr = min(peak - DROP, ABS_SPEECH)   # относительно пика И абсолютный пол
            for i in range(len(db)):
                if db[i] >= thr:                 # первое речевое окно (вкл. плозив)
                    return start + i * HOP
            return start

        res = []
        prev_end = 0.0
        for idx, (a, b) in enumerate(ranges):
            if idx not in NO_SNAP:
                onset = speech_onset(a, b - a)
                if BREATH_MIN < (onset - a) < MAX_TRIM:
                    na = onset - PAD
                    if na > prev_end and (b - na) >= MIN_SEG:
                        a = na
                        snapped += 1
            res.append((a, b))
            prev_end = b
        ranges = res
        tmp.unlink(missing_ok=True)

    src_key = WORK.stem
    ranges = [{"source": src_key, "start": round(a, 3), "end": round(b, 3)} for a, b in ranges]
    kept = sum(r["end"] - r["start"] for r in ranges)
    print(f"слов: {len(WI)} | спанов тишины: {len(spans)} | сегментов: {len(ranges)}")
    print(f"де-вдох срезал: {snapped} | оставлено: {kept:.1f}с  (убрано {dur-kept:.1f}с, -{100*(dur-kept)/dur:.0f}%)")

    edl = {"version": 1, "sources": {src_key: str(WORK)},
           "ranges": ranges, "grade": "none", "total_duration_s": round(kept, 2)}
    if "--out" in sys.argv:
        out_path = Path(argval("--out", ""))
    else:
        out_name = f"edl_{TAG}.json" if TAG else "edl.json"
        out_path = PIECE / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(edl, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"записал {out_path}")

    # ---- аудио-превью (быстрая итерация до видео-рендера) ----
    if "--audio" in sys.argv:
        suffix = f"_{TAG}" if TAG else ""
        adir = out_path.parent / f"_preview_audio{suffix}"
        adir.mkdir(exist_ok=True)
        for f in adir.glob("seg_*.m4a"):
            f.unlink()
        paths = []
        for i, r in enumerate(ranges):
            d = r["end"] - r["start"]
            fo = max(0.0, d - 0.03)
            af = f"afade=t=in:st=0:d=0.03,afade=t=out:st={fo:.3f}:d=0.03"
            op = adir / f"seg_{i:03d}.m4a"
            subprocess.run(["ffmpeg", "-y", "-ss", f"{r['start']:.3f}", "-i", str(WORK),
                            "-t", f"{d:.3f}", "-vn", "-af", af, "-c:a", "aac",
                            "-b:a", "192k", "-ar", "48000", str(op)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            paths.append(op)
        lst = out_path.parent / f"_concat{suffix}.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in paths))
        prev = out_path.parent / f"preview_audio{suffix}.m4a"
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(prev)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        lst.unlink(missing_ok=True)
        print(f"записал preview_audio{suffix}.m4a")


if __name__ == "__main__":
    main()
