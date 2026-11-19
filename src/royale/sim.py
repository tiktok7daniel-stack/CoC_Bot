"""
The bot thinks before it places a card: a small, fast simulation of the next seconds of the arena (the cards' real
numbers from cards.json: hit points, damage, hit speed, range, speed, splash, who targets what) in which every
candidate card is tried on candidate tiles — like a chess player trying moves in his head:
  "the Cannon here pulls the Hog Rider, it dies before it reaches the tower; there it does not".

  plan(brain, side, threat, candidates, stable, hp) -> (slot, card, tile, score, why) or None

Rules of the simulation (enough to compare placements, not a copy of the game):
  - ground units cross the river on the bridge of their lane; air flies straight
  - buildings-only units (Hog, Giant, Balloon...) go for the nearest building — a building of ours in the middle
    pulls them off the princess tower
  - other units fight the nearest enemy they can hit within sight (5.5 tiles), else walk to the nearest building
  - towers shoot the nearest enemy in range (7.5 tiles); splash hits everything around the target
Board: 18 x 32 tiles, our king at y 0, the river y 15-16, bridges x 3.5 / 14.5.
"""
import math

DT = 0.25
HORIZON = 9.0
SIGHT = 5.5
RIVER_LO, RIVER_HI = 14.6, 16.4
BRIDGES = (3.5, 14.5)
PRINCESS = {"hp": 1400.0, "dps": 62.0, "range": 7.5}
KING = {"hp": 2400.0, "dps": 50.0, "range": 7.0}


class U:
    __slots__ = ("name", "team", "x", "y", "hp", "hp0", "dmg", "hit", "cd", "rng", "spd", "air", "hits_air",
                 "bonly", "splash", "building", "value", "wait", "tower")

    def __init__(self, name, team, x, y, c, hp_frac=1.0, wait=0.0, per_value=1.0):
        self.name, self.team, self.x, self.y = name, team, float(x), float(y)
        n = max(1, c.get("count") or 1)
        self.hp0 = float(c.get("hp") or 300.0)
        self.hp = self.hp0 * max(0.05, min(1.0, hp_frac))
        self.dmg = float(c.get("damage") or 0.0)
        self.hit = max(0.3, (c.get("hit_ms") or 1200) / 1000.0)
        self.cd = 0.0
        self.rng = max(0.6, float(c.get("range") or 1.0))
        self.spd = (c.get("speed") or 0.0) / 60.0
        self.air = bool(c.get("air"))
        self.hits_air = bool(c.get("hits_air"))
        self.bonly = bool(c.get("buildings_only"))
        self.splash = float(c.get("splash") or 0.0)
        self.building = c.get("kind") == "building"
        self.value = per_value / n
        self.wait = wait                         # deploy time left
        self.tower = None

    def can_hit(self, o):
        return (self.hits_air or not o.air) and o.hp > 0


def _tower(team, x, y, kind):
    t = U(kind, team, x, y, {"hp": (KING if kind == "king" else PRINCESS)["hp"], "kind": "building"})
    t.dmg = (KING if kind == "king" else PRINCESS)["dps"]
    t.hit, t.rng, t.hits_air, t.tower, t.spd = 1.0, (KING if kind == "king" else PRINCESS)["range"], True, kind, 0.0
    t.value = 0.0
    return t


def _dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def _step_to(u, tx, ty, dt):
    if not u.air:                                  # the river: over the bridge of this side
        a_side, b_side = u.y < RIVER_LO, ty < RIVER_LO
        if a_side != b_side or RIVER_LO <= u.y <= RIVER_HI:
            bx = min(BRIDGES, key=lambda b: abs(b - u.x))
            if abs(u.x - bx) > 0.4 and not (RIVER_LO - 0.3 <= u.y <= RIVER_HI + 0.3 and abs(u.x - bx) < 1.0):
                ty_b = RIVER_LO - 0.2 if u.y < RIVER_LO else RIVER_HI + 0.2
                tx, ty = bx, ty_b if not (RIVER_LO <= u.y <= RIVER_HI) else ty
    d = math.hypot(tx - u.x, ty - u.y)
    if d < 1e-6: return
    k = min(1.0, u.spd * dt / d)
    u.x += (tx - u.x) * k
    u.y += (ty - u.y) * k


def simulate(units, horizon=HORIZON):
    """units: list of U (towers included). -> the units after `horizon` seconds."""
    t = 0.0
    while t < horizon:
        alive = [u for u in units if u.hp > 0]
        if not any(u.team == "them" and not u.tower for u in alive): break
        for u in alive:
            if u.wait > 0:
                u.wait -= DT
                continue
            u.cd = max(0.0, u.cd - DT)
            foes = [o for o in alive if o.team != u.team and o.hp > 0 and o.wait <= 0]
            if u.bonly:
                cands = [o for o in foes if o.building]
            else:
                cands = [o for o in foes if u.can_hit(o) and (_dist(u, o) <= max(SIGHT, u.rng) or o.building)]
            if u.tower or u.building:
                cands = [o for o in cands if _dist(u, o) <= u.rng + 0.5]
            if not cands: continue
            tgt = min(cands, key=lambda o: _dist(u, o))
            if _dist(u, tgt) <= u.rng + 0.5:
                if u.cd <= 0 and u.dmg > 0:
                    if u.splash > 0:
                        for o in foes:
                            if u.can_hit(o) and math.hypot(o.x - tgt.x, o.y - tgt.y) <= u.splash: o.hp -= u.dmg
                    else:
                        tgt.hp -= u.dmg
                    u.cd = u.hit
            elif u.spd > 0:
                _step_to(u, tgt.x, tgt.y, DT)
        t += DT
    return units


# ------------------------------------------------------------------ planning
def board(brain, stable, hp=None):
    """Their units now (with the health seen) + our towers."""
    from royale.brain import card, unit_card, OUR_TOWERS
    units = []
    for u, x, y in stable:
        cn = unit_card(u)
        c = card(cn) if cn else {}
        if not c or c.get("kind") == "spell": continue
        units.append(U(u, "them", x + 0.5, y + 0.5, c, brain.life(u, x, y), 0.0, c.get("cost", 3)))
    towers = brain.tower_seen or {}
    for side in ("left", "right"):
        tx, ty = OUR_TOWERS[side]
        if towers.get(f"our_{side}", 1.0) is not None and float(towers.get(f"our_{side}", 1.0) or 0) <= 0: continue
        units.append(_tower("us", tx, ty, "princess"))
    kx, ky = OUR_TOWERS["king"]
    units.append(_tower("us", kx, ky, "king"))
    return units


def score(units, cost):
    """Our view after the simulation: their elixir worth killed + what is left of ours - tower damage - cost."""
    s = 0.0
    for u in units:
        if u.team == "them" and not u.tower:
            s += u.value * (1.0 - max(0.0, u.hp) / u.hp0)
            # still alive deep on our side: it will keep hitting
            if u.hp > 0 and u.y < 9: s -= 0.6 * u.value * (u.hp / u.hp0)
        elif u.team == "us" and u.tower:
            s -= (u.hp0 - max(0.0, u.hp)) / 180.0          # ~180 tower hp lost = one elixir lost
        elif u.team == "us" and any(u.can_hit(o) or o.hp <= 0 for o in units if o.team == "them" and not o.tower) \
                and (u.bonly is False):
            # survivors that could fight what came: a counter-push for free (a building only stands there and decays: worth little)
            s += (0.1 if u.building else 0.5) * u.value * max(0.0, u.hp) / u.hp0
    return s - cost


def candidate_tiles(name, side, threat):
    from royale.brain import card, pull_spot, behind_tower
    c = card(name)
    cx, cy = threat.get("center") or (3.5 if side == "left" else 14.5, 14)
    tiles = set()
    if c.get("kind") == "building":
        px, py = pull_spot(side)
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-1, 0, 1, 2, 3):
                tiles.add((px + dx, py + dy))
    else:
        for dx in (-2, 0, 2):
            for dy in (-6, -4, -2, 0):
                tiles.add((int(round(cx)) + dx, int(round(cy)) + dy))
        tiles.add(behind_tower(side))
    return [(max(0, min(17, x)), max(1, min(14, y))) for x, y in tiles]


def plan(brain, side, threat, candidates, stable, hp=None, max_cards=3, prior=None):
    """Every candidate card on its candidate tiles, simulated -> the best (slot, card, tile, score, why)."""
    from royale.brain import card
    import copy
    base = board(brain, stable, hp)
    if not any(u.team == "them" for u in base): return None
    nothing = score(simulate(copy.deepcopy(base)), 0.0)
    best = None
    for slot, name in candidates[:max_cards]:
        c = card(name)
        if not c or c.get("kind") == "spell": continue
        n = max(1, c.get("count") or 1)
        for tx, ty in candidate_tiles(name, side, threat):
            units = copy.deepcopy(base)
            for k in range(n):                     # a group lands around the tile
                ang = 2 * math.pi * k / n
                ox, oy = (0.6 * math.cos(ang), 0.6 * math.sin(ang)) if n > 1 else (0.0, 0.0)
                units.append(U(name, "us", tx + 0.5 + ox, ty + 0.5 + oy, c, 1.0,
                               (c.get("deploy_ms") or 1000) / 1000.0, c.get("cost", 3)))
            sc = score(simulate(units), c.get("cost", 3)) + (prior or {}).get(name, 0.0)
            if best is None or sc > best[3]:
                best = (slot, name, (tx, ty), sc, f"thought it through: {sc - nothing:+.1f} elixir vs doing nothing")
    return best
