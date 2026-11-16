"""
Army learning: the bot watches the user prepare an army in the game and learns to do it by itself.

Learning (bot process, CoC_Bot.learn_army):
  the game is brought to the village, then every tap of the user is recorded (getevent, like battle
  recordings) while the screen is captured continuously. For every tap the bot reads the word under
  the finger on the frame just before it (OCR), so a step is remembered as "tap <word>" and not only
  as a position. The last army screen is kept as a picture of the army.
Replay (CoC_Bot.run_army):
  from the village, every step is done again: the word is looked for on the screen and tapped where
  it is now (survives small layout changes); when the word isn't found, the recorded position is used.

Files: ~/.CoC_Bot/armies/<name>.json (+ <name>.jpg picture), requests in ~/.CoC_Bot/army_requests/.
"""
import json, re, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "armies"
REQ_DIR = Path.home() / ".CoC_Bot" / "army_requests"
# words that mean nothing on their own (numbers, single letters) are not used to find a button
_MEANINGLESS = re.compile(r"^[\W\d_]*$")


def _safe(name):
    return "".join(c for c in str(name) if c.isalnum() or c in "-_ ")[:40].strip() or "army"


# ====================================================================== library
def list_armies():
    out = []
    for p in sorted(DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"name": d.get("name", p.stem), "created": d.get("created"), "steps": len(d.get("steps", [])),
                        "words": [s.get("word") for s in d.get("steps", []) if s.get("word")][:8],
                        "picture": (DIR / f"{_safe(d.get('name', p.stem))}.jpg").exists(), "uses": d.get("uses", 0)})
        except (OSError, ValueError):
            continue
    return out


def load(name):
    try: return json.loads((DIR / f"{_safe(name)}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError): return None


def save(data, picture_rgb=None):
    DIR.mkdir(parents=True, exist_ok=True)
    name = _safe(data["name"])
    (DIR / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if picture_rgb is not None:
        import cv2
        small = cv2.resize(picture_rgb, (960, int(960 * picture_rgb.shape[0] / picture_rgb.shape[1])))
        cv2.imwrite(str(DIR / f"{name}.jpg"), cv2.cvtColor(small, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])


def picture_path(name):
    p = DIR / f"{_safe(name)}.jpg"
    return p if p.exists() else None


def delete(name):
    for ext in (".json", ".jpg"):
        try: (DIR / f"{_safe(name)}{ext}").unlink()
        except OSError: pass


def count_use(name):
    d = load(name)
    if d:
        d["uses"] = int(d.get("uses", 0)) + 1
        d["last_used"] = time.time()
        save(d)


# ====================================================================== requests from the window
def request(id, name):
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    (REQ_DIR / f"{id}.json").write_text(json.dumps({"name": name, "t": time.time()}), encoding="utf-8")
    try: (REQ_DIR / f"{id}.stop").unlink()
    except OSError: pass


def pending(id):
    return (REQ_DIR / f"{id}.json").exists()


def take_request(id, max_age=600):
    p = REQ_DIR / f"{id}.json"
    if not p.exists(): return None
    try: d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): d = None
    try: p.unlink()
    except OSError: pass
    if d and time.time() - float(d.get("t", 0)) > max_age: return None
    return d


def request_stop(id):
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    (REQ_DIR / f"{id}.stop").write_text(str(time.time()), encoding="utf-8")


def stop_requested(id):
    p = REQ_DIR / f"{id}.stop"
    if p.exists():
        try: p.unlink()
        except OSError: pass
        return True
    return False


def set_status(id, text, **extra):
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    (REQ_DIR / f"{id}.status").write_text(json.dumps(dict(extra, text=text, t=time.time()), ensure_ascii=False), encoding="utf-8")


def get_status(id):
    try: return json.loads((REQ_DIR / f"{id}.status").read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


# ====================================================================== geometry + words
def touch_to_screen(fx, fy, max_x, max_y):
    """Recorded touch fractions -> screen fractions (inverse of Input_Handler._to_raw)."""
    if max_x >= max_y: return fx, fy
    return fy, 1 - fx           # portrait-ordered touch device (MuMu): rotated 90 degrees


def word_at(boxes, x, y, pad=0.012):
    """The meaningful OCR word under (x, y) (screen fractions), or the nearest one within a small radius."""
    best, best_d = None, 1e9
    for text, x1, y1, x2, y2, conf in boxes:
        t = (text or "").strip()
        if conf < 0.3 or len(t) < 2 or _MEANINGLESS.match(t): continue
        inside = x1 - pad <= x <= x2 + pad and y1 - pad <= y <= y2 + pad
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        d = 0 if inside else ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
        if d < best_d: best, best_d = t, d
    return best if best_d <= 0.045 else None


def find_word(boxes, word, near=None):
    """Where `word` is on the screen now -> (x, y) fractions; the closest match to `near` if it appears twice."""
    from utils import _word_hit
    w = word.lower().strip()
    hits = [((b[1] + b[3]) / 2, (b[2] + b[4]) / 2) for b in boxes if b[5] > 0.3 and (_word_hit(b[0], w) or _word_hit(w, b[0].lower().strip()))]
    if not hits: return None
    if near: hits.sort(key=lambda p: (p[0] - near[0]) ** 2 + (p[1] - near[1]) ** 2)
    return hits[0]


def build_steps(downs, frames, boxes_of, max_x, max_y):
    """downs: [(monotonic t, fx, fy)] touch-down events; frames: the screen captured just before each of them
    (same length, frames[i] belongs to downs[i]). -> steps [{x, y, word, gap}]."""
    steps, last_t = [], None
    for i, (t, fx, fy) in enumerate(downs):
        x, y = touch_to_screen(fx, fy, max_x, max_y)
        word = None
        if i < len(frames):
            try: word = word_at(boxes_of(frames[i]), x, y)
            except Exception: word = None
        steps.append({"x": round(x, 4), "y": round(y, 4), "word": word, "gap": round(0 if last_t is None else t - last_t, 2)})
        last_t = t
    return steps
