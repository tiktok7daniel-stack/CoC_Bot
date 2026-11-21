"""
What the bot sees and thinks during a battle, for the app's "Battle view" screen (qt_ui/screens/royale_live_screen.py)
— the idea of crforge's debug visualizer, on the real game: the arena with every unit the eyes read (side, place,
life), the towers, both elixirs, our hand and theirs as the bot works it out, the moves the engine thought through
with their scores (a heat map), the move chosen and why, and the last plays of both sides.

Written up to 4 times a second to ~/.CoC_Bot/learn/royale_live_<account>.json (atomic replace); the screen polls it.
"""
import json, os, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "learn"
_S = {"t": 0.0, "events": [], "eh": 0}


def path(acc):
    return DIR / f"royale_live_{''.join(c for c in str(acc) if c.isalnum() or c in '-_') or 'main'}.json"


def _write(acc, data):
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        p = path(acc)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def phase(acc, what, note=""):
    """Outside a battle: lobby / waiting / searching / result."""
    _write(acc, {"t": time.time(), "phase": what, "note": note})


def new_battle():
    _S["events"], _S["eh"] = [], 0


def event(who, card, tile, why=""):
    _S["events"].append({"t": time.time(), "who": who, "card": card, "tile": list(tile) if tile else None,
                         "why": why[:140]})
    _S["events"] = _S["events"][-14:]


def battle(acc, brain, st, d, force=False):
    """One look of the battle. Cheap: skipped when the last write is under 0.25 s old (unless a move was made)."""
    now = time.time()
    hist = list(getattr(brain, "enemy_hist", []) or [])
    if len(hist) < _S["eh"]: _S["eh"] = 0
    for _t, name, x, y in hist[_S["eh"]:]:                 # their plays the bot noticed since the last write
        event("them", name, (int(x), int(y)))
    _S["eh"] = len(hist)
    if not force and now - _S["t"] < 0.25: return
    _S["t"] = now
    try:
        from royale import engine
        think = dict(engine._S.get("last") or {})
    except Exception:
        think = {}
    try: th = brain.their_hand()
    except Exception: th = None
    try: tn = brain.their_next()
    except Exception: tn = None
    hp = getattr(brain, "hp_seen", None) or {}

    def life(u, x, y):
        try: return round(float(brain.life(u, x, y)), 2)
        except Exception: return 1.0
    looks = st.get("hand_look") or [""] * 4
    data = {
        "t": now, "phase": "battle",
        "time_s": round(brain.elapsed(), 1),
        "double": bool(brain.double_elixir()),
        "elixir": round(float(st.get("elixir") or 0), 1),
        "their_elixir": round(float(brain.enemy_elixir or 0), 1),
        "hand": [{"card": h, "ready": i in (st.get("ready") or []),
                  "evo": "ev1" in (looks[i] if i < len(looks) else ""),
                  "hero": "hero" in (looks[i] if i < len(looks) else "")} for i, h in enumerate(st.get("hand") or [])],
        "next": st.get("next"),
        "towers": {k: v for k, v in (st.get("towers") or {}).items()},
        "enemies": [{"u": u, "x": x, "y": y, "life": life(u, x, y)} for u, x, y in (brain._stable or [])][:40],
        "allies": [{"u": a[0], "x": a[1], "y": a[2]} for a in (getattr(brain, "_allies_extra", None)
                                                              or st.get("allies") or [])][:40],
        "danger": [{"x": dd[0], "y": dd[1], "r": dd[2]} for dd in (getattr(brain, "danger", None) or [])][:8],
        "deck": list(brain.deck or []),
        "their_seen": sorted(brain.enemy_seen),
        "their_guess": sorted(brain.predicted),
        "their_hand": sorted(th) if th else None,
        "their_next": tn,
        "arch": brain.arch,
        "decision": ({"card": d["card"], "tile": list(d["tile"]), "why": d["why"]} if d else None),
        "think": think,
        "events": _S["events"],
        "engine": engine_state(),
        "perf": st.get("_perf") or {},
    }
    _write(acc, data)


def engine_state():
    try:
        from royale import engine, engine_ai
        st = engine.status()
        ai = engine_ai.status()
        return {"on": bool(st.get("ok")), "why": st.get("why", ""), "ai": bool(ai.get("weights")),
                "training": bool(ai.get("training"))}
    except Exception:
        return {"on": False, "why": "", "ai": False, "training": False}
