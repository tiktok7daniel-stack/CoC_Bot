"""Turn complete replay events into inspectable candidate responses."""
from collections import Counter
from math import isfinite

from royale.deck_catalog import api_card_variant, signature

SIDES = ("team", "opponent")


def validated_plays(rows):
    """Keep source ordering for simultaneous ticks and omit incomplete placements."""
    plays = []
    for row in rows:
        if row.get("kind") != "play_card" or row.get("side") not in SIDES or not row.get("card_key"):
            continue
        x, y, t, index = (row.get(k) for k in ("grid_x", "grid_y", "time_seconds", "event_index"))
        if (type(x) is not int or type(y) is not int or not 0 <= x < 18 or not 0 <= y < 32
                or not isinstance(t, (int, float)) or not isfinite(t) or t < 0 or type(index) is not int):
            continue
        plays.append((float(t), index, row["side"], row["card_key"], x, y))
    return sorted(plays)


def responses(rows, side, max_delay=4.0):
    """Label the first opposing-side play after each threat as a candidate, not a causal outcome."""
    if side not in SIDES:
        raise ValueError("invalid defending side")
    plays = validated_plays(rows)
    threat = None
    for t, index, player, card, x, y in plays:
        if side == "opponent":
            x, y = 17 - x, 31 - y
        if player != side:
            threat = (t, index, card, x, y)
            continue
        if threat is None:
            continue
        started, attack_index, attack, ax, ay = threat
        threat = None
        if not 0 < t - started <= max_delay:
            continue
        center = 6 <= x <= 11 or 6 <= ax <= 11
        same_lane = (x < 9) == (ax < 9)
        yield {"attack_index": attack_index, "reply_index": index, "attack": attack, "reply": card,
               "attack_tile": [ax, ay], "reply_tile": [x, y], "delay_s": round(t - started, 3),
               "geometry": "center" if center else "same_lane" if same_lane else "opposite_lane"}


def official_matchups(battles, cards):
    """Aggregate each battle once across both public player perspectives."""
    target = signature(cards)
    seen = set()
    groups = {}
    for battle in battles:
        left, right = battle.get("team", []), battle.get("opponent", [])
        if len(left) != 1 or len(right) != 1:
            continue
        a, b = left[0], right[0]
        if not battle.get("battleTime") or not a.get("tag") or not b.get("tag"):
            continue
        identity = (battle["battleTime"], *sorted((a["tag"], b["tag"])))
        if identity in seen:
            continue
        seen.add(identity)
        decks = [tuple(sorted(api_card_variant(c) for c in p.get("cards", []))) for p in (a, b)]
        if any(len(deck) != 8 or not all(deck) for deck in decks) or target not in decks:
            continue
        if decks[0] == target:
            own, rival, other = a, b, decks[1]
        else:
            own, rival, other = b, a, decks[0]
        if type(own.get("crowns")) is not int or type(rival.get("crowns")) is not int:
            continue
        counters = groups.setdefault((battle.get("type", "unknown"), other), Counter())
        diff = own["crowns"] - rival["crowns"]
        outcome = "mirrors" if decks[0] == decks[1] else "wins" if diff > 0 else "losses" if diff < 0 else "draws"
        counters[outcome] += 1
    result = [{"mode": mode, "opponent": list(deck), "games": sum(c.values()),
               **{name: c[name] for name in ("wins", "losses", "draws", "mirrors")}}
              for (mode, deck), c in groups.items()]
    return sorted(result, key=lambda row: (-row["games"], row["mode"], row["opponent"]))
