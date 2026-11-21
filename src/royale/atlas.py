"""
The defense atlas at play time (built by scripts/build_royale_atlas.py: every defending card on every tile at
several moments against every attacking card, millions of simulated defenses). When a threat comes, the bot looks
up the best spots ANY card of its hand had against it — spots no player taught it — and gives them to the thinking
(royale.sim.plan), which checks them against the board as it really is right now.
"""
import json, os, sys

_ROOT = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_S = {"d": None}


def data():
    if _S["d"] is None:
        try:
            with open(os.path.join(_ROOT, "assets", "royale", "atlas.json"), encoding="utf-8") as f:
                _S["d"] = json.load(f)
        except (OSError, ValueError):
            _S["d"] = {}
    return _S["d"]


def _spot(x, y, side):
    """Where the threat was dropped (seen from the left lane) -> the atlas spot it is closest to."""
    spots = (data().get("meta") or {}).get("spots") or {}
    lx = x if side == "left" else 17 - x
    return min(spots, key=lambda k: (spots[k][0] - lx) ** 2 + (spots[k][1] - y) ** 2) if spots else None


def answers(threat, first_xy, side, hand, others=()):
    """-> {card: [(x, y, delay, score, tower hp lost), ...]} for the cards of our hand, tiles for THIS lane.
    others: their other cards on the lane — a two-card attack the atlas knows (Ice Golem + Hog...) comes first."""
    a = data().get("atlas") or {}
    sp = _spot(first_xy[0], first_xy[1], side)
    row = None
    for o in others or ():
        row = a.get(f"{threat}+{o}|{sp}") or a.get(f"{o}+{threat}|{sp}") or \
            a.get(f"{threat}+{o}|bridge") or a.get(f"{o}+{threat}|bridge")
        if row: break
    row = row or a.get(f"{threat}|{sp}")
    if not row: return {}
    out = {}
    for n in hand:
        for x, y, delay, sc, lost in row.get(n) or []:
            out.setdefault(n, []).append(((x if side == "left" else 17 - x), y, delay, sc, lost))
    return out


def none_cost(threat, first_xy, side):
    a = data().get("atlas") or {}
    row = a.get(f"{threat}|{_spot(first_xy[0], first_xy[1], side)}") or {}
    return row.get("none"), row.get("none_lost")
