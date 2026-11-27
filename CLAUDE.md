# Clash Royale Bot (ccr-d344ab20-onpy71) — Project Rules

## Project Map
- **Entry point**: `src/royale/game.py:RoyaleBot.run()` → `start_game()` → `battle()` loop
- **Vision pipeline**: `src/royale/eyes.py:Eyes.look()` → `strong_eyes` (YOLOv8 big) + `units` (small) → `UnitTracker`
- **Brain**: `src/royale/brain.py:Brain.decide()` — rule brain + learned policy (`policy.py`) + arena Transformer (`board.py`)
- **Engine**: `src/royale/engine.py` — C++ `clash_royale_env` simulator, 8s rollouts, 80ms budget
- **Recovery**: `game.py:_recover()` — ADB/emulator reconnection with exponential backoff
- **Pre-flight**: `preflight.py:run_preflight()` — assets, ADB, RAM/disk sanity
- **Tests**: `tests/test_phase1_stability.py`, `tests/test_phase2_stability.py`

## Run Commands
```bash
# Run bot (requires LDPlayer + ADB)
python -m src.royale.game

# Run all tests
python -m unittest discover -s tests -v

# Syntax check all modified files
python -m py_compile src/royale/game.py src/royale/engine.py src/royale/eyes.py \
  src/royale/brain.py src/royale/vision/detectors/onnx_detector.py \
  src/royale/preflight.py tests/test_phase1_stability.py tests/test_phase2_stability.py
```

## Non-Negotiable Engineering Rules
1. **Grep before reading** — `grep -rn "symbol" src/` before opening any file
2. **Never repeat a failing command** — diagnose, then change approach
3. **Test real functions** — mock only external boundaries (ADB, ONNX, filesystem, Qt); never bypass the function under test
4. **No bare `except:`** — use specific exceptions, log with context
5. **Fail loud, clear** — missing assets → actionable error with exact path; never silent `{}`/`None`
6. **Zero C++ binary edits** — `clash_royale_env` is compiled; only Python wrappers change
7. **Unit tests must run real code** — `unittest.mock` only for external deps, not the function under test
8. **Token efficiency** — concise output, grep before read, one shot per command

## Branch Discipline
- Work ONLY on `ccr-d344ab20-onpy71` branch
- Version in `src/version.py` (current: 6.9.45)
- Commit: `royale X.Y.Z: what and why`
- Push directly to branch (no PRs, no force-push)