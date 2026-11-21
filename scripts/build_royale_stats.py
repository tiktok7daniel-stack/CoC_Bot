"""
Adds the game's own numbers the bot did not have to assets/royale/cards.json, from the game's data tables as
published by RoyaleAPI (cr-api-data, https://royaleapi.github.io/cr-api-data/, here the copy kept by
hastylmao/Hasty-CR, MIT):

  sight      how far a unit sees its targets (tiles)        -> who it goes for in royale.sim
  radius     its body size (tiles)                          -> body blocks (a Skeleton in front of a Hog)
  deploy_ms  the time it takes to land                      -> timing of defenses
  life_s     how long a building stands                     -> a Cannon placed early is worth less
  mass       how hard it is to push
and the game's level table (power_level_multiplier): the bot's numbers are level 1; level L is x levels[L].

  python scripts/build_royale_stats.py <folder with cards.json, cards_stats_*.json, rarities.json>
"""
import json, os, sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "royale", "cards.json")


def key(s):
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def main(src):
    J = lambda f: json.load(open(os.path.join(src, f), encoding="utf-8"))
    cards = J("cards.json")["cards"]
    troops = {t["name"]: t for t in J("cards_stats_troop.json")}
    chars = {c["name"]: c for c in J("cards_stats_characters.json")}
    blds = {b["name"]: b for b in J("cards_stats_building.json")}
    rar = {r["name"]: r for r in J("rarities.json")}
    by_key = {key(c["key"]): c for c in cards}
    db = json.load(open(OUT, encoding="utf-8"))
    n = 0
    for name, c in db["cards"].items():
        rc = by_key.get(key(name))
        if not rc: continue
        sc = rc.get("sc_key")
        st = None
        if sc in troops:
            st = chars.get(troops[sc].get("summon_character") or "")
        if st is None: st = blds.get(sc) or chars.get(sc)
        if not st: continue
        def ms(k): return st.get(k) or 0
        c["sight"] = round(ms("sight_range") / 1000.0, 2) or None
        c["radius"] = round(ms("collision_radius") / 1000.0, 2) or None
        c["deploy_ms"] = ms("deploy_time") or c.get("deploy_ms")
        c["mass"] = ms("mass") or None
        if ms("life_time"): c["life_s"] = round(ms("life_time") / 1000.0, 1)
        n += 1
    common = rar["Common"]["power_level_multiplier"]
    db["levels"] = {"multiplier": [1.0] + [round(m / 100.0, 3) for m in common],   # index = shown level - 1
                    "note": "stats in cards are level 1; shown level L -> x multiplier[L-1]",
                    "princess_tower_hp_l1": 1400, "king_tower_hp_l1": 2400}
    db["stats_source"] = "RoyaleAPI cr-api-data (game data tables), via hastylmao/Hasty-CR (MIT)"
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=0, ensure_ascii=False)
    print(f"{n} cards got sight / radius / deploy / life / mass; level table {len(db['levels']['multiplier'])} levels")


if __name__ == "__main__":
    main(sys.argv[1])
