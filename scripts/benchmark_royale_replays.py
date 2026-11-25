"""Audit deck replay coverage and compare the current decision policy offline."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from royale import deck_catalog, replay_benchmark

DATASET = "VanguardX101/IL_Replay"


def public_sample(count=1):
    import requests

    def rows(config, length, offset=0):
        response = requests.get("https://datasets-server.huggingface.co/rows",
                                params={"dataset": DATASET, "config": config, "split": "train",
                                        "offset": offset, "length": length}, timeout=15)
        response.raise_for_status()
        return [item["row"] for item in response.json()["rows"]]

    replays = rows("replays", count)
    total = sum(r["event_count"] for r in replays)
    by_id = {r["replay_tag"]: [] for r in replays}
    for offset in range(0, total, 100):
        for row in rows("actions", min(100, total - offset), offset):
            if row["replay_tag"] in by_id:
                by_id[row["replay_tag"]].append(row)
    for replay in replays:
        tag = replay["replay_tag"]
        if len(by_id[tag]) != replay["event_count"]:
            raise ValueError(f"The source did not return the complete sample replay {tag}")
        yield {"replay_tag": tag, "battle": json.loads(replay["payload_json"])["battle"],
               "actions": by_id[tag]}


def run(replays, selected=None):
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
            out.append({"replay_tag": ident, "side": side, **replay_benchmark.evaluate(replay, side)})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", action="append", type=Path, default=[])
    parser.add_argument("--public-sample", action="store_true", help="check complete public replays")
    parser.add_argument("--public-count", type=int, default=1, choices=range(1, 21))
    parser.add_argument("--deck", help="optional exact catalogue ID")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    entry = deck_catalog.lookup(args.deck) if args.deck else None
    if args.deck and entry is None:
        parser.error("unknown deck catalogue ID")
    if not args.public_sample and not args.replay:
        parser.error("supply at least one replay source")
    replays = [json.loads(path.read_text(encoding="utf-8")) for path in args.replay]
    if args.public_sample:
        replays.extend(public_sample(args.public_count))
    selected = deck_catalog.signature(entry["cards"]) if entry else None
    results = run(replays, selected)
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
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(replays)} replays supplied; {len(results)} qualifying perspectives; "
          f"{sum(r.get('summary', {}).get('compared', 0) for r in results)} decisions compared")


if __name__ == "__main__":
    main()
