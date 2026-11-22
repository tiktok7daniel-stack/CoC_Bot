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

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")   # less fragmented card memory
HOME = Path.home() / ".CoC_Bot"
ROOT = HOME / "royale_train"
DATA = ROOT / "data"
STATUS = ROOT / "status.json"
MODELS = HOME / "models"
HF = "https://huggingface.co"
REPO = "SudhishNeel/clash-royale-detection"
BASE_PT_URL = "https://huggingface.co/SudhishNeel/clash-royale-detector/resolve/main/v8/best.pt"
RECIPE = 5                    # 5.98: + 2 Roboflow sets, generated pictures layered — a new recipe trains again at once
DEFAULT_ROBOFLOW = ["yolotrain-c7s7v/clash-royale-ut3g8/4", "clashroyale/clash-royale-of3d3/3",
                    "angelfire/clash-royale-cylln/5", "clash-pxdrz/clash_grid", "dampiix/clash-royale-units",
                    "nathan-yan/clash-royale-detection-cysig/7",
                    "test-0hg7f/clash-royal-cujfo", "cla-09vin/clash-royale-cylln-pb9jx/5",   # the user's finds (5.98)
                    # the biggest Clash Royale arena sets on Roboflow Universe (all CC BY 4.0, 5.99)
                    "clash-royale-swwaz/cr-ai/2", "clashiqcarddeployments/clashiq-arena-tvanj/1",
                    "clashiqcarddeployments/clashiq-detection-lh8rf/1", "bruce-zheng/clash-royale-recognition/1",
                    "clash-royale-data-collection/clash-royale-bhjq1/2", "autoclashroyale/clashroyalechardetector/7",
                    "roham-n24-gmail-com/clash-royale-object-detection-jg666/1"]


def status(**kw):
    ROOT.mkdir(parents=True, exist_ok=True)
    try: d = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError): d = {}
    d.update(kw, t=time.time())
    STATUS.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


def data_note(name, n, note=""):
    """One data source's result for the app (6.01): how many pictures it gave, or why none."""
    d = read_status().get("data") or {}
    d[name] = {"n": int(n), "note": str(note)[:120]}
    status(data=d)


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


def norm_rf(name):
    """A Roboflow set's class name -> the base model's spelling: the side some sets put in the name ("Ally Goblin",
    "Enemy Goblin", "archer0" / "archer1") and their numbering ("-evolution1") are dropped (5.99)."""
    import re
    n = norm(name)
    n = re.sub(r"^(ally|enemy|friendly|opponent|blue|red)-", "", n)
    n = re.sub(r"(?<=[a-z])[01]$", "", n)                 # archer0 / archer1 -> archer
    n = re.sub(r"(-evolution|-evo|-hero)\d+$", r"\1", n)
    n = n.replace("-evo", "-evolution") if n.endswith("-evo") else n
    return n


def _dhash(img_bytes):
    """64-bit picture fingerprint (a Roboflow copy of a test picture is recognised and left out)."""
    import cv2, numpy as np
    im = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if im is None: return None
    s = cv2.resize(im, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (s[:, 1:] > s[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def _test_hashes():
    out = []
    for f in (DATA / "images" / "val").glob("*"):
        try:
            h = _dhash(f.read_bytes())
            if h is not None: out.append(h)
        except OSError:
            pass
    return out


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
    """The test set holds only real pictures labelled by hand (KataCR's real arenas, SudhishNeel's frames), chosen
    by the picture's name so it never changes between trainings and is never trained on. Generated pictures and the
    bot's own (labelled by a model) are always for training: a test on them would flatter the model (5.82)."""
    import zlib
    if name.startswith(("kcrsyn_", "own_", "rf_")): return "train"
    return "val" if zlib.crc32(name.encode()) % 100 < 12 else "train"


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


_hf_total = [0]


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
        _hf_total[0] += n
        data_note("SudhishNeel (HuggingFace)", _hf_total[0])


def take_roboflow(names, key, datasets):
    """Every Roboflow dataset ("workspace/project/version") in YOLOv8 format, names mapped to the base's."""
    if not key:
        data_note("Roboflow", 0, "no Roboflow key (Advanced settings / Bot)")
        return 0
    import requests
    idx = {norm(v): k for k, v in names.items()}
    total, skipped = 0, 0
    test_h = _test_hashes()                                    # KataCR's test pictures are in place first
    for ds in datasets:
        try:
            parts = ds.strip("/").split("/")
            ws, proj = parts[0], parts[1]
            ver = parts[2] if len(parts) > 2 else None
            if not ver:                                   # no version given: the project's newest one
                pj = requests.get(f"https://api.roboflow.com/{ws}/{proj}", params={"api_key": key}, timeout=60).json()
                vs = [str(v.get("id", "")).rsplit("/", 1)[-1] for v in (pj.get("versions") or []) if isinstance(v, dict)]
                vs = [v for v in vs if v.isdigit()]
                pv = (pj.get("project") or {}).get("versions")
                if not vs and isinstance(pv, int) and pv > 0: vs = [str(pv)]      # the project says how many
                if not vs: log(f"Roboflow {ds}: no version ({str(pj)[:120]})"); continue
                ver = str(max(map(int, vs)))
            status(stage="data_roboflow", note=f"{ws}/{proj}/{ver}")
            info = requests.get(f"https://api.roboflow.com/{ws}/{proj}/{ver}/yolov8", params={"api_key": key},
                                timeout=120).json()
            if isinstance(info.get("error"), dict):                # that version is gone: the project's newest
                pj = requests.get(f"https://api.roboflow.com/{ws}/{proj}", params={"api_key": key}, timeout=60).json()
                pv = (pj.get("project") or {}).get("versions")
                vs = [str(v.get("id", "")).rsplit("/", 1)[-1] for v in (pj.get("versions") or []) if isinstance(v, dict)]
                vs = [int(v) for v in vs if v.isdigit()] or ([pv] if isinstance(pv, int) and pv > 0 else [])
                if vs and str(max(vs)) != ver:
                    ver = str(max(vs))
                    info = requests.get(f"https://api.roboflow.com/{ws}/{proj}/{ver}/yolov8", params={"api_key": key},
                                        timeout=120).json()
            for _w in range(40):                                   # Roboflow may still be making the file (~10 min)
                if (info.get("export") or {}).get("link") or "progress" not in info: break
                status(stage="data_roboflow", note=f"{ws}/{proj}/{ver}: Roboflow prepares it ({info.get('progress')})")
                time.sleep(15)
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
            remap = {i: idx.get(norm(n), idx.get(norm_rf(n))) for i, n in enumerate(rf_names)}
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
                hv = _dhash(z.read(img_name))
                if hv is not None and any(bin(hv ^ t).count("1") <= 4 for t in test_h):
                    skipped += 1
                    continue                                   # a copy of a test picture: never trained on
                tag = f"rf_{proj}_{stem}"
                sp = _split(tag)
                (DATA / "images" / sp).mkdir(parents=True, exist_ok=True)
                (DATA / "labels" / sp).mkdir(parents=True, exist_ok=True)
                (DATA / "images" / sp / f"{tag}{Path(img_name).suffix}").write_bytes(z.read(img_name))
                (DATA / "labels" / sp / f"{tag}.txt").write_text(
                    "\n".join(f"{c} {x:.6f} {y:.6f} {w:.6f} {h:.6f}" for c, x, y, w, h in rows), encoding="utf-8")
                n += 1
            total += n
            log(f"Roboflow {ds}: {n} pictures kept (classes matched: {sum(v is not None for v in remap.values())}/{len(remap)}"
                f"; copies of test pictures left out so far: {skipped})")
            data_note(f"Roboflow {ws}/{proj}", n, f"{sum(v is not None for v in remap.values())}/{len(remap)} kinds")
        except Exception as e:
            log(f"Roboflow {ds}: {type(e).__name__}: {e}")
            data_note(f"Roboflow {ds}", 0, f"{type(e).__name__}: {e}")
    return total


# ------------------------------------------------------------------ 3-5. train, test, use
KATACR_ZIP = "https://codeload.github.com/wty-yy/Clash-Royale-Detection-Dataset/zip/refs/heads/master"   # (6.2: was main -> 404)


def take_katacr(names, n_real=8000, n_synth=8000):
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
    jpgs.sort()                                   # a fixed order: the same real pictures are the test every time
    random.Random(11).shuffle(jpgs)

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
        plan = []
        for _ in range(random.randint(4, 14)):
            c = random.choice(list(sprites))
            sp = cv2.imdecode(np.frombuffer(z.read(random.choice(sprites[c])), np.uint8), cv2.IMREAD_UNCHANGED)
            if sp is None or sp.ndim != 3 or sp.shape[2] != 4: continue
            if random.random() < 0.5: sp = sp[:, ::-1]
            sh, sw = sp.shape[:2]
            if sw >= w * 0.6 or sh >= h * 0.4: continue
            for _try in range(6):                     # not on top of another unit (a hidden unit is a wrong label)
                x0 = random.randint(0, w - sw); y0 = random.randint(int(h * 0.05), max(int(h * 0.05) + 1, h - sh - int(h * 0.05)))
                if all(x0 + sw * 0.7 < bx0 or bx1 < x0 + sw * 0.3 or y0 + sh * 0.7 < by0 or by1 < y0 + sh * 0.3
                       for _c, bx0, by0, bx1, by1 in boxes): break
            else:
                continue
            boxes.append((c, x0, y0, x0 + sw, y0 + sh))
            plan.append((y0 + sh, c, sp, x0, y0))
        boxes = boxes[:len(boxes) - len(plan)]
        for _bottom, c, sp, x0, y0 in sorted(plan, key=lambda q: q[0]):   # back to front, as the game draws
            sh, sw = sp.shape[:2]
            a = sp[:, :, 3:4].astype(np.float32) / 255.0
            roi = img[y0:y0 + sh, x0:x0 + sw].astype(np.float32)
            img[y0:y0 + sh, x0:x0 + sw] = (roi * (1 - a) + sp[:, :, :3].astype(np.float32) * a).astype(np.uint8)
            boxes.append((c, x0, y0, x0 + sw, y0 + sh))
        ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok:
            _write(enc.tobytes(), ".jpg", boxes, w, h, f"kcrsyn_{i}")
            made += 1
    log(f"KataCR: {n} real labelled pictures + {made} generated ones")
    data_note("KataCR", n + made, f"{n} real + {made} generated")
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
        rows = [(ids[b[0]], b[2], b[3], b[4], b[5]) for b in boxes if b[0] in ids and float(b[1]) >= 0.6]
        if len(rows) < 3: continue
        _write(img.read_bytes(), ".jpg", rows, 568, 896, f"own_{js.stem}")
        n += 1
    log(f"This PC's own battles: {n} pictures")
    data_note("My battles", n)
    return n


def run(epochs=30, n_bulk=4):
    random.seed(7)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    if not os.environ.get("CF_TRAIN_SAFE"): status(stage="start", started=time.time(), error="", data={})
    status(recipe=RECIPE)
    if not tools(): return False
    fix_nms()
    from ultralytics import YOLO
    import settings
    base = base_model()
    names = {int(k): v for k, v in YOLO(str(base)).names.items()}
    SAFE = bool(os.environ.get("CF_TRAIN_SAFE"))
    if SAFE and (DATA / "images" / "train").exists():
        log("safe mode (after a graphics-card error): the data downloaded before is used, no cuDNN, no AMP, "
            "half the pictures a step")
    else:
        _prepare_data(names, n_bulk)
    _after_data(names, epochs, SAFE)


def _prepare_data(names, n_bulk):
    import settings
    take_hf(names, n_bulk)
    app = settings.load_app()
    acc_cfg = {}
    try: acc_cfg = (settings.load(sys.argv[2] if len(sys.argv) > 2 else "main") or {}).get("royale", {})
    except Exception: pass
    try:
        take_katacr(names)                                     # first: its real pictures make the honest test
    except Exception as e:
        log(f"take_katacr skipped: {e}")
    sets = list(dict.fromkeys(list(acc_cfg.get("roboflow_datasets") or []) + DEFAULT_ROBOFLOW))
    take_roboflow(names, (app.get("roboflow_api_key") or "").strip(), sets)
    for take in (take_own,):
        try:
            take(names)
        except Exception as e:
            log(f"{take.__name__} skipped: {e}")


def _restart_safe(why):
    """A graphics-card error (cuDNN EXECUTION_FAILED, an illegal memory access) breaks the whole CUDA context of
    this process: nothing more can run on the card here. A fresh process takes over in safe mode (6.2)."""
    import subprocess
    if os.environ.get("CF_TRAIN_SAFE"):
        log(f"the graphics card failed again in safe mode ({why}) — stopped; close other programs using the card "
            "(LDPlayer) and train again")
        status(stage="error", error=f"graphics card: {why}"[:300])
        os._exit(1)
    log(f"graphics-card error ({why}) — starting again in a new process, in safe mode")
    status(stage="queued", note="restarting in safe mode")
    env = dict(os.environ, CF_TRAIN_SAFE="1", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")
    kw = {"creationflags": 0x00000010 | 0x00000020} if sys.platform == "win32" else {}
    subprocess.Popen([sys.executable, "-m", "royale.trainer", *sys.argv[1:]],
                     cwd=str(Path(__file__).resolve().parent.parent), env=env, **kw)
    os._exit(0)


def _after_data(names, epochs, SAFE):
    from ultralytics import YOLO
    base = base_model()
    yaml_p = ROOT / "data.yaml"
    yaml_p.write_text(json.dumps({"path": str(DATA), "train": "images/train", "val": "images/val",
                                  "names": {k: v for k, v in names.items()}}), encoding="utf-8")
    n_train = len(list((DATA / "images" / "train").glob("*")))
    log(f"Data ready: {n_train} training pictures")
    status(stage="test_base", pictures=n_train)
    m0 = YOLO(str(base)).val(data=str(yaml_p), imgsz=800, batch=8, device=0, verbose=False, plots=False)
    base_map = float(m0.box.map50)
    status(stage="train", base_map50=round(base_map, 4), note=f"{epochs} rounds on the graphics card")
    # a fixed small batch: the card is shared with LDPlayer and the bot's eyes ("all it can take" ran out of
    # memory -> cuDNN EXECUTION_FAILED); on a cuDNN error once more without cuDNN (slower, works)
    import torch
    # the card at full speed (6.3): cuDNN picks its fastest kernels (off only in safe mode)
    torch.backends.cudnn.benchmark = not SAFE
    if SAFE: torch.backends.cudnn.enabled = False
    _gpu_watch()
    base_m = float(m0.box.map)                                         # mAP50-95: boxes must also be tight
    cands = []
    # two candidates (5.82): the current eyes fine-tuned, and a newer, bigger architecture (YOLO11m, from its COCO
    # start) at a higher resolution — trained one after the other on the card; the honest test picks
    plans = [("finetune", str(base), 800, epochs), ("yolo11m", "yolo11m.pt", 960, max(epochs, 45))]
    for tag, start_w, imgsz, ep in plans:
        for attempt in range(1):
            try:
                m = YOLO(start_w)
                bs = max(2, _gpu_batch(imgsz) // 2) if SAFE else _gpu_batch(imgsz)
                log(f"{tag}: training — {ep} rounds, pictures {imgsz}px, {bs} at a time on the graphics card")
                # no test after every round (its last step ran on the processor while the card waited): the test runs
                # once at the end; every processor core but two prepares pictures so the card never waits (6.3)
                m.train(data=str(yaml_p), epochs=ep, imgsz=imgsz, batch=bs, val=False,
                        device=0, cos_lr=True, close_mosaic=max(3, ep // 6),
                        workers=max(2, min(12, (os.cpu_count() or 4) - 2)), project=str(ROOT / "runs"),
                        name=tag, exist_ok=True, plots=False, verbose=True, amp=not SAFE)
                break
            except Exception as e:
                if any(k in str(e).lower() for k in ("cudnn", "cuda error", "illegal memory", "out of memory",
                                                       "acceleratorerror", "cublas")):
                    _restart_safe(f"{type(e).__name__}: {str(e)[:80]}")
                log(f"{tag} skipped: {e}"); break
        best = ROOT / "runs" / tag / "weights" / "best.pt"
        if not best.exists():
            best = ROOT / "runs" / tag / "weights" / "last.pt"          # no test while training: the last one
        if not best.exists(): continue
        r = YOLO(str(best)).val(data=str(yaml_p), imgsz=imgsz, batch=8, device=0, verbose=False, plots=False)
        cands.append((float(r.box.map), float(r.box.map50), tag, best, imgsz))
        log(f"{tag}: mAP50-95 {cands[-1][0]:.3f}, mAP50 {cands[-1][1]:.3f} (imgsz {imgsz})")
        status(stage="train", note=f"{tag}: {cands[-1][1]:.3f}")
    if not cands:
        status(stage="done", used=False, error="no candidate trained", finished=time.time()); return False
    new_m, new_map, tag, best, imgsz = max(cands)
    log(f"Honest test (real hand-labelled pictures): base {base_map:.3f} / {base_m:.3f} -> {tag} {new_map:.3f} / {new_m:.3f}")
    used = new_m > base_m + 0.005
    if used:
        out = YOLO(str(best)).export(format="onnx", imgsz=imgsz, dynamic=False, simplify=False, opset=12)
        shutil.copy(best, MODELS / "cr_detector_trained.pt")
        os.replace(out, MODELS / "cr_detector_v8.onnx")
        (MODELS / "cr_detector_v8.json").write_text(json.dumps(names), encoding="utf-8")
        (MODELS / "cr_detector_v8.size").write_text(str(imgsz), encoding="utf-8")
    status(recipe=RECIPE)
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
    if st.get("finished") and time.time() - st["finished"] < 7 * 86400 and st.get("recipe") == RECIPE: return False
    if st.get("stage") == "error" and time.time() - st.get("t", 0) < 3 * 86400 and st.get("recipe") == RECIPE:
        return False                                             # not on every start (a new recipe tries at once)
    return True


def start(acc="main"):
    """Its own low-priority process (the bot keeps playing)."""
    import subprocess
    kw = {}
    if sys.platform == "win32":
        # its own window you can watch (every download, every round, the score) and full speed (6.02); the bot
        # keeps playing beside it
        kw["creationflags"] = 0x00000010 | 0x00000020          # a new console, normal priority
    py = sys.executable
    if py.lower().endswith("pythonw.exe"): py = py[:-len("pythonw.exe")] + "python.exe"
    here = Path(__file__).resolve().parent.parent
    subprocess.Popen([py, "-m", "royale.trainer", "--run", acc], cwd=str(here), **kw)
    status(stage="queued")
    return True


def _window_title(t):
    if sys.platform == "win32":
        try: __import__("ctypes").windll.kernel32.SetConsoleTitleW(t)
        except Exception: pass


def _gpu_watch():
    """Every 30 s in the training window: how busy the graphics card is and its memory (nvidia-smi) — so the
    user sees it really works (6.3)."""
    import subprocess, threading

    def run():
        while True:
            try:
                r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                                    "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10,
                                   creationflags=0x08000000 if sys.platform == "win32" else 0)
                u, mu, mt, tc = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
                print(f"   [graphics card] busy {u}% · memory {mu}/{mt} MB · {tc}°C", flush=True)
            except Exception:
                return
            time.sleep(30)
    threading.Thread(target=run, daemon=True, name="gpu-watch").start()


def _gpu_batch(imgsz):
    """As many pictures a step as the graphics card's free memory holds (6.02: was a fixed 6 / 4)."""
    try:
        import torch
        free, _total = torch.cuda.mem_get_info()
        per = 0.45 if imgsz <= 800 else 0.7               # GB a picture needs with AMP, about (YOLO m at that size)
        return int(max(4, min(48, (free / 1e9 - 0.8) / per)))
    except Exception:
        return 6 if imgsz <= 800 else 4


if __name__ == "__main__":
    if "--run" in sys.argv:
        _window_title("Clash Farmer — تدريب عيون كلاش رويال (اقفل الشباك ده = يوقف التدريب)")
        print("=" * 70)
        print("  Clash Farmer: training the Clash Royale eyes on this PC's graphics card")
        print("  every data source is downloaded, then two models train and the better one is kept")
        print("=" * 70, flush=True)
        try:
            run()
        except Exception as e:
            import traceback
            log(traceback.format_exc())
            status(stage="error", error=f"{type(e).__name__}: {e}"[:300])
        st = read_status()
        print("\n" + "=" * 70)
        print(f"  finished: {st.get('stage')} — accuracy {st.get('base_map50')} -> {st.get('new_map50')}"
              f" — {'NEW EYES IN USE' if st.get('used') else 'the old eyes stay'}")
        print("=" * 70, flush=True)
        try: input("  Enter = close this window")
        except Exception: pass
