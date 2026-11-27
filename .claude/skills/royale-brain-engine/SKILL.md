---
name: royale-brain-engine
description: Clash Royale brain decision logic + C++ battle engine integration
version: 1.0
---

# Brain + Engine

## Core Files
- `src/royale/brain.py:Brain` — rule brain + learned policy + arena Transformer
- `src/royale/engine.py` — Python wrapper for C++ `clash_royale_env`
- `src/royale/policy.py` — learned policy net (play history)
- `src/royale/board.py` / `board_net.py` — arena Transformer (full arena state)
- `src/royale/engine_ai.py` — trained AI proposing moves
- `src/royale/card_use.py` — per-card placement rules (soft constraints)

## Decision Flow
```
Brain.decide(hand, ready, elixir, enemies, allies, towers, hp, spells, evo)
  ├─ Observe → threats per lane
  ├─ DEFEND: cheapest real counter (duel sim + K.COUNTERS)
  ├─ SPELLS: value ≥ cost × spell_value
  ├─ ATTACK: elixir advantage + weak tower lane
  ├─ NEVER LEAK: cycle at 9.5+ elixir
  ├─ SPECIAL (6.9.20): Goblin Barrel intercept, King Tower activation
  └─ Engine think (if engine_on):
       engine.think() → plays best candidate on 8s rollout
```

## Engine Contract
- `engine.selftest(log)` — runs Hog+Cannon test, returns bool
- `engine.think(brain, st, hand, playable, my_elixir, rule_d, log)` → `("play", slot, card, tile, why)` | `("wait", why)` | `None`
- Rollout: 80 ticks (8s), `ACTION_DELAY_TICKS=4` (0.4s deploy lag)
- Value: `TOWER_ELIXIR * hp_delta + army_delta - spent`
- Budget: `THINK_BUDGET=80ms` per look

## Key Constants
```python
MAX_PLAY_FRAME_AGE = 0.65      # game.py
ROLE_MAPPING: "spell", "building", "tank", "splash", "anti_air", "ranged", "swarm", "dps", "cycle", "win"
```

## Adding Logic
- **New counter**: edit `knowledge.py:K.COUNTERS["threat_card"]["want"]`
- **New spell rule**: edit `_small_spell_ok()` in `brain.py`
- **Per-card placement**: `card_use.check(brain, card, tile, why, engine_ok)`

## Testing
- Mock `engine.module()` → `MagicMock` with `ClashRoyaleEnv`, `get_card_info`
- `engine.selftest()` failure = engine disabled, brain rules only