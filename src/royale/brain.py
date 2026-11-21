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
from royale import policy
from royale import sim
from royale import board as board_brain

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
ROLLING = {"the_log", "barbarian_barrel"}                                   # spells that roll forward from the drop point
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
        self.mem = None                                     # royale.memory.Memory: set by the game
        self.reset()

    def reset(self):
        self.t0 = time.monotonic()
        self.danger, self.hp_seen = [], {}       # their spells landing (keep troops out) / life read from bars
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
        self.enemy_plays = []                  # (second, card, lane): how they played (the match summary)
        self.enemy_hist = []                   # (second, card, tile x, tile y): what the learned brain sees
        self.steps = []                        # what it saw + what it did, every moment (royale.selfplay learns)
        self.opp_steps = []                    # the same for every card the OPPONENT played (seen from their side)
        self.deaths = []                       # their units that died: (second, unit, x, y, elixir worth, hits buildings only)
        self._my_el = 5.0
        self.tower_log = []                    # (second, towers) once a second: how each moment turned out
        self._ctx, self._last_wait = None, -9.0
        self._pol = None
        self.predicted = set()                 # their whole deck guessed from the cards seen (252k decks)
        if getattr(self, "mem", None): self.mem.start()

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
        if name in ROLLING:                       # it rolls forward from where it is dropped: drop it just behind them
            return (x, max(0.0, y - 1.0))
        ps = c.get("projectile_speed")
        if not ps: return (x, y)
        fly = dist(OUR_TOWERS["king"], (x, y)) / (ps / 60.0) + 0.25
        vy = None
        for t in self.known_enemy.values():
            if t["unit"] == unit and abs(t["x"] - x) <= 2 and abs(t["y"] - y) <= 2: vy = t.get("vy"); break
        if vy is None or vy > 0.5:                                    # no track yet: its walking speed, toward us
            vy = -((card(unit_card(unit) or "").get("speed") or 60) / 60.0)
            # already at one of our towers / buildings: it stands there hitting it, it does not walk on
            if any(dist((x, y), tw) <= 3.0 for k, tw in OUR_TOWERS.items()): vy = 0.0
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
                self.known_enemy[tid] = {"unit": u, "x": x, "y": y, "first": now, "last": now, "fx": x, "fy": y}
                cn = unit_card(u)
                group_recent = any(t["unit"] == u and now - t["first"] < 1.5 and t is not self.known_enemy[tid]
                                   for t in self.known_enemy.values())
                same_now = sum(1 for uu, xx, yy in stable if uu == u and dist((xx, yy), (x, y)) <= 4)
                if cn == "skeletons" and same_now >= 6: cn = "skeleton_army"
                # the same card again within 6 s is the same play seen twice (a flicker of the eyes, a unit that
                # walked out of sight and back): counting it again put their elixir at 0 all battle long, so the
                # bot thought it was always ahead and spent everything (5.38)
                again = cn and any(p[1] == cn and self.elapsed() - p[0] < 6.0 for p in self.enemy_hist[-4:])
                if cn and not group_recent and not again and u not in SPAWNED:   # one card, even 3 skeletons
                    self._learn_opponent(cn, x, y)                    # their move: a lesson too
                    self.enemy_elixir = max(0.0, self.enemy_elixir - card(cn).get("cost", 3))
                    self.enemy_cycle.append(cn)
                    self.enemy_plays.append((round(self.elapsed()), cn, lane(x)))
                    self.enemy_hist.append((self.elapsed(), cn, x, y))
                    self._predict()
                    self.enemy_seen.add(cn)
                    a, plan = K.archetype(self.enemy_seen | self.predicted)
                    if a and a != self.arch: self.arch, self.arch_plan = a, plan
                    if card(cn).get("cost", 0) >= 6 and y >= RIVER_Y + 6:     # heavy card at their back: punish
                        self.heavy_at = (lane(x), now)
            t = self.known_enemy[tid]
            t.update(vy=(y - t["y"]) / max(0.05, now - t["last"]), x=x, y=y, last=now)
        for k in [k for k, t in self.known_enemy.items() if now - t["last"] > 4]:
            t = self.known_enemy.pop(k)
            # gone from the arena = killed (the whole arena is in view): what it was worth, where, when
            cn = unit_card(t["unit"])
            if cn and t["y"] <= RIVER_Y + 6 and t["unit"] not in SPAWNED:
                c = card(cn)
                self.deaths.append((self.elapsed() - 4.0, t["unit"], t["x"], t["y"],
                                    c.get("cost", 3) / max(1, c.get("count") or 1), bool(c.get("buildings_only"))))
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
            per *= self.life(u, x, y)                            # a unit about to die is worth less of a card
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
        zeros = self.__dict__.setdefault("_tower_zero", {})
        for k, v in (towers or {}).items():
            if v is None: continue
            hi = max(self.tower_seen.get(k, 0.0), float(v))
            self.tower_seen[k] = hi
            # down only after 3 looks in a row read it at 0: one covered / misread look is not a lost tower
            zeros[k] = zeros.get(k, 0) + 1 if float(v) <= 0.0 else 0
            if hi > 0.3 and zeros[k] >= 3:
                if k.startswith("their"): ours += 1
                else: theirs += 1
        return ours, theirs

    def their_tower_down(self, side):
        return self.__dict__.get("_tower_zero", {}).get(f"their_{side}", 0) >= 3 and \
            self.tower_seen.get(f"their_{side}", 0) > 0.3

    def legal(self, x, y, name):
        """Can the game take this card on this tile? (our half, not on a tower, not in the river; the pocket on
        their side once their tower of that lane is down) — a card dropped on a wrong tile stays selected and the
        moment is lost."""
        if card(name).get("anywhere") or "spell" in roles(name): return 0 <= x <= 17 and 0 <= y <= 31
        if not (0 <= x <= 17 and 0 <= y <= 31): return False
        if 2 <= x <= 4 and 4 <= y <= 6 or 13 <= x <= 15 and 4 <= y <= 6: return False      # our princess towers
        if 7 <= x <= 10 and 0 <= y <= 3: return False                                       # our king tower
        if y <= 14: return True
        side = lane(x)
        return self.their_tower_down(side) and 17 <= y <= 20

    def legal_tile(self, x, y, name):
        """The nearest tile the game accepts for this card."""
        if self.legal(x, y, name): return x, y
        best = None
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                tx, ty = x + dx, y + dy
                if self.legal(tx, ty, name) and (best is None or dx * dx + dy * dy < best[0]):
                    best = (dx * dx + dy * dy, tx, ty)
        return (best[1], best[2]) if best else (x, max(0, min(14, y)))

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
        keep = self._reserved(name)                                  # kept for a threat they can play (Log for the barrel)
        if keep and keep != threat.get("main") and not threat.get("urgent"): score -= 2.5
        if self.p.get("pro_moves", True):                           # what real players answered it with
            pro_hand = getattr(self, "_pro_hand", None) or {}
            if pro_hand.get(name):
                score += 3.0 * pro_hand[name] / max(pro_hand.values())
            # ...and how often the player who answered it that way WON the game (RoyaleAPI replays' results):
            # 60% wins -> +1.2, 40% -> -1.2
            pw = (getattr(self, "_pro_wins", None) or {}).get(name)
            if pw and pw[0] >= 40:
                score += 6.0 * (pw[1] - 0.5) * min(1.0, pw[0] / 400.0)
        pol = (self._pol or {}).get("cards") or {}
        if pol.get(name) and self.p.get("learned", True):            # the learned brain's choice in this moment
            score += 2.5 * pol[name] / max(pol.values())
        if getattr(self, "mem", None):                              # what worked in OUR battles against it
            score += self.mem.bonus(threat.get("main"), name)
        cost = c.get("cost", 4)
        trade = threat["value"] - cost
        score += 0.25 * max(-4.0, min(3.0, trade))                              # positive elixir trade
        return max(0.0, score)

    def _defense_tile(self, name, side, threat):
        r = roles(name)
        cx, cy = threat["center"] or OUR_TOWERS[side]
        where = K.counter(threat.get("main"), card(threat.get("main") or "")).get("where")
        tx, ty = OUR_TOWERS[side]
        if self.p.get("learned", True) and "spell" not in r and self._pol:
            lt = self._ltile(name)                                               # the learned brains, this moment
            if lt and lt[1] >= 0.25 and lt[0][1] <= 14 and lane(lt[0][0]) == side: return lt[0]
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

    def decide(self, hand, ready, elixir, enemies, allies=(), towers=None, now=None, hp=None, spells=None, evo=None):
        """
        hand: the 4 card names in hand (slot 0..3); ready: playable slots; elixir: ours (0..10);
        enemies / allies: [(unit, tile_x, tile_y, conf)]; towers: {"their_left": hp 0..1, ...}
        -> None or {"slot", "card", "tile": (x, y), "why"}
        """
        now = now or time.monotonic()
        enemies = self._not_ours(enemies or [], allies or [])
        self.hp_seen = hp or {}
        self.evo_seen = evo or []
        if spells: self._spells(spells, now)
        stable = self.observe(enemies, now)
        self._stable, self._towers_now, self._allies = stable, dict(towers or {}), list(allies or [])
        if getattr(self, "mem", None): self.mem.tick(towers, now)
        el_t = self.elapsed()
        if towers and (not self.tower_log or el_t - self.tower_log[-1][0] >= 1.0):
            self.tower_log.append((round(el_t, 1), dict(towers)))
        self._my_el = elixir
        if now - self.last_play < 0.55: return None                              # one card at a time (the game
                                                                                 # shows it ~0.5 s later)
        towers = towers or {}
        playable = [(i, hand[i]) for i in ready if i < len(hand) and hand[i] and card(hand[i])
                    and card(hand[i]).get("cost", 11) <= elixir]
        if not playable: return None
        th = self.threats(stable)
        self._pol = None
        if self.p.get("learned", True):
            try:
                own = [(d["t"], d["card"], d["tile"][0], d["tile"][1]) for d in self.plays]
                self._pol = policy.ask(self.elapsed(), elixir, self.enemy_elixir, self.enemy_hist, own,
                                       [h for h in hand if h], [n for _, n in playable])
            except Exception:
                self._pol = None
            # the board brain (Transformer, the whole arena): its view is mixed in, it knows where everything is
            self._board = None
            try:
                if self.p.get("board", True) and board_brain.ready():
                    self._board = board_brain.ask(self, [h for h in hand if h], [n for _, n in playable], elixir, allies)
            except Exception:
                self._board = None
            if self._pol and self._board and self._board.get("cards"):
                pc, bc = self._pol.get("cards") or {}, self._board["cards"]
                # two brains that learned differently (play history / whole arena): together they choose better
                self._pol["cards"] = {n: 0.5 * pc.get(n, 0.0) + 0.5 * bc.get(n, 0.0) for n in set(pc) | set(bc)}
                self._pol["play"] = 0.5 * self._pol["play"] + 0.5 * self._board["play"]
        self._ctx = (round(el_t, 2), [round(float(v), 4) for v in self._pol["_x"][0]], list(self._pol["_ids"]),
                     (self._board or {}).get("_in")) if self._pol else None
        if self.p.get("ai", False) and self._pol and self._pol.get("cards"):
            d = self._model_decide(playable, elixir, stable, th, now)       # the local AI model plays
        else:
            d = self._decide(hand, ready, elixir, stable, playable, th, towers, now, allies)
        if d is None and self._ctx and el_t - self._last_wait >= 1.0:          # it chose to wait: a moment too
            self._last_wait = el_t
            self.steps.append({"t": self._ctx[0], "x": self._ctx[1], "ids": self._ctx[2], "card": 0, "tile": 0,
                               **({"b": self._ctx[3]} if self._ctx[3] else {})})
        return d

    def _decide(self, hand, ready, elixir, stable, playable, th, towers, now, allies=()):
        # 1. defend the lane in more danger
        side = max(th, key=lambda s: th[s]["value"])
        t = th[side]
        late = K.counter(t.get("main"), card(t.get("main") or "")).get("where") == "late"
        if late and t["center"] and t["center"][1] > 13 and elixir < 9.5:
            pass                                                                 # a tank: let it come (tower helps)
        elif t["value"] >= self.p.get("defend_min", 1.5) or (t.get("urgent") and t["units"]):
            self._pl_lost = None
            self._pro_hand = (pro.answer(t["main"], (t["center"] or (0, 10))[1], side, [n for _, n in playable])
                              if t.get("main") else {})
            self._pro_wins = (pro.answer_wins(t["main"], (t["center"] or (0, 10))[1], [n for _, n in playable])
                              if t.get("main") else {})
            # against THIS kind of deck (its plan: Hog, Golem, X-Bow...): what the winners answered this card with
            plan = self.their_plan()
            mu = pro.matchup_answers(plan, t["main"], (t["center"] or (0, 10))[1], [n for _, n in playable]) \
                if t.get("main") and plan else {}
            for n, (g, w, _tile) in mu.items():
                self._pro_wins[n] = (g, w)                                # the matchup's own numbers come first
            self._mu_tiles = {n: v[2] for n, v in mu.items() if v[2]}
            ranked = sorted(((self._counter_score(n, t), (i, n)) for i, n in playable), key=lambda r: -r[0])
            best, sc = ranked[0][1], ranked[0][0]
            tile, why = self._defense_tile(best[1], side, t), ""
            if sc > 0.8 and self.p.get("think", True) and "spell" not in roles(best[1]):
                # think it through: the good answers on their tiles, simulated a few seconds ahead
                try:
                    good = [(p, s) for s, p in ranked if s > 0.8 and "spell" not in roles(p[1])][:3]
                    # the defense atlas: the best spots every card of the hand had against this threat in millions
                    # of tried defenses — its best card joins the candidates and its spots are tried first
                    extra, prior = {}, {p[1]: 0.15 * s for p, s in good}
                    try:
                        from royale import atlas
                        main = t.get("main")
                        trk = next((k for k in self.known_enemy.values() if unit_card(k["unit"]) == main), None)
                        if main and trk:
                            others = sorted({unit_card(u) for u, _x, _y in t["units"] if unit_card(u)} - {main})
                            ans = atlas.answers(main, (trk["fx"], trk["fy"]), side,
                                                [n for _, n in playable if "spell" not in roles(n)], others)
                            if ans:
                                best_sc = max(v[0][3] for v in ans.values())
                                for n, spots in ans.items():
                                    extra[n] = [(x, y) for x, y, *_r in spots]
                                    prior[n] = prior.get(n, 0.0) + 0.3 * (spots[0][3] >= best_sc - 0.05)
                                top = max(ans, key=lambda n: ans[n][0][3])
                                if all(p[1] != top for p, _ in good):
                                    good.append((next(p for p in playable if p[1] == top), 1.0))
                    except Exception:
                        pass
                    pl = sim.plan(self, side, t, [p for p, _ in good], stable, getattr(self, "hp_seen", None),
                                  prior=prior, extra_tiles=extra, max_cards=4)
                    if pl:
                        best, tile, why = (pl[0], pl[1]), pl[2], f" — {pl[4]}"
                        self._pl_lost = pl[7]
                        deep = any(y <= 8 for _u, _x, y in t["units"])
                        if pl[6] and not t.get("urgent") and not deep:
                            # better a moment later (a building waiting decays, a troop would meet them away from
                            # the tower): hold — and keep the elixir for it
                            self._hold_until = now + 1.2
                            return None
                        if pl[5] < 0.25 and not t.get("urgent") and not deep:
                            # the tower handles it alone: no card spent (elixir for the attack)
                            self._saved_at = now
                            sc = 0.0
                except Exception:
                    pass
            if sc > 0.8:
                d = self._play(best, tile, f"defend {side} vs "
                               f"{', '.join(sorted({u for u, _, _ in t['units']}))}{why}", now)
                if d and getattr(self, "mem", None):
                    self.mem.defended(t.get("main"), best[1], side, towers, now, getattr(self, "_pl_lost", None))
                return d

        if now < getattr(self, "_hold_until", 0.0): return None                 # a defense is coming in a moment

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

        # 3b. the learned brain wants to play now (what real players did in moments like this one): checked by the rules
        lp = self._learned_play(playable, elixir, now)
        if lp: return lp

        # 4. never leak elixir
        if elixir >= self.p.get("cycle_at", 9.5):
            cheap = min(playable, key=lambda p: (("win" in roles(p[1])), card(p[1]).get("cost", 9)))
            r = roles(cheap[1])
            tile = (8, 1) if "spell" not in r else None
            if tile is None:
                return None
            return self._play(cheap, tile, "full elixir: cycling at the back", now)
        return None

    def _model_decide(self, playable, elixir, stable, th, now):
        """The local AI model is in charge: its two networks (the arena Transformer that sees every unit and the
        play-history network; 252k pro games / 17M plays, then every battle of this account) decide whether to
        play now, which card and where. The bot's rules only guard it: a spell must hit units that are surely
        theirs, a tile the game refuses is moved to the nearest legal one, and when the model waits while a push
        is about to hit our tower, the rules' reflex defense goes in."""
        pol = self._pol
        play = pol.get("play", 0.0)
        probs = {n: pol["cards"].get(n, 0.0) for _, n in playable}
        side = max(th, key=lambda s_: th[s_]["value"]) if th else None
        urgent = side is not None and th[side].get("urgent") and th[side].get("units")
        if play >= 0.5:
            for n, pr in sorted(probs.items(), key=lambda kv: -kv[1]):
                if pr < 0.12: break
                if self._reserved(n): continue
                i = next(i for i, m in playable if m == n)
                if "spell" in roles(n) and n not in WIN_SPELLS:
                    sv = self._spell_value(n, stable)            # the model chose the spell; its target: the best
                    if not sv or sv[0] < (card(n).get("cost", 3) - 0.5): continue   # cluster that is surely theirs
                    tile = sv[1]
                else:
                    lt = self._ltile(n, anywhere=bool(card(n).get("anywhere")))
                    if not lt: continue
                    tile = lt[0]
                d = self._play((i, n), tile, f"AI model ({play:.0%} play now, {pr:.0%} {n})", now)
                if d: return d
        if urgent:                                               # a reflex: the push is at our tower
            d = self._decide([n for _, n in playable], [i for i, _ in playable], elixir, stable, playable, th,
                             self._towers_now, now, self._allies)
            if d and d["why"].startswith("defend"):
                d["why"] = "AI reflex — " + d["why"]
                return d
            if d: self.undo(d)
        return None

    def _learned_play(self, playable, elixir, now):
        pol = self._pol
        if not pol or not pol.get("cards") or pol["play"] < self.p.get("learned_play", 0.7): return None
        n = max(pol["cards"], key=pol["cards"].get)
        if pol["cards"][n] < 0.4: return None
        r = roles(n)
        if "spell" in r: return None                                  # spells: only where the rules see a target
        if self._reserved(n): return None
        if n in K.NOT_TOGETHER[0] and now - self.heavy_mine_at < 6: return None
        if card(n).get("cost", 4) >= 6 and elixir < 9 and not self.double_elixir(): return None
        lt = self._ltile(n)
        if not lt or lt[1] < 0.2: return None
        i = next(i for i, m in playable if m == n)
        return self._play((i, n), lt[0], f"learned brain ({pol['play']:.0%} play, {pol['cards'][n]:.0%} {n})", now)

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
        # a counter-push = what survived our defense is crossing the river with real value (2+ units or a sturdy
        # one), and only with elixir to spare; a lone archer at the bridge is not worth a card every second
        counter = [a for a in (allies or []) if a[2] >= RIVER_Y - 2] if self.p.get("counter_push", True) else []
        if counter and not (len(counter) >= 2 or any((card(unit_card(a[0]) or "").get("hp") or 0) >= 1000
                                                     for a in counter)):
            counter = []
        if counter and (elixir < 6 or now - getattr(self, "_counter_at", 0.0) < 8.0):
            counter = []
        # their elixir is a guess: an attack also needs elixir of our own to defend what comes back
        push_ok = (advantage >= self.p.get("push_adv", 2.0) and elixir >= 5) or (double and elixir >= 6) or counter \
            or elixir >= 9
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
        recent = list(self.enemy_cycle)[-3:]                     # played in the last 3 = not back in hand yet
        hand_now = self.their_hand()
        if hand_now is not None:                                 # their hand worked out: everything not in it is out
            recent = [c for c in (self.enemy_seen | self.predicted) if c not in hand_now]
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
        if self.p.get("think", True):
            # the attack thought through: each win condition on both lanes' spots against their towers and the
            # defenders already there; the best one goes in if it really takes something
            try:
                ap = sim.attack_plan(self, [p for p in wins if p[1] not in WIN_SPELLS], stable)
                if ap and ap[4] > 0.5:
                    return self._play((ap[0], ap[1]), ap[2], f"{ap[1]} — attack thought through: {ap[4]:+.1f} elixir", now)
            except Exception:
                pass
        for i, n in sorted(wins, key=lambda p: -card(p[1]).get("cost", 0)):
            r = roles(n)
            c = card(n)
            if n in WIN_SPELLS:
                x, y = THEIR_TOWERS[side]
                return self._play((i, n), (int(x), int(y) - 1), f"{n} on their {side} tower", now)
            pt = pro.place(n, side) if self.p.get("pro_moves", True) else None   # where real players start it
            ab = pro.attack_best(n, side)                                       # where it hurts most (attack atlas)
            if ab: pt = ab
            wp = pro.winners_place(self.their_plan(), n, side)                  # where WINNERS start it vs this deck
            if wp: pt = wp
            lt = self._ltile(n) if self.p.get("learned", True) and self._pol else None
            if lt and lt[1] >= 0.3 and lane(lt[0][0]) == side: pt = lt[0]        # this moment's learned spot
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
                self._counter_at = now
                return self._play((i, n), (x, 12), "supporting the counter-push", now)
        return None

    def _support(self, playable, elixir, now):
        """Our tank / win condition just went in: its support goes behind it (royale.knowledge SUPPORT)."""
        if not self.support_due or now > self.support_due[1]: return None
        side, _until, first = self.support_due
        sup = [(i, n) for i, n in playable if n in K.SUPPORT.get(first, [])]
        study = getattr(self, "study", None) or {}
        mates = [m for m, _w in ((study.get("attack") or {}).get(first) or {}).get("with", [])]
        if mates:                                       # this deck's own partner for it (what winners did)
            sup = [(i, n) for i, n in playable if n in mates] or sup
        fol = pro.follows(first, [n for _, n in playable]) if self.p.get("pro_moves", True) else {}
        if not sup:                                     # what real players played right after it, same lane
            sup = [(i, n) for i, n in playable if fol.get(n, 0) >= 0.08 and "spell" not in roles(n)]
        if not sup: return None
        i, n = max(sup, key=lambda p: (fol.get(p[1], 0), -card(p[1]).get("cost", 9)))
        y = 1 if self.support_due_back else 11
        self.support_due = None
        return self._play((i, n), (LEFT_BRIDGE_X if side == "left" else RIGHT_BRIDGE_X, y), f"{n} behind the {first}", now)

    def score_moves(self):
        """After the battle: every card WE played is judged on its own (the idea RoyaleFish found decisive: the
        lesson lands on the move that earned it, not 100 moves later):
          trade     elixir worth of their units that died near it within 10 s, minus what it cost
          building  a building that pulled nothing (no building-only troop died near it) was wasted: -1.5
          spell     the same trade: a Fireball that killed 2 elixir of troops is -2
        -> step["v"] (elixir) for royale.selfplay."""
        for s in self.steps:
            cid = s.get("card", 0)
            if not cid: continue
            name = next((n for n in cards_db() if policy.card_id(n) == cid), None)
            if not name: continue
            c = card(name)
            x, y = s["tile"] % 18, s["tile"] // 18
            near = [d for d in self.deaths if s["t"] <= d[0] <= s["t"] + 10.0 and dist((d[2], d[3]), (x, y)) <= 7.0
                    and lane(d[2]) == lane(x)]
            v = sum(d[4] for d in near) - c.get("cost", 3)
            if c.get("kind") == "building" and not any(d[5] for d in near): v -= 1.5
            s["v"] = round(v, 2)

    # ---------------------------------------------------------------- levels (official API)
    levels = {}                                # our card -> shown level (royale.game sets it from the API)
    king_level = None
    their_level = None                         # the opponent's usual level (learned from past battle logs)

    evo_cards = {}                             # our card -> evolution cycles (official API: evolutionLevel > 0)

    study = None                               # royale.deck_study of the deck being played

    def _reserved(self, name):
        """Is our `name` kept for a threat they can play: the rules (Log for the barrel) and this deck's study
        (its only good answer to a card the deck struggles with)."""
        th = self.their_threats()
        r = K.reserved(th, name)
        if r: return r
        kf = (self.study or {}).get("keep_for") or {}
        for t, a in kf.items():
            if a == name and any("".join(ch for ch in c if ch.isalnum()) == t for c in (th or ())): return t
        return None
    hand_look = {}                             # our hand card -> the picture it shows now ("", "_ev1", "_hero"...)
    heroes = set()                             # our cards seen with their hero picture (Hero Bowler, ...)

    def see_hand(self, hand, looks):
        """What the hand shows: which card's evolution is charged right now, which are hero cards."""
        self.hand_look = {n: v for n, v in zip(hand or [], looks or []) if n and n != "blank"}
        for n, v in self.hand_look.items():
            if "hero" in v: self.heroes.add(n)
            if "ev1" in v and n not in self.evo_cards: self.evo_cards[n] = 2          # it has an evolution

    def my_evo(self, name):
        """Is our `name` coming out evolved: seen in the hand -> sure (its evolved picture shows when the evolution
        is charged); else one play in (cycles + 1); 0 when it has no evolution."""
        if name in self.hand_look:
            return 1.0 if "ev1" in self.hand_look[name] else 0.0
        cyc = self.evo_cards.get(name)
        return 1.0 / (cyc + 1) if cyc else 0.0

    def is_evo(self, u, x, y):
        """The big model saw this unit of theirs as the evolved one."""
        return any(uu == u and abs(xx - x) <= 1 and abs(yy - y) <= 1 for uu, xx, yy in getattr(self, "evo_seen", ()) or ())

    def my_level(self, name):
        if not name: return None
        k = "".join(ch for ch in str(name).lower() if ch.isalnum())
        return self.levels.get(k) or self.king_level

    def _not_ours(self, enemies, allies):
        """A unit of a card WE just played, where we played it (or on its way from there), is ours even when the
        eyes say "theirs" — the side check can miss, and spelling our own troops is the worst mistake there is."""
        out = []
        t = self.elapsed()
        for e in enemies:
            u, x, y = e[0], e[1], e[2]
            cn = unit_card(u)
            mine = False
            for p in reversed(self.plays):
                if t - p["t"] > 12: break
                if p["card"] == cn or (cn and card(p["card"]).get("units") and u in (card(p["card"]).get("units") or [])):
                    spd = (card(p["card"]).get("speed") or 60) / 60.0
                    if dist((x, y), p["tile"]) <= 2.5 + spd * (t - p["t"]) and y <= RIVER_Y + 3 + spd * (t - p["t"]):
                        mine = True
                        break
            if mine:
                allies = list(allies) + [(u, x, y, e[3] if len(e) > 3 else 0.5)]
            else:
                out.append(e)
        self._allies_extra = [a for a in allies]
        return out

    def _spell_sure(self, name, tile):
        """A damage spell goes only where every unit it would hit is surely theirs. The side the eyes give is not
        enough (our Hog at their tower, our survivors after a defense were read as theirs and spelled — the
        user's Fireball / Arrows on their own troops): a unit counts as theirs only when its card is NOT in our
        deck. A tower in reach is always theirs. Deck not known yet -> no spell on units at all."""
        rad = (card(name).get("splash") or SPELL_SPLASH_DEFAULT.get(name, 2.5)) + 0.5
        if any(dist(t, tile) <= rad + 1.5 for t in THEIR_TOWERS.values()):
            hit = [u for u, x, y in (self._stable or []) if dist((x, y), tile) <= rad]
            if not hit: return True                      # the tower itself (finishing it)
        if len(self.deck or []) != 8: return False
        mine = {unit_card(u) or u for n in self.deck for u in ((card(n) or {}).get("units") or [n])} | set(self.deck)
        hit = [u for u, x, y in (self._stable or []) if dist((x, y), tile) <= rad]
        if not hit: return False
        return all((unit_card(u) or u) not in mine and u not in mine for u in hit)

    def _spell_hits_us(self, name, tile):
        """Would this spell land on our own troops / buildings? (never cast it then)"""
        rad = (card(name).get("splash") or SPELL_SPLASH_DEFAULT.get(name, 2.5)) + 1.0
        ours = list(getattr(self, "_allies", []) or []) + list(getattr(self, "_allies_extra", []) or [])
        t = self.elapsed()
        ours += [(p["card"], p["tile"][0], p["tile"][1], 1.0) for p in self.plays
                 if t - p["t"] <= 4 and "spell" not in roles(p["card"])]
        return any(dist((a[1], a[2]), tile) <= rad for a in ours)

    def calib(self):
        try: return self.mem.calib() if getattr(self, "mem", None) else 1.0
        except Exception: return 1.0

    def their_hand(self):
        """The 4 cards in their hand now, worked out like a player counts the cycle: the deck (seen + guessed) minus
        the last 4 different cards they played (those wait in the queue). None until 6 of their cards are known."""
        deck = list(dict.fromkeys(list(self.enemy_seen) + sorted(self.predicted)))[:8]
        if len(self.enemy_seen) < 4 or len(deck) < 6: return None
        queue = []
        for c in reversed(self.enemy_cycle):
            if c not in queue: queue.append(c)
            if len(queue) == 4: break
        return {c for c in deck if c not in queue}

    def their_next(self):
        """The card that comes back into their hand with their next play (the oldest one waiting)."""
        queue = []
        for c in reversed(self.enemy_cycle):
            if c not in queue: queue.append(c)
            if len(queue) == 4: break
        return queue[-1] if len(queue) == 4 else None

    def their_threats(self):
        """Threats to keep a counter for: what they hold now and what comes next; every card known when unsure."""
        h = self.their_hand()
        if h is None: return self.enemy_seen | self.predicted
        nx = self.their_next()
        return h | ({nx} if nx else set())

    def their_plan(self):
        """Their deck's plan (main win condition), from what they played and what their deck probably holds."""
        try:
            return pro.their_plan(list(self.enemy_seen | self.predicted),
                                  {pro.key(n): (c.get("cost") or 4) for n, c in cards_db().items()})
        except Exception:
            return None

    def _ltile(self, name, anywhere=False):
        """Where the learned brains would put `name` now: the surer of the two."""
        bt = pt = None
        try:
            if getattr(self, "_board", None): bt = board_brain.tile(self._board, name, anywhere)
        except Exception:
            bt = None
        try:
            if self._pol: pt = policy.tile(self._pol, name, anywhere)
        except Exception:
            pt = None
        cands = [t for t in (bt, pt) if t]
        return max(cands, key=lambda t: t[1]) if cands else None

    def life(self, u, x, y):
        """Life left (0..1) read from its health bar, 1 when unhurt / not read."""
        hs = getattr(self, "hp_seen", None) or {}
        if (u, x, y) in hs: return hs[(u, x, y)]
        for (uu, xx, yy), f in hs.items():
            if uu == u and abs(xx - x) <= 1 and abs(yy - y) <= 1: return f
        return 1.0

    def _spells(self, spells, now):
        """Spells the big model saw landing: theirs (on our half) are cards they played — their elixir, their deck —
        and their area is kept free of our troops for a moment."""
        self.danger = [d for d in getattr(self, "danger", []) if d[3] > now]
        for name, tx, ty in spells:
            if ty > RIVER_Y: continue                                  # on their half: ours
            c = card(name)
            if not c: continue
            if any(p[1] == name and self.elapsed() - p[0] < 3.0 for p in self.enemy_hist[-4:]): continue
            self._learn_opponent(name, tx, ty)
            self.enemy_elixir = max(0.0, self.enemy_elixir - c.get("cost", 3))
            self.enemy_cycle.append(name)
            self.enemy_plays.append((round(self.elapsed()), name, lane(tx)))
            self.enemy_hist.append((self.elapsed(), name, tx, ty))
            self.enemy_seen.add(name)
            self._predict()
            rad = (c.get("splash") or SPELL_SPLASH_DEFAULT.get(name, 2.5))
            self.danger.append((tx, ty, rad + 1.0, now + 2.5, name))

    def _learn_opponent(self, cn, x, y):
        """The opponent just played `cn` at (x, y): the moment as THEY saw it (board turned round: their king at
        y 0), what they did — kept to learn from. Their hand: their deck (seen + guessed) minus their last 4."""
        try:
            t = self.elapsed()
            mine = [(d["t"], d["card"], 17 - d["tile"][0], 31 - d["tile"][1]) for d in self.plays]
            theirs = [(et, c, 17 - ex, 31 - ey) for et, c, ex, ey in self.enemy_hist]
            wait = []
            for _t, c, _x, _y in reversed(self.enemy_hist):
                if c not in wait: wait.append(c)
                if len(wait) == 4: break
            deck = list(dict.fromkeys(list(self.enemy_seen) + [cn] + sorted(self.predicted)))[:8]
            hand = [c for c in deck if c not in wait][:4]
            if cn not in hand: hand = ([cn] + hand)[:4]
            mo = policy.moment(t, self.enemy_elixir, self._my_el, mine, theirs, hand)
            if not mo: return
            fx, ids = mo
            tx, ty = 17 - int(x), 31 - int(y)
            bi = None
            try:
                if board_brain.ready():
                    bi = board_brain.inputs(self, [], 0.0, getattr(self, "_allies", []), mirror=True,
                                            my_el=self.enemy_elixir, their_el=self._my_el, hand_override=hand)
            except Exception:
                bi = None
            self.opp_steps.append({**({"b": bi} if bi else {}),
                                   "t": round(t, 2), "x": [round(float(v), 4) for v in fx], "ids": list(ids),
                                   "card": policy.card_id(cn), "tile": max(0, min(31, ty)) * 18 + max(0, min(17, tx))})
        except Exception:
            pass

    def _predict(self):
        """Their whole deck from the cards seen: the decks played RIGHT NOW by the best players (official API,
        royale.cr_api, refreshed daily) first, else the cards played with them in 45%+ of 252k real decks."""
        try:
            names = {pro.key(n): n for n in cards_db()}
            guess = []
            try:
                from royale import cr_api
                guess = [(k, p) for k, p in cr_api.predict_deck([pro.key(c) for c in self.enemy_seen]) if p >= 0.45]
            except Exception:
                guess = []
            if not guess:
                guess = [(k, p) for k, p in pro.predict_deck(self.enemy_seen) if p >= 0.45]
            self.predicted = {names[k] for k, p in guess if k in names} - self.enemy_seen
        except Exception:
            self.predicted = set()

    def undo(self, d):
        """Take back the play decide() just returned (the AI player chose something else)."""
        snap = getattr(self, "_undo_snap", None)
        if not d or not snap or not self.plays or self.plays[-1] is not d: return
        (self.support_due, self.support_due_back, self.heavy_mine_at, self.last_play, nt, ns, self._ctx) = snap
        while len(self.last_tiles) > nt: self.last_tiles.pop()
        del self.steps[ns:]
        self.plays.pop()

    def play_ai(self, slot, n, tile, why, now):
        """A move the AI player chose: through the same checks and records as the brain's own plays."""
        return self._play((slot, n), tile, why, now)

    def _play(self, pick, tile, why, now):
        i, n = pick
        if tile is None: return None
        self._undo_snap = (self.support_due, getattr(self, "support_due_back", False), self.heavy_mine_at,
                           self.last_play, len(self.last_tiles), len(self.steps), getattr(self, "_ctx", None))
        if "spell" in roles(n) and self._spell_hits_us(n, tile):
            return None                                  # never a spell on our own troops
        if "spell" in roles(n) and n not in WIN_SPELLS and not self._spell_sure(n, tile):
            return None                                  # only on units that are surely THEIRS
        if n in K.SUPPORT or (pro.data().get("follow", {}).get(pro.key(n)) and "win" in roles(n)):  # its support next
            self.support_due = (lane(tile[0]), now + 5.0, n)
            self.support_due_back = tile[1] <= 3
        if n in K.NOT_TOGETHER[0]: self.heavy_mine_at = now
        x, y = int(max(0, min(17, tile[0]))), int(tile[1])
        if "spell" not in roles(n):                     # not into a spell of theirs that is landing right there
            for dx_, dy_, rad, _until, *_n in getattr(self, "danger", []):
                if dist((x, y), (dx_, dy_)) <= rad:
                    y = int(max(1, dy_ - rad - 1)) if dy_ - rad - 1 >= 1 else int(min(14, dy_ + rad + 1))
                    break
        if not card(n).get("anywhere"):
            if not self.legal(x, y, n): x, y = self.legal_tile(x, y, n)          # never a tile the game refuses
        self.last_play = now
        self.last_tiles.append((x, y))
        d = {"slot": i, "card": n, "tile": (x, y), "why": why, "t": round(self.elapsed(), 1)}
        if self._ctx:
            self.steps.append({"t": self._ctx[0], "x": self._ctx[1], "ids": self._ctx[2],
                               "card": policy.card_id(n), "tile": y * 18 + x,
                               **({"b": self._ctx[3]} if self._ctx[3] else {})})
            self._ctx = None
        self.plays.append(d)
        return d
