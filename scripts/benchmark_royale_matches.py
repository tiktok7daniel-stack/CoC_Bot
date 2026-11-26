"""Compare two Royale decision policies in side-swapped, seeded simulator matches."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from royale import exit_train


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", default="search", help="search or a board-policy ONNX path")
    parser.add_argument("--baseline", type=Path, default=ROOT / "assets/royale/board.onnx")
    parser.add_argument("--matchups", type=int, default=4)
    parser.add_argument("--seeds", type=int, default=2)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.matchups < 1 or args.seeds < 1:
        parser.error("matchups and seeds must be positive")
    baseline = exit_train.Ctx(args.baseline)
    if not baseline.E.selftest():
        parser.error("native engine did not pass its self-test")
    candidate = "search" if args.candidate == "search" else exit_train.Ctx(Path(args.candidate))
    decks = [(name, names) for name, names in baseline.meta_decks() if len(names) == len(set(names)) == 8]
    featured = ["cannon-ev1", "ice-wizard-hero", "bats-ev1", "barbarian-barrel", "knight",
                "lightning", "minion-giant", "skeletons"]
    variants = [("cannon", 1), ("ice_wizard", 2), ("bats", 1), ("barbarian_barrel", 0),
                ("knight", 0), ("lightning", 0), ("minion_giant", 0), ("skeletons", 0)]
    my_deck = [baseline.ids.get(name, (None, None, None))[variant] for name, variant in variants]
    if len(decks) < args.matchups or None in my_deck or baseline.m.validate_deck_slots(my_deck):
        parser.error("not enough supported complete decks")
    matches = []
    for index, (name, cards) in enumerate(decks[:args.matchups]):
        other = baseline.deck_ids(cards)
        for run in range(args.seeds):
            seed = index * args.seeds + run
            for side in (0, 1):
                pair = [my_deck, other] if side == 0 else [other, my_deck]
                for candidate_side in (0, 1):
                    pilots = [candidate, baseline] if candidate_side == 0 else [baseline, candidate]
                    _, winner, stats = exit_train.battle(
                        baseline, pair, pilots, record=False, explore=0, max_ticks=3600, seed=seed)
                    outcome = "draw" if winner is None else "win" if winner == candidate_side else "loss"
                    matches.append({"opponent_deck": name, "seed": seed, "candidate_side": candidate_side,
                                    "candidate_uses_featured_deck": candidate_side == side,
                                    "outcome": outcome, **stats})
    totals = {result: sum(m["outcome"] == result for m in matches) for result in ("win", "draw", "loss")}
    report = {"candidate": args.candidate, "baseline": args.baseline.name, "native_deck": my_deck,
              "featured_deck": featured, "totals": totals,
              "score": (totals["win"] + totals["draw"] / 2) / len(matches), "matches": matches}
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(totals)


if __name__ == "__main__":
    main()
