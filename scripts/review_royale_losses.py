"""Summarize recorded match losses for offline review."""
import argparse
import json
from pathlib import Path


def loss_windows(match):
    side = match["candidate_side"]
    trace = match.get("play_trace") or []
    windows = []
    for before, after in zip(trace, trace[1:]):
        lost = [max(0, first - last) for first, last in
                zip(before["tower_hp"][side], after["tower_hp"][side])]
        if any(lost):
            windows.append({
                "ticks": [before["tick"], after["tick"]],
                "tower_hp_lost": lost,
                "previous_actions": before["plays"],
                "next_actions": after["plays"],
                "elixir_before": before["elixir"][side],
            })
    return sorted(windows, key=lambda row: -sum(row["tower_hp_lost"]))[:3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    losses = [{"opponent_deck": match["opponent_deck"], "seed": match["seed"],
               "candidate_side": match["candidate_side"], "damage_windows": loss_windows(match)}
              for match in report["matches"] if match["outcome"] == "loss"]
    args.out.write_text(json.dumps({
        "source": args.report.name, "losses": losses,
        "scope": "HP changes between recorded pre-action observations; actions do not establish causation",
    }, indent=2), encoding="utf-8")
    print(f"Summarized {len(losses)} losses")


if __name__ == "__main__":
    main()
