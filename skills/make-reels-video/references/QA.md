# Reels QA contract

A result passes only when:

- speech starts and ends on safe audio boundaries;
- captions cover the speech and remain readable in the vertical safe area;
- no duplicate embedded captions remain;
- every b-roll/PiP item has a real local asset;
- hook and CTA do not collide with captions;
- HyperFrames lint/check pass;
- snapshots from every visual state were inspected;
- the rendered MP4 has video and audio streams;
- beginning, middle, end and every cut were reviewed.

After any composition change, repeat lint, check, snapshots and final media review.
