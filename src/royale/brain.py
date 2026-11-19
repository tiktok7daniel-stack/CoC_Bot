"""
The Clash Royale brain: what to play, where and when — from what the eyes see (royale.vision) and what every card
does (assets/royale/cards.json: game data 16.635). Pure logic, no screen, no taps: royale.game feeds it and plays
what it decides. Every decision takes well under a millisecond.

The arena is a grid of tiles: x 0..17 (left to right), y 0..31 (our king at the bottom, theirs at the top).
Our half is y 0..14, the river y 15..16, theirs y 17..31. Bridges at x 3 and x 14.

How it plays, every look (~4 a second):
  1. TRACK     enemy units seen in 2 of the last 3 looks only (one-frame ghosts of the model are ignored); a new
               enemy unit = a card the opponent played: its cost comes off the opponent's elixir (estimated, with
               the same regeneration as ours) and the card goes into the opponent's cycle
  2. DEFEND    every enemy unit on our half or crossing the river is a threat on its lane, weighted by how far it
               got and what it does (a Hog / Giant / Balloon going for the tower counts most). The answer is the
               cheapest card in hand that really stops it:
                 air  -> only cards that hit air        swarm  -> splash / small spells
                 tank / building-only -> a building in the middle (pulls it) or high damage per second
               placed where it works: buildings in the pull spot, melee in front of the threat, ranged behind the
               tower, spells on the group where it will be a moment later
  3. ATTACK    no threat: attack when we have more elixir than the opponent (estimated), on the weaker tower's lane,
               the win condition at the bridge, a tank from the back when elixir is high; counter-push behind our
               units that survived the defense
  4. NEVER LEAK at 9.5+ elixir something is always played (a cycle card at the back / a push)
  5. SPELLS    on a group worth more elixir than the spell, or to finish a tower that low
  Double elixir (the last minute and overtime): more pressure, both lanes.
"""
import json, os, sys, time
from collections import deque

from royale import knowledge as K
from royale import pro

_ROOT = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DB = {"cards": None}

LEFT_BRIDGE_X, RIGHT_BRIDGE_X = 3, 14
OUR_TOWERS = {"left": (3.5, 5.0), "right": (14.5, 5.0), "king": (8.5, 1.5)}
THEIR_TOWERS = {"left": (3.5, 26.0), "right": (14.5, 26.0), "king": (8.5, 29.5)}
RIVER_Y = 15
REGEN_S = 2.8                               # one elixir every 2.8 s (1.4 s in double elixir)
SPELL_SPLASH_DEFAULT = {"zap": 2.5, "the_log": 2.0, "arrows": 4.0, "fireball": 2.5, "poison": 3.5, "rocket": 2.0,
                        "lightning": 3.5, "tornado": 5.5, "earthquake": 3.5, "giant_snowball": 2.5,
                        "barbarian_barrel": 1.5, "royal_delivery": 3.0, "freeze": 3.0}
SPELL_DAMAGE_DEFAULT = {"zap": 75, "the_log": 96, "arrows": 122, "fireball": 269, "poison": 368, "rocket": 579,
                        "lightning": 413, "earthquake": 170, "giant_snowball": 69, "barbarian_barrel": 72,
                        "royal_delivery": 171}
WIN_SPELLS = {"goblin_barrel", "graveyard", "miner"}           # win conditions you can send anywhere
# units that come out of another one (death / spawner): not a card the opponent played
KAMIKAZE = {"ice_spirit", "fire_spirit", "electro_spirit", "heal_spirit", "wall_breakers", "skeleton_barrel"}
TOWER_DPS = 62.0           # a princess tower helps every defense near it (numbers on the same level as cards.json)
SPAWNED = {"golemite", "lava_pup", "elixir_golem_medium", "elixir_golem_small", "phoenix_egg", "phoenix_small"}


def cards_db():
    if _DB["cards"] is None:
        with open(os.path.join(_ROOT, "assets", "royale", "cards.json"), encoding="utf-8") as f:
            d = json.load(f)
        _DB["cards"] = d["cards"]
        _DB["elixir"] = d.get("elixir") or {"start": 6.0, "steps": [{"seconds": 120, "ms_per_elixir": 2800},
                                                                   {"seconds": 120, "ms_per_elixir": 1400},
                                                                   {"seconds": 60, "ms_per_elixir": 930}]}
        _DB["unit_to_card"] = {}
        # a unit some cards share (skeleton: Skeletons / Skeleton Army / Graveyard / Tombstone): the card that is
        # mostly that unit and cheapest (its own card), the group size picks Skeleton Army (see observe)
        cand = {}
        for name, c in _DB["cards"].items():
            for u in c.get("units") or []:
                cand.setdefault(u, []).append((len(c.get("units") or []), c.get("kind") != "troop", c.get("cost", 9), name))
        for u, lst in cand.items():
            _DB["unit_to_card"][u] = sorted(lst)[0][3]
    return _DB["cards"]


def card(name):
    return cards_db().get(name) or {}


def unit_card(unit_name):
    cards_db()
    return _DB["unit_to_card"].get(unit_name)


# ------------------------------------------------------------------ what a card is
def dps(c):
    d, h = c.get("damage") or 0, c.get("hit_ms") or 0
    return (d * 1000.0 / h) * max(1, c.get("count") or 1) if d and h else 0.0


def roles(name):
    c = card(name)
    k = c.get("kind")
    r = set()
    if k == "spell":
        r.add("spell")
        if name in WIN_SPELLS: r.add("win")
        if name in ("the_log", "zap", "arrows", "barbarian_barrel", "giant_snowball", "royal_delivery"): r.add("small_spell")
        if name in ("fireball", "poison", "rocket", "lightning", "earthquake"): r.add("big_spell")
        return r
    if k == "building":
        r.add("building")
        if c.get("damage"): r.add("defense_building")
        return r
    if c.get("buildings_only"): r.add("win")
    if (c.get("hp") or 0) * max(1, c.get("count") or 1) >= 1500: r.add("tank")
    if (c.get("splash") or 0) > 0: r.add("splash")
    if c.get("hits_air"): r.add("anti_air")
    if (c.get("range") or 0) >= 4: r.add("ranged")
    if (c.get("count") or 1) >= 3: r.add("swarm")
    if dps(c) >= 250: r.add("dps")
    if c.get("cost", 9) <= 2: r.add("cycle")
    if name in ("miner", "goblin_barrel", "graveyard", "hog_rider", "ram_rider", "battle_ram", "royal_hogs",
                "wall_breakers", "balloon", "giant", "royal_giant", "golem", "goblin_giant", "electro_giant",
                "lava_hound", "elixir_golem", "goblin_drill", "x_bow", "mortar", "skeleton_barrel", "sparky"):
        r.add("win")
    return r


# ------------------------------------------------------------------ geometry
def lane(x):
    return "left" if x < 9 else "right"


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def pull_spot(side):
    """A building here pulls a building-targeting troop off the princess tower (the classic middle spot)."""
    return (7, 5) if side == "left" else (10, 5)


def behind_tower(side):
    x, _ = OUR_TOWERS[side]
    return (int(x) - (1 if side == "left" else -1), 2)


def bridge(side, y=14):
    return (LEFT_BRIDGE_X if side == "left" else RIGHT_BRIDGE_X, y)


# ------------------------------------------------------------------ the brain
class Brain:
    def __init__(self, deck=None, params=None):
        self.deck = list(deck or [])
        from royale import learn
        self.p = dict(learn.DEFAULT, **(params or {}))     # this battle's settings (royale.learn picks them)
        self.reset()

    def reset(self):
        self.t0 = time.monotonic()
        self.seen = deque(maxlen=3)            # last looks: sets of (unit, tile_x//2, tile_y//2)
        self.known_enemy = {}                  # track id -> {"unit", "x", "y", "first", "last"}
        self._next_id = 0
        cards_db()
        self.enemy_elixir = float(_DB["elixir"]["start"])     # the game's own timeline: 6 at the start
        self.enemy_t = time.monotonic()
        self.enemy_cycle = deque(maxlen=8)     # cards the opponent played, newest last
        self.last_play = 0.0
        self.last_tiles = deque(maxlen=6)
        self.plays = []
        self.heavy_at = None                   # the opponent just dropped a heavy card (side, time)
        self.enemy_seen = set()                # every card the opponent played this battle (their deck)
        self.arch, self.arch_plan = None, None # their deck's archetype (royale.knowledge)
        self.support_due = None                # (lane, until, our first card): a support goes behind it
        self.heavy_mine_at = 0.0               # our last heavy card (never two together)
        self.support_due_back = False
        self.tower_seen = {}                   # their / our princess towers: highest health seen (crowns)

    # -------------------------------------------------------------- time / elixir
    def elapsed(self):
        return time.monotonic() - self.t0

    def double_elixir(self):
        return self.elapsed() >= 120           # the last minute of 3 + overtime

    def seconds_per_elixir(self, at=None):
        """The game's timeline (game data 16.635): 2.8 s for 2 minutes, 1.4 s (double), then 0.93 s (triple)."""
        t = self.elapsed() if at is None else at
        for st in _DB["elixir"]["steps"]:
            if t < st["seconds"]: return st["ms_per_elixir"] / 1000.0
            t -= st["seconds"]
        return _DB["elixir"]["steps"][-1]["ms_per_elixir"] / 1000.0

    def _regen_enemy(self, now):
        self.enemy_elixir = min(10.0, self.enemy_elixir + (now - self.enemy_t) / self.seconds_per_elixir())
        self.enemy_t = now

    def lead(self, name, x, y, unit=None):
        """Where an enemy unit at (x, y) will be when spell `name` lands: its flight from our king tower (speed from
        the game data) + cast delay, times how fast the unit walks toward us."""
        c = card(name)
        ps = c.get("projectile_speed")
        if not ps: return (x, y)
        fly = dist(OUR_TOWERS["king"], (x, y)) / (ps / 60.0) + 0.25
        vy = None
        for t in self.known_enemy.values():
            if t["unit"] == unit and abs(t["x"] - x) <= 2 and abs(t["y"] - y) <= 2: vy = t.get("vy"); break
        if vy is None or vy > 0.5:                                    # no track yet: its walking speed, toward us
            vy = -((card(unit_card(unit) or "").get("speed") or 60) / 60.0)
        return (x, max(0.0, y + vy * fly))

    # -------------------------------------------------------------- tracking
    def observe(self, enemies, now=None):
        """enemies: [(unit_name, tile_x, tile_y, conf)] from one look. -> stable enemy list [(unit, x, y)]."""
        now = now or time.monotonic()
        self._regen_enemy(now)
        cur = [(u, x, y) for u, x, y, c in enemies if c >= 0.35]
        self.seen.append({(u, x // 2, y // 2) for u, x, y in cur})
        stable = []
        for u, x, y in cur:
            hits = sum(1 for s in self.seen if any(su == u and abs(sx - x // 2) <= 1 and abs(sy - y // 2) <= 1
                                                   for su, sx, sy in s))
            conf = next((c for uu, xx, yy, c in enemies if uu == u and xx == x and yy == y), 0)
            # sure at once (no waiting for a 2nd look): a confident unit, or anything already on our half
            if hits >= 2 or conf >= 0.5 or (y <= RIVER_Y and conf >= 0.4): stable.append((u, x, y))
        # new units = cards the opponent just played (a unit appearing on THEIR half, or a fresh group anywhere)
        for u, x, y in stable:
            tid = next((k for k, t in self.known_enemy.items() if t["unit"] == u and dist((t["x"], t["y"]), (x, y)) <= 4
                        and now - t["last"] < 2.5), None)
            if tid is None:
                self._next_id += 1
                tid = self._next_id
                self.known_enemy[tid] = {"unit": u, "x": x, "y": y, "first": now, "last": now}
                cn = unit_card(u)
                group_recent = any(t["unit"] == u and now - t["first"] < 1.5 and t is not self.known_enemy[tid]
                                   for t in self.known_enemy.values())
                same_now = sum(1 for uu, xx, yy in stable if uu == u and dist((xx, yy), (x, y)) <= 4)
                if cn == "skeletons" and same_now >= 6: cn = "skeleton_army"
                if cn and not group_recent and u not in SPAWNED:   # one card, even when it makes 3 skeletons
                    self.enemy_elixir = max(0.0, self.enemy_elixir - card(cn).get("cost", 3))
                    self.enemy_cycle.append(cn)
                    self.enemy_seen.add(cn)
                    a, plan = K.archetype(self.enemy_seen)
                    if a and a != self.arch: self.arch, self.arch_plan = a, plan
                    if card(cn).get("cost", 0) >= 6 and y >= RIVER_Y + 6:     # heavy card at their back: punish
                        self.heavy_at = (lane(x), now)
            t = self.known_enemy[tid]
            t.update(vy=(y - t["y"]) / max(0.05, now - t["last"]), x=x, y=y, last=now)
        for k in [k for k, t in self.known_enemy.items() if now - t["last"] > 4]:
            del self.known_enemy[k]
        return stable

    # -------------------------------------------------------------- threats
    def threats(self, stable):
        """-> {"left": {...}, "right": {...}}: what is coming to each of our towers."""
        out = {s: {"value": 0.0, "units": [], "air": 0, "ground": 0, "swarm": 0, "tank": 0, "bonly": 0, "center": None}
               for s in ("left", "right")}
        for u, x, y in stable:
            if y > RIVER_Y + 4: continue                        # still far on their side
            cn = unit_card(u)
            c = card(cn) if cn else {}
            per = (c.get("cost", 3) / max(1, c.get("count") or 1)) if c else 1.5
            near = 1.0 + max(0.0, (RIVER_Y + 4 - y) / 6.0)       # deeper in = more urgent
            if c.get("buildings_only"): per *= 1.6               # goes straight for the tower
            s = out[lane(x)]
            s["value"] += per * near
            s["units"].append((u, x, y))
            s["air" if c.get("air") else "ground"] += 1
            if (c.get("count") or 1) >= 3: s["swarm"] += 1
            if (c.get("hp") or 0) >= 1200: s["tank"] += 1
            if c.get("buildings_only"): s["bonly"] += 1
        for s in out.values():
            if s["units"]:
                xs = [x for _, x, _ in s["units"]]; ys = [y for _, _, y in s["units"]]
                s["center"] = (sum(xs) / len(xs), sum(ys) / len(ys))
                # the lane's main threat: the card the knowledge has most to say about, else the most costly
                cards_here = [unit_card(u) for u, _, _ in s["units"] if unit_card(u)]
                # units that appear at our tower without walking there: a Goblin Barrel / Graveyard landed
                near_tower = [u for u, _, y in s["units"] if y <= 8]
                if any(u in ("goblin",) for u in near_tower) and "goblin_barrel" in self.enemy_seen | {"goblin_barrel"} \
                        and not any(u == "spear_goblin" for u, _, _ in s["units"]):
                    cards_here.append("goblin_barrel")
                if any(u == "skeleton" for u in near_tower) and "graveyard" in self.enemy_seen:
                    cards_here.append("graveyard")
                known = [c for c in cards_here if c in K.COUNTERS]               # hand-written first
                pool = known or cards_here
                s["main"] = max(pool, key=lambda c: card(c).get("cost", 0)) if pool else None
                s["urgent"] = any(K.counter(c, card(c)).get("urgent") for c in cards_here)
        return out

    # -------------------------------------------------------------- choosing
    def duel(self, name, threat):
        """The defender `name` against this lane's threat, with the cards' real numbers: how much faster it kills
        the threat than the threat kills it (or reaches the tower). > 1 = it wins."""
        d = card(name)
        if not d or d.get("kind") == "spell": return None
        units = threat["units"]
        if not units: return None
        t_hp = t_dps = 0.0
        air = bonly = False
        for u, _x, _y in units:
            c = card(unit_card(u) or "")
            n = max(1, c.get("count") or 1)
            t_hp += c.get("hp") or 300                           # one detection = one unit (hp is per unit)
            t_dps += dps(c) / n                                  # dps() counts every unit of the card
            air = air or bool(c.get("air"))
            bonly = bonly or bool(c.get("buildings_only"))
        if air and not d.get("hits_air"): return 0.0
        if name in KAMIKAZE:                                     # one hit and gone: what that hit takes off
            return min(2.0, (d.get("damage") or 0) * max(1, d.get("count") or 1) / max(1.0, t_hp) * 2)
        my_dps = dps(d) + TOWER_DPS                              # the tower shoots too
        if (d.get("splash") or 0) > 0 and len(units) >= 3: my_dps *= min(len(units), 4) * 0.8
        if my_dps <= 0: return 0.0
        t_kill = t_hp / my_dps
        my_hp = (d.get("hp") or 0) * max(1, d.get("count") or 1)
        if bonly and d.get("kind") != "building":
            # it walks past troops to the tower: the defender has until it gets there (~ its distance / speed)
            far = min(dist(u2[1:], OUR_TOWERS[lane(u2[1])]) for u2 in units)
            spd = max(0.5, (card(unit_card(units[0][0]) or "").get("speed") or 60) / 60.0)
            t_die = far / spd + 2.0                              # + the tower shooting it too
        else:
            t_die = my_hp / max(1.0, t_dps)
        return t_die / max(0.1, t_kill)

    def crowns(self, towers):
        """(ours, theirs): princess towers that were up and are now down."""
        ours = theirs = 0
        for k, v in (towers or {}).items():
            if v is None: continue
            hi = max(self.tower_seen.get(k, 0.0), float(v))
            self.tower_seen[k] = hi
            if hi > 0.3 and float(v) <= 0.0:
                if k.startswith("their"): ours += 1
                else: theirs += 1
        return ours, theirs

    def _counter_score(self, name, threat):
        """How well card `name` answers this lane's threat (0 = useless)."""
        c, r = card(name), roles(name)
        n_air, n_ground = threat["air"], threat["ground"]
        if n_air and not n_ground and not (c.get("hits_air") or "spell" in r): return 0.0
        score = 1.0
        if n_air and c.get("hits_air"): score += 1.0 + 0.5 * n_air
        if threat["swarm"] or len(threat["units"]) >= 4:
            if "splash" in r or "small_spell" in r: score += 2.0
            if "big_spell" in r: score += 1.0
        if threat["bonly"]:
            if "defense_building" in r or "building" in r: score += 2.5          # pulls it, takes no tower damage
            if "dps" in r or "swarm" in r: score += 1.5
        if threat["tank"]:
            if "dps" in r: score += 2.0
            if "swarm" in r and not threat["swarm"]: score += 1.0
            if "small_spell" in r: score -= 1.0
        if "spell" in r and not (threat["swarm"] or len(threat["units"]) >= 3): score -= 1.5   # not on one unit
        if "win" in r and "building" not in r: score -= 1.5                     # keep the win condition for attack
        if self.p.get("duel_defense", True) and "spell" not in r:
            m = self.duel(name, threat)
            if m is not None:
                if m == 0.0: return 0.0                                          # it cannot even hit it
                score += 1.5 if m >= 1.5 else 0.8 if m >= 1.0 else -1.0          # wins the duel / loses it
        kn = K.counter(threat.get("main"), card(threat.get("main") or ""))
        for rank, want in enumerate(kn.get("want", [])):            # what a good player answers it with
            if want in r or want == name:
                score += 2.5 - 0.6 * rank
                break
        if any(a in r for a in kn.get("avoid", [])): score -= 2.0    # what it beats (Mega Knight on a swarm…)
        keep = K.reserved(self.enemy_seen, name)                    # kept for a threat they have (Log for the barrel)
        if keep and keep != threat.get("main") and not threat.get("urgent"): score -= 2.5
        if self.p.get("pro_moves", True):                           # what real players answered it with
            pro_hand = getattr(self, "_pro_hand", None) or {}
            if pro_hand.get(name):
                score += 3.0 * pro_hand[name] / max(pro_hand.values())
        cost = c.get("cost", 4)
        trade = threat["value"] - cost
        score += 0.25 * max(-4.0, min(3.0, trade))                              # positive elixir trade
        return max(0.0, score)

    def _defense_tile(self, name, side, threat):
        r = roles(name)
        cx, cy = threat["center"] or OUR_TOWERS[side]
        where = K.counter(threat.get("main"), card(threat.get("main") or "")).get("where")
        tx, ty = OUR_TOWERS[side]
        if self.p.get("pro_moves", True) and "spell" not in r and threat.get("main"):
            pt = pro.answer_tile(threat["main"], cy, side, name)                 # where real players put it
            if pt and pt[1] <= 14: return pt
        if where == "tower" and "spell" in r: return (int(tx), int(ty))                # on the tower it hits
        if where == "tower": return (int(tx) + (1 if side == "left" else -1), int(ty) + 1)
        if where == "pull" and "building" in r: return pull_spot(side)
        if where == "late" and "spell" not in r and "building" not in r:            # at the tower: it helps
            return (int(tx) + (2 if side == "left" else -2), int(ty) + 2)
        if where == "behind" and "spell" not in r: return behind_tower(side)
        if "spell" in r:                                                         # where the group will be
            u0 = threat["units"][0][0] if threat["units"] else None
            lx, ly = self.lead(name, cx, cy, u0)
            return (int(round(lx)), int(round(ly)))
        if "building" in r:
            return pull_spot(side)
        c = card(name)
        if "ranged" in r or (c.get("range") or 0) >= 4:
            return behind_tower(side)
        # melee: in front of the threat on our half, toward our tower
        tx = int(round(cx))
        ty = int(min(13, max(2, cy - 2)))
        return (tx, ty)

    def decide(self, hand, ready, elixir, enemies, allies=(), towers=None, now=None):
        """
        hand: the 4 card names in hand (slot 0..3); ready: playable slots; elixir: ours (0..10);
        enemies / allies: [(unit, tile_x, tile_y, conf)]; towers: {"their_left": hp 0..1, ...}
        -> None or {"slot", "card", "tile": (x, y), "why"}
        """
        now = now or time.monotonic()
        stable = self.observe(enemies, now)
        if now - self.last_play < 0.55: return None                              # one card at a time (the game
                                                                                 # shows it ~0.5 s later)
        towers = towers or {}
        playable = [(i, hand[i]) for i in ready if i < len(hand) and hand[i] and card(hand[i])
                    and card(hand[i]).get("cost", 11) <= elixir]
        if not playable: return None
        th = self.threats(stable)

        # 1. defend the lane in more danger
        side = max(th, key=lambda s: th[s]["value"])
        t = th[side]
        late = K.counter(t.get("main"), card(t.get("main") or "")).get("where") == "late"
        if late and t["center"] and t["center"][1] > 13 and elixir < 9.5:
            pass                                                                 # a tank: let it come (tower helps)
        elif t["value"] >= self.p.get("defend_min", 1.5) or (t.get("urgent") and t["units"]):
            self._pro_hand = (pro.answer(t["main"], (t["center"] or (0, 10))[1], side, [n for _, n in playable])
                              if t.get("main") else {})
            best = max(playable, key=lambda p: self._counter_score(p[1], t))
            sc = self._counter_score(best[1], t)
            if sc > 0.8:
                return self._play(best, self._defense_tile(best[1], side, t), f"defend {side} vs "
                                  f"{', '.join(sorted({u for u, _, _ in t['units']}))}", now)

        # 2a. they just dropped a heavy card at their back: punish the other lane first
        if self.p.get("punish_heavy", True) and self.heavy_at and now - self.heavy_at[1] < 4:
            att = self._attack(playable, elixir, stable, allies, towers, now)
            if att: return att
        # 2. spells worth it: a group of theirs on their side, or a tower to finish
        for i, n in playable:
            r = roles(n)
            if "big_spell" in r or "small_spell" in r:
                hit = self._spell_value(n, stable)
                if hit and hit[0] >= card(n).get("cost", 4) * self.p.get("spell_value", 1.0) + 0.5:
                    return self._play((i, n), hit[1], f"spell on a group worth {hit[0]:.0f} elixir", now)

        # 3. attack (first: the support behind the tank / win condition just played)
        sp = self._support(playable, elixir, now)
        if sp: return sp
        att = self._attack(playable, elixir, stable, allies, towers, now)
        if att: return att

        # 4. never leak elixir
        if elixir >= self.p.get("cycle_at", 9.5):
            cheap = min(playable, key=lambda p: (("win" in roles(p[1])), card(p[1]).get("cost", 9)))
            r = roles(cheap[1])
            tile = (8, 1) if "spell" not in r else None
            if tile is None:
                return None
            return self._play(cheap, tile, "full elixir: cycling at the back", now)
        return None

    def _spell_value(self, name, stable):
        rad = (card(name).get("splash") or SPELL_SPLASH_DEFAULT.get(name, 2.5)) * 1.0
        dmg = card(name).get("damage") or SPELL_DAMAGE_DEFAULT.get(name, 100)
        best = None
        for u, x, y in stable:
            val = 0.0
            for u2, x2, y2 in stable:
                if dist((x, y), (x2, y2)) <= rad:
                    c = card(unit_card(u2) or "")
                    hp = c.get("hp") or 300
                    per = c.get("cost", 3) / max(1, c.get("count") or 1)
                    val += per * (1.0 if hp <= dmg else 0.15)                    # killed = full value; chip = little
            if best is None or val > best[0]:
                lx, ly = self.lead(name, x, y, u)
                best = (val, (int(round(lx)), int(round(ly))))
        return best

    def _attack(self, playable, elixir, stable, allies, towers, now):
        double = self.double_elixir()
        weak = "left" if towers.get("their_left", 1.0) <= towers.get("their_right", 1.0) else "right"
        # finish a tower with a big spell
        for i, n in playable:
            if "big_spell" in roles(n):
                for s in ("left", "right"):
                    hp = towers.get(f"their_{s}")
                    if hp is not None and 0 < hp <= 0.12:
                        x, y = THEIR_TOWERS[s]
                        return self._play((i, n), (int(x), int(y)), f"finishing their {s} tower", now)
        advantage = elixir - self.enemy_elixir
        counter = [a for a in (allies or []) if a[2] >= RIVER_Y - 2] if self.p.get("counter_push", True) else []
        push_ok = advantage >= self.p.get("push_adv", 2.0) or (double and elixir >= 6) or counter or elixir >= 9
        # they just dropped a heavy card at their back: the other lane, now (they cannot answer both)
        if self.p.get("punish_heavy", True) and self.heavy_at and now - self.heavy_at[1] < 4:
            push_ok = True
            weak = "right" if self.heavy_at[0] == "left" else "left"
        # the last 30 s of the normal time: behind -> everything goes in; ahead -> only defend
        if self.p.get("endgame", True) and 150 <= self.elapsed() < 180:
            ours, theirs = self.crowns(towers)
            if ours < theirs: push_ok = True
            elif ours > theirs and elixir < 9.5: return None
        # the card that answers our win condition was just played: it is out of their hand -> push now
        recent = list(self.enemy_cycle)[-2:]
        for i, n in playable:
            if "win" in roles(n) and any(a in recent for a in K.ANSWERS_TO.get(n, [])):
                push_ok = True
        if not push_ok: return None
        wins = [(i, n) for i, n in playable if "win" in roles(n)]
        heavy = K.NOT_TOGETHER[0]
        if now - self.heavy_mine_at < 6:                                         # never two heavies at once
            wins = [(i, n) for i, n in wins if n not in heavy]
        if counter:
            side = lane(sum(a[1] for a in counter) / len(counter))
        else:
            side = weak
        for i, n in sorted(wins, key=lambda p: -card(p[1]).get("cost", 0)):
            r = roles(n)
            c = card(n)
            if n in WIN_SPELLS:
                x, y = THEIR_TOWERS[side]
                return self._play((i, n), (int(x), int(y) - 1), f"{n} on their {side} tower", now)
            pt = pro.place(n, side) if self.p.get("pro_moves", True) else None   # where real players start it
            if "tank" in r and c.get("speed", 60) <= 60 and not counter:
                if elixir >= 8 or double:                                       # a big push from the back
                    back = pt if pt and pt[1] <= 3 else (LEFT_BRIDGE_X if side == "left" else RIGHT_BRIDGE_X, 1)
                    return self._play((i, n), back, f"{n}: push from the back ({side})", now)
                continue
            return self._play((i, n), pt or bridge(side), f"{n} at the {side} {'(pro spot)' if pt else 'bridge'}", now)
        if counter:                                                              # support the counter-push
            sup = [(i, n) for i, n in playable if "spell" not in roles(n) and "building" not in roles(n)]
            if sup:
                i, n = min(sup, key=lambda p: card(p[1]).get("cost", 9))
                x = int(sum(a[1] for a in counter) / len(counter))
                return self._play((i, n), (x, 12), "supporting the counter-push", now)
        return None

    def _support(self, playable, elixir, now):
        """Our tank / win condition just went in: its support goes behind it (royale.knowledge SUPPORT)."""
        if not self.support_due or now > self.support_due[1]: return None
        side, _until, first = self.support_due
        sup = [(i, n) for i, n in playable if n in K.SUPPORT.get(first, [])]
        fol = pro.follows(first, [n for _, n in playable]) if self.p.get("pro_moves", True) else {}
        if not sup:                                     # what real players played right after it, same lane
            sup = [(i, n) for i, n in playable if fol.get(n, 0) >= 0.08 and "spell" not in roles(n)]
        if not sup: return None
        i, n = max(sup, key=lambda p: (fol.get(p[1], 0), -card(p[1]).get("cost", 9)))
        y = 1 if self.support_due_back else 11
        self.support_due = None
        return self._play((i, n), (LEFT_BRIDGE_X if side == "left" else RIGHT_BRIDGE_X, y), f"{n} behind the {first}", now)

    def _play(self, pick, tile, why, now):
        i, n = pick
        if tile is None: return None
        if n in K.SUPPORT or (pro.data().get("follow", {}).get(pro.key(n)) and "win" in roles(n)):  # its support next
            self.support_due = (lane(tile[0]), now + 5.0, n)
            self.support_due_back = tile[1] <= 3
        if n in K.NOT_TOGETHER[0]: self.heavy_mine_at = now
        x, y = int(max(0, min(17, tile[0]))), int(tile[1])
        if not card(n).get("anywhere"):
            y = max(0, min(14, y))                                               # our half only (towers up: more)
        self.last_play = now
        self.last_tiles.append((x, y))
        d = {"slot": i, "card": n, "tile": (x, y), "why": why, "t": round(self.elapsed(), 1)}
        self.plays.append(d)
        return d
