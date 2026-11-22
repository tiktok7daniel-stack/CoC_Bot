"""
The hand-card model (6.6): one small image classifier (YOLO11n-cls, trained on this PC by royale.hand_train) that
reads the 5 card slots — the next card + the 4 in hand — in ONE run on the graphics card (TensorRT FP16 via
trt_engine, batch of 5).

Why: the picture matcher (royale.vision CardDetector, 8x8 grey hashes) mixes up cards with the same face —
Goblin Barrel read as Goblin Gang put the barrel on the wrong spot and saved a wrong deck. A trained network sees
the whole card (the barrel, the elixir drop, the frame) and was trained on the real hand pictures of ~20k Roboflow
screenshots + every card picture of the bot in every look the hand has (playable, grey = not enough elixir, darker,
blurred, smaller).

  classes   "<card>" or "<card>_ev1" (its evolution is charged) / "_hero" / "_hero_ev1" — the same names and looks
            as the picture matcher, so the brain gets the same answer, only surer
  deck      once the 8 deck cards are known, only they compete (their chances renormalised)
  steady    a slot's reading is used only when the model is sure (>= 0.60) AND read the same in the last look
            (>= 0.95 alone): a card half-seen while the hand slides is never played. Else the matcher's reading stays.
"""
import json, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "models"
ONNX = DIR / "cr_hand_cls.onnx"
META = DIR / "cr_hand_cls.json"
SURE, SURE_ALONE = 0.60, 0.95
LOOKS = ("_hero_ev1", "_ev1", "_hero")


def split(label):
    """"goblin_barrel_ev1" -> ("goblin_barrel", "_ev1")."""
    for v in LOOKS:
        if label.endswith(v): return label[: -len(v)], v
    return label, ""


def crops(frame, size):
    """The 5 card slots of the game picture (CARD_CONFIG of the 368x652 screen, scaled), each squashed to size x size
    RGB float 0..1 -> (5, 3, size, size). Training squashes the same way (royale.hand_train)."""
    import cv2, numpy as np
    from royale.vision.constants import CARD_CONFIG, SCREENSHOT_WIDTH, SCREENSHOT_HEIGHT
    h, w = frame.shape[:2]
    kx, ky = w / float(SCREENSHOT_WIDTH), h / float(SCREENSHOT_HEIGHT)
    out = np.zeros((5, 3, size, size), np.float32)
    for k, (x0, y0, x1, y1) in enumerate(CARD_CONFIG[:5]):
        c = frame[int(y0 * ky):int(y1 * ky), int(x0 * kx):int(x1 * kx)]
        if c.size == 0: continue
        c = cv2.resize(c, (size, size), interpolation=cv2.INTER_AREA)
        out[k] = c.transpose(2, 0, 1) / 255.0
    return out


class HandClassifier:
    _tried = 0.0

    def __init__(self, sess, classes, size):
        self.sess, self.classes, self.size = sess, list(classes), int(size)
        self.cards = [split(c) for c in self.classes]
        self.batch = 5
        try:
            b = sess.get_inputs()[0].shape[0]
            self.batch = b if isinstance(b, int) and b > 0 else 5
        except Exception:
            pass
        self.prev = [None] * 5
        self.ms = 0.0

    @classmethod
    def load(cls):
        """The trained model, or None (not trained yet: the picture matcher reads alone). Tried once a minute."""
        if not ONNX.exists() or not META.exists() or time.time() - cls._tried < 60: return None
        cls._tried = time.time()
        try:
            meta = json.loads(META.read_text(encoding="utf-8"))
            import trt_engine
            sess = trt_engine.make_session(ONNX, threads=2)
            return cls(sess, meta["classes"], meta.get("imgsz", 128))
        except Exception:
            return None

    def probs(self, frame):
        """(5, classes) chances of the 5 slots, one run (or batches of the model's own size)."""
        import numpy as np
        from royale.vision.detectors.onnx_detector import GPU_LOCK
        x = crops(frame, self.size)
        name = self.sess.get_inputs()[0].name
        t0 = time.perf_counter()
        outs = []
        import contextlib
        with (GPU_LOCK if getattr(self.sess, "kind", "dml") == "dml" else contextlib.nullcontext()):
            for i in range(0, 5, self.batch):
                part = x[i:i + self.batch]
                if len(part) < self.batch:                       # a fixed-batch model: padded
                    part = np.concatenate([part, np.zeros((self.batch - len(part),) + part.shape[1:], part.dtype)])
                outs.append(self.sess.run(None, {name: part})[0][: min(self.batch, 5 - i)])
        self.ms = 0.8 * self.ms + 0.2 * (time.perf_counter() - t0) * 1000 if self.ms else (time.perf_counter() - t0) * 1000
        p = np.concatenate(outs, 0).astype(np.float32)
        if p.min() < 0 or abs(float(p[0].sum()) - 1.0) > 0.05:  # logits: softmax
            e = np.exp(p - p.max(1, keepdims=True))
            p = e / e.sum(1, keepdims=True)
        return p

    def read(self, frame, allowed=None, known=None):
        """-> 5 items (next card, hand 1..4): (card, look) when sure and steady, else None."""
        p = self.probs(frame)
        out = []
        for k in range(5):
            row = p[k]
            best = {}
            for j, (cn, look) in enumerate(self.cards):
                if known is not None and cn not in known: continue
                if allowed is not None and cn not in allowed: continue
                best[(cn, look)] = best.get((cn, look), 0.0) + float(row[j])
            if not best:
                out.append(None); self.prev[k] = None; continue
            tot = sum(best.values()) if allowed is not None else 1.0       # the deck only: renormalised
            (cn, look), pr = max(best.items(), key=lambda kv: kv[1])
            pr = pr / max(1e-6, tot)
            # the card, whatever its look: the looks of one card add up when deciding the card itself
            card_p = sum(v for (c, _l), v in best.items() if c == cn) / max(1e-6, tot)
            steady = self.prev[k] == cn
            self.prev[k] = cn if card_p >= SURE else None
            out.append((cn, look) if (card_p >= SURE and steady) or card_p >= SURE_ALONE else None)
        return out
