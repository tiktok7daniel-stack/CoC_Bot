"""
Today's plan: once the game is open (first time each day, per account) the bot asks in the app
"What do you want to do today?" and waits for the answer (default after a while: the usual).

Plan file ~/.CoC_Bot/plans/<account>.json
  {"date": "YYYY-MM-DD", "mode": "usual" | "custom" | "nothing", "do": {...}, "t": ..., "auto": bool}
The plan never changes the saved settings: overlay(s) returns a copy with today's choices on top, used by
the bot when it reads its settings and by the task exclusions.
"""
import copy, json, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "plans"
ASK_TIMEOUT = 120           # seconds the bot waits for an answer, then does the usual

# what the user can pick -> which settings it controls
ITEMS = {
    "attack":        {"tasks": ["home_attacks"]},
    "buildings":     {"tasks": ["home_base", "builder_apprentice"]},
    "walls":         {"walls": True},
    "lab":           {"tasks": ["home_lab", "lab_assistant"]},
    "heroes":        {"tasks": ["heroes", "pet_house"]},
    "builder_base":  {"tasks": ["builder_attacks", "builder_base", "builder_lab"]},
}


def _safe(x):
    return "".join(c for c in str(x) if c.isalnum() or c in "-_") or "main"


def today():
    return time.strftime("%Y-%m-%d")


def load(id):
    try: d = json.loads((DIR / f"{_safe(id)}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError): return None
    return d if d.get("date") == today() else None


def save(id, mode, do=None, auto=False):
    DIR.mkdir(parents=True, exist_ok=True)
    d = {"date": today(), "mode": mode, "do": do or {}, "t": time.time(), "auto": auto}
    (DIR / f"{_safe(id)}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    try: (DIR / f"{_safe(id)}.ask").unlink()
    except OSError: pass
    return d


def mode(id):
    p = load(id)
    return p["mode"] if p else None


# ====================================================================== asking (bot <-> window)
def ask(id):
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{_safe(id)}.ask").write_text(json.dumps({"t": time.time()}), encoding="utf-8")


def asking(id):
    p = DIR / f"{_safe(id)}.ask"
    if not p.exists(): return None
    try: t = json.loads(p.read_text(encoding="utf-8")).get("t", 0)
    except (OSError, ValueError): t = 0
    if time.time() - t > ASK_TIMEOUT + 30:
        return None
    return {"since": t, "left": max(0, int(ASK_TIMEOUT - (time.time() - t)))}


def cancel_ask(id):
    try: (DIR / f"{_safe(id)}.ask").unlink()
    except OSError: pass


# ====================================================================== settings overlay
def overlay(s, id):
    """Settings with today's plan on top (a copy; the saved settings are untouched)."""
    p = load(id)
    if not p or p.get("mode") == "usual": return s
    s = copy.deepcopy(s)
    tasks = s.setdefault("tasks", {})
    if p["mode"] == "nothing":
        for k in list(tasks): tasks[k] = False
        s.setdefault("walls", {})["enabled"] = False
        farm = s.setdefault("attack", {}).setdefault("farm", {})
        farm["enabled"] = False
        farm["max_walls"] = False
        return s
    do = p.get("do", {})
    for key, what in ITEMS.items():
        if do.get(key, True): continue          # chosen (or not mentioned): keep the user's settings
        for t in what.get("tasks", []): tasks[t] = False
        if what.get("walls"):
            s.setdefault("walls", {})["enabled"] = False
            s.setdefault("attack", {}).setdefault("farm", {})["max_walls"] = False
    if not do.get("attack", True):
        s.setdefault("attack", {}).setdefault("farm", {})["enabled"] = False
    return s


def describe(p):
    """Short English summary for the log."""
    if not p: return "none"
    if p["mode"] != "custom": return p["mode"]
    return ", ".join(k for k, v in p.get("do", {}).items() if v) or "nothing"
