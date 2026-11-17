"""
More training pictures from the labelled ones (copy-paste augmentation, a common YOLO technique).

  python scripts/synth_copy_paste.py <yolo dataset> <how many new pictures> [seed]

For every new picture: a labelled training picture is the background, and buildings cut out of other labelled
pictures (box + a little margin) are pasted on it at new places on the base, slightly bigger / smaller, never on top
of a building that is already there. The labels follow the pasted buildings. Written to images/train + labels/train
with the prefix "syn_", so they can be removed again (rm *syn_*).
"""
import os, random, sys, glob

import cv2
import numpy as np


def read_labels(path):
    out = []
    if os.path.exists(path):
        for line in open(path):
            p = line.split()
            if len(p) == 5: out.append((int(p[0]), *map(float, p[1:])))
    return out


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix, iy = max(0, min(ax2, bx2) - max(ax1, bx1)), max(0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    return inter / max(1e-9, (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter)


def main(ds, n, seed=1):
    rnd = random.Random(seed)
    imgs = sorted(p for p in glob.glob(os.path.join(ds, "images", "train", "*")) if "syn_" not in os.path.basename(p))
    lab = lambda p: os.path.join(ds, "labels", "train", os.path.splitext(os.path.basename(p))[0] + ".txt")
    # the cut-outs: every labelled building of every training picture
    pieces = []
    for p in imgs:
        im = cv2.imread(p)
        H, W = im.shape[:2]
        for c, cx, cy, w, h in read_labels(lab(p)):
            x1, y1 = int((cx - w / 2) * W), int((cy - h / 2) * H)
            x2, y2 = int((cx + w / 2) * W), int((cy + h / 2) * H)
            if x2 - x1 < 8 or y2 - y1 < 8: continue
            pieces.append((c, im[max(0, y1):y2, max(0, x1):x2].copy(), W))
    print(len(imgs), "pictures,", len(pieces), "buildings to paste")
    for k in range(n):
        bg_path = rnd.choice(imgs)
        bg = cv2.imread(bg_path)
        H, W = bg.shape[:2]
        labels = read_labels(lab(bg_path))
        boxes = [((cx - w / 2), (cy - h / 2), (cx + w / 2), (cy + h / 2)) for _c, cx, cy, w, h in labels]
        # where the base is in this picture: the box around its labelled buildings
        if boxes:
            bx1, by1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            bx2, by2 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        else:
            bx1, by1, bx2, by2 = 0.25, 0.25, 0.75, 0.75
        added = 0
        for _try in range(60):
            if added >= rnd.randint(4, 12): break
            c, piece, srcW = rnd.choice(pieces)
            s = rnd.uniform(0.85, 1.15) * W / srcW
            ph, pw = max(8, int(piece.shape[0] * s)), max(8, int(piece.shape[1] * s))
            x = rnd.uniform(bx1, max(bx1, bx2 - pw / W))
            y = rnd.uniform(by1, max(by1, by2 - ph / H))
            box = (x, y, x + pw / W, y + ph / H)
            if box[2] > 1 or box[3] > 1 or any(iou(box, b) > 0.05 for b in boxes): continue
            X, Y = int(x * W), int(y * H)
            bg[Y:Y + ph, X:X + pw] = cv2.resize(piece, (pw, ph))
            boxes.append(box)
            labels.append((c, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, box[2] - box[0], box[3] - box[1]))
            added += 1
        # a little light / colour change so the copies don't look the same
        bg = np.clip(bg.astype(np.float32) * rnd.uniform(0.85, 1.15) + rnd.uniform(-12, 12), 0, 255).astype(np.uint8)
        name = f"syn_{k:05d}"
        cv2.imwrite(os.path.join(ds, "images", "train", name + ".jpg"), bg, [cv2.IMWRITE_JPEG_QUALITY, 90])
        with open(os.path.join(ds, "labels", "train", name + ".txt"), "w") as f:
            f.write("\n".join(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}" for c, cx, cy, w, h in labels))
    print("written", n, "new pictures")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 1)
