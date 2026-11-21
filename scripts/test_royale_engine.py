"""The bot's own checks of the battle engine, with the REAL engine (run by .github/workflows/royale_engine.yml on
Windows after each build, and by hand: python scripts/test_royale_engine.py). Exit code 1 on any failure."""
import os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from royale import engine
from royale.brain import Brain


class Log:
    def info(self, m): print("  log:", m)
    debug = warning = info


fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok: fails.append(name)


ok = engine.selftest(Log())
check("self-test", ok, engine.status()["why"])
if not ok: sys.exit(1)
m = engine.module()
ids = engine.card_ids()
deck = ["hog_rider", "cannon", "musketeer", "fireball", "ice_golem", "skeletons", "ice_spirit", "the_log"]
check("our deck's cards are known", all(n in ids for n in deck), str([n for n in deck if n not in ids]))
user = ["witch", "bowler", "musketeer", "bats", "hog_rider", "cannon", "goblin_barrel", "the_log"]
check("the user's deck's cards are known", all(n in ids for n in user), str([n for n in user if n not in ids]))

# coordinates: a unit put on our tile (3, 10) shows at engine (3, 11); our left Princess is at our (3.5, 5)
e = m.ClashRoyaleEnv(engine._filler_deck(m, []), engine._filler_deck(m, []), 3600)
e.reset()
e.inject(ids["knight"][0] if "knight" in ids else 2, *engine.eng_xy(3, 10), 0, -1.0, 0)
e.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 1)          # an injected body joins the board on the next tick
u = [u for u in e.get_units() if not u.tower]
check("tile -> engine point", u and abs(u[0].x - 3) < 0.3 and abs(u[0].y - 11) < 0.3,
      f"{[(x.x, x.y) for x in u]}")
tw = [(t.x, t.y, t.team) for t in e.get_units() if t.tower]
print("  towers:", tw)
check("our towers at the bottom (team 0, low y)", all((t[1] < 10) == (t[2] == 0) for t in tw))
# the bot's tower places (royale.brain) land on the engine's towers
from royale.brain import OUR_TOWERS, THEIR_TOWERS
ok_t = all(any(abs(tx - (bx - 0.5)) < 0.6 and abs(ty - (by + 1)) < 0.6 for tx, ty, _ in tw)
           for bx, by in list(OUR_TOWERS.values()) + list(THEIR_TOWERS.values()))
check("the bot's tower places = the engine's", ok_t)


def brain(stable, seen=()):
    b = Brain(); b.deck = list(deck); b.reset()
    b._stable = list(stable); b.enemy_seen = set(seen)
    return b


# defense: an enemy Hog at our left bridge, we hold Cannon / Musketeer / Fireball / Log
b = brain([("hog-rider", 3, 14)], {"hog_rider"})
st = {"hand": ["cannon", "musketeer", "fireball", "the_log"], "ready": [0, 1, 2, 3], "towers": {}, "allies": []}
engine._S["debug"] = []
t0 = time.perf_counter()
r = engine.think(b, st, st["hand"], [(i, n) for i, n in enumerate(st["hand"])], 7.0, None, Log())
ms = (time.perf_counter() - t0) * 1000
print("  defense vs Hog:", r, f"{ms:.0f} ms")
for row in sorted(engine._S["debug"], key=lambda x: -x[1] if x[0] == "wait" else -x[0])[:12]: print("   ", row)
engine._S["debug"] = None
check("defends a Hog with a card (not a wait)", r is not None and r[0] == "play")
check("does not answer a lone Hog with Fireball", r is None or r[0] != "play" or r[2] != "fireball")
check("thinks fast enough (< 300 ms)", ms < 300, f"{ms:.0f} ms")

# nothing on the board, nothing wanted: no opinion
b = brain([])
r = engine.think(b, st, st["hand"], [(i, n) for i, n in enumerate(st["hand"])], 7.0, None, Log())
check("empty board: no move forced", r is None, str(r))

# attack: the brain wants a Hog at the left bridge
st2 = {"hand": ["hog_rider", "cannon", "fireball", "the_log"], "ready": [0, 1, 2, 3], "towers": {}, "allies": []}
d = {"slot": 0, "card": "hog_rider", "tile": (3, 14), "why": "rule"}
r = engine.think(brain([]), st2, st2["hand"], [(0, "hog_rider")], 7.0, d, Log())
print("  attack:", r)
check("attack keeps the card and finds a spot", r is not None and r[0] == "play" and r[2] == "hog_rider")

# a Giant + Musketeer push on the right: a building in the middle should beat waiting
b = brain([("giant", 14, 16), ("musketeer", 14, 19)], {"giant", "musketeer"})
r = engine.think(b, st, st["hand"], [(i, n) for i, n in enumerate(st["hand"])], 8.0, None, Log())
print("  defense vs Giant push:", r)
check("defends a Giant push", r is not None and r[0] == "play")

print(f"\n{'ALL PASSED' if not fails else 'FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
