"""
Session statistics, one JSON-lines file per account: ~/.CoC_Bot/stats/<id>.jsonl
Written by the bot process, read by the GUI.

Event types:
  resources : {"gold", "elixir", "dark"}           latest storage reading
  attack    : {"base": "home"|"builder", "gold", "elixir", "dark"}  loot of one attack
  upgrade   : {"kind": "building"|"wall"|"lab"|"pet"|..., "name"}
  cycle     : {"seconds"}                          one full bot cycle
  error     : {"message"}
"""
import json, time, os
from pathlib import Path

STATS_DIR = Path.home() / ".CoC_Bot" / "stats"
MAX_EVENTS = 5000

def _path(id):
    safe = "".join(c for c in str(id) if c.isalnum() or c in "-_") or "main"
    return STATS_DIR / f"{safe}.jsonl"

def record(id, type, **data):
    try:
        STATS_DIR.mkdir(parents=True, exist_ok=True)
        with open(_path(id), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "type": type, **data}, ensure_ascii=False) + "\n")
    except OSError:
        pass

def read(id, since=0):
    p = _path(id)
    if not p.exists(): return []
    events = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get("t", 0) >= since: events.append(e)
                except ValueError: continue
    except OSError:
        return []
    if len(events) > MAX_EVENTS * 2: # keep the file small
        events = events[-MAX_EVENTS:]
        try:
            tmp = p.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                for e in events: f.write(json.dumps(e, ensure_ascii=False) + "\n")
            os.replace(tmp, p)
        except OSError: pass
    return events

def clear(id):
    try: _path(id).unlink()
    except OSError: pass
    record(id, "session_start")

def summary(id):
    events = read(id)
    # session = everything after the last "session_start"
    start_idx = max((i for i, e in enumerate(events) if e["type"] == "session_start"), default=-1)
    session = events[start_idx + 1:]
    session_start = events[start_idx]["t"] if start_idx >= 0 else (session[0]["t"] if session else time.time())
    hours = max((time.time() - session_start) / 3600, 1 / 6) # avoid absurd rates in the first minutes

    attacks = [e for e in session if e["type"] == "attack"]
    upgrades = [e for e in session if e["type"] == "upgrade"]
    cycles = [e for e in session if e["type"] == "cycle"]
    latest_res = next((e for e in reversed(events) if e["type"] == "resources"), None)

    home = [e for e in attacks if e.get("base") == "home"] # builder-base loot is a separate economy
    def total(key): return sum(max(0, int(e.get(key) or 0)) for e in home)
    totals = {k: total(k) for k in ("gold", "elixir", "dark")}
    n = len(home)
    return {
        "session_start": session_start,
        "attacks": len(attacks),
        "home_attacks": sum(1 for e in attacks if e.get("base") == "home"),
        "builder_attacks": sum(1 for e in attacks if e.get("base") == "builder"),
        "totals": totals,
        "per_attack": {k: (v // n if n else 0) for k, v in totals.items()},
        "per_hour": {k: int(v / hours) for k, v in totals.items()},
        "upgrades": len(upgrades),
        "walls": sum(1 for e in upgrades if e.get("kind") == "wall"),
        "cycles": len(cycles),
        "avg_cycle_seconds": int(sum(e.get("seconds", 0) for e in cycles) / len(cycles)) if cycles else 0,
        "resources": {k: latest_res.get(k) for k in ("gold", "elixir", "dark")} if latest_res else None,
        "resources_time": latest_res["t"] if latest_res else None,
        "recent_attacks": list(reversed(attacks[-50:])),
        "recent_upgrades": list(reversed(upgrades[-50:])),
    }
