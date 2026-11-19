"""
The learned brain: a neural network trained on 17 M card plays of 252k real games (scripts/build_royale_policy.py).
It sees what the bot sees (time, both elixirs, the opponent's last plays, ours, our hand) and says how a real player
would go on: play now or wait, which card of the hand, which tile. royale.brain asks it every decision and its own
rules check the answer (never a card that is kept for a threat, never two heavies, our half only, ...).
"""
import json, math, os, sys

_ROOT = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_S = {"sess": None, "meta": None, "tried": False, "path": None, "mtime": 0.0}


def key(name):
    return str(name or "").lower().replace("-", "").replace("_", "").replace(" ", "").replace(".", "")


def _path():
    """This account's self-trained brain (royale.selfplay) when there is one, else the shipped one."""
    try:
        import utils
        from royale import selfplay
        p = selfplay.model_path(utils.INSTANCE_ID)
        if p.exists(): return str(p)
    except Exception:
        pass
    return os.path.join(_ROOT, "assets", "royale", "policy.onnx")


def _load():
    p = _path()
    try: mt = os.path.getmtime(p)
    except OSError: mt = 0.0
    if _S["tried"] and _S["path"] == p and _S["mtime"] == mt: return _S["sess"] is not None
    _S["tried"], _S["path"], _S["mtime"] = True, p, mt
    try:
        import onnxruntime as ort
        d = os.path.join(_ROOT, "assets", "royale")
        with open(os.path.join(d, "policy.json"), encoding="utf-8") as f:
            _S["meta"] = json.load(f)
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        _S["sess"] = ort.InferenceSession(p, sess_options=so, providers=["CPUExecutionProvider"])
    except Exception:
        _S["sess"] = None
    return _S["sess"] is not None


def card_id(name):
    return ((_S["meta"] or {}).get("vocab") or {}).get(key(name), 1)


def self_trained():
    return bool(_S["path"]) and "royale_policy_" in str(_S["path"])


def ready():
    return _load()


def features(t, my_el, their_el, en, own, hand, m):
    """The same picture of the moment the network was trained on (build_royale_policy.features)."""
    vocab, H = m["vocab"], m["horizon"]
    f = [min(t, 300) / 300.0, 1.0 if t >= 120 else 0.0, 1.0 if t >= 180 else 0.0, my_el / 10.0, their_el / 10.0]
    ids = []
    for lst, n in ((en, m["n_en"]), (own, m["n_own"])):
        recent = [e for e in lst if 0 <= t - e[0] <= H][-n:][::-1]
        for k in range(n):
            if k < len(recent):
                et, c, x, y = recent[k]
                f += [1.0, x / 17.0, y / 31.0, (t - et) / H]
                ids.append(vocab.get(key(c), 1))
            else:
                f += [0.0, 0.0, 0.0, 0.0]
                ids.append(0)
    h = sorted(vocab.get(key(c), 1) for c in hand)[:m["n_hand"]]
    return f, ids + h + [0] * (m["n_hand"] - len(h))


def moment(t, my_el, their_el, en, own, hand):
    """(float features, card ids) of a moment, without asking the network (for moments to learn from)."""
    if not _load(): return None
    return features(t, my_el, their_el, en, own, hand, _S["meta"])


def _softmax(v):
    mx = max(v)
    e = [math.exp(x - mx) for x in v]
    s = sum(e)
    return [x / s for x in e]


def ask(t, my_el, their_el, en, own, hand, playable):
    """-> {"play": p, "cards": {name: p among the playable ones}} or None.
    en / own: [(seconds, card name, tile x, tile y)] newest last; hand: the 4 card names; playable: names."""
    if not _load(): return None
    import numpy as np
    m = _S["meta"]
    f, ids = features(t, my_el, their_el, en, own, hand, m)
    x = np.asarray([f], np.float32)
    i = np.asarray([ids + [0]], np.int64)
    play, card, _tile = _S["sess"].run(None, {"x": x, "ids": i})
    voc = m["vocab"]
    names = [n for n in playable if key(n) in voc]
    out = {"play": 1 / (1 + math.exp(-float(play[0]))), "cards": {}, "_x": x, "_ids": ids}
    if names:
        p = _softmax([float(card[0][voc[key(n)]]) for n in names])
        out["cards"] = dict(zip(names, p))
    return out


def tile(asked, name, anywhere=False):
    """Where real players would put `name` now -> ((x, y), p) or None."""
    if not asked or not _load(): return None
    import numpy as np
    m = _S["meta"]
    cid = m["vocab"].get(key(name))
    if not cid: return None
    i = np.asarray([asked["_ids"] + [cid]], np.int64)
    _p, _c, t = _S["sess"].run(None, {"x": asked["_x"], "ids": i})
    v = t[0].astype(float)
    if not anywhere: v[15 * 18:] = -1e9                     # our half only (rows 0..14)
    p = np.asarray(_softmax(list(v))).reshape(32, 18)
    # the spot with the most probability around it (3x3): real players spread a little around the same idea
    pad = np.pad(p, 1)
    near = sum(pad[dy:dy + 32, dx:dx + 18] for dy in range(3) for dx in range(3))
    yy, xx = np.unravel_index(int(np.argmax(near)), near.shape)
    return (int(xx), int(yy)), float(near[yy, xx])


def info():
    return (_S["meta"] or {}).get("test", {}) if _load() else {}
