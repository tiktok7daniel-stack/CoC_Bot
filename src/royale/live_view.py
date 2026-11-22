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


def _boxes(brain, st):
    """What the eyes see, as boxes on the screen (fractions): every unit with its name, side and life."""
    from royale.eyes import tile_xy
    from royale.vision import constants as C
    hw, hh = C.TILE_WIDTH / C.DISPLAY_WIDTH * 0.6, C.TILE_HEIGHT / C.DISPLAY_HEIGHT * 0.75
    out = []

    def add(u, x, y, mine, life):
        cx, cy = tile_xy(x, y)
        out.append({"n": str(u), "m": mine, "b": [round(cx - hw, 4), round(cy - 2 * hh, 4), round(cx + hw, 4),
                                                   round(cy + hh * 0.6, 4)], "l": life})
    for u, x, y in (brain._stable or [])[:40]:
        try: life = round(float(brain.life(u, x, y)), 2)
        except Exception: life = 1.0
        add(u, x, y, False, life)
    for a in (getattr(brain, "_allies_extra", None) or st.get("allies") or [])[:40]:
        add(a[0], a[1], a[2], True, 1.0)
    return out


def _cands_at():
    """The engine's moves of this moment as screen points: [(x, y, value, card)]."""
    try:
        from royale import engine
        from royale.eyes import tile_xy
        last = engine._S.get("last") or {}
        if time.time() - float(last.get("t", 0)) > 3: return []
        return [[*tile_xy(*c["tile"]), c["v"], c["card"]] for c in (last.get("cands") or [])[:16]]
    except Exception:
        return []


def _model(brain):
    """What the AI model thinks this moment (5.89): play now or wait, each playable card's chance, its tiles."""
    pol = getattr(brain, "_pol", None) or {}
    if not pol.get("cards"): return None
    cands = []
    for c in (getattr(brain, "_ai_cands", None) or [])[:4]:
        try:
            from royale.eyes import tile_xy
            cands.append({"card": c[1], "tile": list(c[2]), "at": list(tile_xy(*c[2]))})
        except Exception:
            pass
    return {"play": round(float(pol.get("play", 0.0)), 3),
            "cards": {k: round(float(v), 3) for k, v in sorted(pol["cards"].items(), key=lambda kv: -kv[1])[:6]},
            "tiles": cands, "ai_only": bool(getattr(brain, "p", {}).get("ai_only"))}


def _dets(st):
    """Everything the eyes found in this look, unfiltered (both models): [name, ours, x, y, confidence] with the
    unit's place as screen fractions — the live screen's tracker follows each one (5.97)."""
    from royale.eyes import tile_xy
    out = []
    for lst, mine in ((st.get("enemies") or [], False), (st.get("allies") or [], True)):
        for e in lst[:60]:
            try:
                x, y = tile_xy(e[1], e[2])
                out.append([str(e[0]), mine, round(x, 4), round(y, 4), round(float(e[3]) if len(e) > 3 else 0.6, 2)])
            except Exception:
                pass
    return out


def _tracks(brain, st):
    """The tracker's units (6.6) as screen fractions: id, side, place, speed (fractions / s) and where the last
    spell aimed was led to — the live screen draws the id, an arrow for the speed and the predicted impact."""
    from royale.eyes import tile_xy
    out = []
    for t in (st.get("tracks") or [])[:60]:
        try:
            x, y = tile_xy(t["x"], t["y"])
            x2, y2 = tile_xy(t["x"] + t["vx"], t["y"] + t["vy"])
            out.append({"id": t["id"], "n": t["unit"], "m": t["team"] == "ally", "x": round(x, 4), "y": round(y, 4),
                        "vx": round(x2 - x, 4), "vy": round(y2 - y, 4), "lock": bool(t.get("locked")),
                        "eta": t.get("eta")})
        except Exception:
            pass
    lead = None
    ls = getattr(brain, "_lead_seen", None)
    if ls and time.monotonic() - ls.get("t", 0) < 2.0:
        try:
            lead = {"id": ls["id"], "card": ls["card"], "from": list(tile_xy(*ls["from"])), "to": list(tile_xy(*ls["to"]))}
        except Exception:
            lead = None
    return out, lead


def _save_frame(acc, frame):
    """A small copy of the screen (360 px wide) for the app's "the bot's eyes" panel, twice a second."""
    if frame is None or time.time() - _S.get("ft", 0) < 0.5: return False
    _S["ft"] = time.time()
    try:
        import cv2
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (360, int(h * 360 / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(small, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok: return False
        p = path(acc).with_suffix(".jpg")
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_bytes(buf.tobytes())
        tmp.replace(p)
        return True
    except Exception:
        return False


def battle(acc, brain, st, d, force=False, frame=None):
    """One look of the battle. Cheap: skipped when the last write is under 0.1 s old (unless a move was made)."""
    now = time.time()
    if _save_frame(acc, frame): _S["frame_t"] = now
    hist = list(getattr(brain, "enemy_hist", []) or [])
    if len(hist) < _S["eh"]: _S["eh"] = 0
    for _t, name, x, y in hist[_S["eh"]:]:                 # their plays the bot noticed since the last write
        event("them", name, (int(x), int(y)))
    _S["eh"] = len(hist)
    if not force and now - _S["t"] < 0.05: return            # every look (the live screen's tracker)
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
    trk = _tracks(brain, st)
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
        "frame_t": _S.get("frame_t", 0.0),
        "model": _model(brain),
        "boxes": _boxes(brain, st),
        "dets": _dets(st),
        "tracks": trk[0],
        "lead": trk[1],
        "seen_t": st.get("_seen_t") or now,
        "target": (list(__import__("royale.eyes", fromlist=["tile_xy"]).tile_xy(*d["tile"])) if d else None),
        "slot": (d.get("slot") if d else None),
        "card_at": (list(__import__("royale.eyes", fromlist=["card_xy"]).card_xy(d["slot"])) if d and
                    d.get("slot") is not None else None),
        "cands_at": _cands_at(),
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
