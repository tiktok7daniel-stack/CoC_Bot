"""
Adds the 2026 pro VOD plays (hastylmao/Hasty-CR data/vod/plays.jsonl, MIT: 13.5k plays of 22 top-player videos)
to the starting-tile statistics of assets/royale/pro.json ("place"), weighted x5 for being recent.
In that file "ours" plays at the top (y 16+): every play is turned round onto the player's own side.
  python scripts/build_royale_vod.py <plays.jsonl>
"""
import collections, json, os, sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "royale", "pro.json")
WEIGHT = 5


def key(s):
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def main(src):
    pro = json.load(open(OUT, encoding="utf-8"))
    vod = collections.defaultdict(collections.Counter)
    for line in open(src, encoding="utf-8"):
        r = json.loads(line)
        if r.get("tile_x") is None or r.get("tile_y") is None: continue
        x, y = int(r["tile_x"]), int(r["tile_y"])
        if r.get("side") == "ours": x, y = 17 - x, 31 - y           # their frame had "ours" on top
        if y > 14 and not str(r["card"]).startswith(("the-log", "fireball", "arrows", "zap", "rocket", "poison",
                                                     "lightning", "goblin-barrel", "graveyard", "miner")):
            continue                                                 # a troop is started on its own half
        mx = x if x < 9 else 17 - x
        vod[key(r["card"])][f"{mx}|{y}"] += 1
    n_cards = 0
    for c, cnt in vod.items():
        old = pro["place"].get(c) or {"n": 0, "top": []}
        merged = collections.Counter({t: s * old["n"] for t, s in old["top"]})
        for t, k in cnt.items(): merged[t] += WEIGHT * k
        tot = sum(merged.values())
        if tot <= 0: continue
        pro["place"][c] = {"n": old["n"] + WEIGHT * sum(cnt.values()),
                           "top": [[t, round(k / tot, 4)] for t, k in merged.most_common(6)]}
        n_cards += 1
    pro["vod"] = {"plays": sum(sum(c.values()) for c in vod.values()), "source": "hastylmao/Hasty-CR data/vod (MIT)"}
    json.dump(pro, open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"{pro['vod']['plays']} recent pro plays merged into the starting tiles of {n_cards} cards")


if __name__ == "__main__":
    main(sys.argv[1])
