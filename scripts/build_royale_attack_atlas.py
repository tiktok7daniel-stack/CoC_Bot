"""
The attack atlas: for every win condition / attacking card, every place it can start from (back, bridge, corner,
in front of the king...) is simulated against the defenses real players actually make against it (royale.pro
'respond': their answer cards, where and how often, from 252k replays) -> how much of their tower it takes on
average, weighted by how often each defense is used. The bot starts its attacks where they hurt most.

  python scripts/build_royale_attack_atlas.py [level=11]   -> assets/royale/attack_atlas.json
"""
import json, os, sys, time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
OUT = os.path.join(HERE, "..", "assets", "royale", "attack_atlas.json")
# where an attack can start (left lane; mirrored for the right): x, y in our frame
SPOTS = {"bridge": (3, 14), "bridge_edge": (0, 14), "behind_tower": (3, 4), "back_corner": (1, 1),
         "king_back": (8, 0), "lane_mid": (3, 10), "center_bridge": (6, 14)}


def job(args):
    attacker, level = args
    import copy
    from royale import sim, pro
    from royale.brain import card, THEIR_TOWERS, OUR_TOWERS
    c = card(attacker)
    # their answers to this card (from the replays), on its lane at their side
    rows = (pro.data().get("respond") or {})
    resp = []
    for yb in (3, 4):
        r = rows.get(f"{pro.key(attacker)}|{yb}")
        if r: resp += [(cname, share, (r.get("tiles") or {}).get(cname)) for cname, share in r.get("cards", [])]
    names = {pro.key(n): n for n in __import__("royale.brain", fromlist=["cards_db"]).cards_db()}
    defs, seen = [], set()
    for k, share, tiles in sorted(resp, key=lambda t: -t[1]):
        n = names.get(k)
        if not n or n in seen or not card(n) or card(n).get("kind") == "spell": continue
        seen.add(n)
        # the answer tile is in THEIR frame (their king at y 0): turned round onto ours
        if tiles:
            tx, ty = (int(v) for v in tiles[0][0].split("|"))
            defs.append((n, share, (17 - tx, 31 - ty)))
        if len(defs) == 12: break
    if not defs: return attacker, None
    tot = sum(s for _n, s, _t in defs)
    out = {}
    for spot, (sx, sy) in SPOTS.items():
        dmg = 0.0
        for dn, share, (dx, dy) in defs:
            u = [sim._tower("them", *THEIR_TOWERS["left"], "princess", level),
                 sim._tower("them", *THEIR_TOWERS["right"], "princess", level),
                 sim._tower("them", *THEIR_TOWERS["king"], "king", level),
                 sim._tower("us", *OUR_TOWERS["left"], "princess", level)]
            n = max(1, c.get("count") or 1)
            for k in range(n):
                u.append(sim.U(attacker, "us", sx + 0.5 + 0.5 * (k % 3 - 1), sy + 0.5 + 0.4 * (k // 3), c, 1.0,
                               (c.get("deploy_ms") or 1000) / 1000.0, c.get("cost", 3), level))
            d = card(dn)
            # they answer when it crosses the river (~ its walk to the bridge + 1 s)
            walk = max(0.0, (15 - sy) / max(0.5, (c.get("speed") or 60) / 60.0)) + 1.0
            for k in range(max(1, d.get("count") or 1)):
                u.append(sim.U(dn, "them", dx + 0.5 + 0.5 * (k % 3 - 1), dy + 0.5, d, 1.0,
                               (d.get("deploy_ms") or 1000) / 1000.0 + walk, d.get("cost", 3), level))
            t0 = u[0].hp
            t = 0.0
            while t < 40.0:                   # long enough for a Golem from the back
                sim.step(u, sim.DT); t += sim.DT
            dmg += share / tot * (t0 - max(0.0, u[0].hp))
        out[spot] = round(dmg)
    best = max(out, key=out.get)
    return attacker, {"spots": out, "best": best, "best_xy": SPOTS[best], "defenses": [d[0] for d in defs]}


def main(level=11):
    from royale.brain import cards_db
    from royale.deck_pick import WIN_CONDITIONS
    db = cards_db()
    atk = sorted(n for n, c in db.items() if c.get("kind") in ("troop", "hero") and c.get("hp") and
                 ("".join(ch for ch in n if ch.isalnum()) in WIN_CONDITIONS or (c.get("hp") or 0) >= 1000))
    t0 = time.time()
    res = {}
    with Pool(os.cpu_count() or 4) as pool:
        for a, v in pool.imap_unordered(job, [(a, level) for a in atk]):
            if v: res[a] = v
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"level": level, "spots": SPOTS, "atlas": res}, f, separators=(",", ":"))
    print(f"done: {len(res)} attacking cards x {len(SPOTS)} starts vs their real defenses in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 11)
