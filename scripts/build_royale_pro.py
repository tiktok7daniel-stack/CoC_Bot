"""
The experience of 252,238 real Clash Royale games (17.8 M plays, VanguardX101/IL_Replay on HuggingFace, the replay
set FirstLight CR / RoyaleFish trained on) boiled down to what the bot can use from the screen:

  respond   the opponent played card C at a spot: what pros answered with, and where (within 4 s)
  place     where pros put each card when they start something themselves (nothing of theirs in the last 4 s)
  follow    what pros play right after a card of theirs on the same lane (combos: tank -> support)

Tiles are the 18 x 32 grid seen from the player's side (y 0 = own king), mirrored so the threat / play is always on
the LEFT lane (x < 9); the bot mirrors back. Only the most common answers are kept.
  python scripts/build_royale_pro.py [parts=52]    -> assets/royale/pro.json
"""
import collections, io, json, os, sys, time

import requests

REPO = "VanguardX101/IL_Replay"
HF = "https://huggingface.co"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "royale", "pro.json")


def key(card):
    return str(card or "").lower().replace("-", "").replace("_", "").replace(" ", "")


def mirror(x, y, left):
    return (x, y) if left else (17 - x, y)


def ybin(y):
    return min(31, max(0, y)) // 4                    # 8 rows of 4 tiles: where the threat is


def parts(n):
    tree = requests.get(f"{HF}/api/datasets/{REPO}/tree/main/actions", timeout=60).json()
    return sorted(x["path"] for x in tree if x["path"].endswith(".parquet"))[:n]


def main(n_parts=52, local=None):
    import pyarrow.parquet as pq
    respond = collections.defaultdict(collections.Counter)    # (threat, ybin) -> (card, x, y)
    place = collections.defaultdict(collections.Counter)      # card -> (x, y)
    follow = collections.defaultdict(collections.Counter)     # card -> next card
    games = plays = 0
    t0 = time.time()
    for i, part in enumerate(local or parts(n_parts)):
        if os.path.exists(part):
            src = part
        else:
            src = io.BytesIO(requests.get(f"{HF}/datasets/{REPO}/resolve/main/{part}", timeout=600).content)
        t = pq.read_table(src, columns=["replay_tag", "kind", "side", "card_key", "time_seconds",
                                                    "grid_x", "grid_y"])
        cols = {c: t.column(c).to_pylist() for c in t.column_names}
        by = collections.defaultdict(list)
        for j in range(t.num_rows):
            if cols["kind"][j] != "play_card": continue
            by[cols["replay_tag"][j]].append((cols["time_seconds"][j] or 0.0, cols["side"][j], key(cols["card_key"][j]),
                                              cols["grid_x"][j], cols["grid_y"][j]))
        for tag, ev in by.items():
            ev.sort()
            games += 1
            plays += len(ev)
            for side_me in ("team", "opponent"):
                # each player's own view: their king at y 0
                def own(e):
                    t_, s_, c_, x_, y_ = e
                    return (t_, s_ == side_me, c_, x_, y_ if side_me == "team" else 31 - y_)
                seq = [own(e) for e in ev]
                last_theirs = None
                last_mine = None
                for tt, mine, c, x, y in seq:
                    if x is None or y is None: continue
                    if not mine:
                        last_theirs = (tt, c, x, y)
                        continue
                    if last_theirs and tt - last_theirs[0] <= 4.0:
                        _t, tc, tx, ty = last_theirs
                        left = tx < 9
                        mx, my = mirror(x, y, left)
                        respond[f"{tc}|{ybin(ty)}"][f"{c}|{mx}|{my}"] += 1
                    elif not last_theirs or tt - last_theirs[0] > 4.0:
                        mx, my = mirror(x, y, x < 9)
                        place[c][f"{mx}|{my}"] += 1
                    if last_mine and tt - last_mine[0] <= 2.5 and (last_mine[2] < 9) == (x < 9) and last_mine[1] != c:
                        follow[last_mine[1]][c] += 1
                    last_mine = (tt, c, x, y)
        print(f"part {i + 1}: {games} games, {plays} plays, {time.time() - t0:.0f}s", flush=True)

    def top(counter, k, min_n=3):
        tot = sum(counter.values())
        return {"n": tot, "top": [[a, round(b / tot, 4)] for a, b in counter.most_common(k) if b >= min_n]}
    def answers(counter):
        """(card|x|y) counts -> the answering cards by share, and each card's usual tiles."""
        cards, tiles = collections.Counter(), collections.defaultdict(collections.Counter)
        for k, n in counter.items():
            c, x, y = k.split("|")
            cards[c] += n
            tiles[c][f"{x}|{y}"] += n
        tot = sum(cards.values())
        keep = [(c, n) for c, n in cards.most_common(16) if n >= 3]
        return {"n": tot, "cards": [[c, round(n / tot, 4)] for c, n in keep],
                "tiles": {c: top(tiles[c], 3)["top"] for c, _ in keep}}
    out = {"games": games, "plays": plays, "source": f"{HF}/datasets/{REPO}",
           "respond": {k: answers(v) for k, v in respond.items() if sum(v.values()) >= 30},
           "place": {k: top(v, 6) for k, v in place.items() if sum(v.values()) >= 30},
           "follow": {k: top(v, 6) for k, v in follow.items() if sum(v.values()) >= 30}}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"done: {games} games, {plays} plays -> {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB)")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0].endswith(".parquet"): main(local=a)
    else: main(int(a[0]) if a else 52)
