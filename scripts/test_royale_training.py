"""Smoke test of the self-play training with the account's deck (run on Windows by the engine workflow):
starts python_ai's trainer through royale.engine_ai for a few minutes and checks it runs, then (if it saved
weights) that the trained network proposes a move on a mirrored arena. Exit code 1 on failure."""
import os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("HOME", str(Path.home()))
from royale import engine, engine_ai

deck = ["witch", "bowler", "musketeer", "bats", "hog_rider", "cannon", "goblin_barrel", "the_log"]
assert engine.selftest(), engine.status()["why"]
print("deck spec:", engine_ai.deck_spec(deck))
print("missing:", engine_ai.missing())
ok, msg = engine_ai.start(deck)
print("start:", ok, msg)
if not ok: sys.exit(1)
t0 = time.time()
limit = float(os.environ.get("SMOKE_SECONDS", "420"))
while time.time() - t0 < limit and engine_ai.running():
    time.sleep(15)
    print(f"[{time.time() - t0:.0f}s] {engine_ai.progress()}")
alive = engine_ai.running()
engine_ai.stop()
log = (engine_ai.HOME / "train.log").read_text(encoding="utf-8", errors="ignore")
print("---- training log (tail) ----")
print("\n".join(log.splitlines()[-60:]))
if "Traceback" in log and not alive:
    print("FAIL: the trainer crashed")
    sys.exit(1)
if not alive and time.time() - t0 < limit - 20:
    print("FAIL: the trainer stopped early")
    sys.exit(1)
print("newest weights:", engine_ai.newest())
if engine_ai.newest():
    print("gate:", engine_ai.gate(deck))
w = engine_ai.weights()
print("trusted weights:", w)
if w:
    m = engine.module()
    env = m.ClashRoyaleEnv([int(x) for x in engine_ai.deck_spec(deck).split(",")], [15, 6, 25, 40, 24, 72, 33, 7], 3600)
    env.reset()
    env.set_elixir_for_team(0, 8.0)
    engine_ai.new_battle()                                  # loads the network in the background (as in a battle)
    p = None
    for _ in range(240):                                    # up to 2 minutes for torch + the weights
        p = engine_ai.propose(env)
        if p is not None: break
        time.sleep(0.5)
    print("trained AI proposes:", p, engine_ai.status()["why"])
    if p is None:
        print("FAIL: the trained network could not propose")
        sys.exit(1)
print("PASS")
