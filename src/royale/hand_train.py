"""
Training the hand-card model (6.6) on this PC's graphics card — the first step of "train the eyes" (royale.trainer),
~10-20 minutes on an RTX 4060. Also on its own: `python -m royale.hand_train`.

Data (every picture squashed to 128x128, the way royale.hand_classifier reads the hand):
  real       the Roboflow card sets — ~20.8k hand screenshots in 175 kinds with their evolution / hero looks
             (inspirasians-workspace/ddwgy) + ~8.7k (evgeny-9crvq/cards-clash-royale), class names mapped to the
             bot's card names; their own train / valid split is kept (the valid pictures = the honest test)
  made here  every card picture the bot has (assets/royale/cards: 139 cards + their _ev1 / _hero looks, and the
             pictures it cut from this account's own Info pages) in ~160 looks each: moved / zoomed a little, shrunk
             to the hand's real size and back (the next-card slot is much smaller), brighter / darker, blurred, JPEG,
             and 30% GREY + darker = the card when there is not enough elixir — so a grey card is read as well as a
             playable one
Model: YOLO11n-cls (1.5M weights: ~0.3 ms for the 5 slots in TensorRT), 30 rounds, no flips (cards are never
mirrored). Exported to ONNX with a batch of 5 (the 5 slots in one run) and used only when its accuracy on the real
test pictures is >= 95% and better than the model in use.
"""
import json, os, random, shutil, sys, time, zipfile, io
from pathlib import Path

# 6.9: no page-locked ("pinned") RAM for the picture loaders — on a laptop it ran out ("CUDA error: out of memory" in
# the pin-memory thread while the card itself used 0.8 GB). Read by ultralytics when it is first imported.
os.environ["PIN_MEMORY"] = "False"
# 6.9.10: ultralytics must not pip-install packages in the middle of a training (its ONNX export installed
# onnxruntime-gpu over the onnxruntime already loaded: "No module named onnxruntime.capi..." in the same process)
os.environ["YOLO_AUTOINSTALL"] = "False"

ROOT = Path.home() / ".CoC_Bot" / "royale_hand"
DATA = ROOT / "data"
IMGSZ = 128
SETS = ["inspirasians-workspace/ddwgy", "evgeny-9crvq/cards-clash-royale"]
PER_PICTURE = 160
LOOKS = ("_hero_ev1", "_ev1", "_hero")


def _log(msg):
    try:
        from royale import trainer
        trainer.log("hand cards: " + msg)
    except Exception:
        print(msg, flush=True)


def _status(**kw):
    try:
        from royale import trainer
        trainer.status(**kw)
    except Exception:
        pass


def bot_cards():
    """{label: [picture paths]} for every card picture the bot has (label = card + look)."""
    from royale.vision.constants import IMAGES_DIR
    from royale.vision.detectors.card_detector import USER_DIR
    out = {}
    for p in sorted(Path(IMAGES_DIR, "cards").glob("*.jpg")):
        out.setdefault(p.stem, []).append(p)
    if Path(USER_DIR).exists():
        for p in sorted(Path(USER_DIR).glob("*_user.jpg")):
            out.setdefault(p.stem[: -len("_user")], []).append(p)
    return out


def _key(s):
    return "".join(ch for ch in s.lower() if ch.isalnum())


def map_label(rf_name, known):
    """A Roboflow class ("archers-ev1", "Baby Dragon", "x-bow-evolution") -> the bot's label or None."""
    n = rf_name.strip().lower().replace(" ", "-")
    look = ""
    for suf, lk in (("-hero-ev1", "_hero_ev1"), ("-hero-evo", "_hero_ev1"), ("-ev1", "_ev1"), ("-evolution", "_ev1"),
                    ("-evo", "_ev1"), ("-hero", "_hero")):
        if n.endswith(suf):
            n, look = n[: -len(suf)], lk
            break
    base = known.get(_key(n))
    return (base + look) if base else None


def _squash(img):
    import cv2
    return cv2.resize(img, (IMGSZ, IMGSZ), interpolation=cv2.INTER_AREA)


def _save(img_rgb, path):
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])


def augment(img, rng):
    """One hand-like look of a card picture (RGB uint8)."""
    import cv2, numpy as np
    h, w = img.shape[:2]
    z = rng.uniform(0.88, 1.0)
    cw, ch = int(w * z), int(h * z)
    x0 = rng.randint(0, max(0, w - cw)); y0 = rng.randint(0, max(0, h - ch))
    out = img[y0:y0 + ch, x0:x0 + cw]
    # the hand's real size: ~117x147 at 720p (a hand slot), ~50x63 (the next-card slot), smaller screens
    tw = rng.choice([40, 50, 60, 80, 100, 117, 140])
    out = cv2.resize(out, (tw, int(tw * 147 / 117)), interpolation=cv2.INTER_AREA)
    out = out.astype(np.float32)
    if rng.random() < 0.30:                                  # not enough elixir: grey and darker
        g = out.mean(2, keepdims=True)
        out = (0.85 * g + 0.15 * out) * rng.uniform(0.55, 0.85)
    out = out * rng.uniform(0.75, 1.2) + rng.uniform(-18, 18)
    if rng.random() < 0.4:
        out = (out - out.mean()) * rng.uniform(0.8, 1.2) + out.mean()
    if rng.random() < 0.2:
        out = out + np.random.default_rng(rng.randint(0, 1 << 30)).normal(0, 5, out.shape)
    out = np.clip(out, 0, 255).astype(np.uint8)
    if rng.random() < 0.3:
        out = cv2.GaussianBlur(out, (3, 3), rng.uniform(0.3, 1.0))
    q = rng.randint(35, 95)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, q])
    if ok: out = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return _squash(out)


def make_synthetic(cards):
    import cv2
    rng = random.Random(11)
    n = 0
    for label, paths in cards.items():
        for p in paths:
            img = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)
            if img is None: continue
            for i in range(PER_PICTURE):
                sp = "val" if i % 10 == 0 else "train"
                _save(augment(img, rng), DATA / sp / label / f"syn_{p.stem}_{i}.jpg")
                n += 1
    return n


def take_roboflow(key, known):
    """The Roboflow card sets (folder format) -> real hand pictures; -> {"train": n, "val": n, "kinds": n, "skipped": [..]}"""
    import cv2, numpy as np
    from royale.trainer import rf_export, _get
    res = {"train": 0, "val": 0, "kinds": set(), "skipped": set()}
    if not key:
        _log("no Roboflow key — only the pictures made here (Advanced settings / Bot: the Roboflow key)")
        return res
    for ds in SETS:
        try:
            link, ws, proj, ver = rf_export(ds, key, "folder")
            if not link: continue
            from royale.trainer import fetch_zip, progress
            z = fetch_zip(link, f"rf_{ws}_{proj}_{ver}_folder", f"hand cards {ws}/{proj}/{ver}")
            n = 0
            names_all = z.namelist()
            for k_, name in enumerate(names_all):
                progress(f"hand cards {proj}", k_, len(names_all), 10000)
                parts = name.split("/")
                if len(parts) < 3 or not name.lower().endswith((".jpg", ".jpeg", ".png")): continue
                split, cls = parts[-3].lower(), parts[-2]
                label = map_label(cls, known)
                if not label:
                    res["skipped"].add(cls); continue
                img = cv2.imdecode(np.frombuffer(z.read(name), np.uint8), cv2.IMREAD_COLOR)
                if img is None: continue
                sp = "train" if split == "train" else "val"
                _save(_squash(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)), DATA / sp / label / f"rf_{proj}_{Path(name).stem}.jpg")
                res[sp] += 1; res["kinds"].add(label); n += 1
            _log(f"Roboflow {ws}/{proj}/{ver}: {n} card pictures")
        except Exception as e:
            _log(f"Roboflow {ds}: {type(e).__name__}: {e}")
    return res


def evaluate(onnx_path, classes, only=None, weights=None):
    """The honest test. 6.9.12: with PyTorch on the processor (the trained .pt, the same picture squashing as the bot)
    — it needs no onnxruntime, which was broken on the user's PC and failed this test three times. The ONNX file is
    exported with the same weights."""
    if weights is not None:
        return _evaluate_torch(weights, classes, only)
    return _evaluate(onnx_path, classes, only)


def _evaluate_torch(weights, classes, only=None):
    import cv2, numpy as np, torch
    from ultralytics import YOLO
    from royale.hand_classifier import split
    net = YOLO(str(weights)).model.float().cpu().eval()
    idx = {c: i for i, c in enumerate(classes)}
    xs, ys = [], []
    for d in sorted((DATA / "val").iterdir()):
        if d.name not in idx: continue
        for p in d.glob("*.jpg"):
            if only and not p.name.startswith(only + "_"): continue
            img = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)
            xs.append(_squash(img).transpose(2, 0, 1).astype(np.float32) / 255.0); ys.append(idx[d.name])
    if not xs: return None
    ok = ok_card = 0
    with torch.no_grad():
        for i in range(0, len(xs), 128):
            out = net(torch.from_numpy(np.stack(xs[i:i + 128])))
            out = out[0] if isinstance(out, (list, tuple)) else out
            for j, pj in enumerate(out.argmax(1).tolist()):
                t = ys[i + j]
                ok += int(pj == t)
                ok_card += int(split(classes[pj])[0] == split(classes[t])[0])
    return {"n": len(xs), "top1": ok / len(xs), "card": ok_card / len(xs)}


def _evaluate(onnx_path, classes, only=None):
    """Top-1 (card AND look, and the card alone) of the exported model on the test pictures, read exactly the way the
    bot reads the hand (royale.hand_classifier squashing, the same session). only: "rf" / "syn" / None."""
    import cv2, numpy as np
    import trt_engine
    from royale.hand_classifier import split
    s = trt_engine.make_session(onnx_path)
    b = s.get_inputs()[0].shape[0]
    b = b if isinstance(b, int) and b > 0 else 5
    idx = {c: i for i, c in enumerate(classes)}
    xs, ys = [], []
    for d in sorted((DATA / "val").iterdir()):
        if d.name not in idx: continue
        for p in d.glob("*.jpg"):
            if only and not p.name.startswith(only + "_"): continue
            img = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)
            xs.append(_squash(img).transpose(2, 0, 1).astype(np.float32) / 255.0); ys.append(idx[d.name])
    if not xs: return None
    ok = ok_card = 0
    name = s.get_inputs()[0].name
    for i in range(0, len(xs), b):
        part = np.stack(xs[i:i + b]); k = len(part)
        if k < b: part = np.concatenate([part, np.zeros((b - k,) + part.shape[1:], np.float32)])
        pred = s.run(None, {name: part})[0][:k].argmax(1)
        for j, pj in enumerate(pred):
            t = ys[i + j]
            ok += int(pj == t)
            ok_card += int(split(classes[pj])[0] == split(classes[t])[0])
    return {"n": len(xs), "top1": ok / len(xs), "card": ok_card / len(xs)}


def run(epochs=30, only=None):
    from royale import trainer
    from royale.hand_classifier import ONNX, META, DIR
    import settings
    t0 = time.time()
    _status(stage="hand", note="hand cards: pictures")
    done = ROOT / "trained.json"          # 6.9.11: trained before (its test failed / it was stopped): test it, no retraining
    try:
        tw = Path(json.loads(done.read_text(encoding="utf-8"))["w"])
    except (OSError, ValueError, KeyError):
        tw = None
    last_best = ROOT / "runs" / "hand" / "weights" / "best.pt"
    if tw is None and last_best.exists() and time.time() - last_best.stat().st_mtime < 86400:
        tw = last_best                    # a training of the last day that stopped before this marker existed
    if tw and tw.exists() and (DATA / "val").exists() and not only:
        _log(f"the hand-card model was trained before ({tw.parent.parent.name}) — testing and installing it, not training again")
        return _finish(tw, t0)
    _log("step 0 — the hand-card model: making the pictures")
    if DATA.exists(): shutil.rmtree(DATA, ignore_errors=True)
    cards = bot_cards()
    if only: cards = {k: v for k, v in cards.items() if k in only}          # a quick check on a few cards
    known = {}
    for label in cards:
        base = label
        for v in LOOKS:
            if base.endswith(v): base = base[: -len(v)]; break
        known.setdefault(_key(base), base)
    n_syn = make_synthetic(cards)
    _log(f"{n_syn:,} pictures made from {len(cards)} card pictures")
    key = (settings.load_app().get("roboflow_api_key") or "").strip()
    rf = take_roboflow(key, known)
    _log(f"real hand pictures: {rf['train']:,} to learn, {rf['val']:,} to test, {len(rf['kinds'])} kinds"
         + (f"; names not known to the bot (left out): {', '.join(sorted(rf['skipped']))[:300]}" if rf["skipped"] else ""))
    trainer.data_note("Hand cards (Roboflow + made here)", n_syn + rf["train"] + rf["val"],
                      f"{len(rf['kinds'])} real kinds")
    # the same kinds in both folders, none empty (the folder reader stops on an empty kind): a kind seen in only one
    # of them lends it one picture
    for a, b in (("train", "val"), ("val", "train")):
        for d in (DATA / a).iterdir():
            dst = DATA / b / d.name
            if not dst.exists() or not any(dst.iterdir()):
                dst.mkdir(parents=True, exist_ok=True)
                first = next(d.glob("*.jpg"), None)
                if first: shutil.copy(first, dst / ("lent_" + first.name))
    from ultralytics import YOLO
    import torch
    torch.backends.cudnn.benchmark = True
    bs = 256
    _status(stage="hand", note=f"hand cards: training ({epochs} rounds)")
    _log(f"training YOLO11n-cls — {epochs} rounds, {IMGSZ}px, {bs} pictures at a time on the graphics card")
    trainer.no_pin()                              # 6.9: no pinned RAM (it ran out on the laptop)
    m = YOLO("yolo11n-cls.pt")
    trainer.battle_pause(m)                       # the card is the game's during a battle (6.9)
    try:
        m.train(data=str(DATA), epochs=epochs, imgsz=IMGSZ, batch=bs, device=0 if torch.cuda.is_available() else "cpu",
                workers=max(2, min(6, (os.cpu_count() or 4) - 2)),          # 6.9: fewer loaders (the laptop's RAM)
                fliplr=0.0, scale=0.15, erasing=0.1, hsv_v=0.4, patience=8, cos_lr=True, project=str(ROOT / "runs"),
                amp=torch.cuda.is_available(),
                name="hand", exist_ok=True, plots=False, verbose=True)
    except Exception as e:
        # 6.9: a crash after some rounds keeps what was reached (best.pt = the best tested round), not nothing
        if not (ROOT / "runs" / "hand" / "weights" / "best.pt").exists(): raise
        _log(f"training stopped ({type(e).__name__}: {str(e)[:120]}) — the best round reached so far is used")
    w = ROOT / "runs" / "hand" / "weights" / "best.pt"
    if not w.exists(): w = ROOT / "runs" / "hand" / "weights" / "last.pt"
    (ROOT / "trained.json").write_text(json.dumps({"w": str(w), "t": time.time()}), encoding="utf-8")
    return _finish(w, t0)


def _finish(w, t0):
    """The trained hand model -> ONNX (5 slots), its honest test, installed when good enough."""
    from ultralytics import YOLO
    from royale.hand_classifier import ONNX, META, DIR
    from royale import trainer
    try:
        from royale import trainer
        trainer.repair_onnxruntime()                # 6.9.12: only says which onnxruntime is broken, if any
    except Exception:
        pass
    model = YOLO(str(w))
    classes = [model.names[i] for i in range(len(model.names))]
    out = Path(model.export(format="onnx", imgsz=IMGSZ, batch=5, opset=12, simplify=False, dynamic=False))
    real = evaluate(out, classes, "rf", weights=w)
    syn = evaluate(out, classes, "syn", weights=w)
    _log(f"test — real hand pictures: {real and f'{100 * real['top1']:.1f}% exact, {100 * real['card']:.1f}% right card'}"
         f" ({real and real['n']}); made here: {syn and f'{100 * syn['top1']:.1f}% / {100 * syn['card']:.1f}%'}")
    score = (real or syn or {}).get("card", 0.0)
    try: old = json.loads(META.read_text(encoding="utf-8")).get("score", 0.0)
    except (OSError, ValueError): old = 0.0
    need = 0.95 if real else 0.98
    used = score >= need and score >= old
    if used:
        DIR.mkdir(parents=True, exist_ok=True)
        os.replace(out, ONNX)
        META.write_text(json.dumps({"classes": classes, "imgsz": IMGSZ, "score": round(score, 4),
                                    "real": real, "made": syn, "t": time.time()}), encoding="utf-8")
    _log(f"hand-card model {'IN USE' if used else 'not used'} — card accuracy {100 * score:.1f}%"
         f" (needs {100 * need:.0f}% and >= the one in use {100 * old:.1f}%) · {int(time.time() - t0)} s")
    _status(hand={"score": round(score, 4), "used": used, "real": real, "made": syn})
    (ROOT / "trained.json").unlink(missing_ok=True)          # tested: the next training trains a new one
    return used


if __name__ == "__main__":
    try:                                  # 6.9.14: no broken app-folder onnxruntime inherited from the app
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import ort_gpu
        ort_gpu.sanitize()
    except Exception:
        pass
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    if "--eval" in sys.argv:
        i = sys.argv.index("--eval")
        res = _evaluate(sys.argv[i + 1], json.loads(sys.argv[i + 2]), (sys.argv[i + 3] if len(sys.argv) > i + 3 else "") or None)
        print("EVAL " + json.dumps(res), flush=True)
    else:
        run()
