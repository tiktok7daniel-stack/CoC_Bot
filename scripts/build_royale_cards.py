"""
Builds assets/royale/cards.json: what the Clash Royale brain knows about every card.
  python scripts/build_royale_cards.py <RoyaleFish data_16635 folder>

Joins two open sources by the game's card id:
  ClashRoyaleBuildABot (MIT)   the card names the vision uses, cost, its units (air / ground, what they target)
  RoyaleFish data_16635 (Apache-2.0) the numbers of game version 16.635: hitpoints, damage, hit speed, range,
                                splash radius, speed, how many units, buildings-only, attacks air / ground
"""
import gzip, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from royale.vision.namespaces.cards import Cards   # noqa: E402


def main(data_dir):
    specs = json.load(gzip.open(os.path.join(data_dir, "card_specs.json.gz")))["specs"]
    by_id = {}
    for s in specs:
        by_id.setdefault(s.get("card_id"), s)
    out = {}
    for field in Cards.__dataclass_fields__:
        c = getattr(Cards, field)
        if c.name in ("blank",) or c.id_ < 0: continue
        s = by_id.get(c.id_) or {}
        cat = s.get("categorical_features") or {}
        units = c.units or []
        air_unit = any(str(u.transport) == "air" for u in units)
        targets = sorted({str(u.target) for u in units if u.target})
        kind = s.get("kind") or ("spell" if c.target_anywhere and not units else
                                 "building" if any(str(u.category) == "building" for u in units) else "troop")
        bo = bool(cat.get("target_only_buildings")) or targets == ["buildings"]
        out[c.name] = {
            "id": c.id_, "cost": c.cost, "kind": kind, "anywhere": bool(c.target_anywhere),
            "air": air_unit,
            "hits_air": (not bo) and (bool(cat.get("attacks_air")) or "all" in targets or "air" in targets),
            "hits_ground": cat.get("attacks_ground") is not False and (kind == "spell" or "ground" in targets or
                                                                        "all" in targets or "buildings" in targets),
            "buildings_only": bo,
            "hp": s.get("hitpoints"), "damage": s.get("damage"), "hit_ms": s.get("hit_speed_ms"),
            "range": s.get("range_tiles"), "splash": s.get("radius_tiles"), "speed": s.get("move_speed"),
            "count": s.get("count") or (1 if units else 0), "deploy_ms": s.get("deploy_time_ms"),
            "units": [u.name for u in units], "rarity": cat.get("rarity"),
        }
    dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "royale", "cards.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"version": "16.635", "cards": out}, f, indent=0, ensure_ascii=False)
    print(f"{len(out)} cards -> {dst}; with numbers: {sum(1 for v in out.values() if v['hp'] or v['damage'])}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data_16635")
