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


_LEVELS = {"m": None}


def level_mult(level):
    """x the level-1 numbers for a card shown at `level` (the game's own table, cards.json "levels")."""
    if not level: return 1.0
    if _LEVELS["m"] is None:
        try:
            import json, os
            from royale.brain import _ROOT
            with open(os.path.join(_ROOT, "assets", "royale", "cards.json"), encoding="utf-8") as f:
                _LEVELS["m"] = (json.load(f).get("levels") or {}).get("multiplier") or []
        except Exception:
            _LEVELS["m"] = []
    m = _LEVELS["m"]
    return float(m[max(0, min(len(m) - 1, int(level) - 1))]) if m else 1.0


def tower_mult(level):
    """Crown towers grow a little slower than cards (level 11 princess tower 3052 hp = 1400 x 2.18)."""
    return 1.0 + (level_mult(level) - 1.0) * 0.77 if level else 1.0


class U:
    __slots__ = ("name", "team", "x", "y", "hp", "hp0", "dmg", "hit", "cd", "rng", "spd", "air", "hits_air",
                 "bonly", "splash", "building", "value", "wait", "tower", "born", "radius", "sight", "life")

    def __init__(self, name, team, x, y, c, hp_frac=1.0, wait=0.0, per_value=1.0, level=None):
        self.name, self.team, self.x, self.y = name, team, float(x), float(y)
        n = max(1, c.get("count") or 1)
        k = level_mult(level)                    # the card's real level (the numbers in cards.json are level 1)
        self.hp0 = float(c.get("hp") or 300.0) * k
        self.hp = self.hp0 * max(0.05, min(1.0, hp_frac))
        self.dmg = float(c.get("damage") or 0.0) * k
        self.radius = float(c.get("radius") or 0.5)
        self.sight = float(c.get("sight") or SIGHT)
        self.life = float(c.get("life_s") or 30.0)
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
        self.born = 0.0

    def can_hit(self, o):
        return (self.hits_air or not o.air) and o.hp > 0


def _tower(team, x, y, kind, level=None):
    k = tower_mult(level)
    t = U(kind, team, x, y, {"hp": (KING if kind == "king" else PRINCESS)["hp"] * k, "kind": "building"})
    t.dmg = (KING if kind == "king" else PRINCESS)["dps"] * k
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


def step(units, dt=DT):
    """One moment of the arena: every unit waits / targets / walks / hits."""
    alive = [u for u in units if u.hp > 0]
    for u in alive:
        if u.wait > 0:
            u.wait -= dt
            continue
        u.cd = max(0.0, u.cd - dt)
        foes = [o for o in alive if o.team != u.team and o.hp > 0 and o.wait <= 0]
        if u.bonly:
            cands = [o for o in foes if o.building]
        else:
            cands = [o for o in foes if u.can_hit(o) and (_dist(u, o) <= max(u.sight, u.rng) or o.building)]
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
            # body block: an enemy body right in front (between it and its target) holds a ground unit back —
            # a Skeleton in front of a Hog Rider costs it about half a second
            slow = 1.0
            if not u.air:
                for o in foes:
                    if o.air or o.building or o.tower: continue
                    if _dist(u, o) <= u.radius + o.radius + 0.15 and _dist(o, tgt) < _dist(u, tgt):
                        slow = 0.35
                        break
            _step_to(u, tgt.x, tgt.y, dt * slow)


def simulate(units, horizon=HORIZON):
    """units: list of U (towers included). -> the units after `horizon` seconds."""
    t = 0.0
    while t < horizon:
        if not any(u.team == "them" and not u.tower and u.hp > 0 for u in units): break
        step(units, DT)
        t += DT
    return units


# ------------------------------------------------------------------ a whole battle (both sides)
class Arena:
    """Both sides with their towers; cards are played into it and time runs: used to replay real games and see
    the whole board at every moment (training the board brain), and by the bot to look ahead."""
    LIFETIME = 30.0                                # buildings disappear after ~30 s

    def __init__(self):
        from royale.brain import OUR_TOWERS, THEIR_TOWERS
        self.units = [_tower("us", *OUR_TOWERS["left"], "princess"), _tower("us", *OUR_TOWERS["right"], "princess"),
                      _tower("us", *OUR_TOWERS["king"], "king"), _tower("them", *THEIR_TOWERS["left"], "princess"),
                      _tower("them", *THEIR_TOWERS["right"], "princess"), _tower("them", *THEIR_TOWERS["king"], "king")]
        self.t = 0.0
        self.born = {}
        self.pending = []                          # spells: (land time, team, x, y, card)

    def play(self, team, name, x, y):
        from royale.brain import card
        c = card(name)
        if not c: return
        if c.get("kind") == "spell":
            fly = 1.0 if name not in ("the_log", "barbarian_barrel", "zap") else 0.3
            self.pending.append((self.t + fly, team, x + 0.5, y + 0.5, name))
            return
        n = max(1, c.get("count") or 1)
        for k in range(n):
            ang = 2 * math.pi * k / n
            ox, oy = (0.6 * math.cos(ang), 0.6 * math.sin(ang)) if n > 1 else (0.0, 0.0)
            u = U(name, team, x + 0.5 + ox, y + 0.5 + oy, c, 1.0, (c.get("deploy_ms") or 1000) / 1000.0, c.get("cost", 3))
            u.born = self.t
            self.units.append(u)
            if u.building: self.born[id(u)] = self.t

    def _land(self, team, x, y, name):
        from royale.brain import card, SPELL_SPLASH_DEFAULT, SPELL_DAMAGE_DEFAULT
        c = card(name)
        rad = c.get("splash") or SPELL_SPLASH_DEFAULT.get(name, 2.5)
        dmg = c.get("damage") or SPELL_DAMAGE_DEFAULT.get(name, 100)
        for o in self.units:
            if o.team != team and o.hp > 0 and math.hypot(o.x - x, o.y - y) <= rad:
                o.hp -= dmg * (0.3 if o.tower else 1.0)
        for un in c.get("units") or []:            # Goblin Barrel, Graveyard...: what it brings lands there
            from royale.brain import card as _c
            uc = _c(un) or {"hp": 80, "damage": 50, "hit_ms": 1100, "range": 0.8, "speed": 90, "count": 1}
            for k in range(3 if name == "goblin_barrel" else 1):
                nu = U(un, team, x + 0.4 * (k - 1), y, uc, 1.0, 0.0, c.get("cost", 3) / 3)
                nu.born = self.t
                self.units.append(nu)

    def run_to(self, t, dt=0.4):
        while self.t < t:
            for p in [p for p in self.pending if p[0] <= self.t]:
                self.pending.remove(p)
                self._land(p[1], p[2], p[3], p[4])
            step(self.units, dt)
            self.t += dt
            for u in self.units:
                if u.building and not u.tower and self.t - self.born.get(id(u), self.t) > u.life: u.hp = 0
            self.units = [u for u in self.units if u.hp > 0 or u.tower]

    def board(self, me="us"):
        """[(mine, card, x, y, life, air, building, fresh, age)] seen from `me` (its king at y 0); fresh = still
        deploying / a spell in the air; age = seconds since it was played."""
        out = []
        for u in self.units:
            if u.tower or u.hp <= 0: continue
            x, y = (u.x, u.y) if me == "us" else (17.0 - u.x, 31.0 - u.y)
            out.append((u.team == me, u.name, x, y, max(0.0, u.hp) / u.hp0, u.air, u.building, u.wait > 0,
                        self.t - u.born))
        for _t, team, x, y, name in self.pending:              # spells in the air
            if me != "us": x, y = 17.0 - x, 31.0 - y
            out.append((team == me, name, x, y, 1.0, False, False, True, 0.0))
        return out

    def towers(self, me="us"):
        """Life of the 6 towers, ours first (left, right, king) then theirs, seen from `me`."""
        def side(team):
            ts = [u for u in self.units if u.tower and u.team == team]
            ts.sort(key=lambda u: (u.tower == "king", u.x if me == "us" else -u.x))
            return [max(0.0, u.hp) / u.hp0 for u in ts]
        other = "them" if me == "us" else "us"
        return side(me) + side(other)


# ------------------------------------------------------------------ planning
def _tower_life(brain, k):
    """0..1 life of a tower from what the eyes read (1 when unknown)."""
    hi = (getattr(brain, "tower_seen", None) or {}).get(k)
    now = (getattr(brain, "_towers_now", None) or {}).get(k)
    try:
        return max(0.0, min(1.0, float(now) / max(1e-6, float(hi)))) if hi and now is not None else 1.0
    except (TypeError, ValueError):
        return 1.0


def board(brain, stable, hp=None, allies=None, their_towers=False):
    """The arena now: their units (with the life seen), OUR units already there (so it never sends a second
    defender for what the first one handles), our towers with their real life, and theirs when attacking."""
    from royale.brain import card, unit_card, OUR_TOWERS, THEIR_TOWERS
    units = []
    for u, x, y in stable:
        cn = unit_card(u)
        c = card(cn) if cn else {}
        if not c or c.get("kind") == "spell": continue
        units.append(U(u, "them", x + 0.5, y + 0.5, c, brain.life(u, x, y), 0.0, c.get("cost", 3),
                       getattr(brain, "their_level", None)))
    for a in (allies if allies is not None else getattr(brain, "_allies", []) or []):
        cn = unit_card(a[0])
        c = card(cn) if cn else {}
        if not c or c.get("kind") == "spell": continue
        units.append(U(a[0], "us", a[1] + 0.5, a[2] + 0.5, c, 1.0, 0.0, c.get("cost", 3), brain.my_level(cn)))
    for team, towers, pre in (("us", OUR_TOWERS, "our"), ("them", THEIR_TOWERS, "their")):
        if team == "them" and not their_towers: continue
        for side in ("left", "right"):
            life = _tower_life(brain, f"{pre}_{side}")
            if life <= 0: continue
            lv = getattr(brain, "king_level", None) if team == "us" else getattr(brain, "their_level", None)
            t = _tower(team, *towers[side], "princess", lv)
            t.hp = t.hp0 * life
            units.append(t)
        units.append(_tower(team, *towers["king"], "king",
                            getattr(brain, "king_level", None) if team == "us" else getattr(brain, "their_level", None)))
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
            s -= (u.hp0 - max(0.0, u.hp)) / u.hp0 * 7.8    # a princess tower ~ 8 elixir (180 of 1400 hp = 1)
        elif u.team == "them" and u.tower:
            s += (u.hp0 - max(0.0, u.hp)) / u.hp0 * 7.8    # their tower hp taken (attacks)
        elif u.team == "us" and any(u.can_hit(o) or o.hp <= 0 for o in units if o.team == "them" and not o.tower) \
                and (u.bonly is False):
            # survivors that could fight what came: a counter-push for free (a building only stands there and decays: worth little)
            s += (0.1 if u.building else 0.5) * u.value * max(0.0, u.hp) / u.hp0
    return s - cost


def candidate_tiles(name, side, threat):
    """Where a defender can go: around the threat's path, behind the tower, the pull spots for buildings and the
    KITE spots in the middle (a unit there drags their troops between both towers, where both shoot them)."""
    from royale.brain import card, pull_spot, behind_tower
    c = card(name)
    cx, cy = threat.get("center") or (3.5 if side == "left" else 14.5, 14)
    tiles = set()
    mid = 8 if side == "left" else 9
    if c.get("kind") == "building":
        px, py = pull_spot(side)
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-1, 0, 1, 2, 3, 4):
                tiles.add((px + dx, py + dy))
        tiles.update({(mid, 9), (mid, 10)})
    else:
        for dx in (-3, -1, 1, 3):
            for dy in (-7, -5, -3, -1):
                tiles.add((int(round(cx)) + dx, int(round(cy)) + dy))
        tiles.add(behind_tower(side))
        tiles.update({(mid, 8), (mid, 11), (mid, 5)})           # kite / pull to the middle
    return [(max(0, min(17, x)), max(1, min(14, y))) for x, y in tiles]


def _with(base, name, c, tx, ty, delay=0.0, level=None):
    import copy
    units = copy.deepcopy(base)
    n = max(1, c.get("count") or 1)
    for k in range(n):                         # a group lands around the tile
        ang = 2 * math.pi * k / n
        ox, oy = (0.6 * math.cos(ang), 0.6 * math.sin(ang)) if n > 1 else (0.0, 0.0)
        units.append(U(name, "us", tx + 0.5 + ox, ty + 0.5 + oy, c, 1.0,
                       (c.get("deploy_ms") or 1000) / 1000.0 + delay, c.get("cost", 3), level))
    return units


def plan(brain, side, threat, candidates, stable, hp=None, max_cards=3, prior=None):
    """Every candidate card on its candidate tiles — now, and 1.5 s later — simulated.
    -> (slot, card, tile, score, why, gain over doing nothing, wait) or None. wait=True: placing it a bit later is
    better (a building would decay waiting / the troop would meet them out of the tower's range) -> hold it."""
    from royale.brain import card
    import copy
    base = board(brain, stable, hp)
    if not any(u.team == "them" for u in base): return None
    nothing = score(simulate(copy.deepcopy(base)), 0.0)
    best = None
    for slot, name in candidates[:max_cards]:
        c = card(name)
        if not c or c.get("kind") == "spell": continue
        for tx, ty in candidate_tiles(name, side, threat):
            for delay in (0.0, 1.5):
                sc = score(simulate(_with(base, name, c, tx, ty, delay, brain.my_level(name))), c.get("cost", 3)) \
                    + (prior or {}).get(name, 0.0)
                if delay: sc -= 0.15                    # a small price for waiting (the picture may change)
                if best is None or sc > best[3]:
                    best = (slot, name, (tx, ty), sc, f"thought it through: {sc - nothing:+.1f} elixir vs doing nothing",
                            sc - nothing, delay > 0)
    return best


def attack_plan(brain, candidates, stable, horizon=12.0):
    """Our attack, simulated against their towers and the defenders already on the board: each win condition /
    troop on the pro spots of both lanes. -> (slot, card, tile, score, gain) or None."""
    from royale.brain import card, LEFT_BRIDGE_X, RIGHT_BRIDGE_X
    from royale import pro
    base = board(brain, stable, their_towers=True)
    nothing = score(_run(base, horizon), 0.0)
    best = None
    for slot, name in candidates:
        c = card(name)
        if not c or c.get("kind") in ("spell", "building"): continue
        for side in ("left", "right"):
            bx = LEFT_BRIDGE_X if side == "left" else RIGHT_BRIDGE_X
            tiles = {(bx, 14), (bx, 11), (bx, 1)}
            pt = pro.place(name, side, min_share=0.1)
            if pt: tiles.add(pt)
            for tx, ty in tiles:
                ty = max(0, min(14, ty))
                sc = score(_run(_with(base, name, c, tx, ty, 0.0, brain.my_level(name)), horizon), c.get("cost", 3))
                if best is None or sc > best[3]:
                    best = (slot, name, (tx, ty), sc, sc - nothing)
    return best


def _run(units, horizon):
    import copy
    units = copy.deepcopy(units)
    t = 0.0
    while t < horizon:
        step(units, DT)
        t += DT
    return units
