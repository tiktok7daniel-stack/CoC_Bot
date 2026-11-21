"""
The battle engine the bot thinks with: ClashRoyaleEnv (itzik123/ClashRoyaleAi, MIT) — a C++ simulator of the whole
battle (132 cards, 41 Evolutions, Champions and Heroes, movement calibrated against real matches, ~20,000x real
time), vendored in third_party/clash_royale_env and built for Windows by .github/workflows/royale_engine.yml into
assets/royale/engine/.

Every moment of a battle the bot rebuilds the arena inside the engine (a "mirror"): towers' life, every unit the
eyes see with its side, place and life, both sides' elixir, our hand. Then it THINKS: each candidate move (the rule
brain's choice, the local AI model's cards and tiles, the defensive spots around a threat, spell targets, ...) is
played on a copy of that arena and the battle is run 8 seconds ahead; the move whose future is best (tower life
kept and taken, the elixir worth of units killed, minus what was spent) is the one played. "Wait" is a candidate
too, so a move that does not beat waiting is not made.

  defense  (their units on our half / at the bridge): every playable card x its candidate tiles + wait
  attack   (the brain wants to play): the brain's card on its candidate tiles; a move clearly worse than waiting
           is dropped

The engine is used only after it passes a self-test on this PC (royale.engine.selftest): a Hog walking at our
tower damages it, a Cannon in the middle pulls it, our half is legal and the river is not, copies are
independent. Anything wrong -> the bot plays as before, and says why.
"""
import math, os, sys, time

ROLLOUT_TICKS = 80             # 8 s ahead
TOWER_ELIXIR = {0: 18.0, 1: 10.0, 2: 10.0}    # what a whole tower is worth, in elixir (King more: it ends the game)
OFFENSE_DISCOUNT = 0.5         # in a rollout the opponent does not answer: damage we deal counts half
WAIT_MARGIN = 0.4              # a move must beat waiting by this much (elixir)
VETO_MARGIN = -1.0             # the brain's move is dropped when it is this much worse than waiting

_S = {"mod": None, "ok": None, "why": "", "ids": None, "maxhp": {}}


def _dir():
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(here, "..", "..", "assets", "royale", "engine"),
              os.path.join(getattr(sys, "_MEIPASS", ""), "assets", "royale", "engine")):
        if os.path.isdir(d): return os.path.abspath(d)
    return None


def module():
    """The compiled engine for this Python, or None."""
    if _S["mod"] is not None: return _S["mod"]
    d = _dir()
    if d and d not in sys.path: sys.path.insert(0, d)
    try:
        import clash_royale_env as m
    except ImportError as e:
        _S["why"] = f"no engine build for this Python ({sys.version_info.major}.{sys.version_info.minor}): {e}"
        return None
    _S["mod"] = m
    return m


def _k(s):
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def card_ids():
    """{our card name: (base id, evolution id or None, hero id or None)}."""
    if _S["ids"] is not None: return _S["ids"]
    m = module()
    from royale.brain import cards_db
    by = {}
    for cid in range(1, 260):
        try: info = m.get_card_info(cid)
        except Exception: continue
        name = _k(info["name"])
        is_evo = 123 <= cid <= 163
        if info.get("is_hero") and name.startswith("hero"):
            by.setdefault(name[4:], {})["hero"] = cid
        elif is_evo:
            by.setdefault(name, {})["evo"] = cid
        else:
            by.setdefault(name, {}).setdefault("base", cid)
    out = {}
    alias = {"thelog": "thelog", "minipekka": "minipekka", "pekka": "pekka"}
    for n in cards_db():
        e = by.get(alias.get(_k(n), _k(n)))
        if e and e.get("base"): out[n] = (e["base"], e.get("evo"), e.get("hero"))
    _S["ids"] = out
    return out


def eng_xy(tx, ty):
    """The bot's tile (x 0..17, y 0..31 from our back edge) -> the engine's board point (x 0..17, y 0..33: one extra
    row behind each King; cell i covers [i-0.5, i+0.5])."""
    return float(max(0, min(17, tx))), float(max(0.0, min(33.0, ty + 1)))


def _max_hp(m, cid):
    """A card's first body's full life (read once from a scratch engine)."""
    if cid in _S["maxhp"]: return _S["maxhp"][cid]
    hp = None
    try:
        e = m.ClashRoyaleEnv(_filler_deck(m, [cid]), _filler_deck(m, []), 3600)
        e.reset()
        before = {u.id for u in e.get_units()}
        e.inject(cid, 8.0, 10.0, 0, -1.0, 0)
        e.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 1)
        new = [u for u in e.get_units() if u.id not in before and not u.tower]
        hp = max((u.hp for u in new), default=None)
    except Exception:
        hp = None
    _S["maxhp"][cid] = hp
    return hp


def _filler_deck(m, want):
    """8 distinct card ids starting with `want` (a deck the engine accepts: plain cards only)."""
    deck = []
    for c in list(want) + [15, 6, 25, 40, 24, 72, 33, 7, 1, 2, 3, 4, 5, 8, 9, 10, 11, 12]:
        if c and c not in deck: deck.append(c)
        if len(deck) == 8: break
    return deck


def _deck_ids(m, names):
    """Our card names -> the engine's plain card ids (the hand we set must be made of the same ids; an
    Evolution's own effect is left out of the thinking)."""
    ids = card_ids()
    return _filler_deck(m, [ids[n][0] for n in names if n in ids])


def selftest(log=None):
    """True when the engine behaves as the bot expects; the reason otherwise. Run once per start."""
    if _S["ok"] is not None: return _S["ok"]
    m = module()
    if m is None:
        _S["ok"] = False
        return False
    try:
        ids = card_ids()
        hog, cannon = ids["hog_rider"][0], ids["cannon"][0]
        # 1. an enemy Hog at their side of our left bridge hits our left Princess within 8 s
        e = m.ClashRoyaleEnv(_filler_deck(m, [cannon]), _filler_deck(m, [hog]), 3600)
        e.reset()
        x, y = eng_xy(3, 17)
        e.inject(hog, x, y, 1, -1.0, 0)
        hp0 = e.get_tower_hp(0, 1)
        for _ in range(8): e.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 10)
        lost_alone = hp0 - e.get_tower_hp(0, 1)
        assert lost_alone > 0, "a Hog at our bridge did no damage to our tower"
        # 2. a Cannon in the middle (our tile 8, 9) pulls it: the tower loses less
        e2 = m.ClashRoyaleEnv(_filler_deck(m, [cannon]), _filler_deck(m, [hog]), 3600)
        e2.reset()
        e2.inject(hog, x, y, 1, -1.0, 0)
        cx, cy = eng_xy(8, 9)
        e2.inject(cannon, cx, cy, 0, -1.0, 0)
        for _ in range(8): e2.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 10)
        lost_pulled = hp0 - e2.get_tower_hp(0, 1)
        assert lost_pulled < lost_alone, "a Cannon in the middle did not pull the Hog"
        # 3. our half is legal for a troop, the river is not
        assert e.is_valid_placement(hog, *eng_xy(3, 12), 0), "our half refused"
        assert not e.is_valid_placement(hog, *eng_xy(5, 15), 0), "the river accepted a troop"
        # 4. copies are independent
        s = e2.snapshot()
        s.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 30)
        assert s.get_current_tick() != e2.get_current_tick(), "the copy is not independent"
        _S["ok"] = True
        if log: log.info(f"Clash Royale: the battle engine passed its self-test (Hog alone -{lost_alone}, "
                         f"pulled by a Cannon -{lost_pulled}) — the bot thinks every move through in it")
    except Exception as ex:
        _S["ok"] = False
        _S["why"] = f"self-test failed: {ex}"
        if log: log.warning(f"Clash Royale: the battle engine is OFF — {_S['why']}")
    return _S["ok"]


def ready():
    return bool(_S["ok"])


# ------------------------------------------------------------------ the mirror
def mirror(brain, st, hand, my_elixir):
    """The arena now, inside the engine. -> (env, {our card name: hand index}) or (None, None)."""
    from royale.brain import card, unit_card
    m = module()
    ids = card_ids()
    deck = [n for n in (brain.deck or []) if n in ids]
    if len(deck) < 8 or any(h not in ids for h in hand if h): return None, None
    their = [n for n in list(brain.enemy_seen) + sorted(brain.predicted) if n in ids][:8]
    env = m.ClashRoyaleEnv(_deck_ids(m, deck), _deck_ids(m, their), 3600)
    env.reset()
    env.set_current_tick(int(min(3599, brain.elapsed() * 10)))
    # towers: fractions of life (the engine's towers are level 9; a fraction is what perception can trust)
    tw = st.get("towers") or {}
    for team, side, slot in ((1, "their_left", 1), (1, "their_right", 2), (0, "our_left", 1), (0, "our_right", 2)):
        f = tw.get(side)
        if f is None: continue
        if f <= 0.01: env.destroy_tower(team, slot)
        elif f < 0.999: env.set_tower_hp(team, slot, f * env.get_tower_max_hp(team, slot))
    # units: grouped per card (a Skeletons card is 3 bodies: 3 skeletons seen = 1 card)
    def put(units, team):
        groups = {}
        for u, x, y, *_ in units:
            cn = unit_card(u) or u
            if cn not in ids: continue
            groups.setdefault(cn, []).append((x, y, u))
        for cn, pts in groups.items():
            per = max(1, (card(cn) or {}).get("count") or 1)
            pts = sorted(pts)
            for k in range(0, len(pts), per):
                chunk = pts[k:k + per]
                gx = sum(p[0] for p in chunk) / len(chunk)
                gy = sum(p[1] for p in chunk) / len(chunk)
                cid = ids[cn][0]
                hp = -1.0
                if team == 1:
                    f = brain.life(chunk[0][2], chunk[0][0], chunk[0][1])
                    mh = _max_hp(m, cid) if f < 0.98 else None
                    if mh: hp = max(1.0, f * mh)
                env.inject(cid, *eng_xy(gx, gy), team, hp, 0)
    allies = getattr(brain, "_allies_extra", None) or st.get("allies") or []
    put(allies, 0)
    put([(u, x, y) for u, x, y in (brain._stable or [])], 1)
    env.set_elixir_for_team(0, float(my_elixir))
    env.set_elixir_for_team(1, float(brain.enemy_elixir or 5.0))
    want = [ids[h][0] for h in hand if h]
    slots = {}
    if len(want) == 4 and env.set_hand_for_team(0, want):
        slots = {h: i for i, h in enumerate(hand) if h}
    else:
        got = env.get_hand_for_team(0)
        slots = {h: got.index(ids[h][0]) for h in hand if h and ids[h][0] in got}
    env.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 1)        # the injected bodies settle onto the board
    return env, slots


# ------------------------------------------------------------------ thinking
def _value(env, brain, before):
    """How good the arena is for us now vs `before` (elixir worth)."""
    from royale.brain import card
    v = 0.0
    for team, sign in ((1, OFFENSE_DISCOUNT), (0, -1.0)):
        for slot in (0, 1, 2):
            mx = max(1, env.get_tower_max_hp(team, slot))
            hp = max(0, env.get_tower_hp(team, slot))
            hp0 = before["towers"][(team, slot)]
            v += sign * TOWER_ELIXIR[slot] * (hp0 - hp) / mx
    army = _army(env)
    v += (before["army"][1] - army[1])          # their units' worth destroyed
    v += 0.35 * (army[0] - before["army"][0])   # ours still standing (a counter-push)
    return v


def _army(env):
    """Elixir-weighted life of each side's units (not towers)."""
    m = module()
    out = [0.0, 0.0]
    for u in env.get_units():
        if u.tower or u.team not in (0, 1): continue
        try: info = m.get_card_info(u.card_id)
        except Exception: continue
        mh = _max_hp(m, u.card_id) or max(1, u.hp)
        out[u.team] += info["cost"] / 3.0 * min(1.0, u.hp / mh)
    return out


def _snap_state(env):
    return {"towers": {(t, s): max(0, env.get_tower_hp(t, s)) for t in (0, 1) for s in (0, 1, 2)},
            "army": _army(env)}


def rollout(env, slot, x, y):
    s = env.snapshot()
    if slot is not None:
        s.step_self_play_fast(slot, x, y, -1, 0.0, 0.0, 10)
        left = ROLLOUT_TICKS - 10
    else:
        left = ROLLOUT_TICKS
    while left > 0:
        r = s.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, min(20, left))
        left -= 20
        if r.done: break
    return s


def candidates(brain, playable, rule_d, defend, first=()):
    """(hand slot, card, our tile) to think through; `first` (the trained AI's move) goes first."""
    from royale.brain import card, roles, THEIR_TOWERS
    from royale import pro
    out = []
    seen = set()

    def add(i, n, t):
        if t is None: return
        t = (int(max(0, min(17, t[0]))), int(max(0, min(31, t[1]))))
        if (n, t) in seen: return
        seen.add((n, t))
        out.append((i, n, t))
    for i, n, t in first: add(i, n, t)
    if rule_d: add(rule_d["slot"], rule_d["card"], rule_d["tile"])
    cards = [(i, n) for i, n in playable] if defend else ([(rule_d["slot"], rule_d["card"])] if rule_d else [])
    enemies = [(x, y) for _u, x, y in (brain._stable or [])]
    for i, n in cards:
        r = roles(n)
        c = card(n) or {}
        try:
            lt = brain._ltile(n, anywhere=bool(c.get("anywhere")))
            if lt: add(i, n, lt[0])
        except Exception:
            pass
        if "spell" in r:
            for ex, ey in enemies[:6]: add(i, n, (ex, ey))
            if not enemies or not defend:
                for s in ("left", "right"): add(i, n, THEIR_TOWERS[s])
            continue
        if defend:
            for ex, ey in enemies[:4]:
                for dx, dy in ((0, -2), (0, -4), (-2, -3), (2, -3), (0, -6)):
                    add(i, n, (ex + dx, min(14, ey + dy)))
            add(i, n, (8, 9)); add(i, n, (9, 9)); add(i, n, (8, 6)); add(i, n, (9, 6))
        else:
            for s in ("left", "right"):
                try:
                    p = pro.place(n, s)
                    if p: add(i, n, p)
                except Exception:
                    pass
            for t in ((3, 14), (14, 14), (3, 4), (14, 4), (8, 0), (9, 0)): add(i, n, t)
    return out


def think(brain, st, hand, playable, my_elixir, rule_d, log=None):
    """-> ("play", slot, card, tile, why) | ("wait", why) | None (no opinion: the brain's move stands)."""
    if not ready() or not playable: return None
    t0 = time.perf_counter()
    try:
        env, slots = mirror(brain, st, hand, my_elixir)
    except Exception as ex:
        if log: log.debug(f"engine mirror failed: {ex}")
        return None
    if env is None: return None
    defend = any(y <= 17 for _u, x, y in (brain._stable or []))
    # the bot's own trained AI (royale.engine_ai): its move on this arena, once a second (its memory steps at 1 Hz)
    first, ai_note = [], ""
    try:
        from royale import engine_ai
        if time.monotonic() - _S.get("ai_t", 0.0) >= 1.0:
            _S["ai_t"] = time.monotonic()
            _S["ai_p"] = engine_ai.propose(env)
        p = _S.get("ai_p")
        if p and p[0] is not None:
            names = {v: k for k, v in slots.items()}
            n = names.get(p[0])
            if n and any(n == m for _i, m in playable):
                i = next(i for i, m in playable if m == n)
                first = [(i, n, (int(round(p[1])), int(round(p[2] - 1))))]
                ai_note = f"; the trained AI wanted {n} at {first[0][2]}"
        elif p:
            ai_note = "; the trained AI wanted to wait"
    except Exception:
        pass
    before = _snap_state(env)
    base = _value(rollout(env, None, 0, 0), brain, before)
    best, tried = None, 0
    ids = card_ids()
    for i, n, (tx, ty) in candidates(brain, playable, rule_d, defend, first):
        hs = slots.get(n)
        if hs is None: continue
        x, y = eng_xy(tx, ty)
        try:
            if not env.is_valid_placement(ids[n][0], x, y, 0): continue
        except Exception:
            continue
        v = _value(rollout(env, hs, x, y), brain, before) - base
        tried += 1
        if best is None or v > best[0]: best = (v, i, n, (tx, ty))
        if time.perf_counter() - t0 > 0.25: break                 # a look must stay fast
    ms = (time.perf_counter() - t0) * 1000
    if best is None: return None
    v, i, n, tile = best
    if defend:
        if v > WAIT_MARGIN:
            return ("play", i, n, tile, f"engine: {n} at {tile} is +{v:.1f} elixir vs waiting "
                                         f"({tried} moves thought through, {ms:.0f} ms{ai_note})")
        return ("wait", f"engine: nothing beats waiting ({tried} moves, best {v:+.1f})")
    if first and not rule_d and best[2] == first[0][1] and v > WAIT_MARGIN:
        return ("play", i, n, tile, f"engine: the trained AI's {n} at {tile} is +{v:.1f} vs waiting{ai_note}")
    if rule_d:
        if v < VETO_MARGIN:
            return ("wait", f"engine: {rule_d['card']} now is {v:+.1f} elixir vs waiting — dropped")
        return ("play", i, n, tile, f"engine: {n} best at {tile} ({v:+.1f} vs waiting, {tried} spots, {ms:.0f} ms{ai_note})")
    return None


def status():
    return {"loaded": _S["mod"] is not None, "ok": _S["ok"], "why": _S["why"], "dir": _dir()}
