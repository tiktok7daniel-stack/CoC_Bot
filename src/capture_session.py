"""
Capture mode: the user plays, the bot only watches and photographs every NEW screen.

 - a frame is saved when the screen has settled (two frames in a row almost the same, so no half
   animations) and it differs from every picture already taken this session (perceptual hash), so
   going back to the same screen does not repeat it
 - the user's last tap before each picture is remembered (what was pressed to get there)
 - when the user presses Done, the words on every picture are read (OCR) and the session is shown
   in the app: the user deletes what is not wanted, then sends everything to the learning repo
   (captures/<session>/...) in ONE commit, and asks Claude in the chat to learn them.

Files: ~/.CoC_Bot/captures/<account>/<session>/NNN.jpg + session.json
"""
import json, time
from pathlib import Path

BASE = Path.home() / ".CoC_Bot" / "captures"
REQ = Path.home() / ".CoC_Bot" / "capture_requests"
MAX_SHOTS = 300
MAX_MINUTES = 20


def _safe(x):
    return "".join(c for c in str(x) if c.isalnum() or c in "-_") or "main"


# ====================================================================== requests / status (window <-> bot)
def request(id):
    REQ.mkdir(parents=True, exist_ok=True)
    (REQ / f"{_safe(id)}.json").write_text(json.dumps({"t": time.time()}), encoding="utf-8")
    try: (REQ / f"{_safe(id)}.stop").unlink()
    except OSError: pass


def pending(id):
    return (REQ / f"{_safe(id)}.json").exists()


def take_request(id, max_age=600):
    p = REQ / f"{_safe(id)}.json"
    if not p.exists(): return None
    try: d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): d = {}
    try: p.unlink()
    except OSError: pass
    return d if time.time() - float(d.get("t", 0)) < max_age else None


def request_stop(id):
    REQ.mkdir(parents=True, exist_ok=True)
    (REQ / f"{_safe(id)}.stop").write_text("1", encoding="utf-8")


def stop_requested(id):
    p = REQ / f"{_safe(id)}.stop"
    if p.exists():
        try: p.unlink()
        except OSError: pass
        return True
    return False


def set_status(id, text, **kw):
    REQ.mkdir(parents=True, exist_ok=True)
    (REQ / f"{_safe(id)}.status").write_text(json.dumps(dict(kw, text=text, t=time.time()), ensure_ascii=False), encoding="utf-8")


def get_status(id):
    try: return json.loads((REQ / f"{_safe(id)}.status").read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


# ====================================================================== sessions on disk
def session_dir(id, session):
    return BASE / _safe(id) / _safe(session)


def new_session(id):
    s = time.strftime("%Y%m%d_%H%M%S")
    d = session_dir(id, s)
    d.mkdir(parents=True, exist_ok=True)
    return s, d


def load_session(id, session):
    try: return json.loads((session_dir(id, session) / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError): return None


def save_session(id, session, data):
    d = session_dir(id, session)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "session.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / "session.json")


def sessions(id):
    out = []
    root = BASE / _safe(id)
    if not root.exists(): return out
    for d in sorted(root.iterdir(), reverse=True):
        s = load_session(id, d.name)
        if s: out.append({"session": d.name, "shots": len(s.get("shots", [])), "sent": s.get("sent"), "state": s.get("state")})
    return out


def latest(id):
    lst = sessions(id)
    return lst[0]["session"] if lst else None


def delete_shot(id, session, file):
    s = load_session(id, session)
    if not s: return False
    s["shots"] = [x for x in s.get("shots", []) if x["file"] != file]
    if "/" not in file and "\\" not in file and ".." not in file:
        try: (session_dir(id, session) / file).unlink()
        except OSError: pass
    save_session(id, session, s)
    return True


def delete_session(id, session):
    import shutil
    shutil.rmtree(session_dir(id, session), ignore_errors=True)


# ====================================================================== image similarity
def dhash(frame_rgb):
    """64-bit difference hash of a frame (robust to small changes, cheap)."""
    import cv2
    g = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY) if frame_rgb.ndim == 3 else frame_rgb
    small = cv2.resize(g, (17, 8), interpolation=cv2.INTER_AREA)
    bits = small[:, 1:] > small[:, :-1]
    v = 0
    for b in bits.flatten():
        v = (v << 1) | int(b)
    # a second, coarser look at the layout: 8x8 average hash
    a = cv2.resize(g, (8, 8), interpolation=cv2.INTER_AREA)
    m = a.mean()
    w = 0
    for b in (a > m).flatten():
        w = (w << 1) | int(b)
    return (v, w)


def distance(h1, h2):
    return bin(h1[0] ^ h2[0]).count("1") + bin(h1[1] ^ h2[1]).count("1")


STABLE = 6         # two frames in a row this close = the screen stopped moving
NEW = 22           # at least this far from every saved picture = a new screen


def is_new(h, saved):
    return all(distance(h, s) >= NEW for s in saved)


# ====================================================================== your attacks (inside a capture session)
BATTLE_FRAME_EVERY = 2.0
BATTLE_MAX_FRAMES = 80


def start_battle(folder, n, rec):
    d = folder / f"battle_{n:02d}"
    d.mkdir(parents=True, exist_ok=True)
    return {"n": n, "dir": d, "t0": time.time(), "ev0": len(rec.events) if rec is not None else 0, "frames": [],
            "last_frame": 0.0, "seen": len(rec.events) if rec is not None else 0}


def battle_frame(battle, frame, rec):
    """A picture every 2 s, and one right when a new deploy tap happens (what the battlefield looked like)."""
    import cv2
    now = time.time()
    new_tap = False
    if rec is not None:
        downs = [e for e in rec.events[battle["seen"]:] if e["type"] == "down"]
        battle["seen"] = len(rec.events)
        new_tap = bool(downs)
    if (now - battle["last_frame"] >= BATTLE_FRAME_EVERY or new_tap) and len(battle["frames"]) < BATTLE_MAX_FRAMES:
        name = f"{len(battle['frames']) + 1:03d}.jpg"
        small = cv2.resize(frame, (1280, int(1280 * frame.shape[0] / frame.shape[1])))
        cv2.imwrite(str(battle["dir"] / name), cv2.cvtColor(small, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 75])
        battle["frames"].append({"file": name, "t": round(now - battle["t0"], 2), "tap": new_tap})
        battle["last_frame"] = now


def end_battle(battle, rec, max_x, max_y, session):
    """Save the battle: taps (as screen positions + times), its pictures, and a replayable recording."""
    import army_learn, recorder
    events = list(rec.events[battle["ev0"]:]) if rec is not None else []
    t0 = events[0]["t"] if events else 0
    events = [dict(e, t=round(e["t"] - t0, 3)) for e in events]
    taps = []
    for e in events:
        if e["type"] == "down":
            x, y = army_learn.touch_to_screen(e["fx"], e["fy"], max_x, max_y)
            taps.append({"t": e["t"], "x": round(x, 4), "y": round(y, 4)})
    info = {"n": battle["n"], "folder": battle["dir"].name, "duration": round(time.time() - battle["t0"], 1),
            "taps": len(taps), "frames": len(battle["frames"]), "recording": ""}
    (battle["dir"] / "battle.json").write_text(json.dumps(dict(info, tap_list=taps, frame_list=battle["frames"]),
                                                          ensure_ascii=False, indent=1), encoding="utf-8")
    if taps:   # keep it as a battle recording the bot can replay (Attack -> loadouts)
        name = f"learned {session[4:8]}-{session[9:13]} #{battle['n']}"
        recorder.REC_DIR.mkdir(parents=True, exist_ok=True)
        data = {"name": name, "created": time.time(), "duration": events[-1]["t"] if events else 0,
                "max": [max_x, max_y], "events": events, "learned": True}
        (recorder.REC_DIR / f"{recorder._safe(name)}.json").write_text(json.dumps(data), encoding="utf-8")
        info["recording"] = name
    return info
