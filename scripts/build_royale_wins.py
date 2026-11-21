"""
WHO WON, and how: the 252k RoyaleAPI Path-of-Legends replays of IL_Replay (replays/ = the result, the crowns and both
full decks; actions/ = every card with its tile and second) joined game by game:

  answers   for every attacking card at a spot: every answer real players played (within 4 s), how often, and how
            often the player who answered that way WON the game -> the bot prefers answers that win, not just
            answers that are common
  decks     every deck (8 cards) with its games and wins -> the deck pick knows which decks win
  combos    every two-card attack (same lane, within 2.5 s) with its games and wins
  cards     each card: games and wins when it is in the deck

  python scripts/build_royale_wins.py [parts=52] --cache DIR      -> assets/royale/pro_wins.json
"""
import collections, io, json, os, sys, time
from multiprocessing import Pool

HF = "https://huggingface.co/datasets/VanguardX101/IL_Replay/resolve/main"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "royale", "pro_wins.json")


def key(s):
    s = str(s or "").lower()
    for suf in ("-ev1", "-ev2", "-hero"):
        if s.endswith(suf): s = s[: -len(suf)]
    return "".join(ch for ch in s if ch.isalnum())


def _load(kind, i, cache):
    import requests
    import pyarrow.parquet as pq
    name = f"part-{i:06d}.parquet"
    local = os.path.join(cache, f"{kind}_{name}") if cache else None
    if kind == "actions" and cache and os.path.exists(os.path.join(cache, name)): local = os.path.join(cache, name)
    if local and os.path.exists(local): return pq.read_table(local)
    data = requests.get(f"{HF}/{kind}/{name}", timeout=600).content
    if local:
        with open(local, "wb") as f: f.write(data)
    return pq.read_table(io.BytesIO(data))


def part(args):
    i, cache = args
    rp = _load("replays", i, cache)
    res, decks = {}, {}
    for tag, result, payload in zip(rp.column("replay_tag").to_pylist(), rp.column("result").to_pylist(),
                                    rp.column("payload_json").to_pylist()):
        if result not in ("victory", "defeat"): continue
        res[tag] = result == "victory"                      # did "team" win
        try:
            b = json.loads(payload)["battle"]
            decks[tag] = {s: sorted({key(c["card_key"]) for c in b[s]["players"][0]["deck"]}) for s in ("team", "opponent")}
        except Exception:
            pass
    ac = _load("actions", i, cache).select(["replay_tag", "kind", "side", "card_key", "time_seconds", "grid_x", "grid_y"])
    cols = {c: ac.column(c).to_pylist() for c in ac.column_names}
    by = collections.defaultdict(list)
    for j in range(ac.num_rows):
        if cols["kind"][j] != "play_card" or cols["grid_x"][j] is None: continue
        by[cols["replay_tag"][j]].append((cols["time_seconds"][j] or 0.0, cols["side"][j], key(cols["card_key"][j]),
                                          int(cols["grid_x"][j]), int(cols["grid_y"][j])))
    answers = collections.defaultdict(lambda: [0, 0])        # "threat|ybin|answer" -> [n, wins]
    combos = collections.defaultdict(lambda: [0, 0])
    deckw = collections.defaultdict(lambda: [0, 0])
    cardw = collections.defaultdict(lambda: [0, 0])
    for tag, ev in by.items():
        if tag not in res: continue
        ev.sort()
        team_won = res[tag]
        for side, won in (("team", team_won), ("opponent", not team_won)):
            d = (decks.get(tag) or {}).get(side)
            sd = "T" if side == "team" else "O"          # the replays' "team" is the stronger player (wins ~67%)
            if d and len(d) == 8:
                k = "|".join(d) + "#" + sd
                deckw[k][0] += 1; deckw[k][1] += won
                for c in d: cardw[c + "#" + sd][0] += 1; cardw[c + "#" + sd][1] += won
            flip = side == "opponent"
            seq = [(t, s == side, c, (17 - x) if flip else x, (31 - y) if flip else y) for t, s, c, x, y in ev]
            last_theirs, last_mine = None, None
            for t, mine, c, x, y in seq:
                if not mine:
                    last_theirs = (t, c, x, y)
                    continue
                if last_theirs and t - last_theirs[0] <= 4.0:
                    a = answers[f"{last_theirs[1]}|{min(31, max(0, last_theirs[3])) // 4}|{c}#{sd}"]
                    a[0] += 1; a[1] += won
                if last_mine and t - last_mine[0] <= 2.5 and (last_mine[2] < 9) == (x < 9) and last_mine[1] != c and y >= 10:
                    cb = combos[f"{last_mine[1]}+{c}#{sd}"]
                    cb[0] += 1; cb[1] += won
                last_mine = (t, c, x, y)
    return dict(answers), dict(combos), dict(deckw), dict(cardw), len(res)


def main(n_parts=52, cache=None):
    t0 = time.time()
    tot = [collections.defaultdict(lambda: [0, 0]) for _ in range(4)]
    games = 0
    with Pool(min(4, os.cpu_count() or 4)) as pool:
        for k, out in enumerate(pool.imap_unordered(part, [(i, cache) for i in range(n_parts)])):
            for acc, d in zip(tot, out[:4]):
                for kk, (n, w) in d.items():
                    acc[kk][0] += n; acc[kk][1] += w
            games += out[4]
            print(f"part {k + 1}/{n_parts}: {games:,} games {time.time() - t0:.0f}s", flush=True)
    # each side against its own average: a win rate is "how much better than that side usually does" + 50%
    base = {}
    for sd in ("T", "O"):
        n = sum(v[0] for k, v in tot[3].items() if k.endswith("#" + sd)) or 1
        base[sd] = sum(v[1] for k, v in tot[3].items() if k.endswith("#" + sd)) / n
    print("side baselines:", {k: round(v, 3) for k, v in base.items()})

    def merge(d):
        out = {}
        for k, (n, w) in d.items():
            kk, sd = k.rsplit("#", 1)
            o = out.setdefault(kk, [0, 0.0])
            o[0] += n
            o[1] += w - n * (base[sd] - 0.5)              # wins above that side's usual
        return {k: [n, max(0.0, min(1.0, w / n))] for k, (n, w) in out.items()}
    answers, combos, decks, cards = (merge(d) for d in tot)
    ans = {}
    for k, (n, w) in answers.items():
        if n < 20: continue
        th, yb, a = k.split("|")
        ans.setdefault(f"{th}|{yb}", {})[a] = [n, round(w, 4)]
    out = {"games": games, "source": "VanguardX101/IL_Replay (RoyaleAPI Path of Legends replays): results + placements",
           "answers": ans,
           "baselines": base,
           "combos": {k: [n, round(w, 4)] for k, (n, w) in combos.items() if n >= 30},
           "decks": sorted(({"cards": k.split("|"), "n": n, "w": round(w * n)} for k, (n, w) in decks.items() if n >= 15),
                           key=lambda d: -d["n"])[:3000],
           "cards": {k: [n, round(w, 4)] for k, (n, w) in cards.items() if n >= 50}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"done: {games:,} games -> {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB) in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    cache = sys.argv[sys.argv.index("--cache") + 1] if "--cache" in sys.argv else None
    if cache: a = [x for x in a if x != cache]
    main(int(a[0]) if a else 52, cache)
