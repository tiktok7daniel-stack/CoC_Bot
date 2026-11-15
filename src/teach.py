"""
"Teach the bot": templates and screen regions the user captures from their own emulator.

Stored locally in ~/.CoC_Bot/templates (never shipped in the repo), so they always match
the user's resolution and game version. Features that need them stay inactive until taught.
"""
import json, os, time
from pathlib import Path

APP_DATA_DIR = Path.home() / ".CoC_Bot"
TEMPLATE_DIR = APP_DATA_DIR / "templates"
CAPTURE_DIR = APP_DATA_DIR / "capture"
META_PATH = TEMPLATE_DIR / "meta.json"

# What the user can teach. kind: "button" = image to find & tap, "region" = area to read numbers from.
CATALOG = [
    # --- loot filter (search screen)
    {"key": "next_button",   "kind": "button", "group": "farm",    "multi": False},
    {"key": "enemy_gold",    "kind": "region", "group": "farm"},
    {"key": "enemy_elixir",  "kind": "region", "group": "farm"},
    {"key": "enemy_dark",    "kind": "region", "group": "farm"},
    # --- army
    {"key": "army_button",   "kind": "button", "group": "army",    "multi": False},
    {"key": "hero_add",      "kind": "button", "group": "army",    "multi": True},
    {"key": "train_button",  "kind": "button", "group": "army",    "multi": False},
    {"key": "close_button",  "kind": "button", "group": "general", "multi": False},
    # --- collecting
    {"key": "collector_full","kind": "button", "group": "collect", "multi": True},
    {"key": "loot_cart",     "kind": "button", "group": "collect", "multi": False},
    {"key": "collect_button","kind": "button", "group": "collect", "multi": False},
    # --- battle end (overrides the built-in images when taught)
    {"key": "return_home",   "kind": "button", "group": "battle",  "multi": False},
    {"key": "end_battle",    "kind": "button", "group": "battle",  "multi": False},
    {"key": "okay_button",   "kind": "button", "group": "battle",  "multi": False},
    # --- free slots for anything else (gifts, season pass, events…), used by routines
    *[{"key": f"custom_{i}", "kind": "button", "group": "custom", "multi": True} for i in range(1, 9)],
]
KEYS = {c["key"]: c for c in CATALOG}

def _safe(name):
    return "".join(c for c in str(name) if c.isalnum() or c in "-_")

def load_meta():
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

def save_meta(meta):
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = META_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, META_PATH)

def template_path(key):
    return TEMPLATE_DIR / f"{_safe(key)}.png"

def capture_path(id):
    return CAPTURE_DIR / f"{_safe(id)}.png"

def capture_request_path(id):
    return CAPTURE_DIR / f"{_safe(id)}.req"

def request_capture(id):
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    try: capture_path(id).unlink()
    except OSError: pass
    capture_request_path(id).write_text(str(time.time()))

def teach(key, rect, source_png, label=""):
    """rect = (x1, y1, x2, y2) as fractions of the captured screenshot."""
    import cv2
    if key not in KEYS: raise ValueError("unknown item")
    img = cv2.imread(str(source_png), cv2.IMREAD_COLOR)
    if img is None: raise ValueError("no screenshot captured")
    h, w = img.shape[:2]
    x1, y1, x2, y2 = rect
    x1, x2 = sorted((max(0.0, min(1.0, x1)), max(0.0, min(1.0, x2))))
    y1, y2 = sorted((max(0.0, min(1.0, y1)), max(0.0, min(1.0, y2))))
    if (x2 - x1) * w < 6 or (y2 - y1) * h < 6: raise ValueError("selection too small")
    meta = load_meta()
    entry = {"kind": KEYS[key]["kind"], "rect": [x1, y1, x2, y2], "time": time.time(), "label": label}
    if KEYS[key]["kind"] == "button":
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        crop = img[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]
        cv2.imwrite(str(template_path(key)), crop)
    meta[key] = entry
    save_meta(meta)
    return entry

def forget(key):
    meta = load_meta()
    meta.pop(key, None)
    save_meta(meta)
    try: template_path(key).unlink()
    except OSError: pass

def region(key):
    """Taught region as (x1, y1, x2, y2) fractions, or None."""
    e = load_meta().get(key)
    return tuple(e["rect"]) if e and e.get("kind") == "region" else None

_cache = {}
def template(key):
    """Taught button image as an RGB array (cached, reloaded when re-taught), or None."""
    import cv2
    p = template_path(key)
    try: mtime = p.stat().st_mtime
    except OSError: return None
    hit = _cache.get(key)
    if hit and hit[0] == mtime: return hit[1]
    img = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if img is None: return None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    _cache[key] = (mtime, img)
    return img

def taught(key):
    return key in load_meta()
