"""
What real players did in 252,238 Clash Royale games (assets/royale/pro.json, made by scripts/build_royale_pro.py from
the IL_Replay set): the brain asks it every decision, the same way a player remembers "against a Hog Rider here,
people put a Cannon there".

  answer(threat, y, side, hand)  -> {card: share}   how often each card of our hand was the answer to that threat
  answer_tile(threat, y, side, card) -> (x, y)       where they put it
  place(card, side)              -> (x, y) / None    where they put the card when they start an attack with it
  follows(card, hand)            -> {card: share}   what they played next to it (the push's support)

The file is made with the threat / play always on the LEFT lane: tiles are mirrored back for the right one.
"""
import json, os, sys

_ROOT = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_D = {"d": None}


def key(name):
    return str(name or "").lower().replace("-", "").replace("_", "").replace(" ", "").replace(".", "")


def data():
    if _D["d"] is None:
        try:
            with open(os.path.join(_ROOT, "assets", "royale", "pro.json"), encoding="utf-8") as f:
                _D["d"] = json.load(f)
        except (OSError, ValueError):
            _D["d"] = {}
    return _D["d"]


def games():
    return int(data().get("games") or 0)


def _side(x, y, side):
    return (int(x), int(y)) if side == "left" else (17 - int(x), int(y))


def _row(threat, y):
    r = data().get("respond", {})
    b = min(31, max(0, int(y))) // 4
    for bb in (b, b + 1, b - 1, b + 2, b - 2):                  # the nearest row with enough games
        v = r.get(f"{key(threat)}|{bb}")
        if v: return v
    return None


def answer(threat, y, side, hand):
    """Our hand's cards -> the share of real games where that card answered `threat` (0..1)."""
    v = _row(threat, y)
    if not v: return {}
    share = {c: p for c, p in v.get("cards", [])}
    return {n: share[key(n)] for n in hand if key(n) in share}


def answer_tile(threat, y, side, name):
    v = _row(threat, y)
    if not v: return None
    t = (v.get("tiles") or {}).get(key(name))
    if not t: return None
    x, yy = (int(a) for a in t[0][0].split("|"))
    return _side(x, yy, side)


def place(name, side, min_share=0.25):
    v = data().get("place", {}).get(key(name))
    if not v or not v.get("top"): return None
    xy, p = v["top"][0]
    if p < min_share: return None
    x, y = (int(a) for a in xy.split("|"))
    return _side(x, y, side)


def follows(name, hand):
    v = data().get("follow", {}).get(key(name))
    if not v: return {}
    share = {c: p for c, p in v.get("top", [])}
    return {n: share[key(n)] for n in hand if key(n) in share}
