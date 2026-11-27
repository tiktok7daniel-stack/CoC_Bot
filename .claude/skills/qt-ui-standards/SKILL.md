---
name: qt-ui-standards
description: Qt UI patterns: live video, battle view, settings binding, token theming
version: 1.0
---

# Qt UI Standards

## Core Files
- `src/qt_ui/live_video.py:LiveVideo` — emulator screen relay (H.264 decode, HW accel)
- `src/qt_ui/live_tracker.py:LiveTracker` — UI sync for unit boxes
- `src/qt_ui/screens/royale_live_screen.py` — battle arena + camera view
- `src/qt_ui/screens/royale_home_screen.py` — main controls, toggles
- `src/qt_ui/theme.py:TOKENS` — design tokens (colors, spacing, typography)
- `src/qt_ui/store.py` — reactive settings store (binds to `settings.py`)

## Data Flow
```
Bot (game.py) → royale.live_view → JSON + JPG files
  ↓
RoyaleLiveScreen.refresh() reads ~/.CoC_Bot/learn/royale_live_<acc>.json
  ├─ Arena.set_data() → paintEvent() draws tiles, units, towers, heatmap
  ├─ Camera.set_data() → draws real frame + detection boxes
  └─ Side panels: state, think, them, events
```

## Settings Binding Pattern
```python
# royale_home_screen.py
from ..store import Store
t = bind_toggle(store, Toggle(), "royale.ai_play")
t.toggled.connect(lambda _: QTimer.singleShot(50, lambda: store.save(silent=True)))
```
- Toggles: `royale.ai_play`, `royale.watch_only`, `royale.manage_account`, `royale.training_camp`
- Store auto-saves to `settings.py` on change

## Live Video Contract
- `LiveVideo.start()` → background thread decodes H.264 from LDPlayer (127.0.0.1:27199)
- `take(last_seq)` → `(seq, QImage)` if newer
- `take_at(t, last_key)` → `(key, QImage, ts)` for timestamped replay
- `is_fresh()` → `time.monotonic() - arr_t < 0.75`

## Token Theming
```python
from ..theme import TOKENS, ui_font
p.fillRect(..., QColor(TOKENS["void"]))
p.setPen(QColor(TOKENS["gold"]))
p.setFont(ui_font(10, QFont.Bold))
```
- Use `TOKENS` keys: `void`, `glass_solid`, `border_solid`, `text`, `muted`, `ok`, `bad`, `gold`
- Never hardcode hex colors

## Watch Mode
- UI toggle: `royale.watch_only` (royale_home_screen.py)
- Bot sets `watch_only = bool(self.s.get("watch_only", False))`
- In `watch_only`: `Brain.decide()` skipped, `_detect_human_play()` records human moves to `Brain.plays` + `Memory`

## Testing
- Mock `PySide6` imports in headless tests
- Test token contrast: `TOKENS["text"]` vs `TOKENS["glass_solid"]` ≥ WCAG AAA (12:1)
- Verify `bind_toggle` → `settings.save()` called