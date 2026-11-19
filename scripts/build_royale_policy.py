"""
The Clash Royale bot's learned brain: a neural network trained on what real players did in 252k games
(VanguardX101/IL_Replay, 17 M card plays) — imitation learning, like the first stage of AlphaStar.

It sees what the bot can see from the screen, built from the play history the brain already tracks:
  time, both elixirs (the game's own timeline - what was spent), the opponent's last 6 plays (card, tile, age),
  our last 4 plays (card, tile, age)
and answers three things:
  play   play a card now, or wait?
  card   which card (the bot masks it to the playable cards in its hand)
  tile   where (given the card): 18 x 32 tiles, our king at y 0
The rules of royale.brain check every answer (a bad idea is never played). Exported to ONNX (runs in ~0.1 ms):
  assets/royale/policy.onnx + policy.json (card vocabulary, test accuracy)

  python scripts/build_royale_policy.py [parts=52] [epochs=3] [--cache DIR]
"""
import collections, io, json, math, os, random, sys, time

import numpy as np

REPO = "VanguardX101/IL_Replay"
HF = "https://huggingface.co"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "assets", "royale")
N_EN, N_OWN, N_HAND, HORIZON = 6, 4, 4, 15.0
N_TILE = 18 * 32


def key(card):
    return str(card or "").lower().replace("-", "").replace("_", "").replace(" ", "").replace(".", "")


def costs():
    with open(os.path.join(OUT, "cards.json"), encoding="utf-8") as f:
        d = json.load(f)
    return {key(n): float(c.get("cost") or 3) for n, c in d["cards"].items()}, d.get("elixir", {})


def regen_rate(t):
    """Elixir per second at second t (2.8 s per elixir, 1.4 s from 2:00, 0.93 s in overtime)."""
    return 1 / 2.8 if t < 120 else 1 / 1.4 if t < 180 else 1 / 0.93


def features(t, my_el, their_el, en, own, vocab, hand=()):
    """-> (float vector, int card ids) of one moment. en / own: [(t, card, x, y)] newest last; hand: our cards."""
    f = [min(t, 300) / 300.0, 1.0 if t >= 120 else 0.0, 1.0 if t >= 180 else 0.0, my_el / 10.0, their_el / 10.0]
    ids = []
    for lst, n in ((en, N_EN), (own, N_OWN)):
        recent = [e for e in lst if 0 <= t - e[0] <= HORIZON][-n:][::-1]
        for k in range(n):
            if k < len(recent):
                et, c, x, y = recent[k]
                f += [1.0, x / 17.0, y / 31.0, (t - et) / HORIZON]
                ids.append(vocab.get(c, 1))
            else:
                f += [0.0, 0.0, 0.0, 0.0]
                ids.append(0)
    h = sorted(vocab.get(c, 1) for c in hand)[:N_HAND]
    return f, ids + h + [0] * (N_HAND - len(h))


def parts(n):
    import requests
    tree = requests.get(f"{HF}/api/datasets/{REPO}/tree/main/actions", timeout=60).json()
    return sorted(x["path"] for x in tree if x["path"].endswith(".parquet"))[:n]


def load_part(part, cache):
    import pyarrow.parquet as pq
    local = os.path.join(cache, os.path.basename(part)) if cache else None
    if local and os.path.exists(local):
        src = local
    else:
        import requests
        data = requests.get(f"{HF}/datasets/{REPO}/resolve/main/{part}", timeout=600).content
        if local:
            with open(local, "wb") as fh: fh.write(data)
        src = io.BytesIO(data)
    t = pq.read_table(src, columns=["replay_tag", "kind", "side", "card_key", "time_seconds", "grid_x", "grid_y"])
    return {c: t.column(c).to_pylist() for c in t.column_names}, t.num_rows


def samples(cols, n, vocab, cost, rng):
    by = collections.defaultdict(list)
    for j in range(n):
        if cols["kind"][j] != "play_card" or cols["grid_x"][j] is None: continue
        by[cols["replay_tag"][j]].append((cols["time_seconds"][j] or 0.0, cols["side"][j], key(cols["card_key"][j]),
                                          int(cols["grid_x"][j]), int(cols["grid_y"][j])))
    X, I, P, C, T = [], [], [], [], []
    for ev in by.values():
        ev.sort()
        for me in ("team", "opponent"):
            flip = me == "opponent"
            seq = [(t, s == me, c, (17 - x) if flip else x, (31 - y) if flip else y) for t, s, c, x, y in ev]
            el = {True: 6.0, False: 6.0}                        # the game's start (cards.json timeline)
            last_t = 0.0
            en, own = [], []

            deck = {c for _t, m_, c, _x, _y in seq if m_}           # our deck = the cards we played this game

            def state(at):
                # the hand: the deck minus the 4 cards played last (they wait in the queue)
                wait = []
                for e in reversed(own):
                    if e[1] not in wait: wait.append(e[1])
                    if len(wait) == 4: break
                return features(at, el[True], el[False], en, own, vocab, sorted(deck - set(wait)))

            for t, mine, c, x, y in seq:
                # a moment of waiting between our plays: the right answer there was "wait"
                if mine and t - last_t > 1.5 and rng.random() < 0.6:
                    w = rng.uniform(last_t + 0.5, t - 0.5)
                    for side in (True, False):
                        el[side] = min(10.0, el[side] + (w - last_t) * regen_rate(w))
                    f, ids = state(w)
                    X.append(f); I.append(ids + [0]); P.append(0); C.append(0); T.append(0)
                    last_t = w
                for side in (True, False):
                    el[side] = min(10.0, el[side] + (t - last_t) * regen_rate(t))
                last_t = t
                if mine:
                    f, ids = state(t)
                    X.append(f); I.append(ids + [vocab.get(c, 1)]); P.append(1); C.append(vocab.get(c, 1))
                    T.append(min(31, max(0, y)) * 18 + min(17, max(0, x)))
                    own.append((t, c, x, y))
                else:
                    en.append((t, c, x, y))
                el[mine] = max(0.0, el[mine] - cost.get(c, 3.0))
    return X, I, P, C, T


def model(V, n_float):
    sys.path.insert(0, os.path.join(HERE, "..", "src"))
    from royale import policy_net
    return policy_net.build(V, n_float)


def main(n_parts=52, epochs=3, cache=None):
    import torch, torch.nn.functional as F
    torch.set_num_threads(os.cpu_count() or 4)
    rng = random.Random(7)
    cost, _ = costs()
    # the card vocabulary: every card of the game seen in the data (0 = none, 1 = unknown)
    vocab = {}
    Xs, Is, Ps, Cs, Ts = [], [], [], [], []
    t0 = time.time()
    plist = parts(n_parts)
    for i, part in enumerate(plist):
        cols, n = load_part(part, cache)
        for c in cols["card_key"]:
            k = key(c)
            if k not in vocab: vocab[k] = len(vocab) + 2
        X, I, P, C, T = samples(cols, n, vocab, cost, rng)
        Xs.append(np.asarray(X, np.float32)); Is.append(np.asarray(I, np.int16))
        Ps.append(np.asarray(P, np.float32)); Cs.append(np.asarray(C, np.int64)); Ts.append(np.asarray(T, np.int64))
        print(f"part {i + 1}/{len(plist)}: {sum(len(x) for x in Xs):,} moments, {time.time() - t0:.0f}s", flush=True)
    X = np.concatenate(Xs); I = np.concatenate(Is); P = np.concatenate(Ps); C = np.concatenate(Cs); T = np.concatenate(Ts)
    del Xs, Is, Ps, Cs, Ts
    V = len(vocab) + 2
    n = len(X)
    idx = np.random.default_rng(7).permutation(n)
    n_test = min(200_000, n // 20)
    test, train = idx[:n_test], idx[n_test:]
    m = model(V, X.shape[1])
    opt = torch.optim.AdamW(m.parameters(), lr=2e-3, weight_decay=1e-4)
    B = 4096
    steps = epochs * (len(train) // B)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-3, total_steps=steps)
    tx, tp, tc, tt = (torch.from_numpy(a) for a in (X, P, C, T))
    ti16 = torch.from_numpy(I)

    class _Ids:                                  # card ids are kept small (int16) and widened per batch
        def __getitem__(self, j): return ti16[j].long()
    ti = _Ids()
    step = 0
    for ep in range(epochs):
        m.train()
        perm = torch.from_numpy(np.random.default_rng(ep).permutation(train))
        for b in range(len(train) // B):
            j = perm[b * B:(b + 1) * B]
            pl, cl, tl = m(tx[j], ti[j])
            mask = tp[j] > 0
            loss = F.binary_cross_entropy_with_logits(pl, tp[j])
            if mask.any():
                hand = ti[j][mask][:, N_EN + N_OWN:N_EN + N_OWN + N_HAND]      # the card is chosen from the hand
                hm = torch.full_like(cl[mask], -30.0).scatter(1, hand, 0.0)
                hm[:, 0] = -30.0
                inhand = (hand == tc[j][mask][:, None]).any(1)
                hm = torch.where(inhand[:, None], hm, torch.zeros_like(hm))
                loss = loss + F.cross_entropy(cl[mask] + hm, tc[j][mask]) * 0.5 + F.cross_entropy(cl[mask], tc[j][mask]) * 0.5 + F.cross_entropy(tl[mask], tt[j][mask])
            opt.zero_grad(); loss.backward(); opt.step(); sched.step(); step += 1
            if step % 500 == 0:
                print(f"epoch {ep + 1} step {step}/{steps} loss {loss.item():.3f} {time.time() - t0:.0f}s", flush=True)
    # the test: moments it never saw
    m.eval()
    with torch.no_grad():
        acc = {"play": 0.0, "card_top1": 0.0, "card_top3": 0.0, "card_in_hand": 0.0, "tile_top1": 0.0, "tile_within1": 0.0}
        n_pos = n_all = 0
        for b in range(0, n_test, B):
            j = torch.from_numpy(test[b:b + B])
            pl, cl, tl = m(tx[j], ti[j])
            acc["play"] += ((pl > 0).float() == tp[j]).float().sum().item()
            n_all += len(j)
            mk = tp[j] > 0
            if mk.any():
                hand = ti[j][mk][:, N_EN + N_OWN:N_EN + N_OWN + N_HAND]
                hm = torch.full_like(cl[mk], -1e9).scatter(1, hand, 0.0); hm[:, 0] = -1e9
                acc["card_in_hand"] += ((cl[mk] + hm).argmax(1) == tc[j][mk]).float().sum().item()
                top3 = cl[mk].topk(3, 1).indices
                acc["card_top1"] += (top3[:, 0] == tc[j][mk]).float().sum().item()
                acc["card_top3"] += (top3 == tc[j][mk][:, None]).any(1).float().sum().item()
                pt = tl[mk].argmax(1)
                acc["tile_top1"] += (pt == tt[j][mk]).float().sum().item()
                dx = (pt % 18 - tt[j][mk] % 18).abs(); dy = (pt // 18 - tt[j][mk] // 18).abs()
                acc["tile_within1"] += ((dx <= 1) & (dy <= 1)).float().sum().item()
                n_pos += int(mk.sum())
        acc = {k: round(v / (n_all if k == "play" else max(1, n_pos)), 4) for k, v in acc.items()}
    print("test (unseen moments):", acc, flush=True)
    onnx_p = os.path.join(OUT, "policy.onnx")
    ex = (torch.zeros(1, X.shape[1]), torch.zeros(1, N_EN + N_OWN + N_HAND + 1, dtype=torch.int64))
    torch.onnx.export(m, ex, onnx_p, input_names=["x", "ids"], output_names=["play", "card", "tile"],
                      dynamic_axes={"x": {0: "b"}, "ids": {0: "b"}}, opset_version=17, dynamo=False)
    with open(os.path.join(OUT, "policy.json"), "w", encoding="utf-8") as f:
        json.dump({"vocab": vocab, "n_float": int(X.shape[1]), "n_en": N_EN, "n_own": N_OWN, "n_hand": N_HAND,
                   "horizon": HORIZON,
                   "moments": int(n), "test": acc, "source": f"{HF}/datasets/{REPO}", "made": time.strftime("%Y-%m-%d")},
                  f, separators=(",", ":"))
    print(f"done -> {onnx_p} ({os.path.getsize(onnx_p) / 1e6:.1f} MB) in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    cache = sys.argv[sys.argv.index("--cache") + 1] if "--cache" in sys.argv else None
    if cache: a = [x for x in a if x != cache]
    main(int(a[0]) if a else 52, int(a[1]) if len(a) > 1 else 3, cache)
