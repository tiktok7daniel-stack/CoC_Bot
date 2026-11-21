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

print(f"\n{'ALL PASSED' if not fails else 'FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
