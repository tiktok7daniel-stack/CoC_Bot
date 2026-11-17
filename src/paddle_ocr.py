"""
The bot's text reader: PaddleOCR PP-OCRv6 (the newest PaddleOCR models, Apache-2.0) run with onnxruntime
through RapidOCR — no Paddle install, works on any Windows PC.

  small   ships with the program (in the rapidocr package): ~0.4-0.7 s a screen on the processor
  medium  the strongest model (reads the small numbers on the troop cards, the timers…): downloaded once in the
          background from PaddlePaddle's own page on HuggingFace (~140 MB) and used when there is a graphics card
          (DirectML: any card on Windows, or CUDA) — or always when the user picks "strongest" in the settings

Compared on the game's own screens: PP-OCRv6 reads "VICTORY", "Bonus", "Item delivered to the Temporary Storage",
"17426389" right where easyocr read "Vctony", "BONus", "[Eem delivered Lo Lhe", "WJ 426 383", and it is 3-6x faster.

read(frame) -> [(text, x1, y1, x2, y2, conf)] with fractions of the frame (same as utils.ocr_boxes).
"""
import json, os, threading, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "ocr_models" / "PP-OCRv6_medium"
HF = "https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_{}_onnx/resolve/main/{}"
FILES = (("det", "inference.onnx"), ("rec", "inference.onnx"), ("rec", "inference.yml"))
_S = {"engine": None, "kind": None, "device": "cpu", "error": "", "download": None, "lock": threading.Lock(),
      "ms": None, "tried": False}


def available():
    try:
        import rapidocr, onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def _device():
    """DirectML (any graphics card on Windows) or CUDA when onnxruntime has it, else the processor."""
    try:
        import onnxruntime as ort
        p = ort.get_available_providers()
    except Exception:
        return "cpu"
    if "CUDAExecutionProvider" in p: return "cuda"
    if "DmlExecutionProvider" in p: return "dml"
    return "cpu"


def _want():
    """small / medium: the settings ("ocr_model": auto / small / medium), auto = medium on a graphics card."""
    try:
        import settings
        m = settings.load_app().get("ocr_model", "auto")
    except Exception:
        m = "auto"
    if m in ("small", "medium"): return m
    return "medium" if _device() != "cpu" else "small"


def medium_ready():
    return all((DIR / k / f).exists() for k, f in FILES) and (DIR / "rec" / "keys.txt").exists()


def download_medium(progress=None):
    """The strongest model, once, in the background (resumes; the bot reads with the small one meanwhile)."""
    if medium_ready() or (_S["download"] and _S["download"].is_alive()): return
    def work():
        import requests
        try:
            for k, f in FILES:
                dst = DIR / k / f
                if dst.exists(): continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_suffix(dst.suffix + ".part")
                have = tmp.stat().st_size if tmp.exists() else 0
                with requests.get(HF.format(k, f), stream=True, timeout=60,
                                  headers={"Range": f"bytes={have}-"} if have else {}) as r:
                    if r.status_code not in (200, 206): raise RuntimeError(f"HTTP {r.status_code}")
                    with open(tmp, "ab" if r.status_code == 206 else "wb") as out:
                        for chunk in r.iter_content(1 << 20):
                            out.write(chunk)
                os.replace(tmp, dst)
            import yaml
            chars = yaml.safe_load((DIR / "rec" / "inference.yml").read_text(encoding="utf-8"))["PostProcess"]["character_dict"]
            (DIR / "rec" / "keys.txt").write_text("\n".join(chars), encoding="utf-8")
            _S["error"] = ""
            with _S["lock"]: _S["engine"], _S["tried"] = None, False      # switch to the strong one on the next read
            _log("Strongest text reader (PP-OCRv6 medium) downloaded")
        except Exception as e:
            _S["error"] = f"download: {e}"[:200]
    t = threading.Thread(target=work, daemon=True, name="ppocr-download")
    _S["download"] = t
    t.start()


def _log(msg):
    try:
        from utils import logger
        logger.info(msg)
    except Exception:
        pass


def engine():
    """The loaded reader (loads it the first time: ~1 s)."""
    e = _S["engine"]
    if e is not None: return e
    with _S["lock"]:
        if _S["engine"] is not None: return _S["engine"]
        from rapidocr import RapidOCR
        dev = _device()
        want = _want()
        if want == "medium" and not medium_ready():
            download_medium()
            want = "small"
        p = {"Global.log_level": "error", "Global.text_score": 0.2, "Global.use_cls": False,
             "EngineConfig.onnxruntime.use_cuda": dev == "cuda", "EngineConfig.onnxruntime.use_dml": dev == "dml"}
        if want == "medium":
            p.update({"Det.model_path": str(DIR / "det" / "inference.onnx"), "Rec.model_path": str(DIR / "rec" / "inference.onnx"),
                      "Rec.rec_keys_path": str(DIR / "rec" / "keys.txt")})
        try:
            e = RapidOCR(params=p)
        except Exception:
            if dev == "cpu" and want == "small": raise
            p.update({"EngineConfig.onnxruntime.use_cuda": False, "EngineConfig.onnxruntime.use_dml": False})
            dev = "cpu"
            e = RapidOCR(params=p)
        _S.update(engine=e, kind=want, device=dev)
        return e


def _prep(frame):
    """Small crops (a counter, one number): bigger + a margin around them, else the text detector misses them
    (tested: "2/5", the storage numbers came back empty without it). -> (picture, scale, pad)."""
    import cv2
    if frame.ndim == 2: frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
    elif frame.shape[2] == 4: frame = frame[..., :3]
    h, w = frame.shape[:2]
    if h >= 160 and w >= 240: return frame, 1.0, 0
    k = max(1.0, 96.0 / h)
    if k > 1: frame = cv2.resize(frame, (int(round(w * k)), int(round(h * k))), interpolation=cv2.INTER_CUBIC)
    pad = int(0.25 * frame.shape[0])
    return cv2.copyMakeBorder(frame, pad, pad, pad, pad, cv2.BORDER_REPLICATE), k, pad


def read(frame):
    """RGB (or grey) picture -> [(text, x1, y1, x2, y2, conf)] (fractions of the picture given)."""
    import re
    h, w = frame.shape[:2]
    img, k, pad = _prep(frame)
    t = time.time()
    r = engine()(img)
    _S["ms"] = round((time.time() - t) * 1000)
    out = []
    boxes, txts, scores = getattr(r, "boxes", None), getattr(r, "txts", None) or (), getattr(r, "scores", None) or ()
    if boxes is None: return out
    for pts, text, conf in zip(boxes, txts, scores):
        text = str(text).strip()
        if not text or not re.search(r"[A-Za-z0-9]", text): continue        # the game's text is latin / digits
        xs = [(p[0] - pad) / k for p in pts]
        ys = [(p[1] - pad) / k for p in pts]
        out.append((text, max(0.0, min(xs) / w), max(0.0, min(ys) / h), min(1.0, max(xs) / w), min(1.0, max(ys) / h),
                    float(conf)))
    return out


def install():
    """
    Source installs (an update only replaces the files): put the packages in by themselves, in the background,
    with the program's own Python. Windows: onnxruntime-directml (runs on any graphics card, and on the processor).
    -> True when started.
    """
    import subprocess, sys
    if getattr(sys, "frozen", False) or _S.get("installing"): return False
    rt = "onnxruntime-directml" if sys.platform == "win32" else "onnxruntime"
    py = sys.executable
    if py.lower().endswith("pythonw.exe"): py = py[:-len("pythonw.exe")] + "python.exe"
    _S["installing"] = True

    def work():
        try:
            kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}      # no black window
            r = subprocess.run([py, "-m", "pip", "install", "-q", "rapidocr>=3.10", rt, "pyyaml"], capture_output=True,
                               timeout=1800, **kw)
            if r.returncode == 0:
                import importlib
                importlib.invalidate_caches()
                _log("PaddleOCR installed — the strongest text reader is used from now on")
                warm_up()
            else:
                _S["error"] = "install: " + (r.stderr or b"").decode("utf-8", "ignore")[-200:]
        except Exception as e:
            _S["error"] = f"install: {e}"[:200]
        finally:
            _S["installing"] = False
    threading.Thread(target=work, daemon=True, name="ppocr-install").start()
    return True


def warm_up():
    """Load now (in the background) so the first look is instant; starts the strong model's download if wanted."""
    if not available():
        install()
        return False
    def work():
        t = time.time()
        try:
            engine()
            dev = {"cuda": "the graphics card (CUDA)", "dml": "the graphics card (DirectML)"}.get(_S["device"], "the processor")
            _log(f"Text reader ready: PaddleOCR PP-OCRv6 {_S['kind']} on {dev} ({time.time() - t:.1f}s)")
        except Exception as e:
            _S["error"] = str(e)[:200]
    threading.Thread(target=work, daemon=True, name="ppocr-warmup").start()
    return True


def info():
    """For the app."""
    return {"available": available(), "installing": bool(_S.get("installing")), "model": _S["kind"], "device": _S["device"], "ms": _S["ms"],
            "medium_ready": medium_ready(), "downloading": bool(_S["download"] and _S["download"].is_alive()),
            "error": _S["error"]}
