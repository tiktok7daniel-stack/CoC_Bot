"""
The bot's own AI, trained by playing against itself in the battle engine (royale.engine), on this PC.

  training   third_party/clash_royale_env/python_ai (itzik123/ClashRoyaleAi, MIT): a recurrent PPO network (CNN + LSTM,
             ~1.9M parameters) that picks the card and then one of 612 cells, trained on YOUR deck first against a
             search-based teacher that pilots 16 real ladder decks (difficulty = how far ahead the teacher looks),
             then in a self-play league against its own past versions. Runs in the background at low priority;
             it saves and resumes, so it can be stopped and started any time.
  playing    every moment of a battle the engine mirror of the arena is shown to the trained network, and its move
             joins the candidates royale.engine thinks through — so the network proposes and the engine checks it
             against waiting and against every other candidate before anything is played.

Files: ~/.CoC_Bot/royale_ai/ (weights, training log). Needs torch, gymnasium and tensorboard (installed on demand).
"""
import os, subprocess, sys, time
from pathlib import Path

HOME = Path.home() / ".CoC_Bot" / "royale_ai"
PKG = Path(__file__).resolve().parents[2] / "third_party" / "clash_royale_env"
NEEDS = (("torch", "torch"), ("gymnasium", "gymnasium"), ("tensorboard", "tensorboard"), ("numpy", "numpy"))
_S = {"net": None, "net_mtime": 0.0, "hid": None, "why": "", "loading": False, "paused": []}


TRUSTED = "trusted.pth"
GATE_GAMES = 20                # a new version plays this many games (both sides) against the trusted one
GATE_WIN = 0.55                # and replaces it only with this share of the points


def newest():
    """The newest weights training wrote (phase 1 or the self-play league), or None."""
    if not HOME.exists(): return None
    pth = sorted(HOME.glob("model_weights*.pth"), key=lambda p: p.stat().st_mtime)
    return pth[-1] if pth else None


def weights():
    """The weights the bot PLAYS with: the trusted version (the first one, then only versions that beat it)."""
    t = HOME / TRUSTED
    return t if t.exists() else None


def _load(path):
    import torch
    if str(PKG) not in sys.path: sys.path.insert(0, str(PKG))
    from royale import engine
    if engine._dir() and engine._dir() not in sys.path: sys.path.insert(0, engine._dir())
    from python_ai.models.policy_io import load_net
    net = load_net(str(path), torch.device("cpu"))
    for prm in net.parameters(): prm.requires_grad_(False)
    net.eval()
    return net


def _duel(m, deck, net0, net1, steps=400):
    """One game in the engine, net0 bottom vs net1 top, same deck. -> net0's score (1 / 0.5 / 0)."""
    import numpy as np, torch
    from python_ai.engine_constants import BOARD_W
    env = m.ClashRoyaleEnv(deck, deck, 3600)
    env.reset()
    hid = [(torch.zeros(1, net0.LSTM_HIDDEN), torch.zeros(1, net0.LSTM_HIDDEN)),
           (torch.zeros(1, net1.LSTM_HIDDEN), torch.zeros(1, net1.LSTM_HIDDEN))]
    acts = [None, None]
    with torch.no_grad():
        for _ in range(steps):
            for team, net in ((0, net0), (1, net1)):
                obs = torch.tensor(np.asarray(env.get_observation_for_team(team), dtype=np.float32)).unsqueeze(0)
                feats, emb, sp = net.extract_features(obs)
                lg, _, _, _, h = net.step_lstm_and_card(feats, hid[team], net.affordability_mask(obs))
                gi = int(lg.argmax(-1).item())
                cell = int(net.placement_given_card(h[0], emb, torch.tensor([gi]), obs, sp).argmax(-1).item())
                hid[team] = h
                acts[team] = (gi, float(cell % BOARD_W), float(cell // BOARD_W))
            r = env.step_self_play(acts[0][0], acts[0][1], acts[0][2], acts[1][0], acts[1][1], acts[1][2], 10)
            if r.done: break
    a, b = env.get_towers_alive(0), env.get_towers_alive(1)
    if a != b: return 1.0 if a > b else 0.0
    loser = env.resolve_timeout_outcome()
    return 0.5 if loser < 0 else (1.0 if loser == 1 else 0.0)


def gate(deck_names, log=None):
    """A newer version than the trusted one is played against it (GATE_GAMES, both sides); it becomes the trusted
    version only when it scores GATE_WIN or better. The first version ever trained is trusted as it is.
    -> a short report, or None when there is nothing new."""
    import shutil
    from royale import engine
    new = newest()
    if new is None: return None
    t = HOME / TRUSTED
    if t.exists() and new.stat().st_mtime <= t.stat().st_mtime: return None
    if not t.exists():
        shutil.copy2(new, t)
        return f"first trained AI version is now in use ({new.name})"
    spec = deck_spec(deck_names or [])
    m = engine.module()
    if not spec or m is None: return None
    deck = [int(x) for x in spec.split(",")]
    try:
        a, b = _load(new), _load(t)
        pts = 0.0
        for g in range(GATE_GAMES):
            pts += _duel(m, deck, a, b) if g % 2 == 0 else 1.0 - _duel(m, deck, b, a)
        share = pts / GATE_GAMES
    except Exception as e:
        return f"could not test the new version: {e}"
    if share >= GATE_WIN:
        shutil.copy2(new, t)
        msg = f"the new AI version beat the old one {share:.0%} over {GATE_GAMES} games — now in use"
    else:
        os.utime(t, None)          # this version was judged: wait for a newer one
        msg = f"the new AI version scored {share:.0%} against the one in use — kept the old one"
    if log: log.info("Clash Royale AI: " + msg)
    return msg


def missing():
    import importlib.util
    return [pip for mod, pip in NEEDS if importlib.util.find_spec(mod) is None]


def _pid_file():
    return HOME / "train.pid"


def running():
    try:
        pid = int(_pid_file().read_text())
    except (OSError, ValueError):
        return False
    try:
        import psutil
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False


def deck_spec(names):
    """Our card names -> the engine's ids, for CLASH_DECK (a Hero the engine lacks plays as its plain card)."""
    from royale import engine
    ids = engine.card_ids()
    out = [str(ids[n][0]) for n in names if n in ids]
    return ",".join(out) if len(out) == 8 else None


def start(deck_names, log=None):
    """Start (or resume) training in the background. -> (True, message) / (False, why)."""
    from royale import engine
    if running(): return True, "already training"
    if engine.module() is None: return False, "the battle engine is not built for this Python yet"
    need = missing()
    if need:
        try:
            import deps
            for mod, pip in NEEDS:
                if pip in need: deps.ensure(mod, [pip])
        except Exception:
            pass
        return False, "installing " + ", ".join(need) + " — press again in a few minutes"
    spec = deck_spec(deck_names or [])
    if not spec: return False, "the deck is not known yet (play one battle first)"
    HOME.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(PKG), engine._dir() or "", env.get("PYTHONPATH", "")])
    env["CLASH_DECK"] = spec
    env["CLASH_WEIGHTS"] = str(HOME / "model_weights.pth")
    env["CLASH_LOGDIR"] = str(HOME / "runs")
    py = sys.executable
    if py.lower().endswith("pythonw.exe"): py = py[:-len("pythonw.exe")] + "python.exe"
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000 | 0x00004000          # no window, below-normal priority
    out = open(HOME / "train.log", "a", encoding="utf-8")
    out.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M')} training deck {spec}\n")
    out.flush()
    p = subprocess.Popen([py, "-u", "-m", "python_ai.trainers.train"], cwd=str(PKG), env=env,
                         stdout=out, stderr=subprocess.STDOUT, **kw)
    _pid_file().write_text(str(p.pid))
    if log: log.info(f"Clash Royale AI: training started on this PC (deck {spec}) — log {HOME / 'train.log'}")
    return True, "training started"


def stop():
    try:
        import psutil
        pid = int(_pid_file().read_text())
        proc = psutil.Process(pid)
        for c in proc.children(recursive=True): c.terminate()
        proc.terminate()
        return True
    except Exception:
        return False


def progress():
    """The newest line of the training log that says how far it got."""
    try:
        lines = (HOME / "train.log").read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]
    except OSError:
        return ""
    for ln in reversed(lines):
        if "Episode" in ln or "episode" in ln or "Win" in ln: return ln.strip()[:160]
    return lines[-1].strip()[:160] if lines else ""


def gate_in_background(deck_names):
    """gate() in its own Python process (the games are CPU work; in the bot's process they would slow its battle
    decisions). Waits for it. -> its report or None."""
    import json
    src = str(Path(__file__).resolve().parents[1])
    code = ("import sys, json; sys.path.insert(0, %r); from royale import engine_ai; "
            "print('GATE:' + json.dumps(engine_ai.gate(%r)))") % (src, list(deck_names or []))
    py = sys.executable
    if py.lower().endswith("pythonw.exe"): py = py[:-len("pythonw.exe")] + "python.exe"
    kw = {"creationflags": 0x08000000 | 0x00004000} if sys.platform == "win32" else {}
    try:
        p = subprocess.Popen([py, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, **kw)
        HOME.mkdir(parents=True, exist_ok=True)
        (HOME / "gate.pid").write_text(str(p.pid))
        out, _ = p.communicate(timeout=3600)
    except Exception as e:
        return f"could not test the new version: {e}"
    finally:
        try: (HOME / "gate.pid").unlink()
        except OSError: pass
    for ln in (out or "").splitlines():
        if ln.startswith("GATE:"): return json.loads(ln[5:])
    return None


# ------------------------------------------------------------------ playing
def _net():
    """The trained network (reloaded when training saved a newer one), or None."""
    w = weights()
    if w is None: return None
    try:
        mt = w.stat().st_mtime
        if _S["net"] is not None and mt == _S["net_mtime"]: return _S["net"]
        net = _load(w)
        _S["net"], _S["net_mtime"] = net, mt
        return net
    except Exception as e:
        _S["why"] = f"could not load the trained AI: {e}"
        _S["net"] = None
        return None


def new_battle():
    """A battle starts: the trained AI's memory is cleared and its network is loaded in the background (loading
    torch inside a battle stopped the bot for seconds); training and the version test are paused so the battle
    gets the whole CPU."""
    _S["hid"] = None
    pause_background()
    if weights() is not None and _S["net"] is None and not _S["loading"]:
        import threading
        def _load_bg():
            _S["loading"] = True
            try: _net()
            finally: _S["loading"] = False
        threading.Thread(target=_load_bg, daemon=True, name="ai-load").start()


def _background_pids():
    out = []
    for f in (_pid_file(), HOME / "gate.pid"):
        try: out.append(int(f.read_text()))
        except (OSError, ValueError): pass
    return out


def pause_background():
    """Suspend the training and the version test (and their workers) while the bot plays."""
    try:
        import psutil
    except ImportError:
        return
    for pid in _background_pids():
        try:
            p = psutil.Process(pid)
            for c in [p] + p.children(recursive=True):
                if c.status() != psutil.STATUS_STOPPED:
                    c.suspend(); _S["paused"].append(c.pid)
        except Exception:
            pass


def resume_background():
    """A battle is over: training and the version test go on."""
    try:
        import psutil
    except ImportError:
        return
    for pid in _S["paused"]:
        try: psutil.Process(pid).resume()
        except Exception: pass
    _S["paused"] = []


def propose(env):
    """The trained network's move on the mirrored arena: (hand slot or None for wait, engine x, engine y)."""
    if _S["net"] is None or _S["loading"]: return None          # loaded in the background, never in a battle
    net = _net()
    if net is None: return None
    try:
        import numpy as np, torch
        from python_ai.engine_constants import BOARD_W
        if _S["hid"] is None:
            _S["hid"] = (torch.zeros(1, net.LSTM_HIDDEN), torch.zeros(1, net.LSTM_HIDDEN))
        with torch.no_grad():
            obs = torch.tensor(np.asarray(env.get_observation_for_team(0), dtype=np.float32)).unsqueeze(0)
            feats, emb, sp = net.extract_features(obs)
            lg, _, _, _, hid = net.step_lstm_and_card(feats, _S["hid"], net.affordability_mask(obs))
            gi = int(lg.argmax(-1).item())
            cell = int(net.placement_given_card(hid[0], emb, torch.tensor([gi]), obs, sp).argmax(-1).item())
        _S["hid"] = hid
        if gi >= 4: return (None, 0.0, 0.0)
        return (gi, float(cell % BOARD_W), float(cell // BOARD_W))
    except Exception as e:
        _S["why"] = f"the trained AI failed: {e}"
        return None


def status():
    w = weights()
    return {"training": running(), "weights": str(w) if w else "", "newest": str(newest() or ""), "missing": missing(), "why": _S["why"],
            "progress": progress()}
