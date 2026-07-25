#!/usr/bin/env python3
"""Склейка чанковых subs.json (chunk_NN.json) в один subs.json со сдвигом таймкодов."""
import json
import sys
from pathlib import Path

CHUNK_SEC = 1500.0  # -segment_time при нарезке
files = sorted(Path(".").glob("chunk_*.json"))
if not files:
    sys.exit("нет chunk_*.json")

all_subs, idx = [], 0
for i, f in enumerate(files):
    data = json.loads(f.read_text(encoding="utf-8"))
    off = i * CHUNK_SEC
    for s in data["subs"]:
        s = dict(s)
        s["start"] = round(s["start"] + off, 2)
        s["end"] = round(s["end"] + off, 2)
        s["index"] = idx
        for w in s.get("words", []):
            w["start"] = round(w["start"] + off, 2)
            w["end"] = round(w["end"] + off, 2)
        all_subs.append(s)
        idx += 1

out = {
    "meta": {
        "source": str(Path(sys.argv[1]).resolve()) if len(sys.argv) > 1 else "merged",
        "language": "ru",
        "backend": "groq",
        "model": "whisper-large-v3",
        "phrase_count": len(all_subs),
        "duration": all_subs[-1]["end"] if all_subs else 0,
    },
    "subs": all_subs,
}
Path("subs.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"объединено {len(files)} чанков → subs.json, фраз: {len(all_subs)}")
