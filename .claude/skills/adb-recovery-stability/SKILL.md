---
name: adb-recovery-stability
description: ADB/emulator recovery with exponential backoff, frame fail tracking, pre-flight checks
version: 1.0
---

# ADB Recovery & Stability

## Core Files
- `src/royale/game.py:RoyaleBot._recover()` — main recovery logic
- `src/royale/game.py:start_game()` — game launch
- `src/royale/preflight.py` — startup asset/ADB/RAM checks
- `src/royale/stream_capture.py` — screen capture (LDPlayer @ 127.0.0.1:27199)

## Recovery Flow
```
frame() fails → _frame_fails++
  ↓
_recover(err):
  1. log.warning (first failure)
  2. Emulator_Manager.check() → start() if down
  3. ADB_Manager._adbutils_device = None → connect(timeout=60)
  4. start_game(log) → re-launch CR
  5. success → _frame_fails = 0, continue
  6. failure → exponential backoff: min(30, 5 * 2^min(n,3)) seconds
  7. n ≥ _max_frame_fails (5) → sleep 60s, give up
```

## Key Constants
```python
MAX_PLAY_FRAME_AGE = 0.65      # stale frame rejection
LOOK_EVERY = 0.08              # ~10 looks/sec
_max_frame_fails = 5           # hard limit
backoff = min(30, 5 * 2^min(n,3))  # 10s, 20s, 30s, 30s...
```

## Pre-flight Check (`preflight.py`)
Runs at `RoyaleBot.run()` entry:
- **Assets**: `cards.json`, `units_M_480x352.onnx`, `side.onnx`
- **ADB**: `adb devices` → at least one authorized device
- **RAM**: ≥ 2GB free (warn if less)
- **Disk**: ≥ 1GB free (warn if less)

Returns `PreflightResult(ok, warnings, errors)`; `ok=False` aborts startup.

## Testing
- Mock `utils.ADB_Manager`, `utils.Emulator_Manager`
- Mock `frame()` to raise `Exception` → verify `_recover` called, backoff correct
- Mock `shutil.which("adb")` → `None` for missing ADB test
- Mock `psutil.virtual_memory()` for low RAM test

## Common Issues
| Issue | Symptom | Fix |
|-------|---------|-----|
| ADB unauthorized | `adb devices` shows "unauthorized" | Re-authorize on device, restart ADB |
| LDPlayer not found | `Emulator_Manager.check()` false | Verify LDPlayer path in utils |
| Screen frozen | `frame_age` > 0.5 | game.py skips, `_recover` eventually |
| No devices | `adb devices` empty | Start LDPlayer, check USB debug |