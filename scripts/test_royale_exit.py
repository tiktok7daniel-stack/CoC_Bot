"""Smoke test of Expert Iteration (royale.exit_train) on the real engine (run on Windows by the engine workflow):
one short battle with search on both sides, the answers turned into training data, one round of training, the new
brain exported and played against the old one. Prints the speed (searches per second) for sizing the real run."""
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from royale import exit_train as X

fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name, detail)
    if not ok: fails.append(name)


deck = ["witch", "bowler", "musketeer", "bats", "hog_rider", "cannon", "goblin_barrel", "the_log"]
cx = X.Ctx()
metas = cx.meta_decks()
check("meta decks loaded", len(metas) >= 8, f"{len(metas)}: {[m[0] for m in metas][:6]}")
t0 = time.perf_counter()
samples, w, st = X.battle(cx, [cx.deck_ids(deck), cx.deck_ids(metas[0][1])], ["search", "search"], max_ticks=450, seed=1)
dt = time.perf_counter() - t0
print("  battle:", st, "winner", w, f"{dt:.1f} s, {st['searches'] / max(dt, 1e-6):.1f} searches/s")
check("search made answers", len(samples) >= 10, str(len(samples)))
check("both sides played cards (45 s: ~8+ expected)", st["moves"] >= 8, str(st["moves"]))
plays = [s[1] for s in samples]
print("  play targets:", [round(p, 2) for p in plays[:12]])
check("answers are not all 'wait'", max(plays) > 0.5)
arr = X._arrays(samples)
X.HOME.mkdir(parents=True, exist_ok=True)
out = X.train(arr, ROOT / "assets" / "royale" / "board_weights.npz", X.HOME / "smoke", epochs=1)
check("trained brain exported", Path(out).exists(), out)
sc = X.gate(out, str(ROOT / "assets" / "royale" / "board.onnx"), deck, games=2, max_ticks=300)
print("  gate score (2 short battles):", sc)
check("the gate runs", 0.0 <= sc <= 1.0)
print(f"\n{'ALL PASSED' if not fails else 'FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
