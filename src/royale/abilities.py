"""
Hero / champion abilities: when the bot's Archer Queen, Golden Knight, Skeleton King, Mighty Miner, Monk, Little
Prince, Boss Bandit or Goblinstein is on the field, its ability button shows up just above the cards (on the left,
the right or both sides — the game's setting; up to 2 buttons). The bot finds the button by how the strip above the
cards changed since the battle began (a bright round button appears; grey = cooling down), and uses the ability at a
good moment, paying its elixir:

  archer_queen   Cloaking Cape (1)    enemies close to her or she is at their tower: invisible + faster arrows
  golden_knight  Dashing Dash (1)     2+ enemies near him: he chains through them
  skeleton_king  Soul Summoning (2)   a fight near him (the souls of the dead come back as skeletons)
  mighty_miner   Explosive Escape (1) he is being worn down / at their tower: bomb and switch lanes
  monk           Pensive Protection (1) a spell of theirs landing near him or a push in front of him
  little_prince  Royal Rescue (3)     2+ enemies near him: the guardian charges in
  boss_bandit / goblinstein (1-2)     a fight near them
  hero cards (seen with their hero picture in the hand: Hero Bowler, Knight, Giant, Musketeer, ...):
  bowler (hero)  Stone Swish (2)      plants his feet and throws 4 boulders far (11.5 tiles, 9 s): when he is in
                                      reach of their tower or 2+ enemies; not while they still hold The Log /
                                      Tornado / Barbarian Barrel (a push in the 2.5 s wind-up wastes it)
  other heroes   (2, a guess)         a fight near them
Never pays more elixir than there is; never taps a button that is grey (cooling down).
"""
import time

COST = {"archer_queen": 1, "golden_knight": 1, "skeleton_king": 2, "mighty_miner": 1, "monk": 1,
        "little_prince": 3, "boss_bandit": 1, "goblinstein": 2}
HERO_COST = {"bowler": 2}                   # hero cards' abilities (the others: 2, until their cost is known)
PUSHERS = {"the_log", "tornado", "barbarian_barrel", "fireball", "snowball", "giant_snowball", "bowler"}
# the strip just above the cards (fractions of the 720x1280 screen): the left and the right button places
REGIONS = {"left": (0.0, 0.745, 0.21, 0.835), "right": (0.79, 0.745, 1.0, 0.835)}


class Abilities:
    def __init__(self, log):
        self.log = log
        self.base = {}                       # region -> its picture when no ability button was there
        self.last_tap = {}
        self.backoff = {}

    def reset(self, frame):
        self.base = {k: self._crop(frame, r).astype("float32") for k, r in REGIONS.items()}
        self.last_tap, self.backoff = {}, {}

    @staticmethod
    def _crop(frame, r):
        h, w = frame.shape[:2]
        return frame[int(r[1] * h):int(r[3] * h), int(r[0] * w):int(r[2] * w)]

    def buttons(self, frame):
        """-> {region: (ready, (x, y))} where a button stands now (ready = bright, not grey)."""
        import numpy as np
        out = {}
        for k, r in REGIONS.items():
            cur = self._crop(frame, r).astype("float32")
            b = self.base.get(k)
            if b is None or b.shape != cur.shape: continue
            diff = np.abs(cur - b).mean(axis=2)
            changed = diff > 40
            if changed.mean() < 0.18: continue                  # nothing new there
            ys, xs = np.where(changed)
            cy, cx = ys.mean() / cur.shape[0], xs.mean() / cur.shape[1]
            sat = (cur.max(axis=2) - cur.min(axis=2))[changed].mean()
            ready = sat > 55                                    # colourful; a cooling-down button is greyed out
            x = r[0] + cx * (r[2] - r[0]); y = r[1] + cy * (r[3] - r[1])
            out[k] = (ready, (x, y))
        return out

    def tick(self, frame, brain, elixir, tap):
        """Use an ability when it pays. -> the champion whose ability was used, or None."""
        mine = getattr(brain, "heroes", set()) or set()
        heroes = [p for p in brain.plays if (p["card"] in COST or p["card"] in mine) and brain.elapsed() - p["t"] < 90]
        if not heroes or not self.base: return None
        now = time.monotonic()
        btns = self.buttons(frame)
        if not btns: return None
        # which hero is where: one hero -> any button; two -> the newer one is usually on the right
        heroes = sorted(heroes, key=lambda p: p["t"])
        for k, (ready, xy) in btns.items():
            if not ready or now < self.backoff.get(k, 0) or now - self.last_tap.get(k, 0) < 3.0: continue
            hero = heroes[-1] if (k == "right" or len(heroes) == 1) else heroes[0]
            name = hero["card"]
            cost = COST.get(name) or HERO_COST.get(name, 2)
            if cost > elixir: continue
            if not self._good_moment(name, hero, brain): continue
            tap(*xy)
            self.last_tap[k] = now
            self.backoff[k] = now + 6.0                       # it cools down: do not look again for a while
            self.log.info(f"Clash Royale: {name} ability ({cost} elixir)")
            return name
        return None

    @staticmethod
    def _good_moment(name, hero, brain):
        from royale.brain import dist, THEIR_TOWERS
        hx, hy = hero["tile"]
        # where the hero is now: its unit among our troops on the board (else where it was put)
        for a in getattr(brain, "_allies", []) or []:
            if a[0] in (name, name.replace("_", "")):
                hx, hy = a[1], a[2]
                break
        near = [u for u, x, y in getattr(brain, "_stable", []) or [] if dist((x, y), (hx, hy)) <= 5.0]
        at_tower = any(dist((hx, hy), t) <= 3.5 for t in THEIR_TOWERS.values())
        spell = any(dist((d[0], d[1]), (hx, hy)) <= d[2] + 1 for d in getattr(brain, "danger", []) or [])
        if name == "archer_queen": return len(near) >= 1 or at_tower
        if name == "golden_knight": return len(near) >= 2
        if name == "mighty_miner": return len(near) >= 2 or at_tower
        if name == "monk": return spell or len(near) >= 2
        if name == "little_prince": return len(near) >= 2
        if name == "bowler":
            hand = brain.their_hand() if hasattr(brain, "their_hand") else None
            if hand and any(c in PUSHERS for c in hand): return False      # it would be pushed in the wind-up
            reach = any(dist((hx, hy), t) <= 11.5 for t in THEIR_TOWERS.values()) and hy >= 15
            return reach or len([1 for _u, x, y in getattr(brain, "_stable", []) or []
                                 if dist((x, y), (hx, hy)) <= 11.5]) >= 2
        return len(near) >= 2
