"""
The stronger Clash Royale eyes: SudhishNeel's YOLOv8 arena detector (huggingface.co/SudhishNeel/clash-royale-detector,
v8: phone-frame mAP50 0.839, 174 kinds: every troop, building, spell, evolution and hero). Used next to the first
eyes (royale.vision, 97 kinds): what either one sees is used, the brain keeps only what is seen in 2 of 3 looks.

Nothing of it is shipped with the program: on the first Clash Royale start it is fetched from its author's page and
turned into an ONNX file on this PC (once, in the background; needs the `ultralytics` package, installed by itself),
then it runs with onnxruntime like every other model of the bot.

The model wants the arena only, 568x896 (18x32 tiles). It finds the four princess ("queen") towers and the two
king towers itself, so the exact arena box on this screen is calibrated from them once and remembered.
"""
import json, os, threading, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "models"
ONNX = DIR / "cr_detector_v8.onnx"
NAMES = DIR / "cr_detector_v8.json"
CALIB = DIR / "cr_arena_box.json"
URL = "https://huggingface.co/SudhishNeel/clash-royale-detector/resolve/main/v8/best.pt"
W, H = 568, 896                       # the arena picture the model was trained on
SPEC_QUEENS = [(116, 200), (461, 200), (116, 689), (461, 689)]
_S = {"sess": None, "names": None, "busy": False, "error": "", "tried": 0.0}
# 6.9.18: the FAST eyes — YOLO26s at 640 trained on this PC on the same data (royale.trainer, "fast26"); when the
# big model cannot answer for the very picture (> SYNC_MS), the fast one does, on that same picture
FAST = DIR / "cr_detector_fast.onnx"
FAST_NAMES = DIR / "cr_detector_fast.json"
_F = {"sess": None, "names": None, "mtime": 0.0, "ms": 0.0, "tried": 0.0}
from royale.vision.detectors.onnx_detector import GPU_LOCK as _LOCK      # one model at a time on the card

# the model's names -> the bot's unit names (royale.vision Units / cards.json "units")
RENAME = {"mini-pekka": "minipekka", "elixir-golem-big": "elixir_golem_large", "elixir-golem-mid": "elixir_golem_medium",
          "phoenix-big": "phoenix_large", "firecracker": "fire_cracker", "goblin-brawler": "brawler"}
NOT_UNITS = {"king-tower", "queen-tower", "cannoneer-tower", "dagger-duchess-tower", "elixir", "clock", "dirt", "void",
             "skeleton-king-skill", "arrows", "fireball", "zap", "the-log", "poison", "rocket", "lightning", "freeze",
             "rage", "tornado", "earthquake", "clone", "graveyard", "goblin-curse", "vines", "royal-delivery",
             "giant-snowball", "barbarian-barrel", "goblin-barrel", "axe", "bomb", "goblin-ball", "suspicious-bush"}


def unit_name(cls):
    if cls in NOT_UNITS: return None
    base = cls
    for suf in ("-evolution", "-hero"):
        if base.endswith(suf): base = base[: -len(suf)]
    return RENAME.get(base, base.replace("-", "_"))


# ------------------------------------------------------------------ getting it (once)
def ensure(logger=None):
    """Load it, or start fetching / converting it in the background. -> True when it is ready now."""
    if _S["sess"] is not None: return True
    if _S["busy"] or time.time() - _S["tried"] < 600: return False
    _S["tried"] = time.time()
    if ONNX.exists() and NAMES.exists():
        return _load()
    _S["busy"] = True

    def work():
        try:
            import deps
            if not deps.ensure("ultralytics", ["ultralytics", "onnx"]):
                for _ in range(360):                       # the install runs in the background (up to 30 min)
                    time.sleep(5)
                    try:
                        import importlib; importlib.invalidate_caches(); import ultralytics  # noqa: F401
                        break
                    except ImportError:
                        continue
            import requests
            from ultralytics import YOLO
            DIR.mkdir(parents=True, exist_ok=True)
            pt = DIR / "cr_detector_v8.pt"
            if not pt.exists():
                with requests.get(URL, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    tmp = pt.with_suffix(".part")
                    with open(tmp, "wb") as f:
                        for c in r.iter_content(1 << 20): f.write(c)
                    os.replace(tmp, pt)
            m = YOLO(str(pt))
            out = m.export(format="onnx", imgsz=800, dynamic=False, simplify=False, opset=12)
            os.replace(out, ONNX)
            NAMES.write_text(json.dumps({int(k): v for k, v in m.names.items()}), encoding="utf-8")
            if logger: logger.info("Clash Royale: stronger eyes ready (YOLOv8, 174 kinds)")
            _load()
        except Exception as e:
            _S["error"] = f"{type(e).__name__}: {e}"[:200]
            if logger: logger.warning(f"Clash Royale: stronger eyes not available ({_S['error']}) — the first eyes play alone")
        finally:
            _S["busy"] = False
    threading.Thread(target=work, daemon=True, name="cr-strong-eyes").start()
    return False


def _load():
    try:
        import trt_engine                     # TensorRT FP16 -> CUDA -> DirectML -> processor (6.6)
        _S["sess"] = trt_engine.make_session(ONNX, threads=2)
        _S["mtime"] = ONNX.stat().st_mtime
        _S["names"] = {int(k): v for k, v in json.loads(NAMES.read_text(encoding="utf-8")).items()}
        return True
    except Exception as e:
        _S["error"] = f"load: {e}"[:200]
        return False


def fast_ready():
    """The fast eyes loaded (and reloaded when a training put new ones in place)."""
    try:
        if not FAST.exists() or not FAST_NAMES.exists(): return False
        if _F["sess"] is None or FAST.stat().st_mtime > _F["mtime"] + 1:
            if time.time() - _F["tried"] < 60 and _F["sess"] is None: return False
            _F["tried"] = time.time()
            import trt_engine
            _F["sess"] = trt_engine.make_session(FAST, threads=2)
            _F["names"] = {int(k): v for k, v in json.loads(FAST_NAMES.read_text(encoding="utf-8")).items()}
            _F["mtime"] = FAST.stat().st_mtime
        return _F["sess"] is not None
    except Exception:
        _F["sess"] = None
        return False


def ready():
    """Loaded (and reloaded when the trainer put better eyes in place)."""
    if _S["sess"] is not None and ONNX.exists() and ONNX.stat().st_mtime > _S.get("mtime", 0) + 1:
        _load()
    return _S["sess"] is not None


# ------------------------------------------------------------------ the arena box on this screen
def _saved_arena(frame_shape):
    h, w = frame_shape[:2]
    try:
        data = json.loads(CALIB.read_text(encoding="utf-8"))
        if data["size"] == [w, h]:
            x0, y0, x1, y1 = map(float, data["box"])
            if 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h:
                return (x0, y0, x1, y1)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def arena_box(frame_shape):
    """(x0, y0, x1, y1) pixels of the arena in the game picture: calibrated from the towers, else the tile grid."""
    h, w = frame_shape[:2]
    saved = _saved_arena(frame_shape)
    if saved is not None:
        return saved
    # the tile grid of the 720x1280 game (royale.vision): 18 x 32 tiles from x 52, from y 1280-296 upward
    sx, sy = w / 720.0, h / 1280.0
    return (52 * sx, (984 - 32 * 27.6) * sy, (52 + 18 * 34) * sx, 984 * sy)


def _calibrate(frame_shape, box, dets):
    """Four princess towers seen: the box that puts them where the model expects them (SPEC_QUEENS) -> remembered."""
    import numpy as np
    q = [((d[2] + d[4]) / 2, (d[3] + d[5]) / 2) for d in dets if d[0] == "queen-tower" and d[1] >= 0.7]
    if len(q) != 4: return False
    q.sort(key=lambda p: (p[1] > np.median([pp[1] for pp in q]), p[0]))      # top-left, top-right, bottom-left, -right
    xs = [p[0] for p in q]; ys = [p[1] for p in q]
    # display coordinates of the towers -> a linear map from the spec: x = x0 + sx * spec_x
    sx = ((xs[1] - xs[0]) + (xs[3] - xs[2])) / 2 / (SPEC_QUEENS[1][0] - SPEC_QUEENS[0][0])
    sy = ((ys[2] - ys[0]) + (ys[3] - ys[1])) / 2 / (SPEC_QUEENS[2][1] - SPEC_QUEENS[0][1])
    x0 = sum(xs[i] - sx * SPEC_QUEENS[i][0] for i in range(4)) / 4
    y0 = sum(ys[i] - sy * SPEC_QUEENS[i][1] for i in range(4)) / 4
    new = [x0, y0, x0 + sx * W, y0 + sy * H]
    h, w = frame_shape[:2]
    if not (0.5 < sx / max(1e-6, sy) < 2.0) or new[2] - new[0] < w * 0.5: return False
    DIR.mkdir(parents=True, exist_ok=True)
    new = [max(0, new[0]), max(0, new[1]), min(w, new[2]), min(h, new[3])]
    if not (new[0] < new[2] and new[1] < new[3]): return False
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(dir=CALIB.parent, delete=False) as tmp:
        path = Path(tmp.name)
        try:
            tmp.write(json.dumps({"size": [w, h], "box": new, "t": time.time()}).encode("utf-8"))
            tmp.close()
            path.replace(CALIB)
        finally:
            path.unlink(missing_ok=True)
    return True


# ------------------------------------------------------------------ in the background
# The big model takes 50 ms on a graphics card but up to a second on the processor: it never holds the battle up.
# The game loop hands it the newest picture (submit) and takes whatever it saw last (latest); the fast eyes
# (royale.vision, ~70 ms) answer every look in the meantime.
_A = {"frame": None, "dets": [], "t": 0.0, "sub_t": 0.0, "ms": 0.0, "thread": None, "ev": threading.Event()}


def submit(frame_rgb):
    _A["sub_t"] = time.monotonic()
    _A["frame"] = frame_rgb
    _A["ev"].set()
    if _A["thread"] is None or not _A["thread"].is_alive():
        def work():
            while True:
                _A["ev"].wait(5.0)
                _A["ev"].clear()
                fr, _A["frame"], sub_t = _A["frame"], None, _A.get("sub_t") or time.monotonic()
                if fr is None: continue
                t0 = time.monotonic()
                try:
                    d = detect(fr)
                except Exception:
                    d = []
                _A["dets"], _A["t"] = d, sub_t                  # exact moment the picture was submitted
                _A["seen"] = (fr, d)                            # the picture with what was found in it (royale.frames)
                _A["ms"] = (time.monotonic() - t0) * 1000
        _A["thread"] = threading.Thread(target=work, daemon=True, name="cr-strong-eyes-run")
        _A["thread"].start()


SYNC_MS = 28.0          # the big model answers this fast (graphics card): it looks at the very picture being decided on


def look_now(frame_rgb):
    """The big model's detections for THIS picture when it is fast enough (same moment as the decision: positions
    are exact, no 0.6 s old answer); otherwise in the background, its answer at most 0.35 s old (5.83)."""
    ms = _A.get("ms") or 0.0
    if not (0 < ms <= SYNC_MS) and fast_ready() and (_F["ms"] == 0 or _F["ms"] <= SYNC_MS * 1.6):
        # 6.9.18: the big model is too slow for this very picture — the fast eyes look at it now (same moment); the
        # big one keeps looking in the background (health bars, spells)
        t0 = time.monotonic()
        try:
            d = detect(frame_rgb, state=_F)
        except Exception:
            _A.update(sync=False, fast=False)
            submit(frame_rgb)
            return []
        _F["ms"] = (time.monotonic() - t0) * 1000 if not _F["ms"] else 0.8 * _F["ms"] + 0.2 * (time.monotonic() - t0) * 1000
        _A["sync"] = True
        _A["fast"] = True
        submit(frame_rgb)
        return d
    _A["fast"] = False
    if 0 < ms <= SYNC_MS:
        t0 = time.monotonic()
        try:
            d = detect(frame_rgb)
        except Exception:
            _A.update(sync=False, fast=False)
            submit(frame_rgb)
            return []
        _A["dets"], _A["t"], _A["seen"] = d, t0, (frame_rgb, d)
        _A["ms"] = 0.8 * ms + 0.2 * (time.monotonic() - t0) * 1000
        _A["sync"] = True
        return d
    _A["sync"] = False
    submit(frame_rgb)
    # 6.9.15: on a slow card / the processor its answer is older than 0.35 s every time — it was thrown away and no
    # box was drawn; an answer up to 1.5x its own time old is used (the tracker moves each unit on its speed)
    return latest(max(0.35, min(1.6, 1.5 * (ms or 0) / 1000.0)))


def same_moment():
    return bool(_A.get("sync"))


def latest(max_age=0.6):
    """What the big model saw in a picture at most max_age seconds old, else []."""
    return _A["dets"] if time.monotonic() - _A["t"] <= max_age else []


def last_seen():
    """(picture, detections) of the big model's last look, or None."""
    return _A.get("seen")


def speed_ms():
    return _A["ms"]


def _recover_sess(st, s):
    """Rebuild a failed GPU session (e.g. DirectML 887A0005), falling back briefly to CPU if needed."""
    import onnxruntime as ort
    import trt_engine
    model_path = getattr(s, "path", None) or (FAST if st is _F else ONNX)
    try:
        ns = trt_engine.make_session(model_path, threads=2)
        if getattr(ns, "kind", "cpu") != "cpu":
            st["sess"] = ns
            st["cpu_until"] = 0.0
            return ns
    except Exception:
        pass
    so = ort.SessionOptions()
    so.intra_op_num_threads = max(2, (os.cpu_count() or 4) // 2)
    ns = ort.InferenceSession(str(model_path), sess_options=so, providers=["CPUExecutionProvider"])
    st["sess"] = ns
    st["cpu_until"] = time.monotonic() + 60.0
    st["error"] = "gpu suspended — temporary CPU fallback"
    return ns


def _run_sess(st, s, x):
    """Run one inference tensor, recovering once on GPU error instead of crashing or returning empty forever."""
    if st.get("cpu_until") and time.monotonic() >= st["cpu_until"]:
        st["cpu_until"] = time.monotonic() + 60.0
        try:
            import trt_engine
            ns = trt_engine.make_session(getattr(s, "path", None) or (FAST if st is _F else ONNX), threads=2)
            if getattr(ns, "kind", "cpu") != "cpu":
                st["sess"] = s = ns
                st["cpu_until"] = 0.0
                st["error"] = ""
        except Exception:
            pass
    try:
        if getattr(s, "kind", "dml") == "dml":
            with _LOCK:
                return s.run(None, {s.get_inputs()[0].name: x})[0][0]
        return s.run(None, {s.get_inputs()[0].name: x})[0][0]
    except Exception:
        ns = _recover_sess(st, s)
        if getattr(ns, "kind", "dml") == "dml":
            with _LOCK:
                return ns.run(None, {ns.get_inputs()[0].name: x})[0][0]
        return ns.run(None, {ns.get_inputs()[0].name: x})[0][0]


# ------------------------------------------------------------------ one look
def detect(frame_rgb, conf=0.45, state=None):      # 6.8: 0.35 let skins / sparks through
    """-> [(model_name, conf, x0, y0, x1, y1)] in the game picture's pixels, or [] when not ready.
    state: the model to use (_S the big eyes — the default — or _F the fast eyes: the same output format)."""
    import cv2, numpy as np
    st = state or _S
    s = st["sess"]
    if s is None: return []
    x0, y0, x1, y1 = arena_box(frame_rgb.shape)
    hh, ww = frame_rgb.shape[:2]
    xa, ya, xb, yb = max(0, int(x0)), max(0, int(y0)), min(ww, int(x1)), min(hh, int(y1))
    crop = frame_rgb[ya:yb, xa:xb]
    if crop.size == 0: return []
    arena = cv2.resize(crop, (W, H), interpolation=cv2.INTER_AREA)
    # letterbox into the model's square input (800 for the shipped eyes; a model trained on this PC may be 960)
    try: S = int(s.get_inputs()[0].shape[2])
    except (TypeError, ValueError, IndexError): S = 800
    k = S / max(W, H)
    nw, nh = int(round(W * k)), int(round(H * k))
    img = np.full((S, S, 3), 114, np.uint8)
    px, py = (S - nw) // 2, (S - nh) // 2
    img[py:py + nh, px:px + nw] = cv2.resize(arena, (nw, nh), interpolation=cv2.INTER_LINEAR)
    x = img.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
    out = _run_sess(st, s, x)
    out = out.T
    scores = out[:, 4:]
    cls = scores.argmax(1)
    cf = scores[np.arange(len(cls)), cls]
    keep = cf >= conf
    if not keep.any(): return []
    b = out[keep, :4]; cls = cls[keep]; cf = cf[keep]
    xyxy = np.stack([b[:, 0] - b[:, 2] / 2, b[:, 1] - b[:, 3] / 2, b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2], 1)
    rects = [[float(a), float(c), float(e - a), float(f - c)] for a, c, e, f in xyxy]
    idx = cv2.dnn.NMSBoxes(rects, cf.tolist(), conf, 0.5)
    idx = np.array(idx).reshape(-1) if len(idx) else []
    sx, sy = (xb - xa) / W, (yb - ya) / H
    dets = []
    names = st["names"] or {}
    for i in idx:
        a, c, e, f = xyxy[i]
        a, e = (a - px) / k, (e - px) / k                                  # model input -> arena 568x896
        c, f = (c - py) / k, (f - py) / k
        dets.append((names.get(int(cls[i]), str(int(cls[i]))), float(cf[i]),
                     xa + a * sx, ya + c * sy, xa + e * sx, ya + f * sy))
    try:
        calibrated = time.time() - CALIB.stat().st_mtime <= 3600 and _saved_arena(frame_rgb.shape) is not None
    except OSError:
        calibrated = False
    if not calibrated:
        try: _calibrate(frame_rgb.shape, (x0, y0, x1, y1), dets)
        except Exception: pass
    return dets
