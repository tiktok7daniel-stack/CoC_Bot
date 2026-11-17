"""
The bot's eyes in a battle: a YOLO model that finds the enemy base's buildings on the screen.

assets/models/coc_vision.onnx — trained by Claude (scripts/train_vision.py) on open data (CC BY 4.0, see
assets/models/NOTICE.txt) and on the pictures of this bot's own battles. Runs with OpenCV only (no new library):
~20-60 ms on the processor for one look.

What the rest of the bot gets from it:
  detect(frame)    -> [Obj(name, conf, x1, y1, x2, y2)]  (fractions of the screen)
  look(frame)      -> Base: the objects, the Town Hall, a summary line, and the base's outline (where the
                      red line is, roughly: every building found + a margin) used to choose deploy spots
Every battle the first zoomed-out picture is kept (with what was found) for the next training.
"""
import json, os, sys, threading, time
from pathlib import Path

import numpy as np

SIZE = 640
CONF = 0.35
_NET = {"net": None, "names": None, "tried": False}
_LOCK = threading.Lock()
KEEP = Path.home() / ".CoC_Bot" / "learn" / "battles"


def _model_dir():
    for base in ([Path(sys._MEIPASS)] if hasattr(sys, "_MEIPASS") else []) + [Path(__file__).resolve().parent.parent]:
        p = base / "assets" / "models"
        if (p / "coc_vision.onnx").exists(): return p
    return None


def _load():
    with _LOCK:
        if _NET["tried"]: return _NET["net"]
        _NET["tried"] = True
        d = _model_dir()
        if d is None: return None
        try:
            import cv2
            _NET["net"] = cv2.dnn.readNetFromONNX(str(d / "coc_vision.onnx"))
            _NET["names"] = json.loads((d / "coc_vision.json").read_text(encoding="utf-8"))["names"]
        except Exception:
            _NET["net"] = None
        return _NET["net"]


class Obj:
    __slots__ = ("name", "conf", "x1", "y1", "x2", "y2")

    def __init__(self, name, conf, x1, y1, x2, y2):
        self.name, self.conf, self.x1, self.y1, self.x2, self.y2 = name, conf, x1, y1, x2, y2

    @property
    def center(self):
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    def __repr__(self):
        return f"{self.name}({self.conf:.2f} @ {self.center[0]:.2f},{self.center[1]:.2f})"


def info():
    """For the app: is the model there, how good it is, the last base seen."""
    d = _model_dir()
    meta = {}
    if d is not None:
        try: meta = json.loads((d / "coc_vision.json").read_text(encoding="utf-8"))
        except (OSError, ValueError): meta = {}
    return {"model": d is not None, "map50": meta.get("map50"), "classes": len(meta.get("names", [])),
            "last": _LAST.get("summary", "")}


_LAST = {}


def detect(frame, conf=CONF):
    """RGB frame -> objects found (fractions of the frame). [] when the model isn't there."""
    import cv2
    net = _load()
    if net is None: return []
    h, w = frame.shape[:2]
    s = max(h, w)
    square = np.zeros((s, s, 3), np.uint8)          # same as the training pictures: square, black edges
    oy, ox = (s - h) // 2, (s - w) // 2
    square[oy:oy + h, ox:ox + w] = frame
    blob = cv2.dnn.blobFromImage(square, 1 / 255.0, (SIZE, SIZE), swapRB=False, crop=False)
    with _LOCK:
        net.setInput(blob)
        out = net.forward()
    out = np.squeeze(out, 0).T                      # (8400, 4 + classes)
    scores = out[:, 4:]
    cls = scores.argmax(1)
    best = scores[np.arange(len(cls)), cls]
    keep = best >= conf
    if not keep.any(): return []
    b, cls, best = out[keep, :4], cls[keep], best[keep]
    k = s / SIZE
    boxes = [[(cx - bw / 2) * k - ox, (cy - bh / 2) * k - oy, bw * k, bh * k] for cx, cy, bw, bh in b]
    idx = cv2.dnn.NMSBoxes(boxes, best.tolist(), conf, 0.45)
    names = _NET["names"]
    res = []
    for i in (np.array(idx).flatten() if len(idx) else []):
        x, y, bw, bh = boxes[i]
        res.append(Obj(names[int(cls[i])], float(best[i]), max(0, x / w), max(0, y / h),
                       min(1, (x + bw) / w), min(1, (y + bh) / h)))
    return res


class Base:
    """What the bot sees of the enemy base."""

    def __init__(self, objs):
        self.objs = objs
        self.th = next((o for o in objs if o.name.startswith("th")), None)
        self.hull = None
        if len(objs) >= 4:
            import cv2
            pts = np.array([[o.x1, o.y1] for o in objs] + [[o.x2, o.y2] for o in objs] +
                           [[o.x1, o.y2] for o in objs] + [[o.x2, o.y1] for o in objs], np.float32)
            self.hull = cv2.convexHull(pts)

    def count(self):
        c = {}
        for o in self.objs: c[o.name] = c.get(o.name, 0) + 1
        return c

    def summary(self):
        if not self.objs: return "nothing recognised"
        return ", ".join(f"{n} x{c}" if c > 1 else n for n, c in sorted(self.count().items(), key=lambda x: -x[1]))

    def inside(self, x, y, margin=0.03):
        """Roughly inside the red line: within the base's outline (+ a margin of about one tile)."""
        if self.hull is None: return False
        import cv2
        return cv2.pointPolygonTest(self.hull, (float(x), float(y)), True) >= -margin

    def outside_spots(self, spots, margin=0.03):
        """The spots that are not inside the base (kept in their order), then the others."""
        out = [p for p in spots if not self.inside(*p, margin=margin)]
        return out + [p for p in spots if p not in out]


def look(frame, keep_for_learning=True, logger=None):
    """One look at the battlefield -> Base (empty when the model isn't there). Also keeps the picture for training."""
    t = time.time()
    try:
        objs = detect(frame)
    except Exception:
        objs = []
    base = Base(objs)
    _LAST["summary"] = base.summary()
    if logger is not None and objs:
        logger.info(f"Base seen ({(time.time() - t) * 1000:.0f} ms): {base.summary()}")
    if keep_for_learning and _NET["net"] is not None:
        threading.Thread(target=_keep, args=(frame.copy(), objs), daemon=True).start()
    return base


def _keep(frame, objs, limit=300):
    """The battle picture + what the model found (Claude checks / corrects these for the next training)."""
    try:
        import cv2
        KEEP.mkdir(parents=True, exist_ok=True)
        name = time.strftime("%Y%m%d_%H%M%S")
        cv2.imwrite(str(KEEP / f"{name}.jpg"), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
        (KEEP / f"{name}.json").write_text(json.dumps({"objects": [[o.name, round(o.conf, 3), round(o.x1, 4), round(o.y1, 4),
                                                                     round(o.x2, 4), round(o.y2, 4)] for o in objs]}),
                                           encoding="utf-8")
        old = sorted(KEEP.glob("*.jpg"))[:-limit]
        for p in old:
            for q in (p, p.with_suffix(".json")):
                try: q.unlink()
                except OSError: pass
    except Exception:
        pass
