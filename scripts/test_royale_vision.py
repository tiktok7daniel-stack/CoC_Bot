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
    check("occlusion: gone after 0.4 s unseen", not tr.ghosts(t + 0.5))
    # the spell that landed on it: a full-health Musketeer survives a Fireball (282 hp > 269, the game's numbers),
    # one at 60% life (its bar read before the flash) does not
    keep = lambda: {g.name for g in tr.ghosts(t, dead=lambda g: Eyes._killed(g, [("fireball", 6, 22)]))}
    full = keep()
    next(g for g in tr.tracks if g.name == "musketeer").life = 0.6
    hurt = keep()
    check("occlusion: a full-health Musketeer survives the Fireball (kept)", "musketeer" in full, str(full))
    check("occlusion: a hurt one the Fireball kills is not kept", "musketeer" not in hurt and "knight" in hurt, str(hurt))


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


for fn in (test_tracker, test_brain_lead, test_occlusion, test_path, test_soft_rules, test_team, test_hand, test_sessions):
    try:
        fn()
    except Exception as e:
        import traceback; traceback.print_exc()
        check(fn.__name__, False, f"{type(e).__name__}: {e}")
print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
