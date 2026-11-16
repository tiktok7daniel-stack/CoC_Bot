"""
The bot's own memory of screens — it learns from what it sees, like training.

Every time the bot gets out of a screen it didn't know (it pressed "Later", "Close", "Okay"…) it remembers that
screen's look (fingerprint, a few ms) and the place it pressed, and checks that the press really changed the screen.
The next time the same screen shows up it presses the same place at once: no reading of words (~1 s), no waiting.
A press that didn't work is counted too; a remembered press that keeps failing is dropped.

It also knows which screens it already sent / saved, so the same screen is never stored or sent twice.

~/.CoC_Bot/learn/memory_<account>.json
"""
import json, threading, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "learn"
SAME = 10            # fingerprints this close = the same screen (for pressing)
DUP = 12             # ... for "already stored / sent"
_LOCK = threading.Lock()
_cache = {}


def _safe(x):
    return "".join(c for c in str(x) if c.isalnum() or c in "-_") or "main"


def _path(id):
    return DIR / f"memory_{_safe(id)}.json"


def _load(id):
    if id in _cache: return _cache[id]
    try: d = json.loads(_path(id).read_text(encoding="utf-8"))
    except (OSError, ValueError): d = {}
    d.setdefault("screens", [])
    d.setdefault("seen", {})
    _cache[id] = d
    return d


def _save(id):
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        _path(id).write_text(json.dumps(_load(id), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def fingerprint(frame):
    import capture_session as cs
    return cs.dhash(frame)


def _dist(a, b):
    import capture_session as cs
    return cs.distance(tuple(int(x) for x in a), tuple(int(x) for x in b))


# ---------------------------------------------------------------- what to press
def recall(id, frame=None, h=None):
    """The remembered press for this screen, or None."""
    h = h or fingerprint(frame)
    best, best_d = None, 999
    with _LOCK:
        for e in _load(id)["screens"]:
            if e.get("ok", 0) < 1 or e.get("fail", 0) >= e.get("ok", 0) + 2: continue
            d = _dist(h, e["h"])
            if d < best_d: best, best_d = e, d
    return best if best_d <= SAME else None


def learn(id, h, x, y, word="", worked=True, phase=""):
    """Remember (or correct) what pressing (x, y) did on the screen with fingerprint h."""
    with _LOCK:
        d = _load(id)
        e = next((e for e in d["screens"] if _dist(h, e["h"]) <= SAME and abs(e["x"] - x) < 0.04 and abs(e["y"] - y) < 0.04), None)
        if e is None:
            if not worked: return
            e = {"h": [str(h[0]), str(h[1])], "x": round(x, 4), "y": round(y, 4), "word": word, "ok": 0, "fail": 0,
                 "phase": phase, "first": time.time()}
            d["screens"].append(e)
        e["ok" if worked else "fail"] = e.get("ok" if worked else "fail", 0) + 1
        e["t"] = time.time()
        # forget presses that keep failing; keep the memory small
        d["screens"] = [s for s in d["screens"] if s.get("fail", 0) < s.get("ok", 0) + 3][-400:]
        _save(id)


def press(id, frame, logger=None):
    """
    Known screen -> press the remembered place and check the screen changed. True if pressed.
    Instant: no reading of words.
    """
    from utils import Input_Handler, Frame_Handler
    h = fingerprint(frame)
    e = recall(id, h=h)
    if not e: return False
    Input_Handler.click(e["x"], e["y"])
    worked = changed(h)
    learn(id, h, e["x"], e["y"], e.get("word", ""), worked)
    if logger is not None:
        key = f"{e['x']},{e['y']}"
        if time.time() - _cache.get(("log", key), 0) > 60:
            _cache[("log", key)] = time.time()
            logger.info(f"Remembered screen: pressed {e.get('word') or 'the same place'} right away ({e.get('ok', 0)}x before)")
    return True


def changed(h_before, wait=0.6, tries=3):
    """After a press: did the screen change? (it can take a moment)"""
    from utils import Frame_Handler
    for _ in range(tries):
        time.sleep(wait / tries)
        try:
            if _dist(h_before, fingerprint(Frame_Handler.get_frame(grayscale=False))) > SAME: return True
        except Exception:
            return False
    return False


# ---------------------------------------------------------------- stored / sent already?
def seen_before(id, kind, frame=None, h=None, add=True):
    """True if a screen that looks the same was already stored / sent under `kind`. Remembers it otherwise."""
    h = h or fingerprint(frame)
    with _LOCK:
        d = _load(id)
        lst = d["seen"].setdefault(kind, [])
        for s in lst:
            if _dist(h, s["h"]) <= DUP:
                s["n"] = s.get("n", 1) + 1
                s["t"] = time.time()
                _save(id)
                return True
        if add:
            lst.append({"h": [str(h[0]), str(h[1])], "n": 1, "t": time.time()})
            d["seen"][kind] = lst[-500:]
            _save(id)
    return False


def stats(id):
    d = _load(id)
    return {"screens": len(d["screens"]), "presses": sum(s.get("ok", 0) for s in d["screens"]),
            "seen": {k: len(v) for k, v in d["seen"].items()}}
