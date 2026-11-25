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
check("Knight's native id 0 stays in the deck",
      ids.get("knight", (None,))[0] == 0 and 0 in engine._deck_ids(m, ["knight"]))

# Minion Giant must work through normal card play, including its flight and
# building-only attack. Use a Cannon near midriver, away from the towers.
minion_giant_id = ids.get("minion_giant", (None,))[0]
check("Minion Giant is mapped from the native registry", minion_giant_id is not None)
if minion_giant_id is not None:
    deck_ids = engine._deck_ids(m, ["minion_giant", "knight", *deck[2:]])
    match = m.ClashRoyaleEnv(deck_ids, deck_ids, 3600)
    match.reset()
    check("Minion Giant fits in a native deck and hand", match.set_hand_for_team(0, deck_ids[:4]))
    match.set_elixir_for_team(0, 8.0)
    match.inject(ids["knight"][0], 8.0, 15.0, 1, -1.0, 0)
    match.inject(ids["cannon"][0], 8.0, 18.0, 1, -1.0, 0)
    match.step_self_play_fast(0, 8.0, 13.0, -1, 0.0, 0.0, 1)
    spawned = [u for u in match.get_units() if u.card_id == minion_giant_id and u.team == 0]
    check("Minion Giant costs four elixir and spawns as a flying unit",
          m.get_card_info(minion_giant_id)["cost"] == 4 and
          4 <= match.get_elixir_for_team(0) < 4.1 and len(spawned) == 1 and
          spawned[0].flying and spawned[0].hp == 1817)
    enemy_knight = next(u for u in match.get_units() if u.card_id == ids["knight"][0])
    cannon = next(u for u in match.get_units() if u.card_id == ids["cannon"][0])
    targeted_cannon = False
    for _ in range(40):
        match.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 1)
        targeted_cannon |= any(u.card_id == minion_giant_id and u.target_id == cannon.id
                               for u in match.get_units())
        if match.get_damage_dealt_by_card(minion_giant_id, 0):
            break
    check("Minion Giant targets Cannon for 153 damage and ignores Knight",
          targeted_cannon and match.get_damage_dealt_by_card(minion_giant_id, 0) == 153 and
          any(u.id == enemy_knight.id and u.hp == enemy_knight.hp for u in match.get_units()))

# coordinates: a unit put on our tile (3, 10) shows at engine (3, 11); our left Princess is at our (3.5, 5)
e = m.ClashRoyaleEnv(engine._filler_deck(m, []), engine._filler_deck(m, []), 3600)
e.reset()
e.inject(ids["knight"][0], *engine.eng_xy(3, 10), 0, -1.0, 0)
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
attack = brain([])
attack.elapsed = lambda: 0.0
r = engine.think(attack, st2, st2["hand"], [(0, "hog_rider")], 7.0, d, Log())
check("opening guard vetoes a negative bridge attack", r is not None and r[0] == "wait", str(r))
attack.elapsed = lambda: 16.0
r = engine.think(attack, st2, st2["hand"], [(0, "hog_rider")], 7.0, d, Log())
print("  attack:", r)
check("attack keeps the card and finds a spot", r is not None and r[0] == "play" and r[2] == "hog_rider")
attack.p["ai_only"] = True
check("AI-only engine keeps the model's slot and tile",
      engine.candidates(attack, [(0, "hog_rider"), (1, "cannon")], d, True, [(1, "cannon", (8, 9))])
      == [(0, "hog_rider", (3, 14))])
check("AI-only engine respects waiting", engine.think(attack, st2, st2["hand"], [(0, "hog_rider")], 7.0, None) is None)

# a Giant + Musketeer push on the right: a building in the middle should beat waiting
b = brain([("giant", 14, 16), ("musketeer", 14, 19)], {"giant", "musketeer"})
r = engine.think(b, st, st["hand"], [(i, n) for i, n in enumerate(st["hand"])], 8.0, None, Log())
print("  defense vs Giant push:", r)
check("defends a Giant push", r is not None and r[0] == "play")

# 5.71: a blank slot (a card just played) or a card the engine lacks must not stop the thinking
b = brain([("hog-rider", 3, 14)], {"hog_rider"})
st3 = {"hand": ["cannon", "blank", "fireball", "the_log"], "ready": [0, 2, 3], "towers": {}, "allies": []}
engine.new_battle()
engine._S["debug"] = []
t0 = time.perf_counter()
r = engine.think(b, st3, st3["hand"], [(0, "cannon"), (2, "fireball"), (3, "the_log")], 7.0, None, Log())
print("  defense with a blank slot:", r, engine.skips(), f"{(time.perf_counter() - t0) * 1000:.0f} ms")
for row in engine._S["debug"][:12]: print("   ", row)
print("    candidates:", engine.candidates(b, [(0, "cannon"), (2, "fireball"), (3, "the_log")], None, True)[:12])
engine._S["debug"] = None
check("thinks with a blank slot in the hand", engine.skips().get("thought", 0) == 1, str(engine.skips()))
check("defends the Hog with a blank slot too", r is not None and r[0] == "play")
b.deck = list(deck)[:5]                                     # the deck only half learned yet
r = engine.think(b, st, st["hand"], [(i, n) for i, n in enumerate(st["hand"])], 7.0, None, Log())
check("thinks with the deck half learned", engine.skips().get("thought", 0) == 2, str(engine.skips()))

# the mirror under every unit the eyes can name, anywhere on the board, any towers / elixir (the user's battles
# had "mirror error" in 58 of 69 thoughts): every crash is printed with its traceback
import random, traceback
from royale.brain import cards_db, _DB
cards_db()
units = sorted(set(_DB["unit_to_card"].keys()) | set(n.replace("_", "-") for n in _DB["unit_to_card"].keys()))
random.seed(7)
errs = {}
for k in range(400):
    stable = [(random.choice(units), random.uniform(-1, 18.5), random.uniform(-1, 32.5)) for _ in range(random.randint(0, 9))]
    b = brain(stable, {random.choice(list(engine.card_ids())) for _ in range(random.randint(0, 8))})
    b.enemy_elixir = random.uniform(-1, 11)
    b._allies_extra = [(random.choice(units), random.uniform(0, 17), random.uniform(0, 31)) for _ in range(random.randint(0, 5))]
    towers = {k2: random.choice([None, 0.0, 0.004, 0.5, 1.0, 1.2]) for k2 in ("their_left", "their_right", "our_left", "our_right")}
    hand = random.sample(list(deck), 4)
    if random.random() < 0.3: hand[random.randint(0, 3)] = "blank"
    st4 = {"hand": hand, "ready": [0, 1, 2, 3], "towers": towers, "allies": []}
    try:
        env, slots = engine.mirror(b, st4, hand, random.uniform(0, 10))
    except Exception as ex:
        key = repr(ex)[:120]
        if key not in errs:
            errs[key] = traceback.format_exc(limit=6)
            print("  MIRROR CRASH:", key, "\n", errs[key][-900:], "\n  stable:", stable[:4], "towers:", towers)
check("the mirror never crashes on any arena", not errs, f"{len(errs)} kinds of crash")

# 5.84: the opponent answers inside the search — a Musketeer alone at the bridge is worth less when they hold a Fireball
b = brain([], {"fireball", "hog_rider", "cannon"})
b.enemy_elixir = 7.0
rp = engine.replies(b, "musketeer", 3, 13)
print("  their answers to a Musketeer at the bridge:", rp)
check("the opponent has answers to try", len(rp) >= 1, str(rp))
st5 = {"hand": ["musketeer", "cannon", "fireball", "the_log"], "ready": [0, 1, 2, 3], "towers": {}, "allies": []}
env5, slots5 = engine.mirror(b, st5, st5["hand"], 8.0)
if env5 is not None:
    before = engine._snap_state(env5)
    x5, y5 = engine.eng_xy(3, 13)
    alone = engine._value(engine.rollout(env5, slots5["musketeer"], x5, y5), b, before, 4.0)
    worst = min(engine._value(e, b, before, 4.0) for e in
                (engine.rollout_reply(env5, slots5["musketeer"], x5, y5, r) for r in rp) if e is not None)
    print(f"  Musketeer at the bridge: {alone:+.2f} if they do nothing, {worst:+.2f} after their best answer")
    check("their answer makes a lone Musketeer worse", worst < alone, f"{alone:+.2f} vs {worst:+.2f}")

# 5.85: card levels — our cards 4 levels above theirs come out ~46 % stronger in the engine
if hasattr(m, "set_team_level_scale"):
    hog_id = engine.card_ids()["hog_rider"][0]
    def spawned_hp(scale):
        m.set_team_level_scale(0, scale)
        e = m.ClashRoyaleEnv(engine._filler_deck(m, [hog_id]), engine._filler_deck(m, []), 3600)
        e.reset()
        ids0 = {u.id for u in e.get_units()}
        e.inject(hog_id, 8.0, 10.0, 0, -1.0, 0)
        e.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 1)
        return max(u.hp for u in e.get_units() if u.id not in ids0 and not u.tower)
    h1, h2 = spawned_hp(1.0), spawned_hp(1.1 ** 4)
    m.set_team_level_scale(0, 1.0)
    print(f"  Hog hp at the engine's level {h1}, 4 levels higher {h2}")
    check("card levels change the units' strength", abs(h2 / h1 - 1.1 ** 4) < 0.02, f"{h2 / h1:.3f}")
    b6 = brain([]); b6.levels = {n.replace("_", ""): 15 for n in deck}; b6.their_level = 11
    check("our level 15 vs their 11 -> x1.46", abs(engine.level_scale(b6) - 1.4641) < 0.01, str(engine.level_scale(b6)))
else:
    check("the engine has card levels (rebuilt)", False, "set_team_level_scale missing")

# 5.86: our charged Evolution and our Hero cards go into the engine as themselves
b7 = brain([]); b7.hand_look = {"cannon": "_ev1"}
st7 = {"hand": ["cannon", "musketeer", "fireball", "the_log"], "ready": [0, 1, 2, 3], "towers": {}, "allies": []}
env7, slots7 = engine.mirror(b7, st7, st7["hand"], 6.0)
evo_id = engine.card_ids()["cannon"][1]
if env7 is not None and evo_id:
    got7 = env7.get_hand_for_team(0)
    check("a charged Evolution is the evolved card in the engine", got7[slots7["cannon"]] == evo_id, f"{got7} evo {evo_id}")

print(f"\n{'ALL PASSED' if not fails else 'FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
