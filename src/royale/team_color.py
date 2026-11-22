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
import numpy as np

# OpenCV hue is 0..179
BLUE_H, BLUE_S, BLUE_V = (95, 125), 110, 150
RED_H_LO, RED_H_HI, RED_S, RED_V = 8, 160, 110, 150
WIDTH = 400                                       # the masks are made at this width (a badge stays ~9 px)


class TeamColor:
    def __init__(self):
        self._ib = self._ir = None
        self._shape = None

    # -------------------------------------------------------------- once a look
    def prepare(self, frame_rgb):
        """The masks + integral images of this picture (call once per look, before team())."""
        import cv2
        h, w = frame_rgb.shape[:2]
        k = WIDTH / float(w)
        small = cv2.resize(frame_rgb[:int(h * 0.84)], (WIDTH, max(1, int(round(h * 0.84 * k)))),
                           interpolation=cv2.INTER_LINEAR)              # the arena only (not the hand)
        hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
        blue = cv2.inRange(hsv, (BLUE_H[0], BLUE_S, BLUE_V), (BLUE_H[1], 255, 255))
        red = cv2.bitwise_or(cv2.inRange(hsv, (0, RED_S, RED_V), (RED_H_LO, 255, 255)),
                             cv2.inRange(hsv, (RED_H_HI, RED_S, RED_V), (179, 255, 255)))
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
        best = None
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
            if score and (best is None or score > best[1]): best = (name, score)
        if best is None: return None, 0.0
        # both colours over one unit (a blue unit next to a red badge): the stronger, much less sure
        other = nr if best[0] == "ally" else nb
        mine = nb if best[0] == "ally" else nr
        if other > 0.6 * mine: return best[0], best[1] * 0.4
        return best
