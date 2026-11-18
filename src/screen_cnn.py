"""
The bot's second brain for screens: a deep neural network (DINOv2-small, Meta AI, Apache-2.0) that turns a screen
into 768 numbers describing what is ON it — panels, buttons, icons — not just its colours. Screens are recognised
by the nearest labelled example (the method DINOv2 was made for: it needs few examples per kind and gets better with
every picture it collects).

  model      onnx-community/dinov2-small (int8, 24 MB): downloaded once in the background from HuggingFace
  examples   knowledge/model_cnn.json (the pictures Claude labelled; a copy ships in assets/screen_cnn.json)
             + what the bot collects itself while it plays (~/.CoC_Bot/learn/cnn_self_<account>.json):
             every screen the instant checks or the first brain are sure about, up to 40 per kind
  speed      ~0.2 s on the processor, a few ms with DirectML / CUDA — used when the first (1 ms) brain is not sure

classify(img) -> (kind, similarity) or (None, similarity)
"""
import base64, json, os, sys, threading, time
from pathlib import Path

MODEL = Path.home() / ".CoC_Bot" / "models" / "dinov2_small_int8.onnx"
URL = "https://huggingface.co/onnx-community/dinov2-small/resolve/main/onnx/model_quantized.onnx"
DIR = Path.home() / ".CoC_Bot" / "learn"
REPO_BANK = DIR / "model_cnn.json"
SURE, MARGIN = 0.90, 0.04        # similar enough, and clearly more like that kind than any other (tested: no wrong answers)
SELF_MAX = 40
VERSION = 1
_S = {"sess": None, "tried": 0.0, "dl": None, "bank": None, "labels": [], "t": 0.0, "error": "", "device": "cpu",
      "cache": (None, None, 0.0)}
_LOCK = threading.Lock()
_RATE = {}


# ---------------------------------------------------------------- the network
def download():
    if MODEL.exists() or (_S["dl"] and _S["dl"].is_alive()): return
    def work():
        try:
            import requests
            MODEL.parent.mkdir(parents=True, exist_ok=True)
            tmp = MODEL.with_name(f"{MODEL.name}.{os.getpid()}.part")
            with requests.get(URL, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for c in r.iter_content(1 << 20): f.write(c)
            os.replace(tmp, MODEL)
            _S["tried"] = 0.0
        except Exception as e:
            _S["error"] = f"download: {e}"[:200]
    _S["dl"] = threading.Thread(target=work, daemon=True, name="cnn-download")
    _S["dl"].start()


def _session():
    if _S["sess"] is not None: return _S["sess"]
    if time.time() - _S["tried"] < 300: return None
    with _LOCK:
        if _S["sess"] is not None: return _S["sess"]
        _S["tried"] = time.time()
        if not MODEL.exists():
            download()
            return None
        try:
            import onnxruntime as ort
            av = ort.get_available_providers()
            prov = [p for p in ("CUDAExecutionProvider", "DmlExecutionProvider") if p in av] + ["CPUExecutionProvider"]
            _S["sess"] = ort.InferenceSession(str(MODEL), providers=prov)
            _S["device"] = {"CUDAExecutionProvider": "cuda", "DmlExecutionProvider": "dml"}.get(_S["sess"].get_providers()[0], "cpu")
        except Exception as e:
            _S["error"] = str(e)[:200]
        return _S["sess"]


def ready():
    return _session() is not None


def embed(img):
    """RGB screen -> 768 numbers (unit length), or None while the network isn't there."""
    import cv2, numpy as np
    s = _session()
    if s is None: return None
    x = cv2.resize(img, (224, 224), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    x = ((x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32))
    h = s.run(None, {s.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0]
    v = np.concatenate([h[0], h[1:].mean(0)]).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def _pack(v):
    import numpy as np
    return base64.b64encode(np.asarray(v, np.float16).tobytes()).decode("ascii")


def _unpack(s):
    import numpy as np
    return np.frombuffer(base64.b64decode(s), np.float16).astype(np.float32)


# ---------------------------------------------------------------- the examples
def _bank_files():
    out = [REPO_BANK]
    for base in ([Path(sys._MEIPASS)] if hasattr(sys, "_MEIPASS") else []) + [Path(__file__).resolve().parent.parent]:
        out.append(base / "assets" / "screen_cnn.json")
    return out


def _self_path(id):
    return DIR / f"cnn_self_{''.join(c for c in str(id) if c.isalnum() or c in '-_') or 'main'}.json"


def load(id="main", force=False):
    import numpy as np
    if not force and _S["bank"] is not None and time.time() - _S["t"] < 60: return
    ex, labels = [], []
    for p in _bank_files():
        try: d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError): continue
        if d.get("version") != VERSION: continue
        for it in d.get("items", []): ex.append(_unpack(it["v"])); labels.append(it["rule"])
        break
    try:
        for it in json.loads(_self_path(id).read_text(encoding="utf-8")).get("items", []):
            ex.append(_unpack(it["v"])); labels.append(it["rule"])
    except (OSError, ValueError):
        pass
    _S.update(bank=np.array(ex) if ex else None, labels=labels, t=time.time())


def classify(img, id="main", v=None):
    """-> (screen kind, similarity) when sure, else (None, similarity). Same picture within a second: cached."""
    import numpy as np
    load(id)
    if _S["bank"] is None: return None, None
    key = (img.shape, int(img[::97, ::97].sum())) if v is None else None
    ck, cres, ct = _S["cache"]
    if key is not None and ck == key and time.time() - ct < 1.0: return cres
    if v is None: v = embed(img)
    if v is None or v.shape[0] != _S["bank"].shape[1]: return None, None
    sim = _S["bank"] @ v
    i = int(np.argmax(sim))
    best = _S["labels"][i]
    other = max((float(x) for x, l in zip(sim, _S["labels"]) if l != best), default=-1.0)
    res = ((best if sim[i] >= SURE and sim[i] - other >= MARGIN else None), float(sim[i]))
    if key is not None: _S["cache"] = (key, res, time.time())
    return res


def teach_self(id, img, label):
    """A screen the bot is sure about -> one more example (when it shows something new), at most every 2 minutes."""
    import numpy as np
    k = (id, label)
    if time.time() - _RATE.get(k, 0) < 120: return False
    _RATE[k] = time.time()
    try:
        v = embed(img)
        if v is None: return False
        load(id)
        if _S["bank"] is not None:
            same = [float(_S["bank"][i] @ v) for i, l in enumerate(_S["labels"]) if l == label]
            if same and max(same) > 0.985: return False                 # it knows this look already
        p = _self_path(id)
        try: d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError): d = {"version": VERSION, "items": []}
        mine = [it for it in d.get("items", []) if it["rule"] == label][-(SELF_MAX - 1):]
        d["items"] = [it for it in d.get("items", []) if it["rule"] != label] + mine + [{"rule": label, "v": _pack(v), "t": time.time()}]
        DIR.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d), encoding="utf-8")
        load(id, force=True)
        return True
    except Exception:
        return False


def info(id="main"):
    load(id)
    return {"ready": _S["sess"] is not None, "downloaded": MODEL.exists(), "device": _S["device"],
            "examples": len(_S["labels"]), "kinds": len(set(_S["labels"])), "error": _S["error"]}


def build(pairs):
    """pairs: [(rule, RGB picture)] -> bank dict (knowledge/model_cnn.json). Needs the network here."""
    return {"version": VERSION, "built": time.strftime("%Y-%m-%d %H:%M"), "sure": SURE,
            "items": [{"rule": r, "v": _pack(embed(img))} for r, img in pairs]}
