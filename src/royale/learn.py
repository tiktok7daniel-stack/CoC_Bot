"""
The Clash Royale brain learns by itself which way of playing wins (idea from sacha9214/clash-ai, MIT: a factorised
Thompson-sampling bandit). Every battle plays one value of each setting below; a win or a loss counts for every value
it played, so every battle teaches every setting at once.

  push_adv      elixir lead (ours - theirs, estimated) needed to attack
  defend_min    how big a threat must be before a card is spent on it (small ones: the towers handle them)
  spell_value   a spell is cast only when it destroys at least this x its own cost in elixir
  cycle_at      nothing to do: a cheap card is cycled at the back from this elixir on
  punish_heavy  the opponent dropped a heavy card (6+) at the back: attack the other lane at once
  counter_push  after a good defense, push with the defenders that survived
  endgame       the last 30 s: behind -> everything goes in, ahead -> defend only
  duel_defense  the defender is chosen by a duel simulated with the cards' real numbers
Stored per account: ~/.CoC_Bot/learn/royale_strategy_<account>.json
"""
import json, os, random, time
from pathlib import Path

SPACE = {
    "push_adv": [1.0, 2.0, 3.0],
    "defend_min": [1.0, 1.5, 2.5],
    "spell_value": [0.8, 1.0, 1.3],
    "cycle_at": [8.0, 9.0, 9.5],
    "punish_heavy": [True, False],
    "counter_push": [True, False],
    "endgame": [True, False],
    "duel_defense": [True, False],
}
DEFAULT = {"push_adv": 2.0, "defend_min": 1.5, "spell_value": 1.0, "cycle_at": 9.5, "punish_heavy": True,
           "counter_push": True, "endgame": True, "duel_defense": True}
PRIOR = 2.0                # an untried value counts as 2 battles at the overall win rate
DIR = Path.home() / ".CoC_Bot" / "learn"


def _path(acc):
    return DIR / f"royale_strategy_{''.join(c for c in str(acc) if c.isalnum() or c in '-_') or 'main'}.json"


def load(acc):
    try: return json.loads(_path(acc).read_text(encoding="utf-8"))
    except (OSError, ValueError): return {"games": [], "per": {}}


def _save(acc, d):
    DIR.mkdir(parents=True, exist_ok=True)
    p = _path(acc)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def choose(acc, explore=True):
    """The settings for the next battle: each one drawn from Beta(wins, losses) of its values (Thompson)."""
    d = load(acc)
    per = d.get("per", {})
    games = d.get("games", [])
    w_all = sum(1 for g in games if g.get("won")) + 1
    n_all = len(games) + 2
    base = w_all / n_all
    out = {}
    for k, values in SPACE.items():
        if not explore:
            out[k] = DEFAULT[k]; continue
        best, best_s = DEFAULT[k], -1.0
        for v in values:
            st = per.get(k, {}).get(json.dumps(v), {"w": 0, "l": 0})
            a = st["w"] + PRIOR * base
            b = st["l"] + PRIOR * (1 - base)
            s = random.betavariate(max(0.01, a), max(0.01, b))
            if s > best_s: best, best_s = v, s
        out[k] = best
    return out


def record(acc, params, won):
    """A battle's result -> every setting value it played learns from it."""
    if won is None: return
    d = load(acc)
    per = d.setdefault("per", {})
    for k, v in params.items():
        st = per.setdefault(k, {}).setdefault(json.dumps(v), {"w": 0, "l": 0})
        st["w" if won else "l"] += 1
    d.setdefault("games", []).append({"t": round(time.time()), "won": bool(won), "params": params})
    d["games"] = d["games"][-500:]
    _save(acc, d)


def best(acc):
    """What it learned so far: the value with the best win rate of each setting (for the app / the log)."""
    per = load(acc).get("per", {})
    out = {}
    for k in SPACE:
        rows = [(json.loads(v), st["w"], st["l"]) for v, st in per.get(k, {}).items()]
        rows = [r for r in rows if r[1] + r[2] >= 3]
        if rows: out[k] = max(rows, key=lambda r: (r[1] + 1) / (r[1] + r[2] + 2))[0]
    return out
