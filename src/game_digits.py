"""
Reading the game's numbers (storages, prices) with the game's own font — no OCR.

The numbers are drawn in SupercellMagic: a white (or red = can't afford) fill with a dark outline. The fill is cut
out by colour, split into digits (each digit is one blob), and every blob is compared with the font's digits drawn
at the same size. ~1-3 ms per number, no confusion of 0 / O / D like a text reader.
"""
import functools

FILL_WHITE = 200        # min of R, G, B for the white fill
_cache = {}


def fill_mask(img):
    """White or salmon-red fill pixels of the game font (the outline / background are dark or coloured)."""
    import numpy as np
    r, g, b = (img[..., i].astype(int) for i in range(3))
    white = (r > FILL_WHITE) & (g > FILL_WHITE) & (b > FILL_WHITE)
    red = (r > 215) & (g > 70) & (g < 175) & (b > 60) & (b < 170) & (r - g > 60)
    return (white | red).astype(np.uint8)


@functools.lru_cache(maxsize=64)
def _glyphs(height):
    """The font's digits 0-9 as filled masks, scaled to `height` pixels."""
    import numpy as np, cv2
    from utils import render_text
    out = {}
    for d in "0123456789":
        g = render_text(d, "SupercellMagic", 64)
        m = (g.max(axis=2) > 128).astype(np.uint8)
        ys, xs = np.where(m)
        m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        w = max(1, round(m.shape[1] * height / m.shape[0]))
        out[d] = cv2.resize(m, (w, height), interpolation=cv2.INTER_AREA)
    return out


def _holes(m):
    """Closed holes in a digit (0 4 6 9 -> 1, 8 -> 2, 1 2 3 5 7 -> 0)."""
    import numpy as np, cv2
    pad = np.pad(m.astype(np.uint8), 1)
    cnts, hier = cv2.findContours(pad, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None: return 0
    area = m.shape[0] * m.shape[1]
    return sum(1 for i, h in enumerate(hier[0]) if h[3] >= 0 and cv2.contourArea(cnts[i]) >= area * 0.01)


@functools.lru_cache(maxsize=1)
def _glyph_holes():
    return {d: _holes(g) for d, g in _glyphs(64).items()}


def _blobs(mask):
    """Digit blobs: tall enough, and on one line (same height and middle) — icons and specks are dropped."""
    import numpy as np, cv2
    n, lab, st, _c = cv2.connectedComponentsWithStats(mask, 8)
    boxes = [tuple(st[i, :4]) + (st[i, 4],) for i in range(1, n) if st[i, 3] >= 6 and st[i, 4] >= 10]
    if not boxes: return []
    # the digits are the biggest group of blobs with about the same height and the same vertical middle
    best = []
    for ref in boxes:
        h0, m0 = ref[3], ref[1] + ref[3] / 2
        grp = [b for b in boxes if abs(b[3] - h0) <= max(2, 0.18 * h0) and abs(b[1] + b[3] / 2 - m0) <= 0.25 * h0
               and b[2] <= b[3] * 1.2]
        if len(grp) > len(best) or (len(grp) == len(best) and grp and h0 > best[0][3]): best = grp
    best = sorted(best, key=lambda b: b[0])
    # one number: no big gaps (a gap of more than ~2 digit widths ends it; keep the longest run)
    runs, cur = [], []
    for b in best:
        if cur and b[0] - (cur[-1][0] + cur[-1][2]) > 1.6 * b[3]:
            runs.append(cur); cur = []
        cur.append(b)
    if cur: runs.append(cur)
    return max(runs, key=len) if runs else []


def _classify(blob_mask):
    import numpy as np, cv2
    h, w = blob_mask.shape
    best, best_s = None, -1.0
    for d, g in _glyphs(h).items():
        gw = g.shape[1]
        # width tells a lot (1 is thin): compare at the blob's size, penalise very different widths
        a = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA) if gw != w else g
        a = a > 0
        bm = blob_mask > 0
        inter = (a & bm).sum()
        union = (a | bm).sum() or 1
        s = inter / union - 0.6 * abs(gw - w) / max(gw, w)
        if _holes(bm) != _glyph_holes()[d]: s -= 0.25          # 8 has two holes, 6 one, 5 none…
        if s > best_s: best, best_s = d, s
    return best, best_s


def read(img, want_conf=False):
    """RGB crop holding one number -> int (None when no digit is found). Spaces and commas are skipped."""
    import numpy as np
    m = fill_mask(img)
    blobs = _blobs(m)
    if not blobs: return (None, 0.0) if want_conf else None
    digits, scores = [], []
    for x, y, w, h, area in blobs:
        if w > h * 1.3: continue                         # a dash / underline, not a digit
        d, s = _classify(m[y:y + h, x:x + w])
        digits.append(d)
        scores.append(s)
    if not digits: return (None, 0.0) if want_conf else None
    v = int("".join(digits))
    c = float(min(scores))
    return (v, c) if want_conf else v
