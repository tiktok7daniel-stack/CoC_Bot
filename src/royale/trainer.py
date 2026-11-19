"""
Clash Royale eyes, trained on this PC by themselves (its NVIDIA card), from every open dataset that fits:

  1. the base      SudhishNeel's YOLOv8 arena detector (174 kinds) — the stronger eyes the bot already uses
  2. the data      SudhishNeel's real-arena frames (HuggingFace, parquet: 2,500 frames a part; the rare cards,
                   the spells and a share of the bulk parts) + every Roboflow Clash Royale dataset in the settings
                   (needs the user's own free Roboflow key: Bot settings -> Roboflow key; used only on this PC)
                   names unified to the base model's (dashes, evolutions / heroes kept when it has them, the rest
                   dropped); 5 % kept aside to test
  3. train         fine-tuned from the base on the card (CUDA torch: the bot installs it by itself, gpu_setup)
  4. test          base vs new on the same held-out frames (mAP50); the new one replaces the eyes ONLY when better
  5. tell          Telegram + the app (status file)

Runs in its own process (python -m royale.trainer), low priority, once a week at most (royale.auto_train).
State: ~/.CoC_Bot/royale_train/status.json
"""
import io, json, os, random, shutil, sys, time, zipfile
from pathlib import Path

HOME = Path.home() / ".CoC_Bot"
ROOT = HOME / "royale_train"
DATA = ROOT / "data"
STATUS = ROOT / "status.json"
MODELS = HOME / "models"
HF = "https://huggingface.co"
REPO = "SudhishNeel/clash-royale-detection"
BASE_PT_URL = "https://huggingface.co/SudhishNeel/clash-royale-detector/resolve/main/v8/best.pt"
DEFAULT_ROBOFLOW = ["yolotrain-c7s7v/clash-royale-ut3g8/4", "clashroyale/clash-royale-of3d3/3",
                    "angelfire/clash-royale-cylln/5", "clash-pxdrz/clash_grid/1", "dampiix/clash-royale-units/1",
                    "nathan-yan/clash-royale-detection-cysig/7"]


def status(**kw):
    ROOT.mkdir(parents=True, exist_ok=True)
    try: d = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError): d = {}
    d.update(kw, t=time.time())
    STATUS.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


def read_status():
    try: return json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def log(msg):
    ROOT.mkdir(parents=True, exist_ok=True)
    with open(ROOT / "train.log", "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    print(msg, flush=True)


def norm(name):
    return str(name).strip().lower().replace("_", "-").replace(" ", "-").replace("--", "-")


def _get(url, dst=None, **kw):
    import requests
    r = requests.get(url, stream=True, timeout=120, **kw)
    r.raise_for_status()
    if dst is None: return r
    tmp = Path(str(dst) + ".part")
    with open(tmp, "wb") as f:
        for c in r.iter_content(1 << 20): f.write(c)
    os.replace(tmp, dst)
    return dst


# ------------------------------------------------------------------ 1. tools + base
def tools():
    """CUDA torch (gpu_setup) + ultralytics without pulling a second (CPU) torch. -> True when it can train."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import gpu_setup
    gpu_setup.activate()
    try:
        import torch
        cuda = torch.cuda.is_available()
    except ImportError:
        cuda = False
    if not cuda:
        if gpu_setup.nvidia():
            status(stage="gpu_install", note="installing CUDA torch first (~2.5 GB, once)")
            if not gpu_setup.installing(): gpu_setup.start_install()
        else:
            status(stage="no_gpu", note="no NVIDIA card: training is too slow on the processor")
        return False
    try:
        import ultralytics  # noqa: F401
    except ImportError:
        import subprocess
        kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "ultralytics", "ultralytics-thop"], **kw)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "matplotlib", "pandas", "tqdm", "py-cpuinfo",
                        "pyarrow", "polars"], **kw)
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pyarrow"])
    return True


def fix_nms():
    """A CPU-only torchvision next to the CUDA torch has no CUDA 'nms' (the box clean-up after every look):
    it is run on the processor for those (tiny) inputs, the rest stays on the graphics card."""
    try:
        import torch, torchvision
        from torchvision import ops
        from torchvision.ops import boxes as _b
        try:
            ops.nms(torch.zeros((1, 4), device="cuda"), torch.zeros(1, device="cuda"), 0.5)
            return False                                          # it works on the card
        except Exception:
            pass
        orig = _b.nms

        def nms(b, sc, thr):
            if b.is_cuda:
                return orig(b.cpu(), sc.cpu(), thr).to(b.device)
            return orig(b, sc, thr)
        ops.nms = _b.nms = torchvision.ops.nms = nms
        try:
            import ultralytics.utils.nms as un
            if hasattr(un, "torchvision"): un.torchvision.ops.nms = nms
        except Exception:
            pass
        log("torchvision has no CUDA nms here: it runs on the processor (the rest on the card)")
        return True
    except Exception:
        return False


def base_model():
    MODELS.mkdir(parents=True, exist_ok=True)
    pt = MODELS / "cr_detector_v8.pt"
    if not pt.exists():
        _get(BASE_PT_URL, pt)
    return pt


# ------------------------------------------------------------------ 2. data
def _split(name):
    return "val" if random.random() < 0.05 else "train"


def _write(img_bytes, ext, boxes, iw, ih, stem):
    """boxes: [(cls_id, x0, y0, x1, y1) pixels] -> YOLO image + label."""
    sp = _split(stem)
    (DATA / "images" / sp).mkdir(parents=True, exist_ok=True)
    (DATA / "labels" / sp).mkdir(parents=True, exist_ok=True)
    (DATA / "images" / sp / f"{stem}{ext}").write_bytes(img_bytes)
    rows = []
    for c, x0, y0, x1, y1 in boxes:
        cx, cy, w, h = (x0 + x1) / 2 / iw, (y0 + y1) / 2 / ih, (x1 - x0) / iw, (y1 - y0) / ih
        if w > 0 and h > 0: rows.append(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    (DATA / "labels" / sp / f"{stem}.txt").write_text("\n".join(rows), encoding="utf-8")


def hf_parts(n_bulk=4):
    """The real-arena parquet parts to use: the rare-card and spell parts + the first n bulk parts."""
    import requests
    tree = requests.get(f"{HF}/api/datasets/{REPO}/tree/main/synthetic_arena", timeout=60).json()
    files = sorted(x["path"] for x in tree if x.get("path", "").endswith(".parquet"))
    rare = [f for f in files if "-b2-" in f or "-b3-" in f]
    first = [f for f in files if "train-0000" in f][:2]
    bulk = [f for f in files if "-c" in f.split("/")[-1]][:n_bulk]
    return rare + first + bulk


def take_hf(names, n_bulk=4):
    import pyarrow.parquet as pq
    idx = {norm(v): k for k, v in names.items()}
    done = set(read_status().get("hf_done", []))
    parts = hf_parts(n_bulk)
    for i, part in enumerate(parts):
        if part in done: continue
        status(stage="data_hf", note=f"SudhishNeel part {i + 1}/{len(parts)}")
        tmp = ROOT / "part.parquet"
        _get(f"{HF}/datasets/{REPO}/resolve/main/{part}", tmp)
        t = pq.read_table(tmp)
        try:                                              # its own class list (ids in the file) -> names
            md = json.loads(t.schema.metadata[b"huggingface"])
            cats = md["info"]["features"]["objects"]["feature"]["category"]["names"]
        except Exception:
            cats = None
        n = 0
        for row in t.to_pylist():
            img = row.get("image") or {}
            data = img.get("bytes") if isinstance(img, dict) else None
            objs = row.get("objects") or {}
            if not data or not objs: continue
            boxes = []
            for b, c in zip(objs.get("bbox") or [], objs.get("category") or []):
                if isinstance(c, int) and cats: c = cats[c] if c < len(cats) else ""
                k = idx.get(norm(c))
                if k is not None: boxes.append((k, *b))
            if not boxes: continue
            _write(data, ".jpg", boxes, 568, 896, f"hf_{row.get('image_id') or n}")
            n += 1
        tmp.unlink(missing_ok=True)
        done.add(part)
        status(hf_done=sorted(done))
        log(f"SudhishNeel {part}: {n} frames")


def take_roboflow(names, key, datasets):
    """Every Roboflow dataset ("workspace/project/version") in YOLOv8 format, names mapped to the base's."""
    if not key: return 0
    import requests
    idx = {norm(v): k for k, v in names.items()}
    total = 0
    for ds in datasets:
        try:
            ws, proj, ver = ds.strip("/").split("/")[:3]
            status(stage="data_roboflow", note=ds)
            info = requests.get(f"https://api.roboflow.com/{ws}/{proj}/{ver}/yolov8", params={"api_key": key},
                                timeout=120).json()
            link = (info.get("export") or {}).get("link")
            if not link:
                log(f"Roboflow {ds}: no export ({str(info)[:160]})"); continue
            z = zipfile.ZipFile(io.BytesIO(_get(link).content))
            import yaml
            yml = next((n for n in z.namelist() if n.endswith("data.yaml")), None)
            rf_names = yaml.safe_load(z.read(yml))["names"] if yml else []
            if isinstance(rf_names, dict): rf_names = [rf_names[k] for k in sorted(rf_names)]
            remap = {i: idx.get(norm(n)) for i, n in enumerate(rf_names)}
            n = 0
            for name in z.namelist():
                if "/labels/" not in name or not name.endswith(".txt"): continue
                stem = Path(name).stem
                img_name = next((c for c in (name.replace("/labels/", "/images/")[:-4] + e for e in (".jpg", ".png", ".jpeg"))
                                 if c in z.NameToInfo), None)
                if not img_name: continue
                rows = []
                for line in z.read(name).decode("utf-8", "ignore").splitlines():
                    p = line.split()
                    if len(p) == 5 and remap.get(int(float(p[0]))) is not None:
                        rows.append((remap[int(float(p[0]))], *map(float, p[1:])))
                if not rows: continue
                sp = _split(stem)
                (DATA / "images" / sp).mkdir(parents=True, exist_ok=True)
                (DATA / "labels" / sp).mkdir(parents=True, exist_ok=True)
                tag = f"rf_{proj}_{stem}"
                (DATA / "images" / sp / f"{tag}{Path(img_name).suffix}").write_bytes(z.read(img_name))
                (DATA / "labels" / sp / f"{tag}.txt").write_text(
                    "\n".join(f"{c} {x:.6f} {y:.6f} {w:.6f} {h:.6f}" for c, x, y, w, h in rows), encoding="utf-8")
                n += 1
            total += n
            log(f"Roboflow {ds}: {n} pictures kept (classes matched: {sum(v is not None for v in remap.values())}/{len(remap)})")
        except Exception as e:
            log(f"Roboflow {ds}: {type(e).__name__}: {e}")
    return total


# ------------------------------------------------------------------ 3-5. train, test, use
KATACR_ZIP = "https://codeload.github.com/wty-yy/Clash-Royale-Detection-Dataset/zip/refs/heads/main"


def take_katacr(names, n_real=3000, n_synth=3000):
    """KataCR's open dataset (wty-yy, MIT): ~7.4k real labelled arena pictures + 4.6k cut-out units of 154 kinds.
    The real ones are used as they are; the cut-outs are pasted onto real arenas in new places and mixes (the
    KataCR 'generative dataset' idea): thousands of new pictures with exact labels, every unit and evolution."""
    import io, re, zipfile
    import cv2, numpy as np
    z_p = ROOT / "katacr.zip"
    if not z_p.exists() or z_p.stat().st_size < 10_000_000:
        log("KataCR dataset: downloading (once, ~1-2 GB)")
        _get(KATACR_ZIP, z_p)
    z = zipfile.ZipFile(z_p)
    allf = z.namelist()
    yml = next((f for f in allf if f.endswith("images/part2/ClashRoyale_detection.yaml")), None)
    if not yml: log("KataCR: no class list"); return 0
    kc = {int(m.group(1)): m.group(2).strip() for m in re.finditer(r"^\s+(\d+):\s*(\S+)", z.read(yml).decode(), re.M)}
    ids = {norm(v): k for k, v in names.items()}
    remap = {k: ids.get(norm(v)) for k, v in kc.items()}
    log(f"KataCR: classes matched {sum(v is not None for v in remap.values())}/{len(remap)}")
    names_set = set(allf)
    jpgs = [f for f in allf if "/images/part2/" in f and f.endswith(".jpg") and (f[:-4] + ".txt") in names_set]
    random.shuffle(jpgs)

    def load(f):
        data = z.read(f)
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None: return None, None, []
        h, w = img.shape[:2]
        boxes = []
        for line in z.read(f[:-4] + ".txt").decode().splitlines():
            p = line.split()
            if len(p) < 5: continue
            c = remap.get(int(float(p[0])))
            if c is None: continue
            cx, cy, bw, bh = (float(x) for x in p[1:5])
            boxes.append((c, (cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h))
        return data, img, boxes
    n = 0
    for f in jpgs[:n_real]:
        data, img, boxes = load(f)
        if img is None or not boxes: continue
        _write(data, ".jpg", boxes, img.shape[1], img.shape[0], f"kcr_{n}")
        n += 1
    # the generator: cut-out units (PNG with transparency) pasted onto real arenas
    sprites = {}
    for f in allf:
        m = re.search(r"/images/segment/([^/]+)/[^/]+\.png$", f)
        if m and ids.get(norm(m.group(1))) is not None: sprites.setdefault(ids[norm(m.group(1))], []).append(f)
    made = 0
    pool = jpgs[n_real:] or jpgs
    for i in range(n_synth if sprites else 0):
        _d, img, boxes = load(random.choice(pool))
        if img is None: continue
        h, w = img.shape[:2]
        boxes = list(boxes)
        for _ in range(random.randint(4, 12)):
            c = random.choice(list(sprites))
            sp = cv2.imdecode(np.frombuffer(z.read(random.choice(sprites[c])), np.uint8), cv2.IMREAD_UNCHANGED)
            if sp is None or sp.ndim != 3 or sp.shape[2] != 4: continue
            if random.random() < 0.5: sp = sp[:, ::-1]
            sh, sw = sp.shape[:2]
            if sw >= w * 0.6 or sh >= h * 0.4: continue
            x0 = random.randint(0, w - sw); y0 = random.randint(int(h * 0.05), max(int(h * 0.05) + 1, h - sh - int(h * 0.05)))
            a = sp[:, :, 3:4].astype(np.float32) / 255.0
            roi = img[y0:y0 + sh, x0:x0 + sw].astype(np.float32)
            img[y0:y0 + sh, x0:x0 + sw] = (roi * (1 - a) + sp[:, :, :3].astype(np.float32) * a).astype(np.uint8)
            boxes.append((c, x0, y0, x0 + sw, y0 + sh))
        ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok:
            _write(enc.tobytes(), ".jpg", boxes, w, h, f"kcrsyn_{i}")
            made += 1
    log(f"KataCR: {n} real labelled pictures + {made} generated ones")
    return n + made


def take_own(names):
    """The bot's own battle pictures (royale.frames) with the sure detections of the big model as labels."""
    from royale import frames
    if not frames.DIR.exists(): return 0
    ids = {v: k for k, v in names.items()}
    n = 0
    for js in sorted(frames.DIR.glob("*.json")):
        img = js.with_suffix(".jpg")
        if not img.exists(): continue
        try:
            boxes = json.loads(js.read_text(encoding="utf-8")).get("boxes", [])
        except (OSError, ValueError):
            continue
        rows = [(ids[b[0]], b[2], b[3], b[4], b[5]) for b in boxes if b[0] in ids]
        if len(rows) < 3: continue
        _write(img.read_bytes(), ".jpg", rows, 568, 896, f"own_{js.stem}")
        n += 1
    log(f"This PC's own battles: {n} pictures")
    return n


def run(epochs=30, n_bulk=4):
    random.seed(7)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    status(stage="start", started=time.time(), error="")
    if not tools(): return False
    fix_nms()
    from ultralytics import YOLO
    import settings
    base = base_model()
    names = {int(k): v for k, v in YOLO(str(base)).names.items()}
    take_hf(names, n_bulk)
    app = settings.load_app()
    acc_cfg = {}
    try: acc_cfg = (settings.load(sys.argv[2] if len(sys.argv) > 2 else "main") or {}).get("royale", {})
    except Exception: pass
    take_roboflow(names, (app.get("roboflow_api_key") or "").strip(), acc_cfg.get("roboflow_datasets") or DEFAULT_ROBOFLOW)
    for take in (take_katacr, take_own):
        try:
            take(names)
        except Exception as e:
            log(f"{take.__name__} skipped: {e}")
    yaml_p = ROOT / "data.yaml"
    yaml_p.write_text(json.dumps({"path": str(DATA), "train": "images/train", "val": "images/val",
                                  "names": {k: v for k, v in names.items()}}), encoding="utf-8")
    n_train = len(list((DATA / "images" / "train").glob("*")))
    log(f"Data ready: {n_train} training pictures")
    status(stage="test_base", pictures=n_train)
    m0 = YOLO(str(base)).val(data=str(yaml_p), imgsz=800, batch=16, device=0, verbose=False, plots=False)
    base_map = float(m0.box.map50)
    status(stage="train", base_map50=round(base_map, 4), note=f"{epochs} rounds on the graphics card")
    # a fixed small batch: the card is shared with LDPlayer and the bot's eyes ("all it can take" ran out of
    # memory -> cuDNN EXECUTION_FAILED); on a cuDNN error once more without cuDNN (slower, works)
    import torch
    torch.backends.cudnn.benchmark = False
    for attempt in range(2):
        try:
            m = YOLO(str(base))
            m.train(data=str(yaml_p), epochs=epochs, imgsz=800, batch=6 if attempt == 0 else 4, device=0, patience=8,
                    workers=2, project=str(ROOT / "runs"), name="cr", exist_ok=True, plots=False, verbose=False,
                    amp=attempt == 0)
            break
        except RuntimeError as e:
            if attempt or "cudnn" not in str(e).lower(): raise
            log(f"cuDNN problem ({e}) — training again without cuDNN")
            torch.backends.cudnn.enabled = False
            torch.cuda.empty_cache()
    best = ROOT / "runs" / "cr" / "weights" / "best.pt"
    m1 = YOLO(str(best)).val(data=str(yaml_p), imgsz=800, batch=16, device=0, verbose=False, plots=False)
    new_map = float(m1.box.map50)
    log(f"Test (same held-out frames): base {base_map:.3f} -> new {new_map:.3f}")
    used = new_map > base_map + 0.005
    if used:
        out = YOLO(str(best)).export(format="onnx", imgsz=800, dynamic=False, simplify=False, opset=12)
        shutil.copy(best, MODELS / "cr_detector_trained.pt")
        os.replace(out, MODELS / "cr_detector_v8.onnx")
        (MODELS / "cr_detector_v8.json").write_text(json.dumps(names), encoding="utf-8")
    status(stage="done", base_map50=round(base_map, 4), new_map50=round(new_map, 4), used=used, finished=time.time())
    try:
        import utils
        utils.send_notification(("🧠 عيون كلاش رويال اتدربت على جهازك: الدقة " if used else "🧠 تدريب عيون كلاش رويال خلص: ")
                                + f"{base_map:.2f} ← {new_map:.2f}" + (" — الموديل الجديد اتركّب" if used else " — القديم أحسن، فضل زي ما هو"))
    except Exception:
        pass
    return used


def due(acc="main"):
    """Train now? (auto_train on, not running, not done in the last 7 days, not given up today)."""
    st = read_status()
    if st.get("stage") not in (None, "done", "error", "no_gpu", "gpu_install") and time.time() - st.get("t", 0) < 3 * 3600:
        return False                                             # one is running
    if st.get("stage") == "no_gpu" and time.time() - st.get("t", 0) < 7 * 86400: return False
    if st.get("finished") and time.time() - st["finished"] < 7 * 86400: return False
    if st.get("stage") == "error" and time.time() - st.get("t", 0) < 3 * 86400: return False   # not on every start
    return True


def start(acc="main"):
    """Its own low-priority process (the bot keeps playing)."""
    import subprocess
    kw = {}
    if sys.platform == "win32": kw["creationflags"] = 0x08000000 | 0x00004000          # no window, below normal
    py = sys.executable
    if py.lower().endswith("pythonw.exe"): py = py[:-len("pythonw.exe")] + "python.exe"
    here = Path(__file__).resolve().parent.parent
    subprocess.Popen([py, "-m", "royale.trainer", "--run", acc], cwd=str(here), **kw)
    status(stage="queued")
    return True


if __name__ == "__main__":
    if "--run" in sys.argv:
        try:
            run()
        except Exception as e:
            import traceback
            log(traceback.format_exc())
            status(stage="error", error=f"{type(e).__name__}: {e}"[:300])
