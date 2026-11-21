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


def predict_deck(seen, k=8):
    """The opponent's cards seen so far -> their likely whole deck [(card key, probability)], the seen ones first.
    P(card | each seen card) from 252k decks, averaged: two or three cards seen are usually enough."""
    decks = data().get("decks", {})
    seen_k = [key(s) for s in seen or () if key(s) in decks]
    if not seen_k: return []
    score = {}
    for s in seen_k:
        for o, p in decks[s].get("with", []):
            score[o] = score.get(o, 0.0) + p
    out = [(s, 1.0) for s in dict.fromkeys(seen_k)]
    out += sorted(((o, round(v / len(seen_k), 3)) for o, v in score.items() if o not in seen_k), key=lambda x: -x[1])
    return out[:k]


# ------------------------------------------------------------------ who won (assets/royale/pro_wins.json)
_W = {"d": None}


def wins():
    if _W["d"] is None:
        try:
            with open(os.path.join(_ROOT, "assets", "royale", "pro_wins.json"), encoding="utf-8") as f:
                _W["d"] = json.load(f)
        except (OSError, ValueError):
            _W["d"] = {}
    return _W["d"]


def answer_wins(threat, y, hand, min_n=40):
    """Our hand's cards -> (games, win rate of the player who answered `threat` with it) in 252k real games."""
    a = wins().get("answers") or {}
    b = min(31, max(0, int(y))) // 4
    row = None
    for bb in (b, b + 1, b - 1):
        row = a.get(f"{key(threat)}|{bb}")
        if row: break
    if not row: return {}
    return {n: tuple(row[key(n)]) for n in hand if key(n) in row and row[key(n)][0] >= min_n}


def combo_win(a, b):
    v = (wins().get("combos") or {}).get(f"{key(a)}+{key(b)}")
    return tuple(v) if v else None


WC = {"hogrider", "giant", "golem", "royalgiant", "balloon", "goblinbarrel", "miner", "graveyard", "xbow", "mortar",
      "lavahound", "ramrider", "battleram", "electrogiant", "goblingiant", "royalhogs", "wallbreakers", "goblindrill",
      "elixirgolem", "threemusketeers", "sparky", "pekka", "megaknight", "skeletonbarrel", "goblinstein", "bossbandit",
      "runegiant", "giantskeleton", "princess", "rocket"}


def their_plan(cards, cost=None):
    """The opponent's deck plan (its main win condition) from the cards seen / guessed, or None."""
    w = [key(c) for c in cards if key(c) in WC]
    if not w: return None
    return max(w, key=lambda c: (cost or {}).get(c, 4))


def matchup_answers(plan, threat, y, hand, min_n=40):
    """Against a deck whose plan is `plan`: our hand's cards -> (games, win rate, winners' best tile or None)."""
    if not plan: return {}
    m = wins().get("matchup") or {}
    b = min(31, max(0, int(y))) // 4
    row = None
    for bb in (b, b + 1, b - 1):
        row = m.get(f"{plan}|{key(threat)}|{bb}")
        if row: break
    if not row: return {}
    out = {}
    for n in hand:
        v = row.get(key(n))
        if v and v[0] >= min_n:
            out[n] = (v[0], v[1], tuple(v[2][0][:2]) if v[2] else None)
    return out


def winners_place(plan, name, side, min_share=0.3):
    """Where the WINNERS started `name` against a deck whose plan is `plan` -> (x, y) on `side` or None."""
    if not plan: return None
    v = (wins().get("wplace") or {}).get(f"{plan}|{key(name)}")
    if not v or v[0][2] < min_share: return None
    x, y = v[0][0], v[0][1]
    return (x, y) if side == "left" else (17 - x, y)


# ------------------------------------------------------------------ the attack atlas (scripts/build_royale_attack_atlas.py)
_AA = {"d": None}


def attack_best(name, side):
    """Where an attack with `name` hurts most against the defenses real players make -> (x, y) on `side` or None."""
    if _AA["d"] is None:
        try:
            with open(os.path.join(_ROOT, "assets", "royale", "attack_atlas.json"), encoding="utf-8") as f:
                _AA["d"] = json.load(f)
        except (OSError, ValueError):
            _AA["d"] = {}
    v = (_AA["d"].get("atlas") or {}).get(name)
    if not v: return None
    x, y = v["best_xy"]
    return (x, y) if side == "left" else (17 - x, y)
