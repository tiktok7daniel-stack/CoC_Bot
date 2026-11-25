"""Read-only replay of the decision policy against recorded card deployments."""
import math
import time
from collections import Counter, deque

from royale.brain import Brain, card, cards_db
from royale.deck_catalog import signature, variant_key
from royale.replay_evidence import SIDES, validated_plays
from royale.sim import Arena

TOWERS = ("our_left", "our_right", "our_king", "their_left", "their_right", "their_king")


def _base(name):
    return variant_key(name).split("-", 1)[0]


class _ClockBrain(Brain):
    current = 0.0

    def elapsed(self):
        return self.current

    def observe(self, enemies, now=None):
        history, elixir = list(self.enemy_hist), self.enemy_elixir
        stable = super().observe(enemies, now)
        self.enemy_hist, self.enemy_elixir = history, elixir
        return stable


def _elixir_between(brain, start, end):
    gained = 0.0
    for boundary in (120.0, 180.0, end):
        until = min(end, boundary)
        if until > start:
            gained += (until - start) / brain.seconds_per_elixir(start)
            start = until
    return gained


def evaluate(replay, side, ai_only=True):
    """Compare suggestions at human play times once the four-card cycle is observable."""
    if side not in SIDES:
        raise ValueError("invalid side")
    battle = replay.get("battle") or {}
    players = {s: (battle.get(s) or {}).get("players") or [] for s in SIDES}
    if any(len(p) != 1 for p in players.values()):
        return {"status": "skip", "reason": "not_1v1"}
    decks = {s: signature(c.get("card_key") for c in p[0].get("deck", [])) for s, p in players.items()}
    if any(len(keys) != 8 or len({_base(k) for k in keys}) != 8 or not all(keys) for keys in decks.values()):
        return {"status": "skip", "reason": "incomplete_deck"}
    by_key = {_base(n): n for n in cards_db()}
    rows = replay.get("actions") or []
    plays = validated_plays(rows)
    play_count = sum(r.get("kind") == "play_card" for r in rows)
    if not plays or len(plays) != play_count or plays[-1][0] > 600:
        return {"status": "skip", "reason": "incomplete_or_invalid_placements"}
    if len({p[1] for p in plays}) != len(plays):
        return {"status": "skip", "reason": "duplicate_event_index"}
    unknown = sorted({k for keys in decks.values() for k in keys if _base(k) not in by_key}
                     | {k for _, _, _, k, _, _ in plays if _base(k) not in by_key})
    if unknown:
        return {"status": "skip", "reason": "unsupported_cards", "cards": unknown}
    allowed = {s: {_base(k) for k in keys} for s, keys in decks.items()}
    if any(_base(k) not in allowed[s] for _, _, s, k, _, _ in plays):
        return {"status": "skip", "reason": "card_outside_recorded_deck"}
    perspective = "us" if side == "team" else "them"
    enemy = "opponent" if side == "team" else "team"
    brain = _ClockBrain(deck=[by_key[_base(k)] for k in decks[side]], params={"ai": True, "ai_only": ai_only})
    arena = Arena()
    recent_own = deque(maxlen=4)
    observed_enemy = []
    elixir = dict.fromkeys(SIDES, 6.0)
    base_time = time.monotonic() - plays[-1][0]
    brain.t0 = brain.enemy_t = base_time
    previous = 0.0
    decisions, counts = [], Counter()

    for seconds, index, player, key, gx, gy in plays:
        arena.run_to(seconds, dt=0.1)
        available = _elixir_between(brain, previous, seconds)
        for s in SIDES:
            elixir[s] = min(10.0, elixir[s] + available)
        previous = seconds
        name = by_key[_base(key)]
        x, y = (gx, gy) if side == "team" else (17 - gx, 31 - gy)
        if player == side:
            counts["reference_plays"] += 1
            outside_hand = set(recent_own)
            # A normal four-card cycle keeps the four most recently played cards
            # outside the hand. Skip cycles that visibly violate that assumption.
            hand_keys = sorted(allowed[side] - outside_hand) if len(outside_hand) == 4 else []
            if not hand_keys:
                counts["cycle_unknown"] += 1
            elif _base(key) not in hand_keys:
                counts["cycle_mismatch"] += 1
            elif card(name).get("cost", 11) > elixir[side] + 1e-6:
                counts["elixir_mismatch"] += 1
            else:
                board = arena.board(perspective)
                foes, friends, health = [], [], {}
                for mine, unit, ux, uy, life, _, _, _, _ in board:
                    tx, ty = min(17, max(0, int(ux))), min(31, max(0, int(uy)))
                    (friends if mine else foes).append((unit, tx, ty, 0.9))
                    if not mine:
                        health[unit, tx, ty] = life
                hand = [by_key[k] for k in hand_keys]
                brain.current = seconds
                brain.enemy_elixir, brain.enemy_t = elixir[enemy], base_time + seconds
                brain._pol = None
                pick = brain.decide(hand, list(range(4)), elixir[side], foes, friends,
                                    dict(zip(TOWERS, arena.towers(perspective))),
                                    now=base_time + seconds, hp=health)
                counts["compared"] += 1
                row = {"at_s": seconds, "event": index, "reference": {"card": name, "tile": [x, y]},
                       "inferred_hand": hand, "estimated_elixir": round(elixir[side], 2),
                       "proposal": None, "same_card": False, "tile_error": None}
                if observed_enemy:
                    et, ec, ex, ey = observed_enemy[-1]
                    row["previous_enemy_play"] = {
                        "card": ec, "tile": [ex, ey], "seconds_before": round(seconds - et, 3),
                    }
                if pick:
                    row["proposal"] = {k: pick[k] for k in ("card", "tile", "why")}
                    row["same_card"] = pick["card"] == name
                    if row["same_card"]:
                        row["tile_error"] = round(math.dist(pick["tile"], (x, y)), 3)
                        counts["same_card"] += 1
                    brain.undo(pick)
                else:
                    counts["wait_at_reference_play"] += 1
                decisions.append(row)
            recent_own.append(_base(key))
            brain.last_play = base_time + seconds
            brain.plays.append({"card": name, "tile": (x, y), "t": seconds})
        else:
            observed_enemy.append((seconds, name, x, y))
            brain.enemy_hist = list(observed_enemy)
        arena.play("us" if player == "team" else "them", name, gx, gy)
        elixir[player] = max(0.0, elixir[player] - card(name).get("cost", 3))
    return {"status": "evaluated" if decisions else "insufficient_positions", "side": side,
            "summary": dict(counts), "decisions": decisions,
            "ability_events_unmodeled": sum(r.get("kind") == "activate_ability" for r in rows)}
