"""
The board brain at play time: the arena the eyes see (every unit of both sides with its life, their spells in the
air, the towers, both elixirs, the time, our hand) -> the Transformer (royale.board_net) -> play / wait, which card,
which tile. royale.brain mixes it with the other learned brain (royale.policy) and checks it with its rules.
This account's self-trained version (royale.selfplay) is used when there is one.
"""
import json, math, os, sys

_ROOT = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_S = {"sess": None, "meta": None, "tried": False, "path": None, "mtime": 0.0}


def key(name):
    return str(name or "").lower().replace("-", "").replace("_", "").replace(" ", "").replace(".", "")


def _path():
    try:
        import utils
        from royale import selfplay
        p = selfplay.board_path(utils.INSTANCE_ID)
        if p.exists(): return str(p)
    except Exception:
        pass
    return os.path.join(_ROOT, "assets", "royale", "board.onnx")


def _load():
    p = _path()
    try: mt = os.path.getmtime(p)
    except OSError: mt = 0.0
    if _S["tried"] and _S["path"] == p and _S["mtime"] == mt: return _S["sess"] is not None
    _S["tried"], _S["path"], _S["mtime"] = True, p, mt
    try:
        import onnxruntime as ort
        with open(os.path.join(_ROOT, "assets", "royale", "board.json"), encoding="utf-8") as f:
            _S["meta"] = json.load(f)
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        _S["sess"] = ort.InferenceSession(p, sess_options=so, providers=["CPUExecutionProvider"])
    except Exception:
        _S["sess"] = None
    return _S["sess"] is not None


def ready():
    return _load()


def info():
    return (_S["meta"] or {}).get("test", {}) if _load() else {}


def inputs(brain, hand, elixir, allies, mirror=False, my_el=None, their_el=None, hand_override=None):
    """The moment as the network sees it. mirror=True: from the OPPONENT's side (to learn from their moves)."""
    from royale import board_net as B
    from royale.brain import card, unit_card
    vocab = _S["meta"]["vocab"]
    rows = []
    import time as _t
    now, t_el = _t.monotonic(), brain.elapsed()
    for u, x, y in getattr(brain, "_stable", []) or []:
        c = unit_card(u) or u
        cd = card(c)
        age = next((now - k["first"] for k in brain.known_enemy.values()
                    if k["unit"] == u and abs(k["x"] - x) <= 2 and abs(k["y"] - y) <= 2), 5.0)
        rows.append((False, c, x + 0.5, y + 0.5, brain.life(u, x, y), bool(cd.get("air")), cd.get("kind") == "building",
                     False, age))
    for a in allies or []:
        u, x, y = a[0], a[1], a[2]
        c = unit_card(u) or u
        cd = card(c)
        age = next((t_el - p["t"] for p in reversed(brain.plays) if p["card"] == c), 5.0)
        rows.append((True, c, x + 0.5, y + 0.5, 1.0, bool(cd.get("air")), cd.get("kind") == "building", False, age))
    for dx, dy, _r, _until, *rest in getattr(brain, "danger", []) or []:
        rows.append((False, rest[0] if rest else "fireball", dx + 0.5, dy + 0.5, 1.0, False, False, True, 0.0))
    if mirror:
        rows = [(not m, c, 17.0 - x, 31.0 - y, l, a, b, f, ag) for m, c, x, y, l, a, b, f, ag in rows]
    tok, ids = B.tokens(rows, vocab, key)
    hi = brain.tower_seen or {}
    tw_now = getattr(brain, "_towers_now", {}) or {}

    def frac(k):
        try: return max(0.0, min(1.0, float(tw_now.get(k)) / max(1e-6, hi.get(k, 1.0))))
        except (TypeError, ValueError): return 1.0
    ours = [frac("our_left"), frac("our_right"), 1.0]
    theirs = [frac("their_left"), frac("their_right"), 1.0]
    if mirror: ours, theirs = [theirs[1], theirs[0], 1.0], [ours[1], ours[0], 1.0]
    t = brain.elapsed()
    me_el = elixir if my_el is None else my_el
    ot_el = brain.enemy_elixir if their_el is None else their_el
    glob = [min(t, 300) / 300.0, 1.0 if t >= 120 else 0.0, 1.0 if t >= 180 else 0.0, me_el / 10.0, ot_el / 10.0] \
        + ours + theirs
    hd = sorted(vocab.get(key(c), 1) for c in (hand_override if hand_override is not None else hand) if c)[:4]
    hd += [0] * (4 - len(hd))
    return {"glob": glob, "tok": tok, "tokid": ids, "hand": hd}


def _run(inp, cand=0):
    import numpy as np
    s = _S["sess"]
    return s.run(None, {"glob": np.asarray([inp["glob"]], np.float32), "tok": np.asarray([inp["tok"]], np.float32),
                        "tokid": np.asarray([inp["tokid"]], np.int64), "hand": np.asarray([inp["hand"]], np.int64),
                        "cand": np.asarray([cand], np.int64)})


def ask(brain, hand, playable, elixir, allies):
    if not _load(): return None
    inp = inputs(brain, hand, elixir, allies)
    play, card_l, _t = _run(inp)
    voc = _S["meta"]["vocab"]
    names = [n for n in playable if key(n) in voc]
    out = {"play": 1 / (1 + math.exp(-float(play[0]))), "cards": {}, "_in": inp}
    if names:
        v = [float(card_l[0][voc[key(n)]]) for n in names]
        mx = max(v)
        e = [math.exp(x - mx) for x in v]
        out["cards"] = {n: x / sum(e) for n, x in zip(names, e)}
    return out


def tile(asked, name, anywhere=False):
    if not asked or not _load(): return None
    import numpy as np
    cid = _S["meta"]["vocab"].get(key(name))
    if not cid: return None
    _p, _c, t = _run(asked["_in"], cid)
    v = t[0].astype(float)
    if not anywhere: v[15 * 18:] = -1e9
    v = np.exp(v - v.max()); p = (v / v.sum()).reshape(32, 18)
    pad = np.pad(p, 1)
    near = sum(pad[dy:dy + 32, dx:dx + 18] for dy in range(3) for dx in range(3))
    yy, xx = np.unravel_index(int(np.argmax(near)), near.shape)
    return (int(xx), int(yy)), float(near[yy, xx])


def card_id(name):
    return ((_S["meta"] or {}).get("vocab") or {}).get(key(name), 1)
