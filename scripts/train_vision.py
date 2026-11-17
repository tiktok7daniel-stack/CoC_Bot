"""
Train the bot's battle vision model (YOLOv8n) and export it for the bot (OpenCV can run the ONNX file).

  python scripts/train_vision.py <dataset folder with data.yaml> [epochs]

The dataset is in YOLO format (images/{train,val}, labels/{train,val}, data.yaml with the class names): the open
"Clash of Clans Dataset" (CC BY 4.0) plus the battle pictures the bot uploads to the learning repo
(inbox/battles/), checked and corrected by Claude. Writes assets/models/coc_vision.onnx + coc_vision.json.
"""
import json, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(ds, epochs=80):
    from ultralytics import YOLO
    import yaml
    names = yaml.safe_load(open(os.path.join(ds, "data.yaml")))["names"]
    model = YOLO("yolov8n.pt")
    model.train(data=os.path.join(ds, "data.yaml"), imgsz=640, epochs=epochs, batch=8, patience=25, plots=False,
                project=os.path.join(ds, "runs"), name="coc", exist_ok=True)
    best = YOLO(os.path.join(ds, "runs", "coc", "weights", "best.pt"))
    metrics = best.val(data=os.path.join(ds, "data.yaml"), imgsz=640, plots=False)
    onnx = best.export(format="onnx", imgsz=640, opset=12, simplify=True)
    out = os.path.join(ROOT, "assets", "models")
    os.makedirs(out, exist_ok=True)
    shutil.copy(onnx, os.path.join(out, "coc_vision.onnx"))
    json.dump({"names": list(names.values()) if isinstance(names, dict) else names, "imgsz": 640,
               "map50": round(float(metrics.box.map50), 3), "map50_95": round(float(metrics.box.map), 3)},
              open(os.path.join(out, "coc_vision.json"), "w"), indent=1)
    print("mAP50", metrics.box.map50, "->", out)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 80)
