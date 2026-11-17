"""
Train the bot's battle vision model and export it for the bot (OpenCV runs the ONNX file, no new library).

  python scripts/train_vision.py <dataset folder with data.yaml> [--epochs 100] [--model yolo11s.pt]
                                 [--pseudo <learning repo folder>] [--imgsz 640]

The dataset is in YOLO format (images/{train,val}, labels/{train,val}, data.yaml with the class names): the open
"Clash of Clans Dataset" (CC BY 4.0) + copy-paste pictures (scripts/synth_copy_paste.py).

--pseudo: the battle pictures the bot sends from every attack (learning repo inbox/battles/) join the training
(self-training, "noisy student"): a picture Claude corrected (knowledge/battle_labels/<name>.txt, YOLO format) is used
as it is; the others get the labels the current model is sure about (conf >= 0.55, pictures with at least 5 of them).
The bigger student model learns from more bases than were ever labelled by hand, and the next round's teacher is
better. Pseudo pictures only go into training, never into the validation set (the score stays honest).

Writes assets/models/coc_vision.onnx + coc_vision.json (with the scores on the validation pictures).
"""
import argparse, glob, json, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PSEUDO_CONF, PSEUDO_MIN = 0.55, 5


def add_pseudo(ds, repo, names):
    """Bot battle pictures -> images/train/pl_*.jpg + labels (corrected by Claude, or the teacher's sure ones)."""
    from ultralytics import YOLO
    teacher = None
    fixed_dir = os.path.join(repo, "knowledge", "battle_labels")
    n_fixed = n_pseudo = 0
    for jpg in sorted(glob.glob(os.path.join(repo, "inbox", "battles", "*.jpg"))):
        stem = os.path.splitext(os.path.basename(jpg))[0]
        dst_img = os.path.join(ds, "images", "train", f"pl_{stem}.jpg")
        dst_lab = os.path.join(ds, "labels", "train", f"pl_{stem}.txt")
        fixed = os.path.join(fixed_dir, stem + ".txt")
        if os.path.exists(fixed):
            shutil.copy(jpg, dst_img)
            shutil.copy(fixed, dst_lab)
            n_fixed += 1
            continue
        if teacher is None:
            w = os.path.join(ROOT, "assets", "models", "coc_vision.onnx")
            teacher = YOLO(w, task="detect")
        r = teacher.predict(jpg, imgsz=640, conf=PSEUDO_CONF, verbose=False)[0]
        rows = [f"{int(c)} {x:.6f} {y:.6f} {w:.6f} {h:.6f}" for c, (x, y, w, h) in
                zip(r.boxes.cls.tolist(), r.boxes.xywhn.tolist())]
        if len(rows) < PSEUDO_MIN: continue
        shutil.copy(jpg, dst_img)
        open(dst_lab, "w").write("\n".join(rows))
        n_pseudo += 1
    print(f"bot battle pictures: {n_fixed} corrected by Claude, {n_pseudo} labelled by the teacher")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ds")
    ap.add_argument("epochs", nargs="?", type=int, default=None)
    ap.add_argument("--epochs", dest="ep", type=int, default=100)
    ap.add_argument("--model", default="yolo11s.pt")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--pseudo", default=None)
    ap.add_argument("--batch", type=int, default=8)
    a = ap.parse_args()
    epochs = a.epochs or a.ep
    from ultralytics import YOLO
    import yaml
    ds = a.ds
    names = yaml.safe_load(open(os.path.join(ds, "data.yaml")))["names"]
    names = list(names.values()) if isinstance(names, dict) else names
    if a.pseudo: add_pseudo(ds, a.pseudo, names)
    model = YOLO(a.model)
    model.train(data=os.path.join(ds, "data.yaml"), imgsz=a.imgsz, epochs=epochs, batch=a.batch, patience=30, plots=False,
                project=os.path.join(ds, "runs"), name="coc", exist_ok=True,
                # the game is seen from one fixed angle: no flips up/down, colour changes small (team colours mean things)
                flipud=0.0, fliplr=0.5, hsv_h=0.01, mosaic=1.0, close_mosaic=10, copy_paste=0.3, scale=0.5)
    best = YOLO(os.path.join(ds, "runs", "coc", "weights", "best.pt"))
    metrics = best.val(data=os.path.join(ds, "data.yaml"), imgsz=a.imgsz, plots=False)
    test = None
    if "test" in yaml.safe_load(open(os.path.join(ds, "data.yaml"))):
        test = best.val(data=os.path.join(ds, "data.yaml"), imgsz=a.imgsz, split="test", plots=False)
    onnx = best.export(format="onnx", imgsz=a.imgsz, opset=12, simplify=True)
    out = os.path.join(ROOT, "assets", "models")
    os.makedirs(out, exist_ok=True)
    shutil.copy(onnx, os.path.join(out, "coc_vision.onnx"))
    meta = {"names": names, "imgsz": a.imgsz, "arch": os.path.splitext(os.path.basename(a.model))[0],
            "map50": round(float(metrics.box.map50), 3), "map50_95": round(float(metrics.box.map), 3)}
    if test is not None:
        meta.update(test_map50=round(float(test.box.map50), 3), test_map50_95=round(float(test.box.map), 3))
    json.dump(meta, open(os.path.join(out, "coc_vision.json"), "w"), indent=1)
    print("done:", meta, "->", out)


if __name__ == "__main__":
    main()
