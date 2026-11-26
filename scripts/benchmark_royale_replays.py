"""Audit deck replay coverage and compare the current decision policy offline."""
import argparse
import importlib.util
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from royale import deck_catalog, replay_benchmark

DATASET = "VanguardX101/IL_Replay"


def public_sample(count=1, start=0):
    import requests

    def rows(config, length, offset=0):
        response = requests.get("https://datasets-server.huggingface.co/rows",
                                params={"dataset": DATASET, "config": config, "split": "train",
                                        "offset": offset, "length": length}, timeout=15)
        response.raise_for_status()
        return [item["row"] for item in response.json()["rows"]]

    if start:
        earlier = [r for offset in range(0, start, 100) for r in rows("replays", min(100, start - offset), offset)]
        first_event = sum(r["event_count"] for r in earlier)
    else:
        first_event = 0
    replays = rows("replays", count, start)
    total = sum(r["event_count"] for r in replays)
    by_id = {r["replay_tag"]: [] for r in replays}
    for offset in range(0, total, 100):
        for row in rows("actions", min(100, total - offset), first_event + offset):
            if row["replay_tag"] in by_id:
                by_id[row["replay_tag"]].append(row)
    for replay in replays:
        tag = replay["replay_tag"]
        if len(by_id[tag]) != replay["event_count"]:
            raise ValueError(f"The source did not return the complete sample replay {tag}")
        yield {"replay_tag": tag, "battle": json.loads(replay["payload_json"])["battle"],
               "actions": by_id[tag]}


def run(replays, selected=None, implementations=None):
    out = []
    seen = set()
    for replay in replays:
        battle = replay.get("battle", {})
        ident = replay.get("replay_tag")
        if ident and ident in seen:
            continue
        if ident:
            seen.add(ident)
        for side in ("team", "opponent"):
            players = battle.get(side, {}).get("players", [])
            if selected and (len(players) != 1 or deck_catalog.signature(
                    c.get("card_key") for c in players[0].get("deck", [])) != selected):
                continue
            out.append({"replay_tag": ident, "side": side,
                        **replay_benchmark.evaluate(replay, side, implementations=implementations)})
    return out


def counterfactual_summary(results, labels):
    metrics = ("our_hp_saved", "extra_enemy_damage", "elixir_spent", "extra_ally_value")
    paired = [row["counterfactuals"] for result in results for row in result.get("decisions", [])
              if all((row.get("counterfactuals", {}).get(label) or {}).get("projection") is not None
                     for label in labels)]
    return {label: {"positions": len(paired),
                    **{f"mean_{key}": round(statistics.mean(row[label]["projection"][key] for row in paired), 2)
                       for key in metrics},
                    **({"median_decision_ms": round(statistics.median(row[label]["decision_ms"] for row in paired), 2)}
                       if label != "human_reference" else {})}
            for label in labels} if paired else {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", action="append", type=Path, default=[])
    parser.add_argument("--public-sample", action="store_true", help="check complete public replays")
    parser.add_argument("--public-count", type=int, default=1, choices=range(1, 21))
    parser.add_argument("--public-offset", type=int, default=0, choices=range(101), metavar="0-100")
    parser.add_argument("--compare-engine", action="store_true")
    parser.add_argument("--baseline-engine", type=Path, help="engine.py from the previously released version")
    parser.add_argument("--deck", help="optional exact catalogue ID")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    entry = deck_catalog.lookup(args.deck) if args.deck else None
    if args.deck and entry is None:
        parser.error("unknown deck catalogue ID")
    if not args.public_sample and not args.replay:
        parser.error("supply at least one replay source")
    implementations = {}
    if args.compare_engine or args.baseline_engine:
        from royale import engine, engine_ai
        implementations["current"] = engine
        if args.baseline_engine:
            spec = importlib.util.spec_from_file_location("baseline_royale_engine", args.baseline_engine)
            if spec is None or spec.loader is None:
                parser.error("baseline engine must be an importable Python file")
            baseline = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(baseline)
            implementations["baseline"] = baseline
        if not all(module.selftest() for module in implementations.values()):
            parser.error("native engine did not pass its self-test")
        # Compare native search under the same rule proposal without loading optional AI weights.
        engine_ai.propose = lambda env: None
    replays = [json.loads(path.read_text(encoding="utf-8")) for path in args.replay]
    if args.public_sample:
        replays.extend(public_sample(args.public_count, args.public_offset))
    selected = deck_catalog.signature(entry["cards"]) if entry else None
    results = run(replays, selected, implementations)
    totals = Counter()
    for result in results:
        totals.update(result.get("summary", {}))
    report = {
        "source": DATASET if args.public_sample else "local replay JSON",
        "replays_supplied": len(replays), "exact_deck": args.deck, "totals": dict(totals), "perspectives": results,
        "measurement": "Decision agreement at recorded play times, with an inferred hand and simulated board",
        "limitations": ["No vision or device input is used", "Special forms and activated abilities are not simulated",
                        "The four-card cycle and elixir are estimates; contradictory moments are excluded",
                        "The public sample comes from the published training split",
                        "Agreement does not establish win rate or causal impact"],
    }
    if implementations:
        report["counterfactual_summary"] = counterfactual_summary(results, (*implementations, "human_reference"))
        report["limitations"].append("Counterfactuals use the same simulated position and native binary. "
                                     "Scores are eight-second unopposed projections against waiting.")
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(replays)} replays supplied; {len(results)} qualifying perspectives; "
          f"{sum(r.get('summary', {}).get('compared', 0) for r in results)} decisions compared")


if __name__ == "__main__":
    main()
