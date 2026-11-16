"""
Troop / spell / siege / pet pictures uploaded to the project (army_training/...).
Used to show them in the GUI and to put a name on each card of the battle troop bar.
The pictures are the game's artwork with a transparent background, so a card is named by
comparing it with every picture (only the opaque pixels count) at a few sizes.
"""
from pathlib import Path

import sys
ROOT = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
GROUPS = {"troops": ROOT / "army_training", "spells": ROOT / "army_training" / "spells",
          "sieges": ROOT / "army_training" / "sieges", "pets": ROOT / "army_training" / "pets"}

def catalog():
    """{group: [names]} of the pictures that exist."""
    out = {}
    for g, d in GROUPS.items():
        out[g] = sorted(p.stem for p in d.glob("*.png")) if d.is_dir() else []
    return out

def path(group, name):
    d = GROUPS.get(group)
    if d is None: return None
    p = d / f"{name}.png"
    return p if p.is_file() and p.parent == d else None

_CACHE = {}

def _icons(group):
    """[(name, rgb, mask)] at a fixed working size."""
    import cv2, numpy as np
    if group in _CACHE: return _CACHE[group]
    out = []
    d = GROUPS.get(group)
    for p in sorted(d.glob("*.png")) if d and d.is_dir() else []:
        im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if im is None or im.ndim != 3: continue
        if im.shape[2] == 4:
            rgb, alpha = cv2.cvtColor(im[:, :, :3], cv2.COLOR_BGR2RGB), im[:, :, 3]
        else:
            rgb, alpha = cv2.cvtColor(im, cv2.COLOR_BGR2RGB), np.full(im.shape[:2], 255, np.uint8)
        ys, xs = np.where(alpha > 40)
        if len(xs) == 0: continue
        rgb, alpha = rgb[ys.min():ys.max() + 1, xs.min():xs.max() + 1], alpha[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        out.append((p.stem, rgb, alpha))
    _CACHE[group] = out
    return out

def identify(card_rgb, groups=("troops", "sieges"), min_score=0.80):
    """
    Name of the unit on a card picture (RGB crop of one card), or (None, score).
    Tries each picture at a few sizes relative to the card width.
    """
    import cv2, numpy as np
    h, w = card_rgb.shape[:2]
    if h < 20 or w < 20: return None, 0.0
    # work small: cards are ~130 px wide on 1920x1080, 64 px is plenty
    f = 64.0 / w
    card = cv2.resize(card_rgb, (64, max(20, int(h * f))), interpolation=cv2.INTER_AREA)
    best = (None, 0.0)
    for g in groups:
        for name, rgb, alpha in _icons(g):
            for s in (0.6, 0.7, 0.78, 0.86):
                tw = int(64 * s)
                th = int(rgb.shape[0] * tw / rgb.shape[1])
                if th >= card.shape[0] or tw >= card.shape[1] or th < 8: continue
                t = cv2.resize(rgb, (tw, th), interpolation=cv2.INTER_AREA)
                m = cv2.resize(alpha, (tw, th), interpolation=cv2.INTER_NEAREST)
                m = cv2.merge([m, m, m])
                try:
                    res = cv2.matchTemplate(card, t, cv2.TM_CCOEFF_NORMED, mask=m)
                except cv2.error:
                    continue
                res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
                v = float(res.max())
                if v > best[1]: best = (name, v)
    return (best[0], best[1]) if best[1] >= min_score else (None, best[1])
