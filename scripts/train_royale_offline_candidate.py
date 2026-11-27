"""Train a local candidate from replay-aware simulator search, then test it offline."""
import argparse
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from royale import exit_train
from benchmark_royale_matches import load_replay_atlas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-atlas", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--teacher", choices=("search-replay", "search-crowns"), default="search-crowns")
    parser.add_argument("--training-games", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7013)
    args = parser.parse_args()
    if args.training_games < 2:
        parser.error("training-games must be at least two")

    import torch

    torch.manual_seed(args.seed)
    torch.set_num_threads(2)
    cx = exit_train.Ctx()
    if not cx.E.selftest():
        raise RuntimeError("Native simulator self-test failed")
    atlas = load_replay_atlas(args.replay_atlas)
    if not atlas:
        parser.error("replay atlas has no usable response placements")

    args.out_dir.mkdir(parents=True, exist_ok=False)
    featured = [cx.ids[name][variant] for name, variant in (
        ("cannon", 1), ("ice_wizard", 2), ("bats", 1), ("barbarian_barrel", 0),
        ("knight", 0), ("lightning", 0), ("minion_giant", 0), ("skeletons", 0))]
    decks = sorted((name, names) for name, names in cx.meta_decks() if len(set(names)) == len(names) == 8)
    rng = random.Random(args.seed)
    samples = []
    for index in range(args.training_games):
        _, names = rng.choice(decks)
        pair = [featured, cx.deck_ids(names)]
        if index % 2:
            pair.reverse()
        evidence, _, _ = exit_train.battle(
            cx, pair, [args.teacher, args.teacher], max_ticks=3600,
            explore=.08, seed=args.seed + index, replay_atlases=(atlas, atlas))
        samples.extend(evidence)
        print(f"Training match {index + 1}: {len(evidence)} labeled decisions", flush=True)
    if not samples:
        raise RuntimeError("Search returned no training evidence")
    path = exit_train.train(exit_train._arrays(samples), ROOT / "assets/royale/board_weights.npz",
                            args.out_dir / "candidate", epochs=2, log=lambda msg: print(msg, flush=True))
    report = args.out_dir / "acceptance.json"
    result = subprocess.run([
        sys.executable, str(ROOT / "scripts/benchmark_royale_matches.py"),
        "--candidate", path, "--baseline", args.teacher, "--matchups", "8", "--seeds", "1",
        "--min-win-rate", "0.55", "--out", str(report),
    ])
    if not report.is_file():
        raise RuntimeError("The candidate benchmark did not produce a report")
    (args.out_dir / "training.json").write_text(json.dumps({
        "teacher": args.teacher, "training_matches": args.training_games, "labeled_decisions": len(samples),
        "replay_atlas": args.replay_atlas.name, "atlas_groups": len(atlas), "seed": args.seed,
        "gate_passed": result.returncode == 0,
        "scope": "Offline candidate; simulator search labels. Evaluation uses different seeds.",
    }, indent=2), encoding="utf8")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
