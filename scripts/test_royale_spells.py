"""How the bot uses Goblin Barrel / The Log / Arrows (the user's correction, 5.72). No game, no engine needed:
    python scripts/test_royale_spells.py"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from royale.brain import Brain

b = Brain()
b.deck = ['witch', 'bowler', 'cannon', 'arrows', 'spear_goblins', 'goblin_barrel', 'valkyrie', 'the_log']
b.reset()
now = time.monotonic()
fails = []


def setup(stable, el=5.0, allies=()):
    b._stable = list(stable); b._towers_now = {"their_left": 1.0, "their_right": 1.0}; b._my_el = el
    b.last_play = 0; b._allies = list(allies); b._allies_extra = []; b.plays = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name, detail)
    if not ok: fails.append(name)


setup([("knight", 4, 8)])
d = b._play((0, "goblin_barrel"), (4, 8), "defense", now)
check("Goblin Barrel thrown at home goes onto their tower", d and d["tile"][1] >= 24, str(d and d["tile"]))
setup([]); d = b._play((0, "goblin_barrel"), (14, 18), "x", now)
check("Goblin Barrel on the right lane -> their right tower", d and d["tile"] == (14, 25), str(d and d["tile"]))
setup([]); check("no Log on an empty spot", b._play((1, "the_log"), (8, 10), "x", now) is None)
setup([("goblin", 4, 12)]); check("no Log that misses", b._play((1, "the_log"), (8, 4), "x", now) is None)
setup([("goblin", 4, 9), ("goblin", 5, 9), ("goblin", 4, 10)])
check("the Log kills their goblins", b._play((1, "the_log"), (4, 8), "x", now) is not None)
setup([("skeleton", 4, 9), ("skeleton", 5, 9)], allies=[("witch", 4, 7, 1.0)])
check("no Log on skeletons while our Witch stands", b._play((1, "the_log"), (4, 8), "x", now) is None)
setup([("giant", 4, 10)]); check("no Arrows on one Giant", b._play((2, "arrows"), (4, 10), "x", now) is None)
setup([("minion", 4, 10), ("minion", 5, 10), ("minion", 4, 11)])
check("Arrows on minions", b._play((2, "arrows"), (4, 10), "x", now) is not None)
setup([], el=10)
check("full elixir: the Log rolls into their tower", b._play((1, "the_log"), (3, 23), "full elixir", now) is not None)
empty = {"left": {"value": 0, "center": None, "units": [], "main": None},
         "right": {"value": 0, "center": None, "units": [], "main": None}}
d = b._decide(["the_log", "goblin_barrel", "arrows", "valkyrie"], [0, 1, 2], 10, [],
              [(0, "the_log"), (1, "goblin_barrel"), (2, "arrows")], empty, {"their_left": 1.0, "their_right": 1.0}, now)
check("full elixir with only spells in hand: a play, not a leak", d is not None, str(d))

# 5.73: every card in its own place (royale.card_use)
setup([]); d = b._play((0, "hog_rider"), (4, 6), "x", now)
check("Hog with nothing to defend goes to the bridge", d and d["tile"][1] >= 12, str(d and d["tile"]))
setup([]); d = b._play((0, "musketeer"), (3, 13), "x", now)
check("Musketeer alone at the bridge goes behind our tower", d and d["tile"][1] <= 4, str(d and d["tile"]))
setup([]); b.plays = [{"card": "hog_rider", "tile": (3, 13), "t": b.elapsed()}]
d = b._play((0, "musketeer"), (3, 12), "x", now)
check("Musketeer behind our Hog stays with it", d and d["tile"][1] >= 10, str(d and d["tile"]))
setup([("knight", 4, 10)]); d = b._play((0, "musketeer"), (4, 9), "x", now)
check("Musketeer not dropped on top of a Knight", d and d["tile"][1] <= 7, str(d and d["tile"]))
setup([]); b.enemy_seen = set(); b.predicted = set()
check("no Cannon with nothing to pull", b._play((0, "cannon"), (8, 9), "x", now) is None)
setup([("hog_rider", 3, 14)]); d = b._play((0, "cannon"), (3, 3), "x", now)
check("Cannon vs a Hog goes in the middle", d and 6 <= d["tile"][0] <= 11 and 6 <= d["tile"][1] <= 11, str(d and d["tile"]))
setup([]); check("no Bats alone with nothing to do", b._play((0, "bats"), (14, 20), "x", now) is None)
setup([("mini_pekka", 4, 9)]); check("Bats on a Mini P.E.K.K.A", b._play((0, "bats"), (4, 9), "x", now) is not None)
setup([("giant", 4, 10)]); check("no Fireball on one Giant", b._play((0, "fireball"), (4, 10), "x", now) is None)

# 5.74: AI mode — the AI model plays, but a Hog coming at our tower is always defended
b2 = Brain(); b2.deck = list(b.deck); b2.reset(); b2.p["ai"] = True
t0, got = time.monotonic(), None
for k in range(25):
    got = b2.decide(['witch', 'arrows', 'cannon', 'valkyrie'], [0, 1, 2, 3], 7.0, [("hog_rider", 3, 16 - k * 0.4, 0.9)],
                    [], {"their_left": 1.0, "their_right": 1.0, "our_left": 1.0, "our_right": 1.0}, now=t0 + k * 0.5)
    if got: break
check("AI mode defends a Hog", got is not None and got["card"] != "goblin_barrel", str(got))

# 5.75: AI-only — every card played is one the AI model proposed (the rule brain plays nothing of its own)
b3 = Brain(); b3.deck = list(b.deck); b3.reset(); b3.p["ai"] = True; b3.p["ai_only"] = True
t0, ok_all, n_pl = time.monotonic(), True, 0
for k in range(30):
    d = b3.decide(['witch', 'arrows', 'cannon', 'valkyrie'], [0, 1, 2, 3], 9.0, [("hog_rider", 3, 16 - k * 0.4, 0.9)],
                  [], {"their_left": 1.0, "their_right": 1.0, "our_left": 1.0, "our_right": 1.0}, now=t0 + k * 0.7)
    if d:
        n_pl += 1
        ok_all = ok_all and d["why"].startswith("AI model") and any(c[1] == d["card"] for c in b3._ai_cands)
check("AI-only: only the model's own cards are played", n_pl > 0 and ok_all, f"{n_pl} plays")

print(f"\n{'ALL PASSED' if not fails else 'FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
