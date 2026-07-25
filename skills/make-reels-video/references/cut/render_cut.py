#!/usr/bin/env python3
"""Рендер реза из EDL — БЫСТРО + В СИНКЕ + БЕЗ ЩЕЛЧКОВ, by design.

Порт из montage_v2 (video-use/helpers/render_cut.py), портирован под VPS/рилсы.

Один движок, качество — флаг. Каждый ЧАНК рендерит ВИДЕО+АУДИО ВМЕСТЕ за один
проход (общие точки реза → нет A/V-дрейфа), с PCM-аудио (нет AAC-priming щелчков),
бьётся на ≤--chunk резов (фильтрграф не раздувается до O(N^2)). Чанки склеиваются
`concat -c copy` (PCM остаётся бесшовным на стыке); аудио кодируется в AAC один раз
в конце. Фейды 30мс на каждом стыке (вход/выход) убирают клики.

Качество / скорость:
  (default)  libx264 -crf — резко, ПОРТАТИВНО (работает на любом VPS). Финал.
  --gpu      h264_videotoolbox (-q:v) — быстро, ТОЛЬКО macOS (на Linux упадёт —
             там ставь --nvenc или просто оставь libx264).
  --nvenc    h264_nvenc — быстрый GPU-энкод на Linux/NVIDIA VPS.
  --jobs N   параллельные чанк-энкоды. Default 4 для GPU, 1 для libx264
             (он насыщает ядра → последовательно).

9:16 для рилсов:
  --crop916  центрированный кроп в вертикаль + scale до --vh высоты (см. --vw/--vh).
             Без него — обычный масштаб по ширине/канвасу (как в исходнике).

Одно-источниковый EDL (кейс silence_cut). Оверлеи/субтитры (HyperFrames) кладутся
поверх готового MP4 отдельным шагом.

Использование:
  python3 render_cut.py edl.json -o out.mp4
  python3 render_cut.py edl.json -o reels.mp4 --crop916      # вертикаль 1080x1920
  python3 render_cut.py edl.json -o out.mp4 --gpu            # macOS GPU
  python3 render_cut.py edl.json -o out.mp4 --nvenc          # Linux NVIDIA GPU

Зависимости: ТОЛЬКО stdlib + ffmpeg/ffprobe в PATH.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("edl", type=Path)
ap.add_argument("-o", "--output", type=Path, required=True)
ap.add_argument("--gpu", action="store_true", help="h264_videotoolbox (только macOS)")
ap.add_argument("--nvenc", action="store_true", help="h264_nvenc (Linux/NVIDIA)")
ap.add_argument("--q", type=int, default=80)
ap.add_argument("--crf", type=int, default=18)
ap.add_argument("--canvas", default="")
ap.add_argument("--width", type=int, default=1920)
ap.add_argument("--crop916", action="store_true", help="центр-кроп в вертикаль 9:16")
ap.add_argument("--vw", type=int, default=1080, help="ширина вертикали (default 1080)")
ap.add_argument("--vh", type=int, default=1920, help="высота вертикали (default 1920)")
ap.add_argument("--loudnorm", action="store_true")
ap.add_argument("--chunk", type=int, default=50)
ap.add_argument("--jobs", type=int, default=0)
ap.add_argument("--fps", type=int, default=24)
a = ap.parse_args()

edl = json.loads(a.edl.read_text())
ranges, srcs = edl["ranges"], edl["sources"]
if len(srcs) != 1:
    sys.exit("render_cut.py обрабатывает одно-источниковые EDL; мульти-дубль не поддержан.")
SRC = list(srcs.values())[0]
OUT = a.output.resolve(); WORK = OUT.parent; TAG = OUT.stem
use_gpu = a.gpu or a.nvenc
jobs = a.jobs or (4 if use_gpu else 1)

if a.crop916:
    # центрированный кроп до вертикали 9:16, затем масштаб до vw x vh
    VF = (f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',"
          f"scale={a.vw}:{a.vh}:force_original_aspect_ratio=increase,"
          f"crop={a.vw}:{a.vh},setsar=1,fps={a.fps}")
elif a.canvas:
    cw, ch = a.canvas.split("x")
    VF = (f"scale={cw}:{ch}:force_original_aspect_ratio=decrease,"
          f"pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={a.fps}")
else:
    VF = f"scale={a.width}:-2,setsar=1,fps={a.fps}"

if a.gpu:
    VCODEC = ["-c:v", "h264_videotoolbox", "-q:v", str(a.q)]
elif a.nvenc:
    VCODEC = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(a.crf)]
else:
    VCODEC = ["-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf)]

# ---- чанки: ВИДЕО+АУДИО вместе, PCM-аудио, параллельно ----
chunks, procs = [], []
def drain(limit):
    while len(procs) >= limit:
        p, sf = procs.pop(0)
        if p.wait() != 0:
            sys.exit(f"чанк упал:\n{p.stderr.read().decode()[-600:]}")
        Path(sf).unlink(missing_ok=True)

for ci in range(0, len(ranges), a.chunk):
    part = ranges[ci:ci + a.chunk]
    v, au, lab = [], [], []
    for j, r in enumerate(part):
        d = r["end"] - r["start"]; fo = max(0.0, d - 0.03)
        v.append(f"[0:v]trim=start={r['start']:.3f}:end={r['end']:.3f},setpts=PTS-STARTPTS,{VF}[v{j}]")
        au.append(f"[0:a]atrim=start={r['start']:.3f}:end={r['end']:.3f},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:st=0:d=0.03,afade=t=out:st={fo:.3f}:d=0.03[a{j}]")
        lab.append(f"[v{j}][a{j}]")
    fc = ";\n".join(v + au + [''.join(lab) + f"concat=n={len(part)}:v=1:a=1[cv][ca]"])
    sf = WORK / f"_rc_{TAG}_{ci}.txt"; sf.write_text(fc)
    cm = WORK / f"_rc_{TAG}_{ci}.mov"
    drain(jobs)
    procs.append((subprocess.Popen(
        ["ffmpeg", "-y", "-i", SRC, "-filter_complex_script", str(sf),
         "-map", "[cv]", "-map", "[ca]", *VCODEC, "-pix_fmt", "yuv420p",
         "-c:a", "pcm_s16le", "-ar", "48000", str(cm)], stderr=subprocess.PIPE), str(sf)))
    chunks.append(cm)
drain(1)
enc = "videotoolbox" if a.gpu else ("nvenc" if a.nvenc else "libx264")
print(f"видео+аудио: {len(chunks)} чанк(ов), {jobs} параллельно, энкодер={enc}")

# ---- concat -c copy (h264 copy + PCM остаётся бесшовным) ----
lst = WORK / f"_rc_{TAG}.txt"; lst.write_text("".join(f"file '{c}'\n" for c in chunks))
mov = WORK / f"_rc_{TAG}.mov"
subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(mov)],
               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
lst.unlink()
for c in chunks:
    c.unlink(missing_ok=True)

# ---- финал: видео copy + аудио -> AAC (loudnorm опц.) ----
acmd = ["ffmpeg", "-y", "-i", str(mov), "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy"]
if a.loudnorm:
    acmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
acmd += ["-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(OUT)]
subprocess.run(acmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
mov.unlink(missing_ok=True)

def dur(st):
    return float(subprocess.run(["ffprobe", "-v", "error", "-select_streams", st, "-show_entries",
                                 "stream=duration", "-of", "default=nk=1:nw=1", str(OUT)],
                                capture_output=True, text=True).stdout.strip())
vd, ad = dur("v:0"), dur("a:0")
dr = abs(vd - ad)
flag = "OK" if dr < 0.05 else ("ok (минор)" if dr < 0.15 else "!! A/V ДРЕЙФ — разбирайся")
print(f"{OUT.name}: V={vd:.2f} A={ad:.2f} дрейф={vd-ad:+.3f}с {flag}  {OUT.stat().st_size//(1024*1024)}МБ")
