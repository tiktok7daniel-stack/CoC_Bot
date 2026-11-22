"""
Every unit in the arena followed over its life (6.6): a persistent track id, its place and speed, its side.

  in       each look of the eyes: [Det(name, x, y, conf, team, team_conf, box)] — x / y in TILES (floats, the
           unit's feet), team "ally" / "enemy" with how sure the look is (the health-bar colour is sure, the small
           side model less, "theirs because it is not in our deck" least)
  match    one Hungarian assignment (scipy) of every detection to every track on the distance from where each
           track's Kalman filter says the unit is now (+ a penalty for another name / another side, + a little for a
           doubtful detection, so a sure one wins a contested track — ByteTrack's idea in one pass): two Knights side
           by side keep their ids; a doubtful box right on a followed unit is not a new unit
  filter   a constant-speed Kalman filter per track in tile units (x, y, vx, vy): measurement noise ~0.35 tile
           (the eyes' boxes), walking units change speed slowly; a unit standing at a tower has speed ~0
  side     voted over the track's life, weighted by how sure each look was: once a health-bar colour said "enemy"
           three times, a flickering side model can no longer turn it into one of ours (the bot never spells its
           own troops); a brand new track takes the side of the half it appeared on until a colour is read
  predict  predict_position(track_id, spell): where the unit will be when the spell lands — the look's age + the
           tap until the card is down + the spell's own delay + its flight from our king tower — walked along its
           PATH (6.7): over its lane's bridge, then to the tower / building it goes for, stopped where its range
           reaches it; a unit whose heading is far from that path (chasing a troop) keeps its measured line
  eta      seconds until a unit is hitting the tower / building it walks to (the same path)
  ghosts   a followed unit missing from a look for up to 0.4 s (a spell's flash covered it) stays in the battle
           state, moved on its speed — unless its health bar was at the end or the spell that landed kills it

Pure numpy + scipy (already used by the card reader): ~0.2 ms a look for 30 units.
"""
import math, time
from collections import namedtuple

import numpy as np

Det = namedtuple("Det", "name x y conf team team_conf box")
Det.__new__.__defaults__ = (None, 0.0, None)

ARENA_W, ARENA_H = 18, 32
RIVER_Y = 15                                     # y <= 15: our half (as royale.brain; y grows toward their side)
# our / their towers in tiles (the same as royale.brain)
OUR_TOWERS = {"left": (3.5, 5.0), "right": (14.5, 5.0), "king": (8.5, 1.5)}
THEIR_TOWERS = {"left": (3.5, 26.0), "right": (14.5, 26.0), "king": (8.5, 29.5)}

# the moment a spell's effect starts after our tap, beyond its flight (seconds): the tap reaching the game and the
# card coming down (~0.15 s measured on the bot's taps) + the spell's own wait in the game data (Lightning waits
# for its strikes, Rocket / Fireball fly from the king tower — that part is the flight below)
TAP_DELAY = 0.15
SPELL_TIMING = {
    # name           wait (s)  speed (tiles / s, from our king tower; None = it starts where it is dropped)
    "zap":           (0.00, None),
    "giant_snowball": (0.00, 13.3),
    "arrows":        (0.00, 18.3),
    "fireball":      (0.00, 10.0),
    "rocket":        (0.00, 5.83),
    "poison":        (0.00, None),
    "lightning":     (0.45, None),
    "freeze":        (0.00, None),
    "earthquake":    (0.00, None),
    "tornado":       (0.00, None),
    "the_log":       (0.40, None),      # it appears, then rolls forward (royale.brain drops it behind them)
    "barbarian_barrel": (0.40, None),
    "royal_delivery": (2.00, None),
    "goblin_curse":  (0.00, None),
    "void":          (0.30, None),
    "vines":         (0.50, None),
}
DEFAULT_TIMING = (0.0, 10.0)


def _timing(spell):
    w, sp = SPELL_TIMING.get(spell, (None, None))
    if w is None:
        try:                                       # a spell not in the table: the game data's projectile speed
            from royale.brain import card
            ps = card(spell).get("projectile_speed")
            return 0.0, (ps / 60.0 if ps else None)
        except Exception:
            return DEFAULT_TIMING
    return w, sp


class Track:
    _ids = 0

    def __init__(self, d, t):
        Track._ids += 1
        self.id = Track._ids
        self.s = np.array([d.x, d.y, 0.0, 0.0])          # x, y, vx, vy (tiles, tiles / s)
        self.P = np.diag([0.35 ** 2, 0.35 ** 2, 1.5 ** 2, 1.5 ** 2])
        self.t = self.born = self.seen = t        # t: the filter's time; seen: the last look it was really seen
        self.hits, self.miss = 1, 0
        self.life = None                          # 0..1 from its health bar when read (royale.health)
        self.names = {d.name: float(d.conf)}
        self.team_v = {"ally": 0.0, "enemy": 0.0}
        # a new unit belongs to the half it appeared on until it is seen better (a weak vote, 0.5)
        self.team_v["ally" if d.y <= RIVER_Y else "enemy"] += 0.5
        self._vote_team(d)
        self.conf = float(d.conf)
        self.box = d.box

    # -------------------------------------------------------------- what it is
    @property
    def name(self):
        return max(self.names, key=self.names.get)

    @property
    def team(self):
        return "ally" if self.team_v["ally"] > self.team_v["enemy"] else "enemy"

    def team_sure(self):
        a, e = self.team_v["ally"], self.team_v["enemy"]
        return abs(a - e) / max(1e-6, a + e)

    def locked(self):
        """Its side is settled (3 colour reads' worth of votes ahead): a single doubtful look can not flip it."""
        return abs(self.team_v["ally"] - self.team_v["enemy"]) >= 3.0

    def _vote_team(self, d):
        if d.team in ("ally", "enemy"):
            self.team_v[d.team] += float(d.team_conf or 0.0)

    # -------------------------------------------------------------- motion
    @property
    def x(self): return float(self.s[0])

    @property
    def y(self): return float(self.s[1])

    @property
    def vx(self): return float(self.s[2])

    @property
    def vy(self): return float(self.s[3])

    def speed(self):
        return math.hypot(self.s[2], self.s[3])

    def at(self, t):
        """Where the filter puts it at time t (no update)."""
        dt = max(0.0, t - self.t)
        return self.s[0] + self.s[2] * dt, self.s[1] + self.s[3] * dt

    def predict(self, t, q=2.0):
        dt = max(0.0, t - self.t)
        if dt <= 0: return
        F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]], float)
        # walking units change speed slowly: white acceleration noise q (tiles / s^2)
        G = np.array([[dt * dt / 2, 0], [0, dt * dt / 2], [dt, 0], [0, dt]])
        self.s = F @ self.s
        self.P = F @ self.P @ F.T + G @ (np.eye(2) * q * q) @ G.T
        self.t = t

    def update(self, d, r=0.35):
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], float)
        z = np.array([d.x, d.y])
        S = H @ self.P @ H.T + np.eye(2) * r * r
        K = self.P @ H.T @ np.linalg.inv(S)
        self.s = self.s + K @ (z - H @ self.s)
        self.P = (np.eye(4) - K @ H) @ self.P
        sp = math.hypot(self.s[2], self.s[3])
        if sp > 3.5:                                    # no unit walks faster (a jump of the eyes, not a walk)
            self.s[2:] *= 3.5 / sp
        self.hits += 1
        self.miss = 0
        self.seen = self.t
        self.names[d.name] = self.names.get(d.name, 0.0) + float(d.conf)
        self._vote_team(d)
        self.conf = 0.7 * self.conf + 0.3 * float(d.conf)
        self.box = d.box or self.box

    def as_dict(self, now=None):
        now = now or self.t
        x, y = self.at(now)
        return {"id": self.id, "unit": self.name, "team": self.team, "x": round(float(x), 2), "y": round(float(y), 2),
                "vx": round(self.vx, 2), "vy": round(self.vy, 2), "conf": round(self.conf, 2),
                "locked": self.locked(), "hits": self.hits}


class UnitTracker:
    HIGH = 0.5                  # ByteTrack: the sure detections are matched first
    GATE = 2.2                  # tiles: further than this from the predicted place = another unit
    NAME_PEN = 0.9              # tiles added for another name (the eyes flicker between two names)
    TEAM_PEN = 2.5              # tiles added for the other side when both are sure
    CONFIRM = 2                 # looks before a track counts
    KEEP = 1.0                  # seconds a track lives unseen (hidden behind a tower, a missed look)

    def __init__(self):
        self.tracks = []
        self.t = 0.0
        self.down = set()           # towers already down: ("our" | "their", "left" | "right" | "king")

    def reset(self):
        self.tracks = []

    # -------------------------------------------------------------- one look
    def update(self, dets, t=None):
        """dets: [Det] of one look taken at monotonic time t -> [(Det, Track)] (every detection with its track)."""
        from scipy.optimize import linear_sum_assignment
        t = time.monotonic() if t is None else float(t)
        self.t = t
        for tr in self.tracks: tr.predict(t)
        dets = list(dets or [])
        out = [None] * len(dets)
        free = list(range(len(self.tracks)))
        if dets and free:
            # one assignment over everything (globally best: two Knights side by side keep their own ids); a doubtful
            # detection costs a little more, so a sure one wins a contested track (ByteTrack's order, in one pass)
            C = np.full((len(dets), len(free)), 1e6)
            for i, d in enumerate(dets):
                for b, k in enumerate(free):
                    tr = self.tracks[k]
                    c = math.hypot(d.x - tr.s[0], d.y - tr.s[1])
                    if c > self.GATE + 0.5 * tr.miss: continue
                    if d.name != tr.name and d.name not in tr.names: c += self.NAME_PEN
                    if d.team in ("ally", "enemy") and d.team != tr.team and (d.team_conf or 0) >= 1.0 and tr.locked():
                        c += self.TEAM_PEN
                    if d.conf < self.HIGH: c += 0.3
                    C[i, b] = c
            rows, cols = linear_sum_assignment(C)
            used = set()
            for i, b in zip(rows, cols):
                if C[i, b] >= 1e5: continue
                k = free[b]
                self.tracks[k].update(dets[i])
                out[i] = self.tracks[k]
                used.add(k)
            free = [k for k in free if k not in used]
        for k in free: self.tracks[k].miss += 1
        for i, d in enumerate(dets):                     # what matched no track
            if out[i] is not None: continue
            near = min((math.hypot(d.x - tr.s[0], d.y - tr.s[1]) for tr in self.tracks
                        if tr.name == d.name or d.name in tr.names), default=99.0)
            # a new unit — unless it is a doubtful second box right on a unit already followed (the same unit twice)
            if d.conf >= 0.45 or (d.conf >= 0.3 and near > 1.2):
                tr = Track(d, t)
                self.tracks.append(tr)
                out[i] = tr
        # unseen for KEEP seconds: gone (6.7: by the last time it was SEEN — the filter's own time moves every look)
        self.tracks = [tr for tr in self.tracks if t - tr.seen <= self.KEEP]
        return [(d, tr) for d, tr in zip(dets, out)]

    # -------------------------------------------------------------- what the brain asks
    def confirmed(self, team=None):
        return [tr for tr in self.tracks if tr.hits >= self.CONFIRM and (team is None or tr.team == team)]

    def get(self, track_id):
        return next((tr for tr in self.tracks if tr.id == track_id), None)

    def nearest(self, unit, x, y, team="enemy", within=2.5):
        best = None
        for tr in self.tracks:
            if team and tr.team != team: continue
            if unit and tr.name != unit and unit not in tr.names: continue
            d = math.hypot(tr.x - x, tr.y - y)
            if d <= within and (best is None or d < best[0]): best = (d, tr)
        return best[1] if best else None

    # -------------------------------------------------------------- where a unit walks (6.7: by its path)
    def _card(self, tr):
        try:
            from royale.brain import card, unit_card
            return card(unit_card(tr.name) or "") or {}
        except Exception:
            return {}

    def _targets(self, tr, c):
        """What this unit walks to: the other side's towers still up (+ their half size) and, for a ground unit,
        the other side's buildings it sees (a Hog Rider pulled by a Cannon); a building-only unit (Hog, Giant,
        Balloon, Ram) only these. -> [(x, y, half size)]"""
        side = "our" if tr.team == "enemy" else "their"
        towers = OUR_TOWERS if tr.team == "enemy" else THEIR_TOWERS
        out = [(x, y, 2.0 if k == "king" else 1.5) for k, (x, y) in towers.items() if (side, k) not in self.down]
        for o in self.tracks:
            if o.team == tr.team or o.miss > 2: continue
            oc = self._card(o)
            if oc.get("kind") == "building" or oc.get("type") == "building":
                out.append((o.x, o.y, 1.0))
        return out

    def _walk(self, tr, x, y, vx, vy, T, dt=0.05):
        """The unit's place after T seconds along its PATH: to the bridge of its lane first when the river is between
        it and its target (ground units), then to the nearest target (a tower / a building it is drawn to), stopping
        where its range reaches it. A unit whose measured heading is far from that path is chasing a troop: it
        keeps its measured line (and stops at a tower if it meets one). -> (x, y, seconds until it stopped or T)."""
        c = self._card(tr)
        if c.get("kind") == "building": return x, y, 0.0        # buildings never walk
        rng = float(c.get("range") or 1.0)
        air = bool(c.get("air"))
        bonly = bool(c.get("buildings_only"))
        sp = math.hypot(vx, vy)
        walk = (c.get("speed") or 60) / 60.0
        speed = sp if sp >= 0.15 else walk                 # just placed / waiting: its own walking speed
        targets = self._targets(tr, c)
        if not targets: return x, y, T
        down_side = tr.team == "enemy"                      # theirs walk toward y = 0
        px, py, t, first = x, y, 0.0, None
        while t < T:
            # the target: the nearest one (a building-only unit: buildings and towers alike; others: the towers,
            # or a building within its sight range ~5.5 tiles)
            cand = [(math.hypot(px - tx, py - ty), tx, ty, hs) for tx, ty, hs in targets
                    if bonly or hs >= 1.5 or math.hypot(px - tx, py - ty) <= 5.5]
            if not cand: return px, py, T
            d, tx, ty, hs = min(cand)
            if d <= rng + hs: return px, py, t              # in range: it stands and hits
            wx, wy = tx, ty
            if not air:
                across = (py > RIVER_Y + 1.0 and ty < RIVER_Y) if down_side else (py < RIVER_Y and ty > RIVER_Y + 1.0)
                if across:                                  # the river: over its lane's bridge first
                    wx = 3.5 if px < 9 else 14.5
                    wy = RIVER_Y + 0.5
            hx, hy = wx - px, wy - py
            n = math.hypot(hx, hy) or 1.0
            if first is None:
                first = (hx / n, hy / n)
                if sp >= 0.4 and (vx * first[0] + vy * first[1]) / sp < 0.26:     # > 75 degrees off its path
                    return self._line(tr, x, y, vx, vy, T, targets, rng)
            step = min(speed * dt, n)
            px, py = px + hx / n * step, py + hy / n * step
            t += dt
        return px, py, T

    @staticmethod
    def _line(tr, x, y, vx, vy, T, targets, rng):
        """Its measured line, stopped where it first gets a target in range."""
        stop = T
        a = vx * vx + vy * vy
        for tx, ty, hs in targets:
            reach = rng + hs
            fx, fy = x - tx, y - ty
            c = fx * fx + fy * fy - reach * reach
            if c <= 0: return x, y, 0.0
            if a < 1e-6: continue
            b = 2 * (fx * vx + fy * vy)
            disc = b * b - 4 * a * c
            if disc < 0: continue
            t1 = (-b - math.sqrt(disc)) / (2 * a)
            if 0 <= t1 < stop: stop = t1
        return x + vx * stop, y + vy * stop, stop

    def predict_position(self, track_id, spell, now=None, from_xy=None):
        """Where track `track_id` will be when `spell` takes effect, if cast now -> (x, y) tiles, or None."""
        tr = self.get(track_id)
        if tr is None: return None
        now = time.monotonic() if now is None else now
        x, y = tr.at(now)                                 # the look's age is made up first
        vx, vy = tr.vx, tr.vy
        if math.hypot(vx, vy) < 0.15: vx = vy = 0.0       # standing (at a tower, a building, a bridge)
        wait, sp = _timing(spell)
        fx, fy = from_xy or (OUR_TOWERS["king"] if tr.team == "enemy" else THEIR_TOWERS["king"])
        T = TAP_DELAY + wait
        px, py, _ = self._walk(tr, x, y, vx, vy, T)
        if sp:                                            # its flight: solved again for where it will then be
            for _ in range(2):
                T = TAP_DELAY + wait + math.hypot(px - fx, py - fy) / sp
                px, py, _ = self._walk(tr, x, y, vx, vy, T)
        return (min(ARENA_W - 0.5, max(0.0, px)), min(ARENA_H - 0.5, max(0.0, py)))

    def eta(self, track_id, now=None):
        """Seconds until the unit is hitting the tower / building it walks to (inf: not within 20 s)."""
        tr = self.get(track_id)
        if tr is None: return math.inf
        now = time.monotonic() if now is None else now
        x, y = tr.at(now)
        _x, _y, t = self._walk(tr, x, y, tr.vx, tr.vy, 20.0, dt=0.1)
        return math.inf if t >= 20.0 else t

    # -------------------------------------------------------------- hidden for a moment (6.7)
    GHOST = 0.4

    def ghosts(self, now=None, dead=None):
        """Followed units NOT seen in this look but seen within GHOST seconds (a Fireball / Lightning flash, a unit
        behind another): still there, moved on their speed — so the battle engine does not plan as if they died
        and change its mind when they come back. Not when its health bar was at the end or `dead(track)` says a
        spell that landed on it kills it."""
        now = time.monotonic() if now is None else now
        out = []
        for tr in self.tracks:
            if tr.miss == 0 or tr.hits < 3 or now - tr.seen > self.GHOST: continue
            if tr.life is not None and tr.life <= 0.1: continue
            if dead is not None and dead(tr): continue
            out.append(tr)
        return out

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        out = []
        for tr in self.tracks:
            if tr.hits < self.CONFIRM and now - tr.born < 0.3: continue
            d = tr.as_dict(now)
            d["ghost"] = tr.miss > 0
            e = self.eta(tr.id, now)
            d["eta"] = None if math.isinf(e) else round(e, 1)
            out.append(d)
        return out
