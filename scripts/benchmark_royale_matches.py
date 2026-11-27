"""Compare two Royale decision policies in side-swapped, seeded simulator matches."""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from royale import exit_train


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", default="search", help="search or a board-policy ONNX path")
    parser.add_argument("--baseline", default=str(ROOT / "assets/royale/board.onnx"),
                        help="search or a board-policy ONNX path")
    parser.add_argument("--min-win-rate", type=float)
    parser.add_argument("--max-decision-p95-ms", type=float)
    parser.add_argument("--matchups", type=int, default=4)
    parser.add_argument("--seeds", type=int, default=2)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.matchups < 1 or args.seeds < 1:
        parser.error("matchups and seeds must be positive")
    if args.min_win_rate is not None and not 0 <= args.min_win_rate <= 1:
        parser.error("min-win-rate must be between 0 and 1")
    if args.max_decision_p95_ms is not None and not 0 < args.max_decision_p95_ms < math.inf:
        parser.error("max-decision-p95-ms must be positive and finite")
    baseline = exit_train.Ctx(None if args.baseline == "search" else Path(args.baseline))
    opponent = "search" if args.baseline == "search" else baseline
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
    timings = {"candidate": [], "baseline": []}
    for index, (name, cards) in enumerate(decks[:args.matchups]):
        other = baseline.deck_ids(cards)
        for run in range(args.seeds):
            seed = index * args.seeds + run
            for side in (0, 1):
                pair = [my_deck, other] if side == 0 else [other, my_deck]
                for candidate_side in (0, 1):
                    pilots = [candidate, opponent] if candidate_side == 0 else [opponent, candidate]
                    trace = []
                    elapsed = [[], []]
                    _, winner, stats = exit_train.battle(
                        baseline, pair, pilots, record=False, explore=0, max_ticks=3600, seed=seed, trace=trace,
                        decision_ms=elapsed)
                    timings["candidate"].extend(elapsed[candidate_side])
                    timings["baseline"].extend(elapsed[1 - candidate_side])
                    outcome = "draw" if winner is None else "win" if winner == candidate_side else "loss"
                    matches.append({"opponent_deck": name, "seed": seed, "candidate_side": candidate_side,
                                    "candidate_uses_featured_deck": candidate_side == side,
                                    "outcome": outcome, **stats})
                    if outcome == "loss":
                        matches[-1]["play_trace"] = trace
    totals = {result: sum(m["outcome"] == result for m in matches) for result in ("win", "draw", "loss")}
    decision_latency = {}
    for name, values in timings.items():
        ordered = sorted(values)
        decision_latency[name] = {"samples": len(ordered), **{
            f"p{q}_ms": round(ordered[math.ceil(q / 100 * len(ordered)) - 1], 3) for q in (50, 95, 99)}}
    win_rate = totals["win"] / len(matches)
    gates = {}
    if args.min_win_rate is not None:
        gates["win_rate"] = win_rate >= args.min_win_rate
    if args.max_decision_p95_ms is not None:
        gates["decision_latency"] = len(matches) >= 20 and decision_latency["candidate"]["p95_ms"] <= args.max_decision_p95_ms
    report = {"candidate": Path(args.candidate).name, "baseline": Path(args.baseline).name, "native_deck": my_deck,
              "win_rate": win_rate, "offline_decision_latency": decision_latency,
              "latency_scope": "simulator observation construction and policy decision; excludes vision and dispatch",
              "thresholds": {"min_win_rate": args.min_win_rate, "max_decision_p95_ms": args.max_decision_p95_ms},
              "gates": gates,
              "featured_deck": featured, "totals": totals,
              "score": (totals["win"] + totals["draw"] / 2) / len(matches), "matches": matches}
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(totals, decision_latency, gates)
    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
