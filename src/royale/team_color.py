"""
Ours or theirs from the game's own colours (6.6): every hurt unit carries a health bar over its head and a level
badge at the bar's left — BLUE for ours, RED for theirs. No model, no training:

  1. the picture is turned into HSV once a look, at 400 px wide whatever the screen (OpenCV: ~0.3 ms)
  2. two masks: the game's blue / its crimson. Measured on a real battle picture of this PC (1280x2275): their
     level badge RGB (210, 40, 89) = H 171, S 206; their tower bar (236, 102, 139) = H 170 -> red is H >= 160 or
     <= 8, S >= 110, V >= 150. Ours (royale.health's bar fill b > 200, g > 150, r < 140, badge darker blue) ->
     H 95-125, S >= 110, V >= 150
  3. their integral images: the count of blue / red pixels in ANY box is 4 lookups (nothing coloured: no work)
  4. for each unit, the band just over its box: the coloured blobs in it (connected components of a few hundred
     pixels) are looked at by SHAPE —
       the level badge   a compact square ~2.3% of the screen wide (29x33 px at 1280), there even at FULL health
                         (the real picture: every unhurt enemy shows its red "1" badge, no bar)
       the health bar    thin (h <= 1.2% of the width) and long (w >= 2.5 h), when hurt
     the blue river, a red tower roof, a red unit's cap are other shapes (too big, too tall, too small): left out
  -> ("ally" | "enemy" | None, how sure 0..3): None = no bar (unhurt units hide it) — the tracker then keeps the
     side it already knows (royale.unit_tracker), or the side model / the half it appeared on decides

~0.4 ms a look for 30 units (numpy over small bands + 4 lookups each).
"""
import json, time
from pathlib import Path

import numpy as np

CONF = Path.home() / ".CoC_Bot" / "team_color.json"     # measured ranges (calibrate), when there are some

# OpenCV hue is 0..179
BLUE_H, BLUE_S, BLUE_V = (95, 125), 110, 150
RED_H_LO, RED_H_HI, RED_S, RED_V = 8, 160, 110, 150
WIDTH = 400                                       # the masks are made at this width (a badge stays ~9 px)


def default_ranges():
    """[(h_lo, h_hi, s_min, v_min)] per side (OpenCV hue 0..179)."""
    return {"ally": [(BLUE_H[0], BLUE_H[1], BLUE_S, BLUE_V)],
            "enemy": [(0, RED_H_LO, RED_S, RED_V), (RED_H_HI, 179, RED_S, RED_V)]}


def load_ranges():
    """The ranges measured on this PC's own battles (calibrate) — else the defaults."""
    try:
        d = json.loads(CONF.read_text(encoding="utf-8"))
        r = {k: [tuple(int(v) for v in x) for x in d[k]] for k in ("ally", "enemy")}
        if r["ally"] and r["enemy"]: return r
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return default_ranges()


class TeamColor:
    def __init__(self):
        self._ib = self._ir = None
        self._shape = None
        self.ranges = load_ranges()

    # -------------------------------------------------------------- once a look
    def prepare(self, frame_rgb):
        """The masks + integral images of this picture (call once per look, before team())."""
        import cv2
        h, w = frame_rgb.shape[:2]
        k = WIDTH / float(w)
        small = cv2.resize(frame_rgb[:int(h * 0.84)], (WIDTH, max(1, int(round(h * 0.84 * k)))),
                           interpolation=cv2.INTER_LINEAR)              # the arena only (not the hand)
        hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
        def mask(rs):
            m = None
            for h0, h1, s0, v0 in rs:
                k_ = cv2.inRange(hsv, (h0, s0, v0), (h1, 255, 255))
                m = k_ if m is None else cv2.bitwise_or(m, k_)
            return m
        blue, red = mask(self.ranges["ally"]), mask(self.ranges["enemy"])
        cv2.threshold(blue, 0, 1, cv2.THRESH_BINARY, dst=blue)          # 0 / 1: sums are pixel counts
        cv2.threshold(red, 0, 1, cv2.THRESH_BINARY, dst=red)
        self._mb, self._mr = blue, red
        self._ib, self._ir = cv2.integral(blue), cv2.integral(red)
        self._shape = small.shape[:2]
        self._k = k
        return self

    @staticmethod
    def _sum(I, x0, y0, x1, y1):
        return int(I[y1, x1] - I[y0, x1] - I[y1, x0] + I[y0, x0])

    # -------------------------------------------------------------- one unit
    def team(self, box):
        """box: the unit's (x0, y0, x1, y1) in the picture's pixels -> (team or None, sureness 0..3)."""
        if self._ib is None: return None, 0.0
        k = self._k
        H, W = self._shape
        x0, y0, x1, y1 = [v * k for v in box]
        bw, bh = max(2.0, x1 - x0), max(2.0, y1 - y0)
        # the band over the head: from 0.55 of the box height above it to 0.15 inside it, a bit wider than the box
        xa, xb = int(max(0, x0 - 0.25 * bw)), int(min(W - 1, x1 + 0.25 * bw))
        ya, yb = int(max(0, y0 - 0.55 * bh - 2)), int(min(H - 1, y0 + 0.15 * bh))
        if xb - xa < 3 or yb - ya < 2: return None, 0.0
        nb, nr = self._sum(self._ib, xa, ya, xb, yb), self._sum(self._ir, xa, ya, xb, yb)
        if nb + nr < 6: return None, 0.0                       # nothing coloured over it: unknown
        import cv2
        Wf = W                                                 # sizes relative to the (half-size) screen width
        scores = {}
        for name, m, n in (("ally", self._mb, nb), ("enemy", self._mr, nr)):
            if n < 6: continue
            band = m[ya:yb, xa:xb]
            k_n, _lab, st, _c = cv2.connectedComponentsWithStats(band, connectivity=8)
            score = 0.0
            for j in range(1, k_n):
                x, y, w, h, a = st[j]
                if a < 6: continue
                if w >= 0.9 * (xb - xa) and h >= 0.7 * (yb - ya): continue      # fills the band: river / a roof
                if h > 0.045 * Wf or w > 0.16 * Wf: continue                   # too big for a badge or a bar
                badge = 0.012 * Wf <= h <= 0.040 * Wf and 0.010 * Wf <= w and a >= 0.45 * w * h
                bar = h <= 0.012 * Wf + 1 and w >= 2.5 * h and w >= 0.025 * Wf
                if badge and bar: score = max(score, 3.0)
                elif badge: score = max(score, 2.0 + min(0.5, a / max(1.0, w * h) - 0.45))
                elif bar: score = max(score, 2.5)
            if score:
                scores[name] = score
        if not scores:
            return None, 0.0
        best = max(scores, key=scores.get)
        # Arena paint and effects can be saturated without forming a badge.
        # Reduce confidence only when both colours form plausible markers.
        return best, scores[best] * (0.4 if len(scores) == 2 else 1.0)


# ------------------------------------------------------------------ measuring the colours on real battles (6.7)
def badge_pixels(frame_rgb, box):
    """HSV of the coloured badge / bar over one unit (the largest compact saturated blob in its head band that is not
    the grass) -> array (n, 3) or None."""
    import cv2
    h, w = frame_rgb.shape[:2]
    x0, y0, x1, y1 = box
    bw, bh = max(2.0, x1 - x0), max(2.0, y1 - y0)
    xa, xb = int(max(0, x0 - 0.25 * bw)), int(min(w - 1, x1 + 0.25 * bw))
    ya, yb = int(max(0, y0 - 0.55 * bh - 2)), int(min(h - 1, y0 + 0.15 * bh))
    if xb - xa < 4 or yb - ya < 3: return None
    hsv = cv2.cvtColor(np.ascontiguousarray(frame_rgb[ya:yb, xa:xb]), cv2.COLOR_RGB2HSV)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    # the red family (crimson / pink / purple-red) or the blue family, saturated and bright — the sand path (H 15-28)
    # and the grass (H 30-88) flooded the band before (6.9: 0 badges found in 300 pictures)
    fam = (H <= 10) | (H >= 145) | ((H >= 90) & (H <= 132))
    m = ((S >= 110) & (V >= 120) & fam).astype(np.uint8)
    n, lab, st, _c = cv2.connectedComponentsWithStats(m, connectivity=8)
    best = None
    for j in range(1, n):
        x, y, ww, hh, a = st[j]
        if a < 12 or hh > 0.7 * (yb - ya) and ww > 0.9 * (xb - xa): continue
        if a < 0.35 * ww * hh: continue                                       # not compact: a body / a roof edge
        if best is None or a > best[1]: best = (j, a)
    if best is None: return None
    return hsv[lab == best[0]].reshape(-1, 3)


def ranges_from(pixels):
    """HSV pixels of one side's badges -> [(h_lo, h_hi, s_min, v_min)]: the hue bins holding the colour (red wraps
    around 0 / 179), widened by 3, saturation / brightness from their 5th percentile minus a margin."""
    if pixels is None or len(pixels) < 50: return None
    hist = np.bincount(pixels[:, 0].astype(int), minlength=180).astype(float)
    hist /= hist.sum()
    on = hist >= 0.03                               # a hue holding 3%+ of the badge pixels (stray pixels left out)
    out = []
    k = 0
    while k < 180:
        if on[k]:
            a = k
            while k + 1 < 180 and on[k + 1]: k += 1
            lo, hi = max(0, a - 3), min(179, k + 3)
            if out and lo <= out[-1][1] + 1: out[-1][1] = max(out[-1][1], hi)      # touching ranges: one
            else: out.append([lo, hi])
        k += 1
    s_min = int(max(60, np.percentile(pixels[:, 1], 5) - 20))
    v_min = int(max(90, np.percentile(pixels[:, 2], 5) - 20))
    return [(a, b, s_min, v_min) for a, b in out]


def calibrate(samples, save=True):
    """samples: [(frame_rgb, box, "ally" | "enemy")] whose side is known WITHOUT the colours (the deck rule, the side
    model on the right half) -> {"ally": ranges, "enemy": ranges, "n": {...}} saved to CONF (the eyes use it from
    the next battle). A side with too few badges keeps the default ranges."""
    px = {"ally": [], "enemy": []}
    for fr, box, team in samples:
        p = badge_pixels(fr, box)
        if p is not None: px[team].append(p)
    res = {"n": {k: len(v) for k, v in px.items()}}
    d = default_ranges()
    for team in ("ally", "enemy"):
        r = ranges_from(np.concatenate(px[team])) if len(px[team]) >= 5 else None
        if r:                                       # one side's colour must not swallow the other's: overlap removed
            res[team] = r
        else:
            res[team] = d[team]
    a = {h for lo, hi, *_ in res["ally"] for h in range(lo, hi + 1)}
    e = {h for lo, hi, *_ in res["enemy"] for h in range(lo, hi + 1)}
    res["overlap"] = sorted(a & e)
    if res["overlap"]:                              # unsure where they meet: the defaults stay
        res.update(d)
    res["t"] = time.time()
    if save:
        CONF.parent.mkdir(parents=True, exist_ok=True)
        CONF.write_text(json.dumps(res), encoding="utf-8")
    return res


def auto_calibrate(limit=300, log=print):
    """From this PC's saved battle pictures (royale.frames: the arena + the big model's boxes): each unit's side from
    the deck rule (a unit of none of the account's cards is theirs) and the small side model (ours only on our half,
    theirs only on theirs) — never from the colour itself — then calibrate()."""
    import cv2
    from PIL import Image
    from royale import frames, strong_eyes
    from royale.eyes import Eyes
    pics = sorted(frames.DIR.glob("*.jpg"))[-limit:] if frames.DIR.exists() else []
    if not pics:
        log("team colours: no saved battle pictures yet — the default colours stay"); return None
    mine = {c for d in Eyes.known_decks() for c in d}
    from royale.brain import unit_card
    from royale.vision import constants as C
    from royale.vision.detectors.side_detector import SideDetector
    import os
    side = SideDetector(os.path.join(C.MODELS_DIR, "side.onnx"))
    samples = []
    for p in pics:
        try:
            meta = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
            fr = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)
        except Exception:
            continue
        h = fr.shape[0]
        pil = Image.fromarray(fr)
        for name, cf, x0, y0, x1, y1 in meta.get("boxes", []):
            u = strong_eyes.unit_name(name)
            if not u or cf < 0.6: continue
            cn = unit_card(u)
            if mine and cn and cn not in mine:
                samples.append((fr, (x0, y0, x1, y1), "enemy")); continue
            try: sd = side.run(pil.crop((int(x0), int(y0), int(x1) + 1, int(y1) + 1)))
            except Exception: continue
            low = (y0 + y1) / 2 > h / 2                           # our half is the bottom of the arena picture
            if sd == "ally" and low: samples.append((fr, (x0, y0, x1, y1), "ally"))
            elif sd == "enemy" and not low: samples.append((fr, (x0, y0, x1, y1), "enemy"))
    res = calibrate(samples)
    log(f"team colours measured on {len(pics)} battle pictures: ours {res['n']['ally']} badges -> {res['ally']}, "
        f"theirs {res['n']['enemy']} -> {res['enemy']}" + (" — they overlapped, the defaults stay" if res.get("overlap") else ""))
    return res
