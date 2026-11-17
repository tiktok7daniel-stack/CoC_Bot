"""
Where troops can be dropped in a battle: outside the enemy base's red line — shown by the game itself.

When a troop is selected and you tap inside the base, the game lights the forbidden area up in red for a moment.
At the start of a battle the bot does exactly that once: it selects an ordinary troop (never a spell — that would be
cast — and never a hero), taps the middle of the base (always forbidden: nothing is dropped) and compares the
pictures before / after: what turned red is the forbidden area, exactly as the game sees it (no guessing from the
buildings). ~0.7 s.

Zone.fix(x, y)   a tap that would land inside is moved just outside the line (same direction from the middle)
Zone.snap(x, y)  any drop spot put right on the line (+ a small gap): close to the base, never refused
Nothing clear seen: an empty Zone (everything stays as it was) and the pictures go to Claude.
"""
import time
import numpy as np

SCALE = 8                        # work on a 240 x 135 picture (a few ms)
FIELD = (0.0, 0.07, 1.0, 0.80)   # the battlefield (top bar and the troop bar left out)
PROBE = (0.5, 0.42)              # the middle of the base after zooming out (when the model didn't see the base)


def red_area(before, after):
    """Mask (1/8 scale) of what turned red between two RGB pictures; None when there is no clear red area."""
    import cv2
    w, h = before.shape[1] // SCALE, before.shape[0] // SCALE
    b = cv2.resize(before, (w, h), interpolation=cv2.INTER_AREA).astype(int)
    a = cv2.resize(after, (w, h), interpolation=cv2.INTER_AREA).astype(int)
    redder = (a[..., 0] - a[..., 1]) - (b[..., 0] - b[..., 1])        # R - G went up
    m = ((redder > 18) & (b[..., 1] - a[..., 1] > 8)).astype(np.uint8)
    m[: int(FIELD[1] * h)] = 0
    m[int(FIELD[3] * h):] = 0
    if m.mean() < 0.02: return None                                    # nothing lit up
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, _c = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1: return None
    big = 1 + int(np.argmax(st[1:, 4]))
    base = (lab == big).astype(np.uint8)
    cnts, _ = cv2.findContours(base, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(base)
    cv2.drawContours(filled, cnts, -1, 1, -1)
    share = filled.mean()
    if share < 0.03 or share > 0.75: return None                      # not a base outline
    return filled.astype(bool)


class Zone:
    """The forbidden zone of this battle."""

    def __init__(self, mask=None):
        self.mask = mask
        self.center = None
        if mask is not None:
            ys, xs = np.nonzero(mask)
            H, W = mask.shape
            self.center = (xs.mean() / W, ys.mean() / H)
        self.moved = 0

    def __bool__(self):
        return self.mask is not None

    def inside(self, x, y):
        if self.mask is None: return False
        H, W = self.mask.shape
        i, j = int(min(H - 1, max(0, y * H))), int(min(W - 1, max(0, x * W)))
        return bool(self.mask[i, j])

    def _edge(self, x, y):
        """From the zone's middle through (x, y): the first point outside the line -> (px, py, dx, dy) or None."""
        cx, cy = self.center
        dx, dy = x - cx, y - cy
        n = (dx * dx + dy * dy) ** 0.5
        if n < 1e-3: dx, dy, n = 0.0, 1.0, 1.0
        dx, dy = dx / n, dy / n
        px, py = cx, cy
        for _ in range(400):
            px, py = px + dx * 0.004, py + dy * 0.004
            if not (0.01 < px < 0.99 and FIELD[1] < py < FIELD[3]): return None
            if not self.inside(px, py) and not self.inside(px + dx * 0.008, py + dy * 0.008): return px, py, dx, dy
        return None

    def _clip(self, x, y):
        return min(0.99, max(0.01, x)), min(FIELD[3] - 0.005, max(FIELD[1] + 0.005, y))

    def fix(self, x, y, extra=0.012):
        """(x, y) as it is, or moved just outside the red line on the way out from the base's middle."""
        if self.mask is None or y > FIELD[3] or not self.inside(x, y): return x, y
        e = self._edge(x, y)
        if e is None: return x, y                                         # no way out: leave it as it was
        px, py, dx, dy = e
        self.moved += 1
        return self._clip(px + dx * extra, py + dy * extra)

    def snap(self, x, y, gap=0.015, max_pull=0.10):
        """A drop spot right at the line (+ gap) in the direction of (x, y): inside -> out; far outside -> pulled in
        (by at most max_pull: troops start fighting at once instead of walking)."""
        if self.mask is None or y > FIELD[3]: return x, y
        e = self._edge(x, y)
        if e is None: return x, y
        px, py, dx, dy = e
        tx, ty = px + dx * gap, py + dy * gap
        cx, cy = self.center
        far = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 - ((tx - cx) ** 2 + (ty - cy) ** 2) ** 0.5
        if far > max_pull:                                                # very far out: only part of the way in
            tx, ty = x - dx * max_pull, y - dy * max_pull
        return self._clip(tx, ty)


def reveal(attacker, probe=None, logger=None):
    """
    In a battle, before anything is dropped: show the red line once and read it. -> Zone (empty when unclear).
    Uses an ordinary troop card only (spells would be cast, heroes could be dropped).
    """
    from utils import Frame_Handler, Input_Handler
    probe = probe or PROBE
    try:
        bar = Frame_Handler.get_frame_section(0.0, 0.82, 1.0, 1.0, grayscale=False)
        centers, _b, types, counts, _g = attacker.detect_troop_positions(bar, return_boundaries=True, return_types=True,
                                                                         return_counts=True)
        card = next((c for c, t, n in zip(centers, types, counts) if t == "troop" and (n or 0) >= 2), None)
        if card is None: return Zone()
        Input_Handler.click(card, 0.9)
        time.sleep(0.12)
        before = Frame_Handler.get_frame(grayscale=False)
        Input_Handler.click(*probe)
        best = None
        last = before
        for _ in range(6):                              # the red shows for a moment: catch it (and stop then)
            time.sleep(0.06)
            last = Frame_Handler.get_frame(grayscale=False)
            m = red_area(before, last)
            if m is not None:
                if best is not None and m.mean() <= best.mean() * 1.03: break      # fully shown: done
                best = m
        z = Zone(best)
        if logger is not None:
            logger.info("Red line found: drops go right outside it" if best is not None
                        else "Red line not seen: deploying without it")
        if best is None:                                # the pictures go to Claude: what did the game show?
            try:
                import learn_sync, utils
                learn_sync.report_unknown(utils.INSTANCE_ID, last, "battle", why="red_line")
            except Exception:
                pass
        return z
    except Exception:
        return Zone()
