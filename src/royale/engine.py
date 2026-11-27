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
THINK_BUDGET = 0.08            # seconds of thinking per look at most (a slow PC thinks through fewer moves, never waits)
ACTION_DELAY_TICKS = 4         # from the screen the decision was made on to the card on the board: ~0.4 s
TOWER_ELIXIR = {0: 18.0, 1: 10.0, 2: 10.0}    # what a whole tower is worth, in elixir (King more: it ends the game)
OFFENSE_DISCOUNT = 0.5         # in a rollout the opponent does not answer: damage we deal counts half
WAIT_MARGIN = 0.4              # a move must beat waiting by this much (elixir)
VETO_MARGIN = -1.0             # the brain's attack is dropped when worse than waiting (prevents bridge leaks)

_S = {"mod": None, "ok": None, "why": "", "ids": None, "maxhp": {}, "bodies": {}, "skips": {}}
OURS_STANDING = 1.0            # our units still standing are worth this much of their elixir (they may still die)


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
    for cid in range(260):
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
        if e and "base" in e: out[n] = (e["base"], e.get("evo"), e.get("hero"))
    _S["ids"] = out
    return out


def eng_xy(tx, ty):
    """The bot's tile (x 0..17, y 0..31 from our back edge) -> the engine's board point (x 0..17, y 0..33: one extra
    row behind each King; cell i covers [i-0.5, i+0.5])."""
    return float(max(0, min(17, tx))), float(max(0.0, min(33.0, ty + 1)))


def level_scale(brain):
    """Our cards' strength vs theirs in the engine (5.85): the engine's cards are level 11; only the DIFFERENCE between
    our levels (official API / card scan) and the opponent's usual level (their battle logs) is applied — +10 % hp
    and damage a level, on our side — so towers keep the engine's own levels. Unknown -> 1.0."""
    try:
        theirs = getattr(brain, "their_level", None)
        lv = [brain.my_level(n) for n in (brain.deck or [])]
        lv = [float(x) for x in lv if x]
        if not lv or not theirs: return 1.0
        d = sum(lv) / len(lv) - float(theirs)
        return float(max(0.6, min(1.8, 1.1 ** d)))
    except Exception:
        return 1.0


def _set_levels(m, ours=1.0, theirs=1.0):
    f = getattr(m, "set_team_level_scale", None)
    if f is None: return False                       # an engine built before 5.85
    f(0, float(ours)); f(1, float(theirs))
    return True


def _max_hp(m, cid):
    """A card's first body's full life at the engine's own level (read once from a scratch engine)."""
    if cid in _S["maxhp"]: return _S["maxhp"][cid]
    hp = None
    g = getattr(m, "get_team_level_scale", None)
    keep = (g(0), g(1)) if g else None
    if keep: _set_levels(m, 1.0, 1.0)
    try:
        e = m.ClashRoyaleEnv(_filler_deck(m, [cid]), _filler_deck(m, []), 3600)
        e.reset()
        before = {u.id for u in e.get_units()}
        e.inject(cid, 8.0, 10.0, 0, -1.0, 0)
        e.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 1)
        new = [u for u in e.get_units() if u.id not in before and not u.tower]
        hp = max((u.hp for u in new), default=None)
        _S["bodies"][cid] = max(1, len(new))
    except Exception:
        hp = None
    finally:
        if keep: _set_levels(m, *keep)
    _S["maxhp"][cid] = hp
    return hp


def _kind_of(m, cid):
    """'special' (Champion / Hero), 'evo' (Evolution) or 'plain' — the engine's deck slots depend on it."""
    k = _S.setdefault("kinds", {})
    if cid not in k:
        try:
            info = m.get_card_info(cid) or {}
            k[cid] = "special" if (info.get("is_champion") or info.get("is_hero")) else \
                ("evo" if info.get("is_evolution") or 123 <= cid <= 163 else "plain")
        except Exception:
            k[cid] = "plain"
    return k[cid]


def _filler_deck(m, want):
    """8 distinct card ids starting with `want`, in slots the engine accepts: a Champion / Hero only in slot 1 or 2,
    an Evolution only in slot 0 or 2 (the real game's rule; before 5.77 an opponent with a Champion made the engine
    refuse the deck and the bot played without thinking: 58 of 69 thoughts lost in one of the user's battles).
    What does not fit is left out (its units are still put on the board)."""
    cards = []
    for c in list(want) + [15, 6, 25, 40, 24, 72, 33, 7, 1, 2, 3, 4, 5, 8, 9, 10, 11, 12]:
        if c is not None and c not in cards: cards.append(c)
    slots = [None] * 8
    special = [c for c in cards[:8] if _kind_of(m, c) == "special"][:2]
    evo = [c for c in cards[:8] if _kind_of(m, c) == "evo"]
    for c, i in zip(special, (1, 2)): slots[i] = c
    for c in evo:
        for i in (0, 2):
            if slots[i] is None: slots[i] = c; break
    used = {x for x in slots if x is not None}
    plain = [c for c in cards if c not in used and _kind_of(m, c) == "plain"]
    for i in range(8):
        if slots[i] is None and plain: slots[i] = plain.pop(0)
    return [c for c in slots if c is not None]


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
        _S["why"] = "no engine module for this Python version"
        if log: log.warning("Clash Royale: battle engine not available — no compiled module for this Python")
        return False
    try:
        ids = card_ids()
        if "hog_rider" not in ids:
            raise KeyError("hog_rider not in card_ids")
        hog, cannon = ids["hog_rider"][0], ids["cannon"][0]
        # 1. an enemy Hog at their side of our left bridge hits our left Princess within 8 s
        e = m.ClashRoyaleEnv(_filler_deck(m, [cannon]), _filler_deck(m, [hog]), 3600)
        e.reset()
        x, y = eng_xy(3, 17)
        e.inject(hog, x, y, 1, -1.0, 0)
        hp0 = e.get_tower_hp(0, 1)
        for _ in range(8): e.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 10)
        lost_alone = hp0 - e.get_tower_hp(0, 1)
        assert lost_alone > 0, f"Hog alone did -{lost_alone} damage (expected > 0)"
        # 2. a Cannon in the middle (our tile 8, 9) pulls it: the tower loses less
        e2 = m.ClashRoyaleEnv(_filler_deck(m, [cannon]), _filler_deck(m, [hog]), 3600)
        e2.reset()
        e2.inject(hog, x, y, 1, -1.0, 0)
        cx, cy = eng_xy(8, 9)
        e2.inject(cannon, cx, cy, 0, -1.0, 0)
        for _ in range(8): e2.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 10)
        lost_pulled = hp0 - e2.get_tower_hp(0, 1)
        assert lost_pulled < lost_alone, f"Cannon pull failed: {lost_pulled} >= {lost_alone}"
        # 3. our half is legal for a troop, the river is not
        assert e.is_valid_placement(hog, *eng_xy(3, 12), 0), "our half refused"
        assert not e.is_valid_placement(hog, *eng_xy(5, 15), 0), "the river accepted a troop"
        # 4. copies are independent
        s = e2.snapshot()
        s.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 30)
        assert s.get_current_tick() != e2.get_current_tick(), "the copy is not independent"
        _S["ok"] = True
        if log: log.info(f"Clash Royale: battle engine passed selftest (Hog alone -{lost_alone:.1f}, pulled -{lost_pulled:.1f})")
    except AssertionError as ex:
        _S["ok"] = False
        _S["why"] = f"assertion failed: {ex}"
        if log: log.warning(f"Clash Royale: engine skipped ({_S['why']})")
    except Exception as ex:
        _S["ok"] = False
        _S["why"] = f"{type(ex).__name__}: {ex}"
        if log: log.warning(f"Clash Royale: engine skipped ({_S['why']})")
    return _S["ok"]


def ready():
    return bool(_S["ok"])


# ------------------------------------------------------------------ the mirror
def mirror(brain, st, hand, my_elixir):
    """The arena now, inside the engine. -> (env, {our card name: hand index}) or (None, None)."""
    from royale.brain import card, unit_card
    m = module()
    ids = card_ids()
    # a blank slot (a card just played, the next one sliding in) or a card the engine lacks no longer stops the
    # thinking (before 5.71 it did, and the engine hardly ever thought: 0.1 ms a moment in the user's reports):
    # the known cards are thought through, the deck is filled up with the hand and plain filler cards
    hand = [h if h in ids else None for h in hand]
    deck = [h for h in hand if h]                                  # the hand first: it must be in the deck
    deck = list(dict.fromkeys(deck + [n for n in (brain.deck or []) if n in ids]))[:8]
    if not any(hand): return None, "no card of the hand is known to the engine"
    their = [n for n in list(brain.enemy_seen) + sorted(brain.predicted) if n in ids][:8]
    _set_levels(m, level_scale(brain), 1.0)                   # our levels vs theirs (5.85)

    def vid(n):
        """Our card as it comes out now (5.86): its Evolution when the evolved picture shows in the hand (charged),
        its Hero version when it is a hero card of ours; else the plain card."""
        base, evo, hero = ids[n]
        look = (getattr(brain, "hand_look", {}) or {}).get(n, "")
        if hero and (n in (getattr(brain, "heroes", set()) or set()) or "hero" in look): return hero
        if evo and "ev1" in look: return evo
        return base
    my_ids = _filler_deck(m, [vid(n) for n in deck])
    env = m.ClashRoyaleEnv(my_ids, _deck_ids(m, their), 3600)
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
            uu = str(u).replace("-", "_")                       # the eyes' names and the big model's ("hog-rider")
            cn = unit_card(u) or unit_card(uu) or uu
            if cn not in ids:
                _S.setdefault("unknown_units", set()).add(str(u))
                continue
            groups.setdefault(cn, []).append((x, y, u))
        for cn, pts in groups.items():
            per = max(1, (card(cn) or {}).get("count") or 1)
            pts = sorted(pts)
            for k in range(0, len(pts), per):
                chunk = pts[k:k + per]
                gx = sum(p[0] for p in chunk) / len(chunk)
                gy = sum(p[1] for p in chunk) / len(chunk)
                cid = ids[cn][0]
                if team == 1 and ids[cn][1]:                      # their unit seen evolved by the big eyes
                    try:
                        if brain.is_evo(chunk[0][2], chunk[0][0], chunk[0][1]): cid = ids[cn][1]
                    except Exception:
                        pass
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
    # 2v2: the engine has one opponent — the one with more elixir is the danger (half the pool, at least)
    el1 = float(brain.enemy_elixir or 5.0)
    if brain.p.get("2v2"): el1 = min(10.0, max(el1 / 2.0, el1 - 10.0))
    env.set_elixir_for_team(1, el1)
    want = [vid(h) if h and h != "blank" else None for h in hand]
    # 6.9.18: a blank slot (a card just played) is filled with another card of the deck, so the REAL hand is still set
    # — before, the engine kept its own shuffled hand and a playable card (the Cannon in the CI check) was sometimes
    # not in it: never thought through, the Hog went undefended
    if len(want) == 4 and any(w is None for w in want):
        spare = [c for c in my_ids if c not in want]
        want = [w if w is not None else (spare.pop(0) if spare else None) for w in want]
    slots = {}
    if len(want) == 4 and None not in want and env.set_hand_for_team(0, want):
        slots = {h: i for i, h in enumerate(hand) if h and h != "blank"}
    else:
        got = env.get_hand_for_team(0)
        slots = {h: got.index(vid(h)) for h in hand if h and vid(h) in got}
    env.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, 1)        # the injected bodies settle onto the board
    return env, slots


# ------------------------------------------------------------------ thinking
def _value(env, brain, before, spent=0.0):
    """How good the arena is for us now vs `before` (elixir worth)."""
    from royale.brain import card
    v = 0.0
    for team, sign in ((1, OFFENSE_DISCOUNT), (0, -1.0)):
        for slot in (0, 1, 2):
            mx = env.get_tower_max_hp(team, slot)
            hp0 = before["towers"][(team, slot)]
            if hp0 <= 0: continue
            if env.get_tower_hp(team, slot) <= 0:
                v += sign * TOWER_ELIXIR[slot]  # losing the last HP also costs a crown
            if mx < 100: continue                      # a destroyed tower (max 0): nothing to count (was +72130)
            hp = max(0, env.get_tower_hp(team, slot))
            v += sign * TOWER_ELIXIR[slot] * max(-1.0, min(1.0, (hp0 - hp) / mx))
    army = _army(env)
    v += before["army"][1] - army[1]                        # their units' worth destroyed
    v += OURS_STANDING * (army[0] - before["army"][0])      # ours still standing (a counter-push), or lost
    v -= spent                                              # the elixir the move cost
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
        per = info["cost"] / float(_S["bodies"].get(u.card_id, 1))     # one body's share of the card
        out[u.team] += per * min(1.0, u.hp / mh)
    return out


def _detail(env, before):
    """For checks: tower life lost per side and each side's army worth now vs before."""
    lost = {t: sum(before["towers"][(t, k)] - max(0, env.get_tower_hp(t, k)) for k in (0, 1, 2)) for t in (0, 1)}
    a = _army(env)
    return {"our_tower_lost": lost[0], "their_tower_lost": lost[1], "army_ours": (round(before["army"][0], 2),
            round(a[0], 2)), "army_theirs": (round(before["army"][1], 2), round(a[1], 2))}


def _snap_state(env):
    return {"towers": {(t, s): max(0, env.get_tower_hp(t, s)) for t in (0, 1) for s in (0, 1, 2)},
            "army": _army(env)}


def compare_rollouts(wait, move, before, cost):
    """Unopposed eight-second projection, in HP and elixir versus waiting."""
    comparison = _detail(move, before)
    idle = _detail(wait, before)
    return {"our_hp_saved": idle["our_tower_lost"] - comparison["our_tower_lost"],
            "extra_enemy_damage": comparison["their_tower_lost"] - idle["their_tower_lost"],
            "elixir_spent": cost,
            "extra_ally_value": round(comparison["army_ours"][1] - idle["army_ours"][1], 2)}


def rollout(env, slot, x, y):
    """The arena run ROLLOUT_TICKS ahead with our move. The move lands ACTION_DELAY_TICKS late, as it does for real
    (the picture the decision was made on is already old and the taps take time; the card then has its own
    deploy second in the engine) — a lesson of FirstLight CR, whose model got markedly better once it played
    with the real game's delay."""
    s = env.snapshot()
    left = ROLLOUT_TICKS
    if slot is not None:
        s.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, ACTION_DELAY_TICKS)
        s.step_self_play_fast(slot, x, y, -1, 0.0, 0.0, 10)
        left -= ACTION_DELAY_TICKS + 10
    while left > 0:
        r = s.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, min(20, left))
        left -= 20
        if r.done: break
    return s


REPLY_TICKS = 15               # the opponent answers our card ~1.5 s after it lands
REPLY_MAX = 3                  # their likeliest answers tried for each of our moves


def replies(brain, name, tx, ty):
    """What the opponent can answer our card with, as the bot counts their hand and elixir: their cards that answer
    it (royale.knowledge ANSWERS_TO) first, then the rest of their hand — each on the spot it would go (a spell on
    our unit; a troop / building on their side of that lane). -> [(engine card id, x, y)] (5.84)."""
    from royale import knowledge as K
    from royale.brain import card, roles
    ids = card_ids()
    el = float(getattr(brain, "enemy_elixir", 0) or 0)
    observed = set(getattr(brain, "enemy_seen", ()) or ())
    known = observed | set(getattr(brain, "predicted", ()) or ())
    recent = list(getattr(brain, "enemy_cycle", ()))[-4:]
    if (len(observed) == 8 and len(set(recent)) == 4 and set(recent) <= observed
            and not brain.p.get("2v2") and "mirror" not in observed
            and all(c in ids and not module().get_card_info(ids[c][0]).get("is_champion") for c in observed)):
        # Only exclude cards when the standard four-card cycle is observed.
        available = observed - set(recent)
    else:
        available = known
    hand = brain.their_hand() or ()
    pool = ([c for c in K.ANSWERS_TO.get(name, []) if c in available]
            + sorted(set(hand) & available) + sorted(available))
    out, seen = [], set()
    for c in pool:
        if c in seen or c not in ids: continue
        seen.add(c)
        if (card(c) or {}).get("cost", 9) > el + 0.5: continue
        r = roles(c)
        if "spell" in r: p = (tx, ty)
        elif "building" in r: p = (8 if tx < 9 else 9, 22)
        else: p = (tx, max(17, min(ty + 2, 26)))
        out.append((ids[c][0], *eng_xy(*p)))
        if len(out) >= REPLY_MAX: break
    return out


def rollout_reply(env, slot, x, y, reply):
    """Like rollout(), and the opponent answers with `reply` (card id, x, y) REPLY_TICKS after our card."""
    s = env.snapshot()
    s.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, ACTION_DELAY_TICKS)
    s.step_self_play_fast(slot, x, y, -1, 0.0, 0.0, REPLY_TICKS)
    try: s.inject(reply[0], reply[1], reply[2], 1, -1.0, 0)
    except Exception: return None
    left = ROLLOUT_TICKS - ACTION_DELAY_TICKS - REPLY_TICKS
    while left > 0:
        r = s.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, min(20, left))
        left -= 20
        if r.done: break
    return s


def candidates(brain, playable, rule_d, defend, first=()):
    """(hand slot, card, our tile) to think through; `first` (the trained AI's move) goes first."""
    from royale.brain import card, roles, pull_spot, unit_card, SPELL_SPLASH_DEFAULT, THEIR_TOWERS
    from royale import pro
    out = []
    seen = set()

    def add(i, n, t):
        if t is None: return
        t = (int(max(0, min(17, t[0]))), int(max(0, min(31, t[1]))))
        if (n, t) in seen: return
        seen.add((n, t))
        out.append((i, n, t))
    if rule_d: add(rule_d["slot"], rule_d["card"], rule_d["tile"])
    if brain.p.get("ai_only"):
        return out
    for i, n, t in first: add(i, n, t)
    priority_count = len(out)
    cards = [(i, n) for i, n in playable] if defend else ([(rule_d["slot"], rule_d["card"])] if rule_d else [])
    enemies = [(x, y) for _u, x, y in (brain._stable or [])]
    # 6.9.18: the tiles where a card HELD against this threat before (our battles + the opponents' answers to us)
    try:
        th = brain.threats(brain._stable or []) if getattr(brain, "mem", None) else {}
        for side, t_ in th.items():
            if not t_.get("main"): continue
            for i, n in cards:
                for tile, _rate, _n in brain.mem.best_tiles(t_["main"], n, side, k=2):
                    add(i, n, tile)
    except Exception:
        pass
    if defend and brain.p.get("pro_moves", True):
        # Replay placements add candidates. Current legality, elixir and simulated
        # tower outcomes still decide which move is worth playing.
        playable_names = [name for _, name in cards]
        for unit, x, y in (brain._stable or [])[:4]:
            threat = unit_card(unit)
            if not threat:
                continue
            side = "left" if x < 9 else "right"
            observed = pro.answer(threat, y, side, playable_names)
            for i, name in cards:
                if observed.get(name, 0) >= 0.025:
                    for tile in pro.answer_tiles(threat, y, side, name):
                        if brain.legal(*tile, name):
                            add(i, name, tile)
    for i, n in cards:
        r = roles(n)
        c = card(n) or {}
        try:
            lt = brain._ltile(n, anywhere=bool(c.get("anywhere")))
            if lt: add(i, n, lt[0])
        except Exception:
            pass
        if "spell" in r:
            targets = enemies[:6]
            radius = c.get("splash") or SPELL_SPLASH_DEFAULT.get(n, 0)
            for j, (ex, ey) in enumerate(targets):
                add(i, n, (ex, ey))
                for x, y in targets[:j]:
                    if radius < math.hypot(x - ex, y - ey) <= 2 * radius:
                        add(i, n, (round((x + ex) / 2), round((y + ey) / 2)))
            if not enemies or not defend:
                for s in ("left", "right"): add(i, n, THEIR_TOWERS[s])
            continue
        if defend:
            if "building" in r:
                for threat, ex, ey in (brain._stable or [])[:4]:
                    add(i, n, pull_spot("left" if ex < 9 else "right", threat))
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
    if not defend:
        return out
    # Search every usable defensive card before refining the position of one.
    # A crowded lane can otherwise spend the whole frame budget on slot 0.
    by_card = {}
    for candidate in out[priority_count:]:
        by_card.setdefault(candidate[1], []).append(candidate)
    from itertools import zip_longest
    return out[:priority_count] + [candidate for row in zip_longest(*by_card.values())
                                   for candidate in row if candidate is not None]


def _skip(why):
    """Counted per battle (the perf report says why the engine did not think)."""
    _S["skips"][why] = _S["skips"].get(why, 0) + 1
    return None


def new_battle():
    _S["skips"] = {}
    _S["last_error"] = ""
    for k in ("last", "ai_t", "ai_p"):
        _S.pop(k, None)


def skips():
    out = dict(_S["skips"])
    if _S.get("last_error"): out["last_error"] = _S["last_error"]
    return out


def _early_rush(brain, env, waiting, before):
    """Open the defensive search before the bridge if waiting exposes a tower."""
    from royale.brain import card, unit_card

    rush = any(17 < y <= 21 and card(unit_card(unit) or "").get("buildings_only")
               for unit, _, y in (brain._stable or []))
    if not rush:
        return False
    for slot in (0, 1, 2):
        start_hp = before["towers"][(0, slot)]
        remaining = max(0, waiting.get_tower_hp(0, slot))
        if start_hp > 0 and (remaining == 0 or start_hp - remaining >= 0.08 * env.get_tower_max_hp(0, slot)):
            return True
    return False


def think(brain, st, hand, playable, my_elixir, rule_d, log=None):
    """-> ("play", slot, card, tile, why) | ("wait", why) | None (no opinion: the brain's move stands)."""
    if not ready(): return _skip("engine off")
    if not playable: return _skip("no card ready")
    ai_only = bool(brain.p.get("ai_only"))
    if ai_only and not rule_d:
        return None
    t0 = time.perf_counter()
    try:
        env, slots = mirror(brain, st, hand, my_elixir)
    except Exception as ex:
        if log and _S["skips"].get("mirror error", 0) < 3: log.warning(f"Clash Royale: engine mirror failed: {ex!r}")
        import traceback
        _S["last_error"] = traceback.format_exc(limit=4)[-600:]
        return _skip("mirror error")
    if env is None: return _skip(slots or "mirror refused")
    _S["skips"]["thought"] = _S["skips"].get("thought", 0) + 1
    defend = any(y <= 17 for _u, x, y in (brain._stable or []))
    # the bot's own trained AI (royale.engine_ai): its move on this arena, once a second (its memory steps at 1 Hz)
    first, ai_note = [], ""
    try:
        from royale import engine_ai
        if not ai_only and time.monotonic() - _S.get("ai_t", 0.0) >= 1.0:
            _S["ai_t"] = time.monotonic()
            _S["ai_p"] = engine_ai.propose(env)
        p = None if ai_only else _S.get("ai_p")
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
    try:
        pol = getattr(brain, "_pol", None)
        if pol and pol.get("cards") and not brain.p.get("ai_only"):
            names = dict((m, i) for i, m in playable)
            for n, pr in sorted(pol["cards"].items(), key=lambda kv: -kv[1])[:3]:
                if n not in names or pr < 0.08: continue
                lt = brain._ltile(n, anywhere=bool((__import__("royale.brain", fromlist=["card"]).card(n)
                                                      or {}).get("anywhere")))
                if lt: first.append((names[n], n, (int(lt[0][0]), int(lt[0][1]))))
    except Exception:
        pass
    before = _snap_state(env)
    w_end = rollout(env, None, 0, 0)
    early_rush = not defend and not ai_only and _early_rush(brain, env, w_end, before)
    defend = defend or early_rush
    base = _value(w_end, brain, before)
    if _S.get("debug") is not None:
        _S["debug"].append(("wait", round(base, 2), _detail(w_end, before)))
    best, tried, scored, rule_v = None, 0, [], None
    m = module()
    native_hand = env.get_hand_for_team(0)
    winning_rollout = None
    waiting_hp = sum(max(0, w_end.get_tower_hp(0, slot)) for slot in (0, 1, 2)) if early_rush else None
    for i, n, (tx, ty) in candidates(brain, playable, rule_d, defend, first):
        hs = slots.get(n)
        if hs is None: continue
        x, y = eng_xy(tx, ty)
        cid = native_hand[hs]
        try:
            if not env.is_valid_placement(cid, x, y, 0): continue
            cost = float(m.get_card_info(cid)["cost"])
        except Exception:
            continue
        if cost > my_elixir: continue
        end = rollout(env, hs, x, y)
        v = _value(end, brain, before, cost) - base
        # the opponent answers (5.84): a move is only as good as it stays after their likeliest answers — half the
        # worst case, half the average (they do not always find the best answer)
        vs = [v]
        # only for an attack (a card for their half, nothing of theirs on ours): a defense is judged on the threat
        # in front of it — "what if they send more" made every defense look worse than waiting (5.87: the Giant push
        # went undefended in the engine test)
        if not defend and ty >= 13 and time.perf_counter() - t0 < THINK_BUDGET * 0.75:
            for rp in replies(brain, n, tx, ty):
                e2 = rollout_reply(env, hs, x, y, rp)
                if e2 is not None: vs.append(_value(e2, brain, before, cost) - base)
        if len(vs) > 1: v = 0.5 * min(vs) + 0.5 * sum(vs) / len(vs)
        # the card's preferences as a cost, not a ban (6.7, royale.card_use): the engine may still pick a building
        # before a push or a Log for small value when the battle clearly says so
        try:
            from royale import card_use
            pen, _why = card_use.penalty(brain, n, (tx, ty))
            v -= pen
        except Exception:
            pass
        tried += 1
        scored.append({"card": n, "tile": [tx, ty], "v": round(v, 2)})
        if _S.get("debug") is not None:
            _S["debug"].append((round(v, 2), n, (tx, ty), _detail(end, before)))
        saves_hp = waiting_hp is None or sum(max(0, end.get_tower_hp(0, slot)) for slot in (0, 1, 2)) > waiting_hp
        if saves_hp and (best is None or v > best[0]):
            best = (v, i, n, (tx, ty))
            winning_rollout = end, cost
        if rule_d and n == rule_d["card"] and (tx, ty) == tuple(rule_d["tile"]): rule_v = v
        if time.perf_counter() - t0 > THINK_BUDGET: break         # a look must stay fast
    ms = (time.perf_counter() - t0) * 1000
    # what was thought through, for the app's battle view (royale.live_view)
    _S["last"] = {"t": time.time(), "seen_t": st.get("_seen_t"), "defend": defend, "wait": round(base, 2), "ms": round(ms),
                  "tried": tried, "ai": ai_note.strip("; "),
                  "cands": sorted(scored, key=lambda c: -c["v"])[:24]}
    if best is None: return None
    v, i, n, tile = best
    comparison = compare_rollouts(w_end, winning_rollout[0], before, winning_rollout[1])
    _S["last"]["best"] = {"card": n, "tile": list(tile), "comparison": comparison}
    if defend:
        if v > WAIT_MARGIN:
            prefix = "early defense" if early_rush else "engine"
            return ("play", i, n, tile, f"{prefix}: {n} at {tile} is +{v:.1f} elixir vs waiting "
                                         f"({tried} moves thought through, {ms:.0f} ms{ai_note})")
        # nothing clearly better than waiting: the brain's own move stands unless the engine finds it clearly bad
        # (before 5.69 the engine cancelled it and the bot looked slow and hesitant)
        if rule_d and (rule_v is None or rule_v >= VETO_MARGIN): return None
        return ("wait", f"engine: nothing beats waiting ({tried} moves, best {v:+.1f})")
    if first and not rule_d and any(best[2] == f[1] for f in first) and v > WAIT_MARGIN:
        return ("play", i, n, tile, f"AI: {n} at {tile}, checked in the engine +{v:.1f} vs waiting{ai_note}")
    if rule_d:
        if v < VETO_MARGIN or (not ai_only and tile[1] >= 13 and v < 0.0 and brain.elapsed() < 15.0):
            return ("wait", f"engine: {rule_d['card']} now is {v:+.1f} elixir vs waiting — dropped")
        return ("play", i, n, tile, f"engine: {n} best at {tile} ({v:+.1f} vs waiting, {tried} spots, {ms:.0f} ms{ai_note})")
    return None


def status():
    return {"loaded": _S["mod"] is not None, "ok": _S["ok"], "why": _S["why"], "dir": _dir()}
