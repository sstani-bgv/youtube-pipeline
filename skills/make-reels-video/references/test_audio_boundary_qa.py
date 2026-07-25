#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

SCRIPT = Path(__file__).with_name("audio_boundary_qa.py")


def write_fixture(path: Path) -> None:
    """1s mono WAV: silence 0-.25, tone .25-.60, silence .60-1.0."""
    sample_rate = 16_000
    frames = bytearray()
    for index in range(sample_rate):
        time_s = index / sample_rate
        sample = int(12_000 * math.sin(2 * math.pi * 220 * time_s)) if 0.25 <= time_s < 0.60 else 0
        frames.extend(struct.pack("<h", sample))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)


class AudioBoundaryQaTest(unittest.TestCase):
    def run_qa(self, media: Path, range_value: str, out_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(media), "--range", range_value,
             "--out", str(out_dir), "--min-handle-ms", "100"],
            capture_output=True,
            text=True,
        )

    def test_rejects_end_boundary_inside_active_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "fixture.wav"
            out_dir = root / "unsafe"
            write_fixture(media)

            result = self.run_qa(media, "0.10:0.55", out_dir)

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
            end_result = next(item for item in report["boundaries"] if item["kind"] == "end")
            self.assertEqual(end_result["status"], "unsafe")
            self.assertLess(end_result["handle_ms"], 100)

    def test_accepts_silence_handles_and_renders_waveform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "fixture.wav"
            out_dir = root / "safe"
            edl = root / "edl.json"
            write_fixture(media)
            edl.write_text(
                json.dumps({"version": 1, "ranges": [{"source": "main", "start": 0.10, "end": 0.75}]}),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(media), "--ranges", str(edl),
                 "--out", str(out_dir), "--min-handle-ms", "100"],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["ok"])
            self.assertTrue((out_dir / "contact-sheet.png").exists())
            self.assertEqual({item["status"] for item in report["boundaries"]}, {"safe"})


if __name__ == "__main__":
    unittest.main()
