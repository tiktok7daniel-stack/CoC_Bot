"""
The battle bar's cards, found and recognised without mistakes (any number of cards: a long army fills more than the
screen and the bar is scrolled; only WHOLE cards are taken, the cut one at the edge waits for the scroll).

  find(bar)       -> [(x1, x2)] fractions of every whole card, left to right
                     every vertical edge, even a weak one (a dark hero picture next to the frame), paired as cards of
                     the game's fixed width (0.068 of the screen), the best set of cards that don't overlap; a dashed
                     empty slot (after the last card) is dropped: it has no level badge (dark square + light digits)
  thumb(bar, x1, x2) -> a small grey picture of the card's middle: the same card coloured or gray (used up) matches
  Bank            the cards the bot knows: seed (assets/card_bank.json, from the user's own bars) + learned by itself
                  (~/.CoC_Bot/learn/card_bank_<account>.json): a card it is sure about while it is coloured
                  (a siege by its blue frame, a troop / spell by its count) is remembered, so later — gray, after it
                  was used — it is still known (tested: same card 0.55-1.0, any other card <= 0.36)

Tested on the user's battles (17 bars): every card found (the Queen the old edge finder lost), 0 empty slots taken.
"""
import json, os, sys, threading, time
from pathlib import Path

CARD_W = 0.068            # card width (fraction of the screen width)
W_TOL = (0.058, 0.078)
SURE, MARGIN = 0.45, 0.15
SELF_MAX = 60
ROOT = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
LEARN = Path.home() / ".CoC_Bot" / "learn"
_B = {"items": None, "t": 0.0, "id": None, "lock": threading.Lock()}


def _profile(bar):
    import cv2, numpy as np
    g = cv2.equalizeHist(cv2.cvtColor(bar, cv2.COLOR_RGB2GRAY))
    ex = cv2.convertScaleAbs(np.abs(cv2.Sobel(g, cv2.CV_64F, 1, 0, ksize=3))).astype(np.float32)
    p = ex.sum(0)
    return (p - p.min()) / (p.max() - p.min() + 1e-9)


def has_badge(bar, x1, x2):
    """Every real card has its level in a flat-coloured square bottom-left with light digits — dark normally,
    BLUE when the army is boosted, GOLD at max level (any colour: the square is one flat colour). An empty dashed
    slot shows the map (no flat square, and its frame is dashed)."""
    import cv2, numpy as np
    H = bar.shape[0]
    w = x2 - x1
    r = bar[int(H * 0.68):int(H * 0.88), x1 + int(w * 0.04):x1 + int(w * 0.36)]
    if r.size == 0: return False
    g = cv2.cvtColor(r, cv2.COLOR_RGB2GRAY).astype(np.int16)
    hi = float(np.percentile(g, 97))
    rest = r[g < hi - 50].astype(np.int16)                  # not the digits
    if len(rest) < 0.3 * g.size: return False
    med = np.median(rest, axis=0)
    flat = float((np.abs(rest - med).max(axis=1) < 40).mean())   # one flat colour (the square)
    return flat >= 0.45


def _jumpy(g, W):
    import cv2, numpy as np
    if g.size == 0: return 0.0
    g = g.astype(np.float32)
    row = g[int(np.argmax(g.mean(1)))]
    k = max(5, (W // 128) | 1)
    return float(np.abs(row - cv2.blur(row.reshape(1, -1), (k, 1)).ravel()).mean())


def dashed(bar, x1, x2):
    """An empty slot's frame is a dashed line all round: along its top AND bottom border the brightness jumps every
    few pixels (empty slots 27-49; real cards 0.4-15 — a hero's crown or pet icon can make the top jumpy, never the
    bottom too)."""
    import cv2
    H, W = bar.shape[:2]
    a, b = int(x1 * W), int(x2 * W)
    m = (b - a) * 0.15
    a, b = int(a + m), int(b - m)
    top = cv2.cvtColor(bar[1:int(H * 0.2), a:b], cv2.COLOR_RGB2GRAY)
    bottom = cv2.cvtColor(bar[int(H * 0.82):H - 1, a:b], cv2.COLOR_RGB2GRAY)
    return _jumpy(top, W) > 22 and _jumpy(bottom, W) > 22


def find(bar, min_x=0.0):
    """bar: RGB strip (y 0.82..1.0 of the screen). -> [(x1, x2)] fractions, left to right."""
    import bisect, numpy as np, scipy.signal
    W = bar.shape[1]
    p = _profile(bar)
    pk = scipy.signal.find_peaks(p, height=0.4, distance=max(3, W // 320))[0]
    cand = []
    for a in range(len(pk)):
        for b in range(a + 1, len(pk)):
            w = (pk[b] - pk[a]) / W
            if w > W_TOL[1]: break
            if w < W_TOL[0]: continue
            cand.append((int(pk[a]), int(pk[b]), float(p[pk[a]] + p[pk[b]] - abs(w - CARD_W) * 40)))
    cand.sort(key=lambda c: c[1])
    ends = [c[1] for c in cand]
    gap = max(2, W // 640)
    dp = [(0.0, [])]                       # best set of non-overlapping cards among the first i
    for i, c in enumerate(cand):
        j = bisect.bisect_right(ends, c[0] - gap, 0, i)
        take = dp[j][0] + c[2]
        dp.append((take, dp[j][1] + [c]) if take > dp[-1][0] else dp[-1])
    out = [(c[0] / W, c[1] / W) for c in dp[-1][1] if c[0] / W >= min_x - 0.004 and has_badge(bar, c[0], c[1])
           and not dashed(bar, c[0] / W, c[1] / W)]
    return out


def is_gray(bar, x1, x2):
    """A used-up card is gray (no colour left in its picture)."""
    import numpy as np
    H, W = bar.shape[:2]
    a, b = int(x1 * W), int(x2 * W)
    c = bar[int(H * 0.25):int(H * 0.65), a + (b - a) // 5:b - (b - a) // 5].astype(np.int16)
    if c.size == 0: return False
    return float(((c.max(axis=2) - c.min(axis=2)) <= 16).mean()) >= 0.85


def thumb(bar, x1, x2):
    """Fractions -> the card's middle picture (no count, no level) as 576 grey numbers of unit length."""
    import cv2, numpy as np
    H, W = bar.shape[:2]
    a, b = int(x1 * W), int(x2 * W)
    w = b - a
    g = bar[int(H * 0.22):int(H * 0.66), a + int(w * 0.08):b - int(w * 0.08)]
    if g.size == 0: return None
    g = cv2.resize(cv2.cvtColor(g, cv2.COLOR_RGB2GRAY), (24, 24), interpolation=cv2.INTER_AREA).astype(np.float32)
    g -= g.mean()
    return (g / (np.linalg.norm(g) + 1e-6)).ravel()


# ---------------------------------------------------------------- what the bot knows
def _pack(v):
    import base64, numpy as np
    return base64.b64encode(np.asarray(v, np.float16).tobytes()).decode("ascii")


def _unpack(s):
    import base64, numpy as np
    return np.frombuffer(base64.b64decode(s), np.float16).astype(np.float32)


def _self_path(id):
    return LEARN / f"card_bank_{''.join(c for c in str(id) if c.isalnum() or c in '-_') or 'main'}.json"


def _load(id="main"):
    with _B["lock"]:
        if _B["items"] is not None and _B["id"] == id and time.time() - _B["t"] < 120: return _B["items"]
        items = []
        for p in (ROOT / "assets" / "card_bank.json", _self_path(id)):
            try:
                for it in json.loads(p.read_text(encoding="utf-8")).get("items", []):
                    items.append((it["type"], it.get("name") or "", _unpack(it["v"]), p.name.startswith("card_bank_")))
            except (OSError, ValueError, KeyError):
                continue
        _B.update(items=items, t=time.time(), id=id)
        return items


def known(v, id="main", allow=None):
    """A card's thumb -> (type, name, similarity) when the bot is sure which card it is, else None.
    allow: the types it can be (a card with a count "x5" is a troop / spell, one without a hero / siege)."""
    if v is None: return None
    best = {}
    for t, n, e, _mine in _load(id):
        if e.shape != v.shape or (allow and t not in allow): continue
        s = float(e @ v)
        k = (t, n)
        if s > best.get(k, -1): best[k] = s
    if not best: return None
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    (t, n), s = ranked[0]
    other = next((s2 for (t2, n2), s2 in ranked[1:] if t2 != t or (n2 and n and n2 != n)), -1.0)
    if s >= SURE and s - other >= MARGIN: return t, n, s
    return None


def learn(v, type_, name="", id="main"):
    """A card the bot is sure about (coloured) -> remembered (unless it looks like one it knows already)."""
    if v is None or type_ not in ("troop", "spell", "clan", "hero"): return False
    try:
        for t, n, e, _m in _load(id):
            if e.shape == v.shape and float(e @ v) > 0.97 and t == type_: return False
        p = _self_path(id)
        try: d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError): d = {"version": 1, "items": []}
        d["items"] = (d.get("items") or [])[-(SELF_MAX - 1):] + [{"type": type_, "name": name or "", "v": _pack(v),
                                                                 "t": round(time.time())}]
        LEARN.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, p)
        with _B["lock"]: _B["items"] = None
        return True
    except Exception:
        return False


def build_seed(examples, path=None):
    """examples: [(type, name, bar RGB, x1, x2)] -> writes assets/card_bank.json (for Claude / the learning repo)."""
    items = []
    for t, n, bar, x1, x2 in examples:
        v = thumb(bar, x1, x2)
        if v is not None: items.append({"type": t, "name": n, "v": _pack(v)})
    path = Path(path or ROOT / "assets" / "card_bank.json")
    path.write_text(json.dumps({"version": 1, "built": time.strftime("%Y-%m-%d"), "items": items}), encoding="utf-8")
    return len(items)


def continues(bar, last_x2):
    """Is there more of the army to the right of the last whole card (a card cut by the screen's edge)?
    No when the last card ends early (room for one more whole card) or the next slot is an empty dashed one.
    The cut card still shows its left part: its level square (bottom-left) is there. -> bool"""
    if last_x2 < 0.86: return False                  # room for one more whole card: the army ends here
    H, W = bar.shape[:2]
    a = last_x2 + 0.0075
    e = min(1.0, a + CARD_W)
    if (1.0 - a) < CARD_W * 0.4: return True         # only a sliver shows: assume more (a scroll costs little)
    if dashed(bar, a, e): return False
    return has_badge(bar, int(a * W), int(e * W))
