"""
The bot's brain for screens: knows what screen the game shows by how it looks — in ~1 ms, without reading a word.

Trained on the pictures the user sent and Claude labelled (knowledge/model.json in the learning repo, fetched
by the bot; a copy ships in assets/screen_model.json). Every labelled picture becomes an example:
  - layout   16x9 colours of the whole screen
  - edges    16x9 map of where the buttons / panels / text are
  - colours  hue x saturation histogram in each third of the screen (3x3)
The nearest example wins when it is close enough; else the screen is "unknown" (then the words are read as before).

It also trains itself while it plays: when the instant colour checks are sure (the village, the army screen…)
the picture is added as an example of that screen (~/.CoC_Bot/learn/self_model_<account>.json, a few per kind).

A live watcher looks at the newest picture a few times a second, so the bot always knows where it is:
current() -> ("battle_result_claim", 0.012) and the app shows it ("the screen now: …").
"""
import base64, json, sys, threading, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "learn"
REPO_MODEL = DIR / "model.json"                    # fetched from the learning repo
SURE = 0.030                                       # nearest example closer than this: that screen
SELF_MAX = 12                                      # self-taught examples kept per kind
VERSION = 1

_M = {"t": 0.0, "ex": None, "labels": [], "titles": {}, "src": ""}
_LOCK = threading.Lock()
_RATE = {}
_NOW = {"label": None, "dist": None, "t": 0.0, "since": 0.0}


# ---------------------------------------------------------------- features
def features(img):
    import cv2, numpy as np
    small = cv2.resize(img, (64, 36), interpolation=cv2.INTER_AREA)
    lay = cv2.resize(small, (16, 9), interpolation=cv2.INTER_AREA).astype(np.float32).flatten() / 255
    g = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32)
    ed = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0)) + np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1))
    ed = cv2.resize(ed, (16, 9), interpolation=cv2.INTER_AREA).flatten()
    ed /= ed.max() + 1e-6
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    hs = []
    for i in range(3):
        for j in range(3):
            c = hsv[i * 12:(i + 1) * 12, j * 21:(j + 1) * 21]
            h = cv2.calcHist([c], [0, 1], None, [12, 4], [0, 180, 0, 256]).flatten()
            hs.append(h / (h.sum() + 1e-6))
    return np.concatenate([lay, ed, np.concatenate(hs) * 3.0]).astype(np.float32)


def _pack(v):
    import numpy as np
    return base64.b64encode(np.asarray(v, dtype=np.float16).tobytes()).decode("ascii")


def _unpack(s):
    import numpy as np
    return np.frombuffer(base64.b64decode(s), dtype=np.float16).astype(np.float32)


# ---------------------------------------------------------------- the model
def _model_files():
    out = [REPO_MODEL]
    for base in ([Path(sys._MEIPASS)] if hasattr(sys, "_MEIPASS") else []) + [Path(__file__).resolve().parent.parent]:
        out.append(base / "assets" / "screen_model.json")
    return out


def _self_path(id):
    return DIR / f"self_model_{''.join(c for c in str(id) if c.isalnum() or c in '-_') or 'main'}.json"


def load(id="main", force=False):
    """Examples from the repo model (or the shipped one) + the self-taught ones. Reloaded every minute."""
    import numpy as np
    with _LOCK:
        if not force and _M["ex"] is not None and time.time() - _M["t"] < 60: return _M
        ex, labels, titles, src = [], [], {}, ""
        for p in _model_files():
            try: d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError): continue
            if d.get("version") != VERSION: continue
            for it in d.get("items", []):
                ex.append(_unpack(it["v"])); labels.append(it["rule"])
            titles.update(d.get("titles", {}))
            src = str(p)
            break
        try:
            for it in json.loads(_self_path(id).read_text(encoding="utf-8")).get("items", []):
                ex.append(_unpack(it["v"])); labels.append(it["rule"])
        except (OSError, ValueError):
            pass
        _M.update(t=time.time(), ex=np.array(ex) if ex else None, labels=labels, titles=titles, src=src)
        return _M


def classify(img, id="main"):
    """-> (screen kind, distance) of the nearest example, or (None, distance) when nothing is close enough."""
    import numpy as np
    m = load(id)
    if m["ex"] is None or not len(m["labels"]): return None, None
    f = features(img)
    if f.shape[0] != m["ex"].shape[1]: return None, None
    d = np.abs(m["ex"] - f).mean(1)
    i = int(np.argmin(d))
    best = m["labels"][i]
    # sure only when it is clearly that kind: the nearest example of any other kind is well farther away
    other = min((float(x) for x, l in zip(d, m["labels"]) if l != best), default=9.0)
    sure = d[i] <= SURE and other >= max(d[i] * 1.5, d[i] + 0.008)
    return (best if sure else None), float(d[i])


def title(label):
    return load()["titles"].get(label, label or "")


def teach_self(id, img, label):
    """A picture the instant checks are sure about -> one more example of that screen (only if it adds something)."""
    import numpy as np
    key = (id, label)
    if time.time() - _RATE.get(key, 0) < 120: return False      # at most every 2 minutes per screen kind
    _RATE[key] = time.time()
    try:
        p = _self_path(id)
        try: d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError): d = {"version": VERSION, "items": []}
        f = features(img)
        m = load(id)
        if m["ex"] is not None and len(m["labels"]):
            dist = np.abs(m["ex"] - f).mean(1)
            same = [dist[i] for i, l in enumerate(m["labels"]) if l == label]
            if same and min(same) < SURE * 0.4: return False          # nothing new: it already knows this look
        items = [it for it in d.get("items", []) if it["rule"] == label][-(SELF_MAX - 1):]
        items = [it for it in d.get("items", []) if it["rule"] != label] + items + [{"rule": label, "v": _pack(f), "t": time.time()}]
        d["items"] = items
        DIR.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d), encoding="utf-8")
        load(id, force=True)
        return True
    except Exception:
        return False


def info(id="main"):
    m = load(id)
    return {"screens": len(m["labels"]), "kinds": len(set(m["labels"])), "now": _NOW.get("label"),
            "now_title": title(_NOW.get("label")) if _NOW.get("label") else ""}


# ---------------------------------------------------------------- live watcher
def current(max_age=1.0):
    """What the screen is right now, as the watcher saw it (None when not sure / too old)."""
    if time.monotonic() - _NOW["t"] > max_age: return None, None
    return _NOW["label"], _NOW["dist"]


def watch(id, get_frame, logger=None, every=0.25):
    """Background thread: classify the newest picture a few times a second (cheap with the live screen)."""
    def loop():
        last = None
        while True:
            try:
                img = get_frame()
                if img is not None:
                    label, dist = classify(img, id)
                    now = time.monotonic()
                    if label != _NOW["label"]: _NOW["since"] = now
                    _NOW.update(label=label, dist=dist, t=now)
                    if label and label != last and logger is not None:
                        logger.debug(f"Screen now: {label} ({dist:.3f})")
                    last = label
            except Exception:
                pass
            time.sleep(every)
    t = threading.Thread(target=loop, daemon=True, name="screen-watcher")
    t.start()
    return t


# ---------------------------------------------------------------- building the model (Claude, learning repo)
def build(pairs, titles=None):
    """pairs: [(rule, RGB picture)] -> model dict (knowledge/model.json)."""
    return {"version": VERSION, "built": time.strftime("%Y-%m-%d %H:%M"), "sure": SURE, "titles": titles or {},
            "items": [{"rule": r, "v": _pack(features(img))} for r, img in pairs]}
