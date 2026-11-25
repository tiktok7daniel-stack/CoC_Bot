"""
Checks of the 6.6 eyes (no graphics card needed; CI runs them on Windows):
  tracker    units crossing the bridge with noisy looks and missed looks: one id each, the side never flips once
             locked, the Fireball led to where the unit will be (< 0.8 tile), stopped at the tower it hits, ETA
  team       the colour reader on drawn badges / bars: blue = ours, red = theirs, the river / grass = unknown,
             and on a real battle picture when it is there (every unhurt enemy read from its red level badge)
  hand       the hand-model reader with a fake model: deck-only choice, a slot used only when sure and steady,
             5 slots cut and squashed the same way as the training
  sessions   trt_engine.VisionSession runs the bot's real models (on the processor here) like an InferenceSession
"""
import math, os, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
fails = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {info}" if info else ""), flush=True)
    if not ok: fails.append(name)


# ------------------------------------------------------------------ tracker
def test_tracker():
    from royale.unit_tracker import UnitTracker, Det
    random.seed(1)
    tr = UnitTracker()
    units = [("knight", 3.0, 24.0, 0.0, -1.0, "enemy"), ("knight", 4.2, 24.6, -0.1, -1.0, "enemy"),
             ("musketeer", 4.0, 8.0, 0.0, 0.8, "ally"), ("hog_rider", 14.0, 22.0, 0.0, -2.0, "enemy")]
    ids = {i: [] for i in range(len(units))}
    flips = 0
    dt = 0.1
    for k in range(60):
        t = k * dt
        dets, who = [], []
        for i, (n, x, y, vx, vy, team) in enumerate(units):
            if random.random() < 0.12: continue                       # a missed look
            px, py = x + vx * t, max(0.0, y + vy * t)
            col = team if random.random() < 0.6 else None              # the colour read 60% of the time
            side = team if random.random() < 0.8 else ("ally" if team == "enemy" else "enemy")   # side model 80%
            v = {"ally": 0.0, "enemy": 0.0}
            if col: v[col] += 2.3
            v[side] += 1.0
            tm = max(v, key=v.get)
            dets.append(Det(n, px + random.gauss(0, 0.3), py + random.gauss(0, 0.3), random.uniform(0.4, 0.9), tm,
                            abs(v["ally"] - v["enemy"]), None))
            who.append(i)
        for (d, track), i in zip(tr.update(dets, t), who):
            ids[i].append(track.id)
            if k > 15 and track.team != units[i][5]: flips += 1
    # two Knights 0.6 tile apart with 0.3 tile of noise can trade places for one look (one missed): what matters is
    # that no unit is ever split into a new track and each keeps its own id on (almost) every look
    own = {i: max(set(v), key=v.count) for i, v in ids.items()}
    share = min(v.count(own[i]) / len(v) for i, v in ids.items())
    made = len({x for v in ids.values() for x in v})
    check("tracker: no unit split into a new track (4 units = 4 ids)", made == len(units), f"{made} ids")
    check("tracker: each unit keeps its own id through the bridge (>= 95% of looks)", share >= 0.95,
          f"worst {100 * share:.0f}%")
    check("tracker: the side never flips once settled", flips == 0, f"{flips} wrong looks")
    t = 59 * dt
    kn = tr.nearest("knight", 3.0, 18.1, team="enemy")
    p = tr.predict_position(kn.id, "fireball", now=t)
    # truth: where it is when the fireball lands (tap 0.15 s + flight from our king tower at 10 tiles / s)
    y_now = 24.0 - t
    T = 0.15
    for _ in range(3): T = 0.15 + math.hypot(3.0 - 8.5, (y_now - T) - 1.5) / 10.0
    err = math.hypot(p[0] - 3.0, p[1] - (y_now - T))
    check("tracker: Fireball led onto the walking unit", err < 0.8, f"error {err:.2f} tile")
    hog = tr.nearest("hog_rider", 14.0, 10.0, team="enemy", within=8)
    p2 = tr.predict_position(hog.id, "rocket", now=t)
    check("tracker: a unit stops at the tower it hits (no lead past it)", p2[1] >= 5.0 + 0.8 + 1.0,
          f"hog led to y {p2[1]:.1f}")
    e = tr.eta(kn.id, now=t)
    check("tracker: ETA to our tower", 7 < e < 16, f"{e:.1f} s")
    ally = tr.nearest("musketeer", 4.0, 12.8, team="ally", within=3)
    check("tracker: our unit stays ours", ally is not None and ally.team == "ally")


def test_brain_lead():
    """The brain aims its spells with the tracker: a Fireball on a Hog Rider running at our tower lands ahead of it."""
    import time
    from royale.brain import Brain
    from royale.unit_tracker import UnitTracker, Det
    b = Brain(["fireball", "the_log", "arrows", "knight", "musketeer", "hog_rider", "skeletons", "cannon"])
    tr = UnitTracker()
    t0 = time.monotonic() - 1.0
    for k in range(11):                                    # 1 s of a Hog Rider running down the right lane
        tr.update([Det("hog_rider", 14.0, 22.0 - 2.0 * k * 0.1, 0.9, "enemy", 3.0, None)], t0 + k * 0.1)
    b.tracker = tr
    x, y = b.lead("fireball", 14, 20, "hog_rider")
    check("brain: the Fireball is led ahead of a running Hog Rider", y < 19.0 and abs(x - 14.0) < 0.5, f"({x:.1f}, {y:.1f})")
    check("brain: the lead is shown on the live screen", getattr(b, "_lead_seen", {}).get("card") == "fireball")


def test_occlusion():
    """A Fireball's flash hides a Knight for 3 looks (0.1 s each): it stays in the battle state, moved on its speed;
    a unit missing longer than 0.4 s is gone; one whose spell killed it is not kept."""
    from royale.unit_tracker import UnitTracker, Det
    from royale.eyes import Eyes
    tr = UnitTracker()
    t = 0.0
    for k in range(10):
        t = k * 0.1
        tr.update([Det("knight", 4.0, 20.0 - t, 0.9, "enemy", 3.0, None), Det("musketeer", 6.0, 22.0, 0.8, "enemy", 3.0, None)], t)
    hidden = []
    for k in range(10, 13):                                         # 3 looks: neither unit seen
        t = k * 0.1
        tr.update([], t)
        hidden.append({g.name for g in tr.ghosts(t)})
    check("occlusion: both units kept through 3 hidden looks", all(h == {"knight", "musketeer"} for h in hidden), str(hidden))
    kn = next(g for g in tr.ghosts(t) if g.name == "knight")
    x, y = kn.at(t)
    check("occlusion: the hidden Knight keeps walking on its speed", 18.4 < y < 19.2, f"y {y:.2f} (seen last at 19.1)")
    check("occlusion: gone after 0.35 s unseen", not tr.ghosts(t + 0.5))
    # the spell that landed on it: a full-health Musketeer survives a Fireball (282 hp > 269, the game's numbers),
    # one at 60% life (its bar read before the flash) does not
    keep = lambda: {g.name for g in tr.ghosts(t, dead=lambda g: Eyes._killed(g, [("fireball", 6, 22)]))}
    full = keep()
    next(g for g in tr.tracks if g.name == "musketeer").life = 0.6
    hurt = keep()
    check("occlusion: a full-health Musketeer survives the Fireball (kept)", "musketeer" in full, str(full))
    check("occlusion: a hurt one the Fireball kills is not kept", "musketeer" not in hurt and "knight" in hurt, str(hurt))


def test_skins_and_ids():
    """6.8: a tower skin read as an Archer never becomes a unit; flickering doubtful boxes (sparks, spell flashes) do
    not open new tracks (the ids stay small); ids start from 1 every battle; an arrow never runs past the unit's
    own speed."""
    import random
    from royale.unit_tracker import UnitTracker, Det
    random.seed(3)
    tr = UnitTracker(); tr.reset()
    seen_skin = []
    for k in range(87 * 10 // 10):                       # 8.7 s at 10 looks a second
        t = k * 0.1
        dets = [Det("archer", 3.5, 26.0, 0.7, "enemy", 2.0, None, True),        # the skull skin on their tower
                Det("knight", 9.0, 20.0 - 0.9 * t, 0.85, "enemy", 3.0, None, False)]
        # sparks / explosions: 4 doubtful boxes a look in random places
        dets += [Det(random.choice(["spirit", "skeleton", "archer"]), random.uniform(0, 17), random.uniform(0, 31),
                     random.uniform(0.3, 0.49), None, 0.0, None, False) for _ in range(4)]
        out = tr.update(dets, t)
        seen_skin.append(out[0][1] is not None)
    snap = tr.snapshot(t)
    check("skins: the tower skin is not a unit after 0.8 s", not any(seen_skin[10:]) and
          not any(d["unit"] == "archer" and abs(d["x"] - 3.5) < 1 for d in snap), f"{sum(seen_skin[10:])} looks")
    from royale.unit_tracker import Track
    check("ids: doubtful sparks open no tracks (ids stay small)", Track._ids <= 3, f"last id #{Track._ids}")
    tr.reset()
    tr.update([Det("knight", 5.0, 20.0, 0.9, "enemy", 3.0, None, False)], 0.0)
    check("ids: count from #1 every battle", tr.tracks[0].id == 1, f"#{tr.tracks[0].id}")
    t2 = UnitTracker(); t2.reset()
    for k in range(10):                                  # the eyes jump 2 tiles a look: not a walk
        t2.update([Det("giant", 9.0, 20.0 - 2.0 * k, 0.9, "enemy", 3.0, None, False)], k * 0.1)
    g = t2.tracks[0]
    check("speed: never faster than the card walks (+30%)", g.speed() <= 1.3 * 45 / 60 + 1e-6, f"{g.speed():.2f} tiles/s")


def test_team_birth():
    """6.9.17: whose a unit is, from where it was born and the bot's own placements — not from one look."""
    from royale.unit_tracker import UnitTracker, Det
    tr = UnitTracker(); tr.reset()
    tr.note_play("knight", (5, 8))
    out = tr.update([Det("knight", 5.2, 8.4, 0.8, "enemy", 2.3, None)], __import__("time").monotonic())   # a wrong red read
    check("team: our just-placed Knight is ours despite a wrong colour read", out[0][1].team == "ally", out[0][1].team)
    out = tr.update([Det("musketeer", 9.0, 24.0, 0.8, "ally", 1.0, None)], __import__("time").monotonic())  # side model wrong
    check("team: a unit born on their half is theirs despite a wrong side-model read", out[0][1].team == "enemy",
          out[0][1].team)
    t2 = UnitTracker(); t2.reset()
    out = t2.update([Det("goblin", 3.5, 7.0, 0.8, "enemy", 2.3, None)], 0.0)       # a Goblin Barrel at our tower
    check("team: barrel goblins on our half go by their colour (red = theirs)", out[0][1].team == "enemy", out[0][1].team)


def test_fast_eyes():
    """6.9.18: the big eyes too slow for the very picture -> the fast eyes (YOLO26s) look at it (same moment)."""
    import numpy as np, time
    from royale import strong_eyes as se

    class Sess:
        def __init__(self, ms, cls): self.ms, self.cls, self.kind = ms, cls, "cpu"
        def get_inputs(self):
            class I: name, shape = "images", [1, 3, 640, 640]
            return [I()]
        def run(self, _n, feed):
            time.sleep(self.ms / 1000)
            out = np.zeros((1, 4 + 3, 10), np.float32)
            out[0, :4, 0] = [320, 320, 40, 40]; out[0, 4 + self.cls, 0] = 0.9      # one box of class `cls`
            return [out]
    saved = (dict(se._S), dict(se._F), dict(se._A), se.fast_ready)
    try:
        se._S.update(sess=Sess(60, 0), names={0: "knight", 1: "archer", 2: "giant"})
        se._F.update(sess=Sess(5, 2), names={0: "knight", 1: "archer", 2: "giant"}, ms=0.0)
        se._A.update(ms=60.0, t=0.0, dets=[])
        se.fast_ready = lambda: True
        d = se.look_now(np.zeros((1280, 720, 3), np.uint8))
        check("fast eyes: a slow big model -> the fast one answers for the very picture",
              bool(d) and d[0][0] == "giant" and se.same_moment(), str(d[:1]))
    finally:
        se._S.clear(); se._S.update(saved[0]); se._F.clear(); se._F.update(saved[1])
        se._A.update({k: v for k, v in saved[2].items() if k != "thread"}); se.fast_ready = saved[3]


def test_double_drop():
    """6.9.18: a second card right after the first when a fast threat is about to hit a tower; not otherwise."""
    import time
    from royale.brain import Brain
    from royale.unit_tracker import UnitTracker, Det
    b = Brain(["cannon", "musketeer", "fireball", "the_log", "knight", "skeletons", "ice_spirit", "hog_rider"])
    tr = UnitTracker(); tr.reset()
    t0 = time.monotonic() - 0.6
    for k in range(7):
        tr.update([Det("hog_rider", 14.5, 12.0 - 2.0 * k * 0.1, 0.9, "enemy", 3.0, None)], t0 + k * 0.1)
    b.tracker = tr
    b._stable = [("hog_rider", 14, 11)]
    check("double drop: a Hog about to hit our tower is urgent", b._urgent_defence([("hog_rider", 14, 11)]))
    check("double drop: nothing coming is not urgent", not b._urgent_defence([]))


def test_replay_heat():
    """6.9.18: answers remembered with their tile; their answers to our attacks learned turned round to our half."""
    import tempfile, os
    from pathlib import Path
    os.environ["HOME"] = tempfile.mkdtemp()
    import importlib, royale.memory as mm
    importlib.reload(mm)
    m = mm.Memory("t"); m.start()
    ok_t = {"our_left": 1.0, "our_right": 1.0, "their_left": 1.0, "their_right": 1.0}
    bad_t = dict(ok_t, our_left=0.7)
    t = 0.0
    for _ in range(3):
        m.defended("hog_rider", "cannon", "left", ok_t, t, tile=(7, 9)); t += 9; m.tick(ok_t, t)
    m.defended("hog_rider", "cannon", "left", ok_t, t, tile=(5, 4)); t += 9; m.tick(bad_t, t)
    for _ in range(2):
        m.opp_defended("hog_rider", "tesla", "right", (10, 21), ok_t, t); t += 9; m.tick(ok_t, t)
    check("replay heat: the tile that held comes back", m.best_tiles("hog_rider", "cannon", "left")[0][0] == (7, 9))
    check("replay heat: mirrored for the other lane", m.best_tiles("hog_rider", "cannon", "right")[0][0] == (10, 9))
    check("replay heat: the failed tile does not", all(x[0] != (5, 4) for x in m.best_tiles("hog_rider", "cannon", "left")))
    check("replay heat: their answer learned on our half", m.best_tiles("hog_rider", "tesla", "left")[0][0] == (7, 10))


def test_path():
    """The aim follows the path: a Hog Rider goes over its bridge then turns to the Cannon pulling it; a unit already
    at our tower stands there (no lead behind it); a building never walks."""
    from royale.unit_tracker import UnitTracker, Det
    tr = UnitTracker()
    for k in range(8):
        tr.update([Det("hog_rider", 14.5, 24 - 0.2 * k, 0.9, "enemy", 3, None), Det("cannon", 9.0, 9.0, 0.9, "ally", 3, None)], k * 0.1)
    h = tr.nearest("hog_rider", 14.5, 22.6, team="enemy")
    x4, y4, _ = tr._walk(h, h.x, h.y, h.vx, h.vy, 4.0)
    x6, y6, _ = tr._walk(h, h.x, h.y, h.vx, h.vy, 6.0)
    check("path: the Hog crosses at its bridge (x stays on the lane)", abs(x4 - 14.5) < 1.2 and 14.5 <= y4 <= 17.0,
          f"({x4:.1f}, {y4:.1f}) at 4 s")
    check("path: then it turns toward our Cannon, not straight down", x6 < 13.5, f"({x6:.1f}, {y6:.1f}) at 6 s")
    tr2 = UnitTracker()
    for k in range(6):
        tr2.update([Det("giant", 3.5, 7.4, 0.9, "enemy", 3, None)], k * 0.1)       # at our left tower, hitting it
    g = tr2.tracks[0]
    p = tr2.predict_position(g.id, "fireball", now=0.5)
    check("path: a unit at our tower is aimed where it stands", abs(p[1] - 7.4) < 0.4, f"{p}")
    c = tr.nearest("cannon", 9.0, 9.0, team="ally")
    check("path: a building never walks", tr._walk(c, 9.0, 9.0, 0.0, 0.0, 5.0)[:2] == (9.0, 9.0))


def test_soft_rules():
    """A defensive building with nothing coming: the rule brain alone does not play it, the engine may (it paid the
    preference's cost in its comparison); a spell on nothing stays forbidden for everyone."""
    from royale.brain import Brain
    from royale import card_use
    b = Brain(["cannon", "hog_rider", "the_log", "fireball", "musketeer", "ice_spirit", "skeletons", "knight"])
    b._stable = []
    pen, why = card_use.penalty(b, "cannon", (8, 9))
    check("rules: an idle building costs elixir, it is not banned", pen > 0 and why, f"{pen} {why}")
    check("rules: the rule brain alone still does not play it", card_use.check(b, "cannon", (8, 9), "x") is None)
    check("rules: the engine-weighed move goes through", card_use.check(b, "cannon", (8, 9), "x", engine_ok=True) is not None)
    d = b.play_ai(0, "the_log", (9, 12), "engine", __import__("time").monotonic(), engine_ok=True)
    check("rules: a spell on nothing stays forbidden, even from the engine", d is None)


# ------------------------------------------------------------------ team colour
def test_team():
    import numpy as np
    from royale.team_color import TeamColor
    f = np.full((1280, 720, 3), (90, 140, 60), np.uint8)               # grass
    f[560:640, :] = (80, 170, 230)                                       # the river
    f[290:306, 110:128] = (40, 110, 230)                                 # our badge (blue square) over a unit
    f[690:706, 410:428] = (210, 40, 89)                                  # their badge (the game's crimson)
    f[300:304, 130:170] = (60, 170, 240)                                 # our health bar
    tc = TeamColor().prepare(f)
    a = tc.team((110, 310, 160, 370))[0]
    b = tc.team((405, 710, 455, 770))[0]
    c = tc.team((300, 640, 340, 700))[0]
    d = tc.team((600, 900, 640, 960))[0]
    check("team: blue badge + bar = ours", a == "ally", str(a))
    check("team: crimson badge = theirs (full health, no bar)", b == "enemy", str(b))
    check("team: the river under a unit is not a colour", c is None, str(c))
    check("team: plain grass = unknown", d is None, str(d))
    real = Path.home() / "clashfarmer-learning" / "inbox" / "stuck" / "clash_20261118_230915.jpg"
    if not real.exists(): real = Path("/home/user/clashfarmer-learning/inbox/stuck/clash_20261118_230915.jpg")
    if real.exists():
        from PIL import Image
        im = np.array(Image.open(real).convert("RGB").resize((720, 1280)))
        tc.prepare(im)
        s = 720 / 1280
        got = [tc.team([v * s for v in b])[0] for b in ((420, 410, 470, 470), (512, 410, 562, 470),
                                                       (420, 485, 470, 545), (270, 545, 320, 610))]
        check("team: a real battle picture — 4 unhurt enemies read from their badges", got == ["enemy"] * 4, str(got))


# ------------------------------------------------------------------ hand model reader
def test_hand():
    import numpy as np
    from royale import hand_classifier as hc

    class Fake:
        def __init__(self, rows): self.rows = rows
        def get_inputs(self):
            class I: name, shape = "images", [5, 3, 128, 128]
            return [I()]
        def run(self, _n, feed):
            assert feed["images"].shape == (5, 3, 128, 128)
            return [np.array(self.rows, np.float32)]
    classes = ["goblin_barrel", "goblin_gang", "knight", "knight_ev1", "arrows"]
    # slot rows: next, hand 1..4
    rows = [[0.40, 0.55, 0.02, 0.02, 0.01],   # gang read, but it is in no deck: the barrel wins inside the deck
            [0.7, 0.2, 0.05, 0.03, 0.02],      # barrel, sure
            [0.01, 0.01, 0.3, 0.66, 0.02],     # knight evolved (the knight's two looks add up)
            [0.3, 0.3, 0.2, 0.1, 0.1],         # unsure
            [0.0, 0.0, 0.0, 0.0, 1.0]]         # arrows, certain
    c = hc.HandClassifier(Fake(rows), classes, 128)
    frame = np.zeros((1280, 720, 3), np.uint8)
    deck = {"goblin_barrel", "knight", "arrows", "fireball", "the_log", "musketeer", "hog_rider", "skeletons"}
    first = c.read(frame, allowed=deck)
    check("hand: a certain card is used at once", first[4] == ("arrows", ""), str(first[4]))
    check("hand: a sure card waits for a 2nd look (steady)", first[1] is None, str(first[1]))
    second = c.read(frame, allowed=deck)
    check("hand: sure + steady is used", second[1] == ("goblin_barrel", ""), str(second[1]))
    check("hand: the evolved look is kept", second[2] == ("knight", "_ev1"), str(second[2]))
    check("hand: an unsure slot keeps the picture matcher's reading", second[3] is None, str(second[3]))
    check("hand: only deck cards compete (Gang read -> Barrel)", second[0] == ("goblin_barrel", ""), str(second[0]))
    x = hc.crops(np.random.randint(0, 255, (1280, 720, 3), np.uint8), 128)
    check("hand: 5 slots cut and squashed", x.shape == (5, 3, 128, 128) and 0 <= x.min() and x.max() <= 1.0)


# ------------------------------------------------------------------ sessions
def test_sessions():
    import numpy as np
    import trt_engine
    m = ROOT / "assets" / "royale" / "models" / "units_M_480x352.onnx"
    s = trt_engine.make_session(m, threads=2)
    out = s.run(None, {s.get_inputs()[0].name: np.random.rand(1, 3, 480, 352).astype(np.float16)})[0]
    check("sessions: the drop-in runs the units model", out.shape == (1, 300, 6), f"{s.kind} {out.shape}")
    check("sessions: no TensorRT here = no crash, a working provider", s.kind in ("cpu", "dml", "cuda", "trt"), s.kind)


def test_tactics():
    """6.9.20: the Goblin Barrel is hit as it lands (not while far), the King Tower is woken once, never twice."""
    import time
    from royale.brain import Brain
    deck = ["the_log", "arrows", "knight", "musketeer", "hog_rider", "skeletons", "tornado", "fireball"]
    now = time.monotonic()
    b = Brain(deck); b.reset(); b._stable, b._towers_now = [], {}
    b._barrels = [(now - 0.1, 4.0, 18.0), (now, 3.9, 16.0)]
    check("barrel: still far = wait (elixir kept)", b._intercept_barrel([(0, "the_log")], now) is None)
    b._barrels = [(now - 0.1, 3.6, 8.5), (now, 3.5, 7.5)]
    d = b._intercept_barrel([(0, "the_log")], now)
    check("barrel: about to land = the Log at the landing tile", d is not None and d["card"] == "the_log"
          and d["tile"] == (4, 6), str(d and d["tile"]))
    k = Brain(deck); k.reset(); k.t0 = now - 30; k._towers_now = {"our_left": 1.0, "our_right": 1.0}
    k._stable, k._allies = [("mega_knight", 6, 9)], []
    d1 = k._king_activation([(1, "skeletons")], k._stable, {}, now)
    check("king: splash on our side = cheap bait on the king", d1 is not None and d1["card"] == "skeletons", str(d1))
    check("king: only once a battle", k._king_activation([(1, "skeletons")], k._stable, {}, now) is None)
    k2 = Brain(deck); k2.reset(); k2.t0 = now - 30; k2._towers_now = {"our_left": 0.0, "our_right": 1.0}
    k2._stable = [("mega_knight", 6, 9)]
    check("king: a princess tower down (king awake) = nothing", k2._king_activation([(1, "skeletons")], k2._stable, {}, now) is None)


def test_tactics_stronger():
    """6.9.21: barrel picks cheapest spell & keeps target on _play fail; far king splash ignored; early def spell & no bridge leak."""
    import time, types
    from royale.brain import Brain
    from royale import engine
    now = time.monotonic()
    deck = ["fireball", "knight", "the_log", "musketeer", "hog_rider", "skeletons", "arrows", "cannon"]
    b = Brain(deck); b.reset(); b._stable = []; b._towers_now = {}
    b._barrels = [(now - 0.1, 3.6, 8.5), (now, 3.5, 7.5)]
    d = b._intercept_barrel([(0, "fireball"), (2, "the_log")], now)
    check("barrel: picks the_log before earlier-slot fireball", d is not None and d["card"] == "the_log", str(d))

    # if _play declines (e.g. hold / blocked), keep _barrels intact
    b2 = Brain(deck); b2.reset(); b2._stable = []; b2._towers_now = {}
    b2._barrels = [(now - 0.1, 3.6, 8.5), (now, 3.5, 7.5)]
    b2._play = lambda *a, **kw: None
    d_none = b2._intercept_barrel([(2, "the_log")], now)
    check("barrel: keeps tracked barrel when _play returns None", d_none is None and len(b2._barrels) == 2)

    # king activation ignores far splash troops at river (y=11)
    k = Brain(deck); k.reset(); k.t0 = now - 30; k._towers_now = {"our_left": 1.0, "our_right": 1.0}
    k._stable, k._allies = [("bowler", 5, 11)], []
    check("king: ignores far bowler at y=11", k._king_activation([(5, "skeletons")], k._stable, {}, now) is None)

    # defensive spell allowed before all 8 deck cards known (on our half, swarm >= 2), blocked on their half
    bs = Brain(["the_log", "witch", "hog_rider"]); bs.reset()
    bs._allies, bs._allies_extra = [], []
    bs._stable = [("skeleton", 4.0, 8.0), ("skeleton", 4.5, 8.2)]
    check("spell: early defensive swarm allowed before 8 cards", bs._spell_sure("the_log", (4, 7)))
    bs._stable = [("skeleton", 4.0, 24.0), ("skeleton", 4.5, 24.2)]
    check("spell: blind attack spell still blocked before 8 cards", not bs._spell_sure("the_log", (4, 24)))

    # ai_only opening hold < 4s without threat / full elixir
    ba = Brain(deck); ba.reset(); ba.t0 = now - 1.5; ba._stable = []
    ba._pol = {"play": 0.9, "cards": {"goblin_gang": 0.8, "hog_rider": 0.5}}
    check("opening: ai_only waits < 4s when no threat and not full",
          ba._ai_only_decide([(0, "hog_rider")], 6.0, [], {}, now) is None)

    # engine vetoes losing early bridge play (v = -0.6 at ty=14)
    orig = {k: getattr(engine, k) for k in ("ready", "module", "card_ids", "mirror", "rollout", "replies", "_snap_state", "_value", "candidates")}
    try:
        class _FakeEnv:
            def is_valid_placement(self, *a): return True
        class _FakeMod:
            def get_card_info(self, cid): return {"cost": 3}
        be = Brain(deck); be.reset(); be.t0 = now - 2.0; be._stable = []
        engine.ready = lambda: True
        engine.module = lambda: _FakeMod()
        engine.card_ids = lambda: {"goblin_gang": (1, 0)}
        engine.mirror = lambda br, st, hand, el: (_FakeEnv(), {"goblin_gang": 0})
        engine.rollout = lambda *a: types.SimpleNamespace(v=0)
        engine.replies = lambda *a: []
        engine._snap_state = lambda env: {}
        engine._value = lambda end, br, before, cost=0.0: (10.0 - 0.6) if cost else 10.0
        engine.candidates = lambda *a: [(0, "goblin_gang", (3, 14))]
        res = engine.think(be, {}, ["goblin_gang"], [(0, "goblin_gang")], 6.0,
                           rule_d={"slot": 0, "card": "goblin_gang", "tile": (3, 14)})
        check("engine: vetoes negative early bridge drop", res and res[0] == "wait", str(res))
    finally:
        for k, v in orig.items(): setattr(engine, k, v)


def test_trt_and_gpu_recovery():
    """6.9.21: trt_engine.activate succeeds even when ort_trt is inherited in sys.path; strong_eyes/OnnxDetector recover."""
    import tempfile, types
    import numpy as np
    import trt_engine, ort_gpu

    orig_ort = sys.modules.get("onnxruntime")
    class _FakeSO: pass
    if orig_ort is None:
        sys.modules["onnxruntime"] = types.SimpleNamespace(
            SessionOptions=_FakeSO,
            InferenceSession=lambda *a, **kw: types.SimpleNamespace(get_providers=lambda: ["CPUExecutionProvider"], run=lambda *a: [np.array([1.0])]),
            get_available_providers=lambda: ["CPUExecutionProvider"],
        )
    from royale import strong_eyes

    # 1) trt_engine.activate with TARGET already in sys.path (inherited via PYTHONPATH)
    orig_target, orig_ready, orig_s = trt_engine.TARGET, trt_engine.READY, dict(trt_engine._S)
    orig_info, orig_dirs, orig_healthy = trt_engine.info, trt_engine.dll_dirs, ort_gpu.healthy
    orig_path_env, orig_pp, orig_sys_path = os.environ.get("PATH", ""), os.environ.get("PYTHONPATH"), list(sys.path)
    try:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td); dll = tp / "tensorrt_libs"; dll.mkdir()
            (tp / "READY").write_text("ok", encoding="utf-8")
            trt_engine.TARGET = tp; trt_engine.READY = tp / "READY"
            trt_engine._S.update(active=False)
            trt_engine.info = lambda: {"mode": "trt"}
            trt_engine.dll_dirs = lambda: [dll]
            ort_gpu.healthy = lambda folder: True
            sys.path.insert(0, str(tp))
            ok = trt_engine.activate()
            check("trt_engine: activates even when inherited in sys.path",
                  ok and trt_engine.active() and str(dll) in os.environ.get("PATH", ""), str(ok))
    finally:
        trt_engine.TARGET, trt_engine.READY = orig_target, orig_ready
        trt_engine._S.clear(); trt_engine._S.update(orig_s)
        trt_engine.info, trt_engine.dll_dirs = orig_info, orig_dirs
        ort_gpu.healthy = orig_healthy
        os.environ["PATH"] = orig_path_env
        if orig_pp is None: os.environ.pop("PYTHONPATH", None)
        else: os.environ["PYTHONPATH"] = orig_pp
        sys.path[:] = orig_sys_path

    # 2) strong_eyes._run_sess rebuilds GPU session instead of crashing on 887A0005
    class _FailSess:
        kind = "dml"; path = "fake.onnx"
        def get_inputs(self): return [types.SimpleNamespace(name="images")]
        def run(self, *a): raise RuntimeError("887A0005 The GPU device instance has been suspended")
    class _GoodSess:
        kind = "trt"; path = "fake.onnx"
        def get_inputs(self): return [types.SimpleNamespace(name="images")]
        def run(self, *a): return [np.array([[[1.0, 2.0]]], dtype=np.float32)]
    orig_se_s = dict(strong_eyes._S)
    orig_make = trt_engine.make_session
    try:
        st = {"sess": _FailSess(), "cpu_until": 0.0, "error": ""}
        trt_engine.make_session = lambda *a, **kw: _GoodSess()
        out = strong_eyes._run_sess(st, st["sess"], np.zeros((1, 3, 16, 16), np.float32))
        check("strong_eyes: rebuilds GPU session after DirectML 887A0005",
              out.shape == (1, 2) and isinstance(st["sess"], _GoodSess), str(out.shape))

        # 3) OnnxDetector._infer rebuilds GPU rather than staying locked on CPU forever
        from royale.vision.detectors.onnx_detector import OnnxDetector
        det = OnnxDetector.__new__(OnnxDetector)
        det.model_path, det.output_name, det.input_name = "m.onnx", "out", "in"
        det.gpu, det._gpu_retry_at, det._threads = True, 0.0, 2
        det.sess = _FailSess()
        trt_engine.make_session = lambda *a, **kw: types.SimpleNamespace(
            kind="trt", get_providers=lambda: ["TensorrtExecutionProvider"],
            run=lambda *a: [np.array([42.0])]
        )
        res = det._infer(np.zeros((1, 3, 8, 8), np.float32))
        check("onnx_detector: restores GPU session on error instead of locking CPU",
              det.gpu and float(res[0]) == 42.0, str(res))
    finally:
        trt_engine.make_session = orig_make
        strong_eyes._S.clear(); strong_eyes._S.update(orig_se_s)
        if orig_ort is None: sys.modules.pop("onnxruntime", None)


def test_adb_and_stream_fixes():
    """6.9.21: start_game routes through _recover on ADB loss; verified fresh stream avoids periodic adb_grab; side_detector skipped when color sure."""
    import time, types
    import numpy as np
    orig_cv2 = sys.modules.get("cv2")
    if orig_cv2 is None:
        sys.modules["cv2"] = types.SimpleNamespace(INTER_LINEAR=1, resize=lambda img, d, interpolation=1: img)
    try:
        import stream_capture
        from royale import game as rgame

        # 1) start_game failure in RoyaleBot.run() triggers _recover instead of escaping to launch.py
        bot = rgame.RoyaleBot.__new__(rgame.RoyaleBot)
        bot.s, bot.log, bot._frame_fails = {}, types.SimpleNamespace(info=lambda *a: None, warning=lambda *a: None, debug=lambda *a, **k: None), 0
        recovered = {"n": 0}
        def fake_recover(err):
            recovered["n"] += 1
            bot._frame_fails = 0
        bot._recover = fake_recover
        bot._status = lambda *a: None
        bot._say = lambda *a, **kw: None
        orig_start, orig_u = rgame.start_game, rgame._u
        try:
            rgame.start_game = lambda log: (_ for _ in ()).throw(RuntimeError("Action 'shell' failed"))
            calls = {"n": 0}
            def fake_running():
                calls["n"] += 1
                return calls["n"] == 1
            rgame._u = lambda: types.SimpleNamespace(running=fake_running)
            bot.run()
            check("game: start_game failure calls _recover cleanly", recovered["n"] == 1, str(recovered))
        finally:
            rgame.start_game, rgame._u = orig_start, orig_u

        # 2) stream_capture skips periodic adb_grab when already verified and frames are fresh
        orig_s = dict(stream_capture._S)
        orig_en, orig_cl = stream_capture._enabled, stream_capture._client
        try:
            adb_calls = {"n": 0}
            fake_c = types.SimpleNamespace(alive=True, frame_t=time.monotonic(), frames=50,
                                           latest=lambda: np.zeros((1280, 720, 3), np.uint8))
            stream_capture._enabled = lambda: True
            stream_capture._client = lambda dev: fake_c
            stream_capture._S.update(off_until=0.0, verified=True, ok_until=0.0, checking=False)
            out = stream_capture.frame((720, 1280), lambda: adb_calls.__setitem__("n", adb_calls["n"] + 1), None)
            check("stream_capture: skips adb_grab verify on healthy verified stream",
                  out is not None and adb_calls["n"] == 0 and stream_capture._S["ok_until"] > time.time() + 10,
                  str((adb_calls["n"], out is not None)))
        finally:
            stream_capture._enabled, stream_capture._client = orig_en, orig_cl
            stream_capture._S.clear(); stream_capture._S.update(orig_s)

        # 3) Eyes._units skips side_detector.run when TeamColor sure >= 2.0, calls when < 2.0, and _match_hp matches +/-1 tile
        from royale.eyes import Eyes
        e = Eyes.__new__(Eyes)
        side_calls = {"n": 0}
        e.colors = types.SimpleNamespace(prepare=lambda f: None, team=lambda box: ("ally", 2.5))
        e.units = types.SimpleNamespace(
            possible_ally_names={"knight"},
            side_detector=types.SimpleNamespace(run=lambda img: side_calls.__setitem__("n", side_calls["n"] + 1) or "ally"),
        )
        class _Tr:
            def update(self, dets, now): return [(d, types.SimpleNamespace(team=d.team, life=None, conf=d.conf, x=d.x, y=d.y)) for d in dets]
            def ghosts(self, *a, **kw): return []
        e.tracker = _Tr(); e.two_v_two = False
        small = types.SimpleNamespace(width=720, height=1280, crop=lambda box: None)
        fr = np.zeros((1280, 720, 3), np.uint8)
        en, al = e._units(fr, [], [("knight", 0.9, 100, 600, 140, 660)], small, 10.0,
                          hp={("knight", 2, 11): 0.72}, spells=[])
        check("eyes: skips side_detector when color sure >= 2.0", side_calls["n"] == 0 and len(al) == 1, str((side_calls["n"], al)))
        e.colors = types.SimpleNamespace(prepare=lambda f: None, team=lambda box: ("ally", 0.8))
        e._units(fr, [], [("knight", 0.9, 100, 600, 140, 660)], small, 10.1, hp={}, spells=[])
        check("eyes: calls side_detector when color sure < 2.0", side_calls["n"] == 1, str(side_calls["n"]))
        check("eyes: _match_hp recovers life across 1-tile shift",
              Eyes._match_hp({("hog_rider", 14, 18): 0.65}, "hog_rider", 14, 17) == 0.65
              and Eyes._match_hp({("hog_rider", 14, 18): 0.65}, "hog_rider", 14, 10) is None)
    finally:
        if orig_cv2 is None: sys.modules.pop("cv2", None)


for fn in (test_tracker, test_brain_lead, test_occlusion, test_skins_and_ids, test_team_birth, test_fast_eyes, test_double_drop, test_replay_heat, test_path, test_soft_rules, test_team, test_hand, test_sessions, test_tactics, test_tactics_stronger, test_trt_and_gpu_recovery, test_adb_and_stream_fixes):
    try:
        fn()
    except Exception as e:
        import traceback; traceback.print_exc()
        check(fn.__name__, False, f"{type(e).__name__}: {e}")
print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
