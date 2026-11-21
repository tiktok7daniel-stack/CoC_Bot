"""
The defense atlas: like a chess endgame tablebase, but for Clash Royale defense. Nobody copied, nothing guessed —
for every attacking card of the game, dropped where attackers drop it, EVERY defending card of the game is tried on
EVERY tile of our half and at several moments, in royale.sim (the cards' real numbers, levels, body blocks,
pulls). The best answers are kept:

  "hog_rider|bridge": {"none": <what doing nothing costs>,
                       "cannon": [[x, y, delay, score, tower hp lost], ...best 3 different spots],
                       "skeletons": [...], ...}

Millions of defenses, tried once on this PC, give the bot placements no player has tested (the RoyaleFish search
found Skeletons + Ice Golem stop a Hog with zero damage in 0.3% of 88,000 tries — this finds such spots for
every pair of cards). The threat is on the LEFT lane (the bot mirrors for the right one).

  python scripts/build_royale_atlas.py [level=11]   -> assets/royale/atlas.json
"""
import json, os, sys, time
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
OUT = os.path.join(HERE, "..", "assets", "royale", "atlas.json")
SPOTS = {"bridge": (3, 17), "corner": (0, 18), "back": (5, 23)}
DELAYS = (0.5, 1.5, 3.0)                  # seconds after the threat is dropped (the bot sees it ~0.5-1 s later)
HORIZON = {"bridge": 14.0, "corner": 15.0, "back": 20.0}


def horizon(threat, spot):
    """Long enough for the threat to reach our tower and hit it a few times (a Golem from the back needs ~30 s)."""
    from royale.brain import card
    spd = max(0.5, (card(threat).get("speed") or 60) / 60.0)
    walk = (SPOTS[spot][1] - 5.0) / spd                       # to our princess tower's row
    return max(HORIZON[spot], min(40.0, 1.0 + walk + 8.0))


def tiles():
    from royale.brain import Brain
    b = Brain([])
    return [(x, y) for x in range(0, 11) for y in range(1, 14) if b.legal(x, y, "knight")]


def board(threat, spot, level):
    from royale import sim
    from royale.brain import card, OUR_TOWERS
    c = card(threat)
    u = [sim._tower("us", *OUR_TOWERS["left"], "princess", level), sim._tower("us", *OUR_TOWERS["right"], "princess", level),
         sim._tower("us", *OUR_TOWERS["king"], "king", level)]
    n = max(1, c.get("count") or 1)
    sx, sy = SPOTS[spot]
    for k in range(n):
        u.append(sim.U(threat, "them", sx + 0.5 + 0.5 * (k % 3 - 1), sy + 0.5 + 0.5 * (k // 3), c, 1.0,
                       (c.get("deploy_ms") or 1000) / 1000.0, c.get("cost", 3), level))
    return u


def tower_lost(units):
    return sum(u.hp0 - max(0.0, u.hp) for u in units if u.tower and u.team == "us")


def job(args):
    threat, spot, defenders, level = args
    import copy
    from royale import sim
    from royale.brain import card
    base = board(threat, spot, level)
    H = horizon(threat, spot)
    none_u = sim.simulate(copy.deepcopy(base), H)
    out = {"none": round(sim.score(none_u, 0.0), 3), "none_lost": round(tower_lost(none_u))}
    tl = tiles()
    for de in defenders:
        d = card(de)
        m = max(1, d.get("count") or 1)
        res = []
        for (x, y) in tl:
            for delay in DELAYS:
                u = copy.deepcopy(base)
                for k in range(m):
                    u.append(sim.U(de, "us", x + 0.5 + 0.5 * (k % 3 - 1), y + 0.5 + 0.4 * (k // 3), d, 1.0,
                                   (d.get("deploy_ms") or 1000) / 1000.0 + delay, d.get("cost", 3), level))
                sim.simulate(u, H)
                res.append((round(sim.score(u, d.get("cost", 3)), 3), x, y, delay, round(tower_lost(u))))
        res.sort(reverse=True)
        keep = []
        for sc, x, y, delay, lost in res:                       # the best 3 clearly different spots
            if all(abs(x - k[0]) + abs(y - k[1]) >= 3 for k in keep):
                keep.append([x, y, delay, sc, lost])
            if len(keep) == 3: break
        out[de] = keep
    return f"{threat}|{spot}", out


def main(level=11):
    from royale.brain import cards_db
    db = cards_db()
    threats = sorted(n for n, c in db.items() if c.get("kind") in ("troop", "hero") and c.get("hp"))
    defenders = sorted(n for n, c in db.items() if c.get("kind") in ("troop", "hero", "building") and c.get("hp"))
    jobs = [(t, s, defenders, level) for t in threats for s in SPOTS]
    t0 = time.time()
    atlas = {}
    with Pool(os.cpu_count() or 4) as pool:
        for i, (k, v) in enumerate(pool.imap_unordered(job, jobs, chunksize=1)):
            atlas[k] = v
            if i % 20 == 0: print(f"{i + 1}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
    meta = {"level": level, "spots": SPOTS, "delays": DELAYS, "threats": len(threats), "defenders": len(defenders),
            "tries": len(jobs) * len(defenders) * len(tiles()) * len(DELAYS), "made": time.strftime("%Y-%m-%d")}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "atlas": atlas}, f, separators=(",", ":"))
    print(f"done: {meta['tries']:,} defenses tried in {time.time() - t0:.0f}s -> {OUT} "
          f"({os.path.getsize(OUT) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 11)
