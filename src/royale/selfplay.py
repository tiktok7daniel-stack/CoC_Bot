"""
The learned brain teaches itself from its own battles (reinforcement learning, no orders from anyone).

  every battle   each moment the bot decided (play a card here / wait) is written down with what it saw, then the
                 battle is scored: towers it took / lost in the 10 s after each moment, and the win or the loss
  every 3        the networks are trained again on this PC (low priority, in the background):
  battles          moments that led to good things are made more likely, bad ones less (advantage-weighted
                   learning, the kind of RL that is safe on few games), mixed with 40k pro moments it never saw
                   so it cannot forget how real players play
  every card     judged on its own too: the elixir worth it killed minus its cost, a building that pulled nothing
                 is wasted (-1.5) — the lesson lands on the move that earned it
  checked        a new brain is kept only if it still plays like the pros on unseen moments (no collapse), and
                 every 30 battles the win rate is compared: a block that wins clearly less puts the best brains back
Files: ~/.CoC_Bot/learn/royale_selfplay_<account>/ (battles), ~/.CoC_Bot/models/royale_policy_<account>.onnx
"""
import json, math, os, sys, time
from pathlib import Path

HOME = Path.home() / ".CoC_Bot"
EVERY = 3                    # trained again every 3 battles (a few seconds in the background)
HORIZON = 10.0
_ROOT = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _safe(acc):
    return "".join(c for c in str(acc) if c.isalnum() or c in "-_") or "main"


def bdir(acc):
    return HOME / "learn" / f"royale_selfplay_{_safe(acc)}"


def model_path(acc):
    return HOME / "models" / f"royale_policy_{_safe(acc)}.onnx"


def board_path(acc):
    return HOME / "models" / f"royale_board_{_safe(acc)}.onnx"


def state_path(acc):
    return bdir(acc) / "state.json"


def read_state(acc):
    try:
        return json.loads(state_path(acc).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 0, "trained_at_battles": 0, "battles": 0, "per_version": {}}


def _write_state(acc, st):
    bdir(acc).mkdir(parents=True, exist_ok=True)
    state_path(acc).write_text(json.dumps(st), encoding="utf-8")


# ------------------------------------------------------------------ during / after a battle
def record(acc, steps, towers, won, opp_steps=()):
    """steps: [{"t", "x", "ids", "card", "tile"}] (card 0 = waited); towers: [(t, {name: hp})].
    -> the battle saved with a return for every moment."""
    if not steps or won is None: return
    hi = {}
    for _t, tw in towers:
        for k, v in (tw or {}).items():
            try: hi[k] = max(hi.get(k, 0.0), float(v))
            except (TypeError, ValueError): pass

    def hp(t):                                   # the last reading at or before t, as a fraction of the highest
        cur = {}
        for tt, tw in towers:
            if tt > t: break
            for k, v in (tw or {}).items():
                try: cur[k] = float(v) / max(1e-6, hi.get(k, 1.0))
                except (TypeError, ValueError): pass
        return cur
    final = 1.0 if won else -1.0
    rows = []
    # our moments, and the opponent's (seen from their side: what they took is what we lost, their win our loss)
    for lst, opp in ((steps, False), (opp_steps or (), True)):
        for s in lst:
            a, b = hp(s["t"]), hp(s["t"] + HORIZON)
            dealt = sum(max(0.0, a.get(k, 1) - b.get(k, a.get(k, 1))) for k in a if k.startswith("their"))
            lost = sum(max(0.0, a.get(k, 1) - b.get(k, a.get(k, 1))) for k in a if k.startswith("our"))
            r = (lost - dealt - 0.5 * final) if opp else (dealt - lost + 0.5 * final)
            r += 0.25 * float(s.get("v", 0.0))         # the card's own trade (royale.brain.score_moves)
            rows.append({**s, "r": round(r, 4), **({"o": 1} if opp else {})})
    d = bdir(acc)
    d.mkdir(parents=True, exist_ok=True)
    st = read_state(acc)
    (d / f"{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(json.dumps({"won": bool(won), "v": st["version"],
                                                                           "steps": rows}), encoding="utf-8")
    st["battles"] += 1
    _check_rollback(acc, st)
    st["blocks"][-1]["n"] += 1
    st["blocks"][-1]["w"] += int(bool(won))
    _write_state(acc, st)


BLOCK = 30


def _model_files(acc):
    out = []
    for p in (model_path(acc), board_path(acc)):
        out += [p, p.with_suffix(".npz")]
    return out


def _check_rollback(acc, st):
    """The brains change every few battles, so they are judged in blocks of 30 battles: at the start of each block
    the brains are saved; a block that wins clearly less (10+ points) than the best block so far puts the best
    block's brains back. It never gets worse for long."""
    import shutil
    blocks = st.setdefault("blocks", [])
    if not blocks or blocks[-1]["n"] >= BLOCK:
        if blocks:
            done = blocks[-1]
            best = max(blocks, key=lambda b: (b["w"] / max(1, b["n"]), -b["k"]))
            if done["w"] / done["n"] < best["w"] / best["n"] - 0.10 and best is not done:
                src = bdir(acc) / "blocks" / str(best["k"])
                for f in _model_files(acc):
                    b = src / f.name
                    if b.exists(): shutil.copy2(b, f)
                    elif f.exists(): f.unlink()
                st["rolled_back"] = st.get("rolled_back", 0) + 1
                st["note"] = (f"block {done['k']} won {done['w']}/{done['n']}, less than block {best['k']} "
                              f"({best['w']}/{best['n']}): its brains are back")
        k = (blocks[-1]["k"] + 1) if blocks else 0
        dst = bdir(acc) / "blocks" / str(k)
        dst.mkdir(parents=True, exist_ok=True)
        for f in _model_files(acc):
            if f.exists(): shutil.copy2(f, dst / f.name)
        blocks.append({"k": k, "w": 0, "n": 0})
        for old in blocks[:-6]:                                   # the newest 6 blocks are kept on disk
            shutil.rmtree(bdir(acc) / "blocks" / str(old["k"]), ignore_errors=True)
    st["blocks"] = blocks[-12:]


def due(acc):
    st = read_state(acc)
    return st["battles"] - st["trained_at_battles"] >= EVERY and st.get("stage") != "training"


def start(acc):
    """Its own low-priority process (the bot keeps playing)."""
    import subprocess
    kw = {}
    if sys.platform == "win32": kw["creationflags"] = 0x08000000 | 0x00004000
    py = sys.executable
    if py.lower().endswith("pythonw.exe"): py = py[:-len("pythonw.exe")] + "python.exe"
    here = Path(__file__).resolve().parent.parent
    st = read_state(acc); st["stage"] = "training"; st["t"] = time.time(); _write_state(acc, st)
    subprocess.Popen([py, "-m", "royale.selfplay", "--run", acc], cwd=str(here), **kw)


# ------------------------------------------------------------------ the training (its own process)
def run(acc, epochs=2):
    import numpy as np, torch, torch.nn.functional as F
    from royale import policy_net as N
    torch.set_num_threads(max(1, (os.cpu_count() or 4) // 2))
    a = Path(_ROOT) / "assets" / "royale"
    meta = json.loads((a / "policy.json").read_text(encoding="utf-8"))
    V, nf = len(meta["vocab"]) + 2, meta["n_float"]
    mine = model_path(acc).with_suffix(".npz")
    m = N.load(mine if mine.exists() and model_path(acc).exists() else a / "policy_weights.npz", V, nf)
    anc = np.load(a / "policy_anchor.npz")
    ax, ai = torch.from_numpy(anc["x"]), torch.from_numpy(anc["ids"].astype(np.int64))
    ap, ac, at = torch.from_numpy(anc["play"].astype(np.float32)), torch.from_numpy(anc["card"].astype(np.int64)), \
        torch.from_numpy(anc["tile"].astype(np.int64))

    def anchor_acc(model):
        model.eval()
        with torch.no_grad():
            pl, cl, _ = model(ax, ai)
            mk = ap > 0
            hand = ai[mk][:, 10:14]
            hm = torch.full_like(cl[mk], -1e9).scatter(1, hand, 0.0); hm[:, 0] = -1e9
            return float(((cl[mk] + hm).argmax(1) == ac[mk]).float().mean())
    base = anchor_acc(m)
    # the bot's own moments, newest 200 battles
    rows = []
    for f in sorted(bdir(acc).glob("2*.json"))[-60:]:              # the newest 60 battles
        try: rows += json.loads(f.read_text(encoding="utf-8"))["steps"]
        except (OSError, ValueError, KeyError): pass
    rows = [r for r in rows if len(r.get("x", [])) == nf and len(r.get("ids", [])) == 14]
    if len(rows) < 200:
        st = read_state(acc); st["stage"] = "waiting"; st["note"] = f"{len(rows)} moments so far"; _write_state(acc, st)
        return False
    R = np.asarray([r["r"] for r in rows], np.float32)
    adv = (R - R.mean()) / (R.std() + 1e-6)
    w = np.clip(np.exp(adv / 1.0), 0.2, 3.0).astype(np.float32)       # advantage weights (AWR)
    X = torch.tensor([r["x"] for r in rows], dtype=torch.float32)
    card = torch.tensor([int(r["card"]) for r in rows])
    I = torch.tensor([r["ids"] + [int(r["card"])] for r in rows], dtype=torch.int64)
    P = (card > 0).float()
    T = torch.tensor([int(r["tile"]) for r in rows])
    W = torch.from_numpy(w)
    opt = torch.optim.AdamW(m.parameters(), lr=1e-4, weight_decay=1e-4)
    m.train()
    B = 256
    for ep in range(epochs):
        perm = torch.randperm(len(rows))
        for b in range(0, len(rows), B):
            j = perm[b:b + B]
            pl, cl, tl = m(X[j], I[j])
            loss = (F.binary_cross_entropy_with_logits(pl, P[j], reduction="none") * W[j]).mean()
            mk = P[j] > 0
            if mk.any():
                loss = loss + (F.cross_entropy(cl[mk], card[j][mk], reduction="none") * W[j][mk]).mean() \
                    + (F.cross_entropy(tl[mk], T[j][mk], reduction="none") * W[j][mk]).mean()
            # the pros' moments next to it: it may learn its own style, never forget theirs
            k = torch.randint(0, len(ax), (B,))
            apl, acl, atl = m(ax[k], ai[k])
            am = ap[k] > 0
            loss = loss + F.binary_cross_entropy_with_logits(apl, ap[k]) + \
                F.cross_entropy(acl[am], ac[k][am]) + F.cross_entropy(atl[am], at[k][am])
            opt.zero_grad(); loss.backward(); opt.step()
    new = anchor_acc(m)
    st = read_state(acc)
    st["trained_at_battles"] = st["battles"]
    st["stage"] = "done"
    st["anchor"] = {"before": round(base, 4), "after": round(new, 4)}
    if new >= base - 0.03:                                             # still plays like the pros
        p = model_path(acc)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            os.replace(p, p.with_name(p.stem + "_prev.onnx"))
            if p.with_suffix(".npz").exists(): os.replace(p.with_suffix(".npz"), p.with_name(p.stem + "_prev.npz"))
        tmp = p.with_name(p.stem + ".tmp.onnx")
        N.export(m, tmp, nf)
        N.save_weights(m, p.with_suffix(".npz"))
        os.replace(tmp, p)
        st["version"] += 1
        st["note"] = f"v{st['version']}: learned from {len(rows)} of its own moments"
    else:
        st["note"] = f"not kept (pro check {base:.2f} -> {new:.2f})"
    try:                                                               # the board brain learns the same way
        bn = run_board(acc, rows, w, epochs)
        if bn: st["note"] = st.get("note", "") + f" | board brain: {bn}"
    except Exception as e:
        st["note"] = st.get("note", "") + f" | board brain skipped ({type(e).__name__})"
    st["finished"] = time.time()
    _write_state(acc, st)
    return True


def run_board(acc, rows, w, epochs=4):
    """The Transformer (royale.board_net) trained on its own / its opponents' moments that carry the whole arena,
    advantage-weighted, next to unseen pro moments (assets/royale/board_anchor.npz) so it never forgets them."""
    import numpy as np, torch, torch.nn.functional as F
    from royale import board_net as B
    a = Path(_ROOT) / "assets" / "royale"
    if not (a / "board_weights.npz").exists(): return None
    meta = json.loads((a / "board.json").read_text(encoding="utf-8"))
    V = len(meta["vocab"]) + 2
    keep = [k for k, r in enumerate(rows) if isinstance(r.get("b"), dict)]
    if len(keep) < 200: return f"{len(keep)} arena moments so far"
    mine = board_path(acc).with_suffix(".npz")
    m = B.load(mine if mine.exists() and board_path(acc).exists() else a / "board_weights.npz", V)
    R = [rows[k] for k in keep]
    G = torch.tensor([r["b"]["glob"] for r in R], dtype=torch.float32)
    T = torch.tensor([r["b"]["tok"] for r in R], dtype=torch.float32)
    I = torch.tensor([r["b"]["tokid"] for r in R], dtype=torch.int64)
    H = torch.tensor([r["b"]["hand"] for r in R], dtype=torch.int64)
    C = torch.tensor([int(r["card"]) for r in R]); P = (C > 0).float()
    Ti = torch.tensor([int(r["tile"]) for r in R]); W = torch.from_numpy(np.asarray([w[k] for k in keep], np.float32))
    anc = np.load(a / "board_anchor.npz") if (a / "board_anchor.npz").exists() else None

    def anchor_acc(model):
        if anc is None: return 0.0
        model.eval()
        with torch.no_grad():
            ag, at, ai, ah = (torch.from_numpy(anc[k].astype(np.float32 if k in ("glob", "tok") else np.int64))
                              for k in ("glob", "tok", "tokid", "hand"))
            ac, ap = torch.from_numpy(anc["card"].astype(np.int64)), torch.from_numpy(anc["play"].astype(np.float32))
            _p, cl, _t = model(ag, at, ai, ah, ac)
            mk = ap > 0
            hm = torch.full_like(cl[mk], -1e9).scatter(1, ah[mk], 0.0); hm[:, 0] = -1e9
            return float(((cl[mk] + hm).argmax(1) == ac[mk]).float().mean())
    base = anchor_acc(m)
    opt = torch.optim.AdamW(m.parameters(), lr=1e-4, weight_decay=1e-4)
    m.train()
    Bs = 128
    for _ in range(epochs):
        perm = torch.randperm(len(R))
        for b in range(0, len(R), Bs):
            j = perm[b:b + Bs]
            pl, cl, tl = m(G[j], T[j], I[j], H[j], C[j])
            loss = (F.binary_cross_entropy_with_logits(pl, P[j], reduction="none") * W[j]).mean()
            mk = P[j] > 0
            if mk.any():
                loss = loss + (F.cross_entropy(cl[mk], C[j][mk], reduction="none") * W[j][mk]).mean() \
                    + (F.cross_entropy(tl[mk], Ti[j][mk], reduction="none") * W[j][mk]).mean()
            if anc is not None:
                k = torch.from_numpy(np.random.randint(0, len(anc["card"]), Bs))
                ag = torch.from_numpy(anc["glob"][k.numpy()].astype(np.float32))
                at = torch.from_numpy(anc["tok"][k.numpy()].astype(np.float32))
                ai = torch.from_numpy(anc["tokid"][k.numpy()].astype(np.int64))
                ah = torch.from_numpy(anc["hand"][k.numpy()].astype(np.int64))
                ac = torch.from_numpy(anc["card"][k.numpy()].astype(np.int64))
                ap = torch.from_numpy(anc["play"][k.numpy()].astype(np.float32))
                at_ = torch.from_numpy(anc["tile"][k.numpy()].astype(np.int64))
                apl, acl, atl = m(ag, at, ai, ah, ac)
                am = ap > 0
                loss = loss + F.binary_cross_entropy_with_logits(apl, ap) + F.cross_entropy(acl[am], ac[am]) \
                    + F.cross_entropy(atl[am], at_[am])
            opt.zero_grad(); loss.backward(); opt.step()
    new = anchor_acc(m)
    if anc is not None and new < base - 0.03: return f"not kept ({base:.2f} -> {new:.2f})"
    p = board_path(acc)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.stem + ".tmp.onnx")
    B.export(m, tmp)
    B.save_weights(m, p.with_suffix(".npz"))
    os.replace(tmp, p)
    return f"learned from {len(R)} arena moments (pro check {base:.2f} -> {new:.2f})"


if __name__ == "__main__":
    if "--run" in sys.argv:
        acc = sys.argv[sys.argv.index("--run") + 1]
        try:
            run(acc)
        except Exception as e:
            st = read_state(acc); st["stage"] = "error"; st["note"] = f"{type(e).__name__}: {e}"[:200]
            _write_state(acc, st)
