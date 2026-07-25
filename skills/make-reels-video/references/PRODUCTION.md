# Production reference

## Dependencies

- `ffmpeg` and `ffprobe`;
- Python 3.10+;
- Pillow for storyboard;
- Groq key only when fresh word timestamps are required; it is not needed when
  a valid transcript with word timestamps already exists;
- HyperFrames CLI.

Install HyperFrames:

```bash
npm install -g hyperframes
hyperframes --version
```

## Commands

```bash
python3 references/transcribe_subs.py source.mp4 -o subs.json --language ru
python3 references/audio_boundary_qa.py source.mp4 \
  --range 0:30 --out qa/audio-boundaries
python3 references/storyboard.py plan.json source.mp4 -o storyboard.png
```

Inside the composition directory:

```bash
hyperframes lint .
hyperframes check .
hyperframes snapshot . --at "0.5,2,5,8"
hyperframes render . --quality high --output short-final.mp4
ffprobe -v error -show_format short-final.mp4
```

Use only local assets with known provenance and rights. Keep downloadable media,
temporary audio and snapshots outside the skill folder.
