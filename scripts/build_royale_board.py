"""
Trains the board brain (src/royale/board_net.py) on real games: every game of IL_Replay is replayed card by card in
royale.sim.Arena, so at every moment the whole arena is known (units of both sides, their life, spells in the air,
towers) — then a Transformer learns what the player did there (play / wait, card, tile), from both players' side.

  python scripts/build_royale_board.py [parts=12] [games_per_part=2500] [epochs=3] --cache DIR
-> assets/royale/board.onnx + board_weights.npz + board.json
"""
import collections, json, os, random, sys, time
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "..", "assets", "royale")


def _game_samples(args):
    ev, vocab, names, cost, seed = args[:5]
    team_won = args[5] if len(args) > 5 else None             # the replay's result: the winner's moves count more
    wt = lambda side: 1.0 if team_won is None else (1.4 if (team_won if side == "team" else not team_won) else 0.6)
    from royale.sim import Arena
    from royale import board_net as B
    from build_royale_policy import key, regen_rate
    rng = random.Random(seed)
    arena = Arena()
    out = []
    el = {"team": 6.0, "opponent": 6.0}
    last_t = 0.0
    played = {"team": [], "opponent": []}
    deck = {s: {c for _t, s2, c, _x, _y in ev if s2 == s} for s in ("team", "opponent")}

    def snap(at, side):
        me = "us" if side == "team" else "them"
        other = "opponent" if side == "team" else "team"
        board = arena.board(me)
        tok, ids = B.tokens([(m, names.get(c, c), x, y, l, a, b, f, ag) for m, c, x, y, l, a, b, f, ag in board],
                            vocab, key)
        tw = arena.towers(me)
        tw = (tw + [1.0] * 6)[:6]
        glob = [min(at, 300) / 300.0, 1.0 if at >= 120 else 0.0, 1.0 if at >= 180 else 0.0,
                el[side] / 10.0, el[other] / 10.0] + tw
        wait = []
        for c in reversed(played[side]):
            if c not in wait: wait.append(c)
            if len(wait) == 4: break
        hand = sorted(vocab.get(c, 1) for c in deck[side] - set(wait))[:4]
        hand += [0] * (4 - len(hand))
        return glob, tok, ids, hand

    def regen(to):
        for s in el: el[s] = min(10.0, el[s] + (to - last_t) * regen_rate(to))

    for t, side, c, x, y in ev:
        # a waiting moment of this player before its play
        if t - last_t > 1.5 and rng.random() < 0.5:
            w = rng.uniform(last_t + 0.5, t - 0.5)
            arena.run_to(w); regen(w); last_t = w
            g, tk, ids, hd = snap(w, side)
            out.append((g, tk, ids, hd, 0, 0, 0, wt(side)))
        arena.run_to(t); regen(t); last_t = t
        g, tk, ids, hd = snap(t, side)
        mx, my = (x, y) if side == "team" else (17 - x, 31 - y)
        out.append((g, tk, ids, hd, 1, vocab.get(c, 1), max(0, min(31, my)) * 18 + max(0, min(17, mx)), wt(side)))
        arena.play("us" if side == "team" else "them", names.get(c, c), x, y)
        played[side].append(c)
        el[side] = max(0.0, el[side] - cost.get(c, 3.0))
    if not out: return None
    g, tk, ids, hd, pl, c, ti, w = zip(*out)                  # compact arrays (millions of moments fit in memory)
    return (np.asarray(g, np.float16), np.asarray(tk, np.float16), np.asarray(ids, np.int16), np.asarray(hd, np.int16),
            np.asarray(w, np.float16),
            np.asarray(pl, np.int8), np.asarray(c, np.int16), np.asarray(ti, np.int16))


def main(n_parts=12, per_part=2500, epochs=3, cache=None):
    import torch, torch.nn.functional as F
    import build_royale_policy as P
    from royale import board_net as B
    from royale.brain import cards_db
    meta = json.load(open(os.path.join(OUT, "policy.json"), encoding="utf-8"))
    vocab = meta["vocab"]
    names = {P.key(n): n for n in cards_db()}                   # data key -> the bot's card name
    cost, _ = P.costs()
    t0 = time.time()
    G, T, I, H, Pl, C, Ti, Wl = [], [], [], [], [], [], [], []
    plist = P.parts(n_parts) if not cache else sorted(
        os.path.join("actions", f) for f in os.listdir(cache) if f.endswith(".parquet"))[:n_parts]
    with Pool(max(1, (os.cpu_count() or 4))) as pool:
        for i, part in enumerate(plist):
            cols, n = P.load_part(part, cache)
            by = collections.defaultdict(list)
            for j in range(n):
                if cols["kind"][j] != "play_card" or cols["grid_x"][j] is None: continue
                by[cols["replay_tag"][j]].append((cols["time_seconds"][j] or 0.0, cols["side"][j], P.key(cols["card_key"][j]),
                                                  int(cols["grid_x"][j]), int(cols["grid_y"][j])))
            res_part = P.results(part, cache) if cache else {}
            games = list(by.items())[:per_part]
            for _tg, ev in games: ev.sort()
            for res in pool.imap_unordered(_game_samples, [(ev, vocab, names, cost, k, res_part.get(tg))
                                                           for k, (tg, ev) in enumerate(games)], chunksize=16):
                if res is None: continue
                g_, t_, i_, h_, w_, *rest = res
                Wl.append(w_)
                for lst, arr in zip((G, T, I, H, Pl, C, Ti), (g_, t_, i_, h_, *rest)): lst.append(arr)
            print(f"part {i + 1}/{len(plist)}: {sum(len(x) for x in G):,} moments, {time.time() - t0:.0f}s", flush=True)
    G, T, I, H, Pl, C, Ti = (torch.from_numpy(np.concatenate(x)) for x in (G, T, I, H, Pl, C, Ti))
    Wt = torch.from_numpy(np.concatenate(Wl).astype(np.float32))

    class _W:                                         # stored small, widened per batch
        def __init__(self, a, f): self.a, self.f = a, f
        def __getitem__(self, j): return self.f(self.a[j])
        def __len__(self): return len(self.a)
    G, T = _W(G, lambda x: x.float()), _W(T, lambda x: x.float())
    I, H, C, Ti = (_W(x, lambda y: y.long()) for x in (I, H, C, Ti))
    Pl = _W(Pl, lambda x: x.float())
    V = len(vocab) + 2
    n = len(G)
    perm = torch.from_numpy(np.random.default_rng(7).permutation(n))
    n_test = min(100_000, n // 20)
    test, train = perm[:n_test], perm[n_test:]
    torch.set_num_threads(os.cpu_count() or 4)
    m = B.build(V)
    Bs = 1024
    steps = epochs * (len(train) // Bs)
    opt = torch.optim.AdamW(m.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=1e-3, total_steps=max(1, steps))
    step = 0
    for ep in range(epochs):
        m.train()
        pp = train[torch.randperm(len(train))]
        for b in range(len(train) // Bs):
            j = pp[b * Bs:(b + 1) * Bs]
            pl, cl, tl = m(G[j], T[j], I[j], H[j], C[j])
            mk = Pl[j] > 0
            wj = Wt[j]
            loss = (F.binary_cross_entropy_with_logits(pl, Pl[j], reduction="none") * wj).mean()
            if mk.any():
                hm = torch.full_like(cl[mk], -30.0).scatter(1, H[j][mk], 0.0); hm[:, 0] = -30.0
                inh = (H[j][mk] == C[j][mk][:, None]).any(1)
                hm = torch.where(inh[:, None], hm, torch.zeros_like(hm))
                wm = wj[mk]
                ce = lambda a, b: (F.cross_entropy(a, b, reduction="none") * wm).mean()
                loss = loss + 0.5 * ce(cl[mk] + hm, C[j][mk]) + 0.5 * ce(cl[mk], C[j][mk]) + ce(tl[mk], Ti[j][mk])
            opt.zero_grad(); loss.backward(); opt.step(); sched.step(); step += 1
            if step % 300 == 0:
                print(f"epoch {ep + 1} step {step}/{steps} loss {loss.item():.3f} {time.time() - t0:.0f}s", flush=True)
    m.eval()
    acc = {"play": 0.0, "card_in_hand": 0.0, "tile_top1": 0.0, "tile_within1": 0.0}
    npos = 0
    with torch.no_grad():
        for b in range(0, n_test, Bs):
            j = test[b:b + Bs]
            pl, cl, tl = m(G[j], T[j], I[j], H[j], C[j])
            acc["play"] += ((pl > 0).float() == Pl[j]).float().sum().item()
            mk = Pl[j] > 0
            if mk.any():
                hm = torch.full_like(cl[mk], -1e9).scatter(1, H[j][mk], 0.0); hm[:, 0] = -1e9
                acc["card_in_hand"] += ((cl[mk] + hm).argmax(1) == C[j][mk]).float().sum().item()
                pt = tl[mk].argmax(1)
                acc["tile_top1"] += (pt == Ti[j][mk]).float().sum().item()
                acc["tile_within1"] += (((pt % 18 - Ti[j][mk] % 18).abs() <= 1) &
                                        ((pt // 18 - Ti[j][mk] // 18).abs() <= 1)).float().sum().item()
                npos += int(mk.sum())
    acc = {k: round(v / (n_test if k == "play" else max(1, npos)), 4) for k, v in acc.items()}
    print("test (unseen moments):", acc, flush=True)
    B.export(m, os.path.join(OUT, "board.onnx"))
    B.save_weights(m, os.path.join(OUT, "board_weights.npz"))
    with open(os.path.join(OUT, "board.json"), "w", encoding="utf-8") as f:
        json.dump({"vocab": vocab, "moments": int(n), "test": acc, "made": time.strftime("%Y-%m-%d"),
                   "source": "IL_Replay games replayed in royale.sim.Arena"}, f, separators=(",", ":"))
    print(f"done in {time.time() - t0:.0f}s")





def anchor(part="actions/part-000050.parquet", cache=None, games=500, keep=30000):
    """Unseen pro moments with the whole arena (a game part not used in training): the self-training trains next to
    them and must still answer them like the pros -> assets/royale/board_anchor.npz"""
    import build_royale_policy as P
    from royale.brain import cards_db
    meta = json.load(open(os.path.join(OUT, "policy.json"), encoding="utf-8"))
    names = {P.key(n): n for n in cards_db()}
    cost, _ = P.costs()
    cols, n = P.load_part(part, cache)
    by = collections.defaultdict(list)
    for j in range(n):
        if cols["kind"][j] != "play_card" or cols["grid_x"][j] is None: continue
        by[cols["replay_tag"][j]].append((cols["time_seconds"][j] or 0.0, cols["side"][j], P.key(cols["card_key"][j]),
                                          int(cols["grid_x"][j]), int(cols["grid_y"][j])))
    res = []
    for k, ev in enumerate(list(by.values())[:games]):
        ev.sort()
        r = _game_samples((ev, meta["vocab"], names, cost, k))
        if r: res.append(r)
    g, t, i, h, _w, p, c, ti = (np.concatenate(x) for x in zip(*res))
    sel = np.random.default_rng(5).permutation(len(g))[:keep]
    np.savez_compressed(os.path.join(OUT, "board_anchor.npz"), glob=g[sel], tok=t[sel], tokid=i[sel], hand=h[sel],
                        play=p[sel], card=c[sel], tile=ti[sel])
    print("anchor:", len(sel), os.path.getsize(os.path.join(OUT, "board_anchor.npz")) / 1e6, "MB")


if __name__ == "__main__" and "--anchor" in sys.argv:
    anchor(cache=sys.argv[sys.argv.index("--cache") + 1] if "--cache" in sys.argv else None)
elif __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    cache = sys.argv[sys.argv.index("--cache") + 1] if "--cache" in sys.argv else None
    if cache: a = [x for x in a if x != cache]
    main(int(a[0]) if a else 12, int(a[1]) if len(a) > 1 else 2500, int(a[2]) if len(a) > 2 else 3, cache)
