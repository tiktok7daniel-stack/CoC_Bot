"""Produce local matchup evidence from official cache and optional replay JSON."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from royale import cr_api, deck_catalog, replay_evidence


def cached_battles(directory):
    for path in directory.glob("c__players__*_battlelog.json"):
        try:
            with path.open(encoding="utf-8") as stream:
                rows = json.load(stream)
        except (OSError, ValueError):
            continue
        if isinstance(rows, list):
            yield from (row for row in rows if isinstance(row, dict))


def analyze(deck, directory, replay_files):
    report = {"deck": deck, "official_cache": {"placements_available": False, "matchups": []}, "replays": []}
    report["official_cache"]["matchups"] = replay_evidence.official_matchups(cached_battles(directory), deck["cards"])
    signature = deck_catalog.signature(deck["cards"])
    for path in replay_files:
        replay = json.loads(path.read_text(encoding="utf-8"))
        battle, events = replay["battle"], replay["actions"]
        sides = [side for side in replay_evidence.SIDES
                 if len(battle.get(side, {}).get("players", [])) == 1
                 and deck_catalog.signature(card["card_key"] for card in battle[side]["players"][0]["deck"])
                 == signature]
        for side in sides:
            report["replays"].append({"id": replay.get("replay_tag"), "side": side,
                                      "crowns": {s: battle[s].get("crowns") for s in replay_evidence.SIDES},
                                      "decks": {s: [c["card_key"] for c in battle[s]["players"][0]["deck"]]
                                                for s in replay_evidence.SIDES},
                                      "plays": replay_evidence.validated_plays(events),
                                      "response_candidates": list(replay_evidence.responses(events, side))})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", default=deck_catalog.FEATURED_ID)
    parser.add_argument("--cache", type=Path, default=cr_api.CACHE)
    parser.add_argument("--replay", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    deck = deck_catalog.lookup(args.deck)
    if deck is None:
        parser.error("unknown deck ID")
    report = analyze(deck, args.cache, args.replay)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{sum(r['games'] for r in report['official_cache']['matchups'])} unique cached battles, "
          f"{len(report['replays'])} matching replay perspectives")


if __name__ == "__main__":
    main()
