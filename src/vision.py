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
    """onnxruntime first (fast, any graphics card with DirectML / CUDA), OpenCV's dnn as the fallback.
    A model that can't load is logged as an error (it reaches Claude) instead of silently seeing nothing."""
    with _LOCK:
        if _NET["tried"]: return _NET["net"]
        _NET["tried"] = True
        d = _model_dir()
        if d is None:
            _log_error("Vision model file missing (assets/models/coc_vision.onnx)")
            return None
        _NET["names"] = json.loads((d / "coc_vision.json").read_text(encoding="utf-8"))["names"]
        errs = []
        try:
            import onnxruntime as ort
            av = ort.get_available_providers()
            prov = [p for p in ("CUDAExecutionProvider", "DmlExecutionProvider") if p in av] + ["CPUExecutionProvider"]
            so = ort.SessionOptions()
            so.enable_cpu_mem_arena = False
            so.intra_op_num_threads = 4
            sess = ort.InferenceSession(str(d / "coc_vision.onnx"), sess_options=so, providers=prov)
            _NET.update(net=sess, kind="ort", device=sess.get_providers()[0])
            return sess
        except Exception as e:
            errs.append(f"onnxruntime: {type(e).__name__}: {e}")
        try:
            import cv2
            _NET.update(net=cv2.dnn.readNetFromONNX(str(d / "coc_vision.onnx")), kind="cv2", device="cv2")
            return _NET["net"]
        except Exception as e:
            errs.append(f"opencv {getattr(__import__('cv2'), '__version__', '?')}: {type(e).__name__}: {e}")
        _NET["net"] = None
        _log_error("Vision model could not load — " + " | ".join(errs)[:500])
        return None


def _log_error(msg):
    try:
        from utils import logger
        logger.error(msg)
    except Exception:
        pass


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
    return {"model": d is not None, "loaded": _NET.get("net") is not None, "engine": _NET.get("device"), "map50": meta.get("map50"), "classes": len(meta.get("names", [])),
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
        if _NET.get("kind") == "ort":
            out = net.run(None, {net.get_inputs()[0].name: blob})[0]
        else:
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


def off_map(frame):
    """
    The forest and water around the map (troops can't be dropped there) -> bool mask at 1/8 scale.
    The forest is the grass's hue but deeper (more saturated) or in shadow; water is blue. Only big areas that touch
    the edge of the battlefield count (a dark patch inside the base is not the forest).
    """
    import cv2
    H, W = frame.shape[0] // 8, frame.shape[1] // 8
    small = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV).astype(int)
    h, sat, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    raw = ((h >= 24) & (h <= 55) & ((sat > 158) | (v < 75))) | ((h >= 85) & (h <= 130) & (sat > 60))
    dense = (cv2.blur(raw.astype(np.float32), (5, 5)) > 0.55).astype(np.uint8)
    y1, y2 = int(0.08 * H), int(0.80 * H)                       # the field (not the top bar / the troop cards)
    dense[:y1] = 0
    dense[y2:] = 0
    n, lab, st, _c = cv2.connectedComponentsWithStats(dense, 8)
    out = np.zeros((H, W), bool)
    for k in range(1, n):
        x, y, w, hh, area = st[k]
        touches = x <= 1 or x + w >= W - 1 or y <= y1 + 1 or y + hh >= y2 - 1
        if touches and area >= 0.03 * W * (y2 - y1):
            out |= lab == k
    return out


class Base:
    """What the bot sees of the enemy base."""

    def __init__(self, objs, frame=None):
        self.objs = objs
        self.off = self.grass = None
        if frame is not None:                    # 1/8 scale: the map's light grass, and the forest / water around it
            self.off = off_map(frame)
            import cv2
            small = cv2.resize(frame, (self.off.shape[1], self.off.shape[0]), interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV).astype(int)
            h, sat, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
            self.grass = (h >= 24) & (h <= 50) & (sat >= 60) & (sat <= 158) & (v >= 100) & ~self.off
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

    # how dangerous each defense is for an attack coming in (more = avoid that side)
    DANGER = {"inferno": 3.0, "eagle": 3.0, "scattershot": 2.5, "xbow": 2.0, "wizztower": 1.5, "bombtower": 1.5,
              "ad": 1.0, "mortar": 1.0, "canon": 1.0, "airsweeper": 0.8, "clancastle": 1.0}
    # the map is a diamond: the 4 sides a base can be attacked from (screen directions), the bottom ones first when
    # equal (the view is scrolled up: the bottom of the map is on screen)
    SIDES = {"bottom-left": (-0.7071, 0.7071), "bottom-right": (0.7071, 0.7071),
             "top-left": (-0.7071, -0.7071), "top-right": (0.7071, -0.7071)}
    # sides the user can pick (one-side attack): straight left / right / bottom, plus the four diagonal ones
    PICK = dict(SIDES, left=(-1.0, 0.0), right=(1.0, 0.0), bottom=(0.0, 1.0))
    FIELD = (0.03, 0.10, 0.97, 0.78)
    # the game's buttons / counters over the battlefield: never a drop spot
    UI = ((0.74, 0.0, 1.0, 0.23),        # gold / elixir / dark elixir bars (top right)
          (0.0, 0.0, 0.22, 0.30),        # player name + available loot (top left)
          (0.38, 0.0, 0.62, 0.09),       # battle timer
          (0.0, 0.68, 0.50, 0.80),       # End Battle / Surrender / boosts (bottom left)
          (0.80, 0.60, 1.0, 0.80),       # Next / damage % (bottom right)
          (0.92, 0.45, 1.0, 0.66))       # speed button

    def on_ui(self, x, y):
        return any(x1 <= x <= x2 and y1 <= y <= y2 for x1, y1, x2, y2 in self.UI)

    def on_grass(self, x, y):
        """On the map's grass (not the forest / water / sand / rocks around it, not a building, not the game's UI)."""
        if self.on_ui(x, y): return False
        if self.grass is None: return True
        H, W = self.grass.shape
        i, j = int(min(H - 1, max(0, y * H))), int(min(W - 1, max(0, x * W)))
        if self.off[i, j]: return False
        win = self.grass[max(0, i - 1):i + 2, max(0, j - 1):j + 2]        # a 3x3 patch: a flower is not the end
        return bool(win.mean() >= 0.4)

    def _room(self, x, y, dx, dy, limit=0.4):
        """
        From (x, y) outward in direction (dx, dy): where the open grass starts and how far it goes (then the forest /
        sand / water / the screen's edge) -> (start, length) as distances.
        """
        x1, y1, x2, y2 = self.FIELD
        d, start, miss = 0.0, None, 0
        while d < limit:
            px, py = x + dx * d, y + dy * d
            if not (x1 <= px <= x2 and y1 <= py <= y2): break
            ok = self.on_grass(px, py)
            if start is None:
                if ok: start = d
                elif d > 0.10: return 0.0, 0.0           # no grass right after the base: that side is off the map
            else:
                miss = 0 if ok else miss + 1
                if miss >= 3: return start, max(0.0, d - start - 0.03)
            d += 0.01
        return (start or 0.0), (max(0.0, d - start - 0.01) if start is not None else 0.0)

    def attack_plan(self, n_points=5, out=0.05, spread=0.13, side=None):
        """
        The weakest side of the base and where to drop on it -> {"side", "points", "spell", "danger"} or None.
        points: a line of deploy spots just outside the base on that side; spell: the defenses packed together a bit
        inside from that side (rage / heal / freeze go there).
        side: "left" / "right" / "bottom" / "bottom-left"… = that side, whatever its danger (the user's choice);
        None / "auto" = the weakest side.
        """
        if self.hull is None: return None
        hull = self.hull.reshape(-1, 2)
        cx, cy = hull.mean(axis=0)
        x1, y1, x2, y2 = self.FIELD
        best = None
        forced = side if side in self.PICK else None
        sides = {forced: self.PICK[forced]} if forced else self.SIDES
        if forced in ("left", "right"): spread = max(spread, 0.17)       # a long straight line along the side
        for name, (dx, dy) in sides.items():
            proj = hull @ np.array([dx, dy])
            edge = hull[int(np.argmax(proj))]
            px, py = -dy, dx                                     # along the side
            # between the base and the end of the map: every spot on its own, from the base's side outward over the
            # open grass (the forest / sand / water is no-go), in the middle of it
            onscreen = []
            if forced:
                # the user's side: a line that follows the base's own edge on that side — from the base's middle,
                # rays fanned ±40° around the side's direction, each to the outline, then out onto the grass
                import math
                poly = [[float(a), float(b)] for a, b in hull]
                base_ang = math.atan2(dy, dx)
                for a in np.linspace(-math.radians(40), math.radians(40), n_points + 2):
                    ux, uy = math.cos(base_ang + a), math.sin(base_ang + a)
                    r = ray_radius(poly, float(cx), float(cy), ux, uy)
                    if r is None: continue
                    ex, ey = float(cx + ux * r), float(cy + uy * r)
                    st, room = self._room(ex, ey, ux, uy)
                    if room < 0.02: continue
                    d = st + min(room * 0.5, max(out * 0.6, 0.25 * room))
                    qx, qy = ex + ux * d, ey + uy * d
                    if x1 <= qx <= x2 and y1 <= qy <= y2 and self.on_grass(qx, qy):
                        onscreen.append((qx, qy))
            for t in (np.linspace(-1, 1, n_points) if not forced else []):
                sx, sy = float(edge[0] + px * spread * t), float(edge[1] + py * spread * t)
                for _ in range(40):                                # out of the base's outline first
                    if not self.inside(sx, sy, margin=0.01): break
                    sx, sy = sx + dx * 0.01, sy + dy * 0.01
                st, room = self._room(sx, sy, dx, dy)
                if room < 0.02: continue
                d = st + min(room * 0.5, max(out, 0.3 * room))
                qx, qy = sx + dx * d, sy + dy * d
                if x1 <= qx <= x2 and y1 <= qy <= y2 and self.on_grass(qx, qy):
                    onscreen.append((float(qx), float(qy)))
            if len(onscreen) < (1 if forced else max(2, n_points // 2)): continue    # that side is off the screen
            # danger: the defenses near that side's edge (closer counts more)
            danger = 0.0
            for o in self.objs:
                ox, oy = o.center
                d = ((ox - edge[0]) ** 2 + (oy - edge[1]) ** 2) ** 0.5
                if d < 0.30: danger += self.DANGER.get(o.name, 0.5) * (1.0 - d / 0.30)
            # a side with room for every spot first (a cramped side spreads the troops badly)
            score = danger + 1.5 * (n_points - len(onscreen)) - (0.15 if name.startswith("bottom") else 0)
            if best is None or score < best[0]:
                inner = edge - np.array([dx, dy]) * 0.12           # a bit inside the base from that side
                near = [o.center for o in self.objs if self.DANGER.get(o.name, 0) >= 1.5 and
                        ((o.center[0] - inner[0]) ** 2 + (o.center[1] - inner[1]) ** 2) ** 0.5 < 0.18]
                spell = (float(np.mean([p[0] for p in near])), float(np.mean([p[1] for p in near]))) if near else \
                        (float(inner[0]), float(inner[1]))
                # in front of the troops: from the middle of their line toward the middle of the base, a spot every
                # 0.08 (the first spell card close to them, the next ones further in, where they will be fighting)
                mx = sum(p[0] for p in onscreen) / len(onscreen)
                my = sum(p[1] for p in onscreen) / len(onscreen)
                vx, vy = cx - mx, cy - my
                n = (vx * vx + vy * vy) ** 0.5 or 1.0
                path = [(float(min(0.95, max(0.05, mx + vx / n * d))), float(min(0.78, max(0.12, my + vy / n * d))))
                        for d in (0.12, 0.20, 0.28, 0.36)]
                best = (score, {"side": name, "points": onscreen, "spell": spell, "spell_path": path,
                                "danger": round(danger, 1)})
        return best[1] if best else None

    def outline(self):
        """The outline as plain lists (saved with a recording), or None."""
        return None if self.hull is None else [[round(float(x), 4), round(float(y), 4)] for x, y in self.hull.reshape(-1, 2)]

    def outside_spots(self, spots, margin=0.03):
        """The spots that are not inside the base (kept in their order), then the others."""
        out = [p for p in spots if not self.inside(*p, margin=margin)]
        return out + [p for p in spots if p not in out]


def ray_radius(poly, cx, cy, dx, dy):
    """From (cx, cy) in direction (dx, dy): how far to the outline poly ([[x, y], ...]) -> distance or None."""
    best = None
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if abs(den) < 1e-12: continue
        t = ((ax - cx) * ey - (ay - cy) * ex) / den           # along the ray
        u = ((ax - cx) * dy - (ay - cy) * dx) / den           # along the edge
        if t > 0 and -1e-9 <= u <= 1 + 1e-9 and (best is None or t > best): best = t
    return best


def look(frame, keep_for_learning=True, logger=None):
    """One look at the battlefield -> Base (empty when the model isn't there). Also keeps the picture for training."""
    t = time.time()
    try:
        objs = detect(frame)
    except Exception:
        objs = []
    base = Base(objs, frame)
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
