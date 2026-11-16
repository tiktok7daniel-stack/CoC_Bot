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
    e = {"t": time.time(), "type": type, **data}
    try:
        STATS_DIR.mkdir(parents=True, exist_ok=True)
        with open(_path(id), "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    except OSError:
        pass
    try: _ledger_add(id, e)
    except Exception: pass


# ====================================================================== permanent daily ledger
# The event file is trimmed to stay small; the ledger keeps one compact row per day forever:
# ~/.CoC_Bot/stats/<id>.daily.json  {"YYYY-MM-DD": {...counters...}}
DAY_KEYS = ("attacks", "home_attacks", "builder_attacks", "gold", "elixir", "dark", "bb_gold", "bb_elixir",
            "searches", "skipped", "upgrades", "walls", "buildings", "lab", "cycles", "cycle_seconds", "errors",
            "warnings", "best_gold", "best_elixir", "best_dark", "zero_loot")


def _ledger_path(id):
    return _path(id).with_suffix(".daily.json")


def _ledger_load(id):
    p = _ledger_path(id)
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError): pass
    # first use: build it from the events still on disk
    led = {}
    for e in read(id): _apply(led, e)
    _ledger_save(id, led)
    return led


def _ledger_save(id, led):
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    p = _ledger_path(id)
    tmp = p.with_suffix(".tmp2")
    tmp.write_text(json.dumps(led, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _apply(led, e):
    t = e.get("t", time.time())
    day = time.strftime("%Y-%m-%d", time.localtime(t))
    d = led.setdefault(day, {k: 0 for k in DAY_KEYS})
    for k in DAY_KEYS: d.setdefault(k, 0)
    d.setdefault("hours", [0] * 24)
    d["first"] = min(d.get("first") or t, t)
    d["last"] = max(d.get("last") or t, t)
    typ = e.get("type")
    if typ == "attack":
        d["attacks"] += 1
        g, el, dk = (max(0, int(e.get(k) or 0)) for k in ("gold", "elixir", "dark"))
        if e.get("base") == "builder":
            d["builder_attacks"] += 1
            d["bb_gold"] += g
            d["bb_elixir"] += el
        else:
            d["home_attacks"] += 1
            d["gold"] += g
            d["elixir"] += el
            d["dark"] += dk
            d["best_gold"] = max(d["best_gold"], g)
            d["best_elixir"] = max(d["best_elixir"], el)
            d["best_dark"] = max(d["best_dark"], dk)
            if g + el + dk == 0: d["zero_loot"] += 1
            d["hours"][time.localtime(t).tm_hour] += g + el
    elif typ == "search":
        d["searches"] += 1
        if not e.get("accepted", True): d["skipped"] += 1
    elif typ == "upgrade":
        d["upgrades"] += 1
        kind = e.get("kind")
        if kind == "wall": d["walls"] += 1
        elif kind == "lab": d["lab"] += 1
        else: d["buildings"] += 1
        names = d.setdefault("names", [])
        if kind != "wall" and e.get("name") and len(names) < 40: names.append(str(e.get("name")))
    elif typ == "cycle":
        d["cycles"] += 1
        d["cycle_seconds"] += int(e.get("seconds") or 0)
    elif typ == "error": d["errors"] += 1
    elif typ == "warning": d["warnings"] += 1


def _ledger_add(id, e):
    if e.get("type") not in ("attack", "search", "upgrade", "cycle", "error", "warning"): return
    fresh = not _ledger_path(id).exists()
    led = _ledger_load(id)          # a fresh ledger is rebuilt from the event file, which already has e
    if fresh: return
    _apply(led, e)
    _ledger_save(id, led)


def daily(id, days=0):
    """Rows oldest -> newest; days=0 means everything. Each row has derived loot/hour and active hours."""
    led = _ledger_load(id)
    keys = sorted(led)
    if days:
        cut = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days - 1) * 86400))
        keys = [k for k in keys if k >= cut]
    out = []
    for k in keys:
        d = dict(led[k])
        active = d.get("cycle_seconds") or max(0, (d.get("last") or 0) - (d.get("first") or 0))
        d["date"] = k
        d["active_hours"] = round(active / 3600, 2)
        d["loot"] = d.get("gold", 0) + d.get("elixir", 0)
        d["loot_per_hour"] = int(d["loot"] / max(active / 3600, 0.25)) if d["loot"] else 0
        out.append(d)
    return out


def merge_days(rows_lists):
    """Combine several accounts' daily rows by date."""
    by = {}
    for rows in rows_lists:
        for r in rows:
            m = by.setdefault(r["date"], {"date": r["date"], "hours": [0] * 24})
            for k, v in r.items():
                if k in ("date", "names", "first", "last"): continue
                if k == "hours": m["hours"] = [a + b for a, b in zip(m["hours"], v)]
                elif k.startswith("best_"): m[k] = max(m.get(k, 0), v)
                elif isinstance(v, (int, float)): m[k] = m.get(k, 0) + v
            m.setdefault("names", []).extend(r.get("names", []))
    return [by[k] for k in sorted(by)]

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
        "strategies": strategy_scores(events),
        "searches": sum(1 for e in session if e["type"] == "search"),
        "skipped": sum(1 for e in session if e["type"] == "search" and not e.get("accepted", True)),
        "best": {k: max((int(e.get(k) or 0) for e in home), default=0) for k in ("gold", "elixir", "dark")},
        "worst": {k: min((int(e.get(k) or 0) for e in home), default=0) for k in ("gold", "elixir", "dark")},
        "errors": sum(1 for e in session if e["type"] == "error"),
        "warnings": sum(1 for e in session if e["type"] == "warning"),
    }

def problems(id, limit=150):
    """Most recent errors / warnings, newest first."""
    events = read(id)
    cut = max((i for i, e in enumerate(events) if e["type"] == "errors_cleared"), default=-1)
    return list(reversed([e for e in events[cut + 1:] if e["type"] in ("error", "warning")][-limit:]))

def strategy_scores(events):
    """What the bot has learned: average loot per deployment strategy (all sessions)."""
    out = {}
    for e in events:
        if e["type"] != "attack" or e.get("base") != "home" or not e.get("strategy"): continue
        d = out.setdefault(e["strategy"], {"attacks": 0, "gold": 0, "elixir": 0, "dark": 0})
        d["attacks"] += 1
        for k in ("gold", "elixir", "dark"): d[k] += int(e.get(k) or 0)
    for d in out.values():
        for k in ("gold", "elixir", "dark"): d[k] //= max(1, d["attacks"])
    return out

def error_groups(id, since=0):
    """Errors grouped by message (numbers stripped), most frequent first."""
    import re
    groups = {}
    for e in read(id, since):
        if e["type"] not in ("error", "warning"): continue
        key = re.sub(r"\d+", "#", e.get("message", ""))[:160]
        g = groups.setdefault(key, {"message": e.get("message", ""), "type": e["type"], "count": 0, "phases": set(),
                                    "where": e.get("where", ""), "detail": e.get("detail", ""), "last": 0})
        g["count"] += 1
        g["phases"].add(e.get("phase", ""))
        g["last"] = max(g["last"], e["t"])
    out = sorted(groups.values(), key=lambda g: -g["count"])
    for g in out: g["phases"] = sorted(p for p in g["phases"] if p)
    return out
