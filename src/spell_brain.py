"""
The bot's spell knowledge: which spell is on a card (recognised by the deep brain against the unit pictures) and
where it does its job, as strong players use them — on the base the eyes (YOLO) see, and the line the troops go in:

  lightning     the air defenses nearest the attack (an air army's biggest threat), ~4 bolts each, cast at once
  earthquake    the defenses packed together on the troops' way in
  freeze        the strongest defense in front of the troops (Inferno / Eagle / Scattershot / X-Bow)
  invisibility  same: the strongest defense the troops walk into
  poison        the enemy Clan Castle (its troops come out there), else in front of the troops
  rage / haste / healing / recall / totem / overgrowth / jump / clone / skeleton / bat
                in front of the troops, where they start fighting (each card a step further in)
Unknown spell: in front of the troops (never in the middle of nowhere).
"""
import glob, os, threading

ROLE = {
    "lightning": "air_defense", "earthquake": "cluster", "freeze": "strong", "invisibility": "strong",
    "poison": "clan", "rage": "front", "haste": "front", "healing": "front", "recall": "front", "totem": "front",
    "overgrowth": "front", "jump": "front", "clone": "front", "skeleton": "front", "bat": "front",
    "revive": "front", "ice_block": "strong", "fury": "front",
}
NOW = {"lightning", "earthquake"}          # cast before the troops arrive (they clear the way)
STRONG = ("inferno", "eagle", "scattershot", "xbow", "bombtower", "wizztower")
_E = {"icons": None, "lock": threading.Lock()}


def _icons():
    """The spell pictures' deep-brain numbers (once)."""
    with _E["lock"]:
        if _E["icons"] is not None: return _E["icons"]
        import cv2, numpy as np, screen_cnn
        out = {}
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for p in glob.glob(os.path.join(here, "army_training", "spells", "*.png")):
            im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
            if im is None: continue
            if im.ndim == 3 and im.shape[2] == 4:
                a = im[..., 3:] / 255.0
                im = (im[..., :3] * a + 128 * (1 - a)).astype(np.uint8)
            v = screen_cnn.embed(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
            if v is not None: out[os.path.basename(p)[:-4]] = v
        _E["icons"] = out
        return out


def identify(card_rgb):
    """RGB picture of a spell card -> its name, or None when not sure (best >= 0.55 and 0.05 ahead of the next)."""
    try:
        import screen_cnn
        if not screen_cnn.ready(): return None
        h = card_rgb.shape[0]
        v = screen_cnn.embed(card_rgb[int(0.12 * h):int(0.80 * h)])     # the picture, not the count / level
        icons = _icons()
        if v is None or not icons: return None
        sims = sorted(((float(v @ e), n) for n, e in icons.items()), reverse=True)
        if sims[0][0] >= 0.55 and (len(sims) < 2 or sims[0][0] - sims[1][0] >= 0.05): return sims[0][1]
    except Exception:
        pass
    return None


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def targets(name, n, base, front, k=0):
    """
    Where to cast `n` of spell `name` -> [(x, y)] (one spot per cast). base: what the eyes saw (vision.Base);
    front: the spots in front of the troops (nearest first); k: how many spell cards were cast before.
    """
    role = ROLE.get(name or "", "front")
    objs = getattr(base, "objs", None) or []
    start = front[0] if front else (0.5, 0.45)
    pick = None
    if role == "air_defense":
        ads = sorted((o.center for o in objs if o.name == "ad"), key=lambda c: _dist(c, start))
        if ads:
            per = 4                                      # ~4 bolts take an air defense down
            out = []
            for i in range(n):
                out.append(ads[min(i // per, len(ads) - 1)])
            return out
    elif role == "strong":
        cands = [o for o in objs if o.name in STRONG]
        if cands:
            pick = min(cands, key=lambda o: (STRONG.index(o.name) * 0.05) + _dist(o.center, start)).center
    elif role == "clan":
        cc = [o.center for o in objs if o.name == "clancastle"]
        if cc: pick = min(cc, key=lambda c: _dist(c, start))
    elif role == "cluster":
        strong = [o.center for o in objs if o.name in STRONG + ("ad", "canon", "mortar")]
        if strong:
            pick = max(strong, key=lambda c: sum(_dist(c, d) < 0.12 for d in strong) - _dist(c, start))
    if pick is None:
        pick = front[min(k, len(front) - 1)] if front else start
    return [pick] * max(1, n)
