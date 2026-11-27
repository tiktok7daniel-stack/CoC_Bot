---
name: royale-vision
description: Clash Royale vision pipeline: capture → detectors → tracker → brain input
version: 1.0
---

# Royale Vision Pipeline

## Core Files
- `src/royale/eyes.py:Eyes` — main entry, one look per frame
- `src/royale/strong_eyes.py` — big YOLOv8 (97 classes, mAP50 0.918)
- `src/royale/vision/detectors/unit_detector.py` — small ONNX detector
- `src/royale/vision/detectors/onnx_detector.py` — base ONNX runner (TensorRT→CUDA→DML→CPU)
- `src/royale/unit_tracker.py` — Kalman + Hungarian tracker, id persistence
- `src/royale/team_color.py` — badge/health-bar color classification

## Flow
```
frame_rgb → eyes.look()
  ├─ strong_eyes.look_now() [big model, async]
  ├─ units.run() [small model, current frame]
  ├─ _card_det.run() [hand cards]
  ├─ numbers.run() [elixir, tower HP]
  └─ _units() fusion → tracker.update() → (enemies, allies) with tile coords
```

## Key Contracts
- `Eyes.look()` returns dict with: `enemies`, `allies`, `frame_age`, `vision_source`, `vision_timing`
- `vision_source` ∈ {`large-current-frame`, `fast-current-frame`, `combined-current-frame`, `small-current-frame`}
- `frame_age > 0.5` → stale frame (game.py skips battle decision)

## Common Tasks
- **Add detector**: subclass `OnnxDetector`, implement `_post_process`
- **Change model path**: update `MODELS_DIR` in `vision/constants.py`
- **Debug tracker**: `UnitTracker.snapshot(now)` returns tracked units with id, position, velocity
- **Mock in tests**: patch `sys.modules` for `numpy`, `cv2`, `PIL`; mock `CardDetector`, `UnitDetector`

## Failure Modes
| Symptom | Cause | Fix |
|---------|-------|-----|
| `frame_age` high | LDPlayer/ADB lag | `_recover()` triggers, exponential backoff |
| `vision_source` = `small-current-frame` | big model slow | check `ort_gpu.on_gpu()`, TensorRT |
| tracker id flips | side model 80% wrong | `team_color` badge read (2-3 votes) |