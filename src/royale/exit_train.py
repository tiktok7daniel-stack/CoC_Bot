"""
Expert Iteration (the AlphaGo Zero idea) for the bot's arena brain (royale.board_net, the Transformer that sees the
whole arena): it stops only IMITATING the pros and learns what actually WINS.

  1. play     the battle engine (royale.engine, ClashRoyaleEnv) plays whole battles: the account's deck against the
              16 ladder decks of python_ai (RoyaleAPI archetypes); both sides are piloted by the brain + search
  2. search   at every decision every playable card is tried on the brain's best tiles and on the spots the moment
              calls for (on the threat, the bridges, their towers) and the arena is run 6 s ahead for each — the
              moves that really came out best (towers, army, elixir) are the answer
  3. learn    the brain is trained on those answers on this PC's NVIDIA card (CPU if none), starting from what it
              learned from 252k pro games (assets/royale/board_weights.npz) and never drifting far from it
  4. gate     the new brain plays the one in use (no search, brain against brain, both decks on both sides): it
              replaces it only when it wins 55 %+; then royale.board loads it in the next battle

Runs in its own low-priority process (python -m royale.exit_train), paused while the bot plays a battle
(royale.engine_ai.pause_background), resumes where it stopped. Progress: ~/.CoC_Bot/royale_ai/exit/progress.json
"""
import json, math, os, random, sys, time
from pathlib import Path

HOME = Path.home() / ".CoC_Bot" / "royale_ai" / "exit"
DECIDE = 10                 # a decision every second (10 ticks)
ROLL = 100                  # each move is looked at 10 s ahead
STAND = 1.0                 # our army still standing keeps its worth (a card just placed is not a loss)
PRESSURE = 0.25             # elixir per unit of ours on their half at the end (pressure on their towers)
DELAY = 3                   # a move lands a moment late, as in the real game
TAU = 1.0                   # elixir: how sharp the search's answer is
GATE_WIN = 0.55


def _root():
    return Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ the engine and the brain's vocabulary
class Ctx:
    def __init__(self, model_path=None):
        from royale import engine, board
        self.E = engine
        self.m = engine.module()
        if self.m is None: raise RuntimeError("the battle engine is not built for this Python")
        engine.selftest()
        self.ids = engine.card_ids()                                     # our name -> (base, evo, hero)
        self.names = {}
        for n, t in self.ids.items():
            for c in t:
                if c is not None: self.names.setdefault(c, n)
        meta = json.loads((_root() / "assets" / "royale" / "board.json").read_text(encoding="utf-8"))
        self.vocab = meta["vocab"]
        self.key = board.key
        self.sess = None
        self.model_path = model_path or str(_root() / "assets" / "royale" / "board.onnx")
        self.load(self.model_path)

    def load(self, path):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        self.sess = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
        self.model_path = str(path)

    def vid(self, name):
        return self.vocab.get(self.key(name), 1)

    def deck_ids(self, names):
        return self.E._deck_ids(self.m, [n for n in names if n in self.ids])

    def meta_decks(self):
        p = _root() / "third_party" / "clash_royale_env" / "python_ai" / "opponents" / "decks" / "meta_decks.json"
        out = []
        try:
            by = {self.E._k(n): n for n in self.ids}
            for d in json.loads(p.read_text(encoding="utf-8")).get("decks", []):
                if not d.get("enabled", True): continue
                names = [by.get(self.E._k(c)) for c in d.get("cards", [])]
                names = [n for n in names if n]
                if len(names) >= 6: out.append((d.get("name", "?"), names))
        except Exception:
            pass
        return out or [("hog", ["hog_rider", "musketeer", "cannon", "ice_golem", "skeletons", "ice_spirit",
                                "fireball", "the_log"])]


# ------------------------------------------------------------------ the arena as the brain sees it (one side's view)
def inputs(cx, env, team, first):
    from royale import board_net as B
    tick = env.get_current_tick()
    rows = []
    for u in env.get_units():
        if u.tower or u.team not in (0, 1): continue
        n = cx.names.get(u.card_id)
        if not n: continue
        fs = first.setdefault(u.id, tick)
        mh = cx.E._max_hp(cx.m, u.card_id) or max(1.0, u.hp)
        if team == 0: x, y = u.x + 0.5, u.y - 0.5
        else: x, y = 17.5 - u.x, 32.5 - u.y
        rows.append((u.team == team, n, x, y, min(1.0, max(0.0, u.hp / mh)), bool(u.flying), bool(u.building),
                     u.deploy_ticks > 0, (tick - fs) / 10.0))
    tok, ids = B.tokens(rows, cx.vocab, cx.key)

    def f(t, s):
        try: return max(0.0, min(1.0, env.get_tower_hp(t, s) / max(1.0, env.get_tower_max_hp(t, s))))
        except Exception: return 1.0
    o = 1 - team
    ours = [f(team, 1), f(team, 2)] if team == 0 else [f(team, 2), f(team, 1)]
    theirs = [f(o, 1), f(o, 2)] if team == 0 else [f(o, 2), f(o, 1)]
    t = tick / 10.0
    glob = [min(t, 300) / 300.0, 1.0 if t >= 120 else 0.0, 1.0 if t >= 180 else 0.0,
            env.get_elixir_for_team(team) / 10.0, env.get_elixir_for_team(o) / 10.0] + ours + [1.0] + theirs + [1.0]
    hand = [cx.names.get(c) for c in env.get_hand_for_team(team)]
    hd = sorted(cx.vid(n) for n in hand if n)[:4]
    hd += [0] * (4 - len(hd))
    return {"glob": glob, "tok": tok, "tokid": ids, "hand": hd}, hand


def _run(cx, inp, cand=0):
    import numpy as np
    return cx.sess.run(None, {"glob": np.asarray([inp["glob"]], np.float32), "tok": np.asarray([inp["tok"]], np.float32),
                              "tokid": np.asarray([inp["tokid"]], np.int64), "hand": np.asarray([inp["hand"]], np.int64),
                              "cand": np.asarray([cand], np.int64)})


def eng_point(team, tx, ty):
    return (float(tx), float(ty + 1)) if team == 0 else (float(17 - tx), float(32 - ty))


def _top_tiles(cx, inp, name, k, anywhere):
    import numpy as np
    _p, _c, t = _run(cx, inp, cx.vid(name))
    v = t[0].astype(float)
    if not anywhere: v[15 * 18:] = -1e9
    order = np.argsort(-v)[:40]
    return [(int(i % 18), int(i // 18)) for i in order][:k * 4]


def _playable(cx, env, team, hand):
    el = env.get_elixir_for_team(team)
    out = []
    native_hand = env.get_hand_for_team(team)
    for slot, n in enumerate(hand):
        if not n: continue
        try: cost = (cx.m.get_card_info(native_hand[slot]) or {}).get("cost", 11)
        except Exception: continue
        if cost <= el + 1e-6: out.append((slot, n, float(cost)))
    return out


def _valid(env, team, slot, tile):
    x, y = eng_point(team, *tile)
    try: return env.is_valid_placement(env.get_hand_for_team(team)[slot], x, y, team)
    except Exception: return False


def candidates(cx, env, team, inp, hand, per_card=3, replay_placements=False, replay_atlas=None):
    """(slot, card, tile in the side's own view) worth looking at."""
    from royale import pro
    from royale.brain import card, roles
    out = []
    enemies = []
    named_threats = []
    for u in env.get_units():
        if u.tower or u.team in (team,) or u.team not in (0, 1): continue
        x, y = (u.x, u.y - 1) if team == 0 else (17 - u.x, 32 - u.y)
        enemies.append((int(round(x)), int(round(y))))
        name = cx.names.get(u.card_id)
        if replay_placements and name and y <= 19:
            named_threats.append((name, x, y))
    named_threats.sort(key=lambda threat: threat[2])
    enemies.sort(key=lambda p: p[1])
    for slot, n, _cost in _playable(cx, env, team, hand):
        c = card(n) or {}
        anywhere = bool(c.get("anywhere")) or "spell" in roles(n)
        tiles = []
        for t in _top_tiles(cx, inp, n, per_card, anywhere):
            if len(tiles) >= per_card: break
            if _valid(env, team, slot, t): tiles.append(t)
        extra = []
        if "spell" in roles(n): extra += enemies[:2] + [(3, 26), (14, 26)]
        elif enemies and enemies[0][1] <= 17:
            ex, ey = enemies[0]
            extra += [(ex, max(1, min(14, ey - 2))), (8 if ex < 9 else 9, 9)]
        else:
            extra += [(3, 13), (14, 13)]
        for t in extra:
            if t not in tiles and len(tiles) < per_card + 2 and _valid(env, team, slot, t): tiles.append(t)
        if replay_placements:
            learned = []
            for threat, x, y in named_threats[:2]:
                side = "left" if x < 9 else "right"
                if pro.answer(threat, y, side, [n]).get(n, 0) >= 0.025:
                    learned.extend(pro.answer_tiles(threat, y, side, n)[:2])
                if replay_atlas:
                    recorded = replay_atlas.get((pro.key(threat), int(y) // 4, pro.key(n)), ())
                    learned.extend((tx if side == "left" else 17 - tx, ty) for tx, ty in recorded)
            if not named_threats:
                learned.extend(t for side in ("left", "right") if (t := pro.place(n, side)) is not None)
            for t in learned:
                if t not in tiles and _valid(env, team, slot, t):
                    tiles.append(t)
        out += [(slot, n, t) for t in tiles]
    return out


# ------------------------------------------------------------------ search
def _value(cx, env, team, before, spent):
    E = cx.E
    v = 0.0
    o = 1 - team
    for t, sign in ((o, E.OFFENSE_DISCOUNT), (team, -1.0)):
        for s in (0, 1, 2):
            mx = env.get_tower_max_hp(t, s)
            if mx < 100: continue                      # destroyed (max 0)
            v += sign * E.TOWER_ELIXIR[s] * max(-1.0, min(1.0, (before["towers"][(t, s)] - max(0, env.get_tower_hp(t, s))) / mx))
    army = E._army(env)
    v += before["army"][o] - army[o]
    v += STAND * (army[team] - before["army"][team])
    for u in env.get_units():                       # pressure: ours across the river
        if u.tower or u.team != team: continue
        if (u.y > 17 if team == 0 else u.y < 16): v += PRESSURE
    return v - spent


def _leak(env, team, spent):
    """Elixir that would overflow (wasted) during the look-ahead after spending `spent`."""
    el = env.get_elixir_for_team(team) - spent
    t = env.get_current_tick() / 10.0
    gain = (ROLL / 10.0) / (1.4 if t >= 120 else 2.8)
    return max(0.0, el + gain - 10.0)


REPLY_AFTER = 15            # the opponent answers ~1.5 s after our card lands
REPLIES = 2                 # their likeliest answers tried for every move (5.84)


def _act(s, team, slot, x, y, ticks):
    if team == 0: return s.step_self_play_fast(slot, x, y, -1, 0.0, 0.0, ticks)
    return s.step_self_play_fast(-1, 0.0, 0.0, slot, x, s.BOARD_HEIGHT - 1 - y, ticks)


def _rollout(env, team, act, reply=None):
    """`reply`: (slot, x, y) the OTHER side plays REPLY_AFTER ticks after our card."""
    s = env.snapshot()
    left = ROLL
    if act is not None:
        slot, x, y = act
        s.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, DELAY)
        if reply is None:
            _act(s, team, slot, x, y, 5)
            left -= DELAY + 5
        else:
            _act(s, team, slot, x, y, REPLY_AFTER)
            _act(s, 1 - team, reply[0], reply[1], reply[2], 5)
            left -= DELAY + REPLY_AFTER + 5
    while left > 0:
        r = s.step_self_play_fast(-1, 0.0, 0.0, -1, 0.0, 0.0, min(20, left))
        left -= 20
        if r.done: break
    return s


def search(cx, env, team, cands, prioritize_counters=False):
    """-> [(value vs waiting, slot, card, tile)] (wait = (0, None, None, None) first)."""
    from royale.brain import roles
    from royale.knowledge import ANSWERS_TO

    E = cx.E
    before = E._snap_state(env)
    base = _value(cx, _rollout(env, team, None), team, before, 0.0) - _leak(env, team, 0.0)
    out = [(0.0, None, None, None)]
    o = 1 - team
    their = _playable(cx, env, o, [cx.names.get(c) for c in env.get_hand_for_team(o)])
    native_hand = env.get_hand_for_team(team)
    for slot, n, tile in cands:
        cost = float(cx.m.get_card_info(native_hand[slot])["cost"])
        pt = eng_point(team, *tile)
        end = _rollout(env, team, (slot, *pt))
        v = _value(cx, end, team, before, cost) - _leak(env, team, cost) - base
        # the opponent answers with the cards really in their hand (5.84): half the worst, half the average
        vs = [v]
        otile = (17 - tile[0], 31 - tile[1])                   # our card's tile as THEY see it
        replies = their
        if prioritize_counters:
            rank = {name: index for index, name in enumerate(ANSWERS_TO.get(n, ()))}
            replies = sorted(their, key=lambda action: rank.get(action[1], len(rank)))
        tested = 0
        for oslot, on, _oc in replies if prioritize_counters else replies[:REPLIES]:
            if "spell" in roles(on): t2 = otile
            else: t2 = (otile[0], max(1, min(14, otile[1] - 2)))
            if not _valid(env, o, oslot, t2): continue
            e2 = _rollout(env, team, (slot, *pt), (oslot, *eng_point(o, *t2)))
            vs.append(_value(cx, e2, team, before, cost) - _leak(env, team, cost) - base)
            tested += 1
            if tested == REPLIES:
                break
        if len(vs) > 1: v = 0.5 * min(vs) + 0.5 * sum(vs) / len(vs)
        out.append((v, slot, n, tile))
    return out


def label(cx, res):
    """The search's answer as training targets: play / wait, which card, which tile (soft, by value)."""
    vs = [r[0] for r in res]
    mx = max(vs)
    w = [math.exp((v - mx) / TAU) for v in vs]
    z = sum(w)
    p = [x / z for x in w]
    play_t = 1.0 - p[0]
    cards, tiles = {}, {}
    for pr, (_v, _s, n, t) in zip(p[1:], res[1:]):
        cards[n] = cards.get(n, 0.0) + pr
    best = max(range(1, len(res)), key=lambda i: res[i][0]) if len(res) > 1 else None
    tile_card, tile_t = 0, {}
    if best is not None:
        bn = res[best][2]
        tile_card = cx.vid(bn)
        sub = [(pr, t) for pr, (_v, _s, n, t) in zip(p[1:], res[1:]) if n == bn]
        zz = sum(pr for pr, _t in sub) or 1.0
        for pr, (tx, ty) in sub:
            tile_t[ty * 18 + tx] = tile_t.get(ty * 18 + tx, 0.0) + pr / zz
    zc = sum(cards.values()) or 1.0
    return play_t, {cx.vid(n): v / zc for n, v in cards.items()}, tile_card, tile_t, p


# ------------------------------------------------------------------ the brain alone (no search): for the gate
def net_move(cx, env, team, inp, hand):
    import numpy as np
    play, card_l, _t = _run(cx, inp)
    if 1 / (1 + math.exp(-float(play[0]))) < 0.5: return None
    pl = _playable(cx, env, team, hand)
    if not pl: return None
    from royale.brain import card, roles
    for slot, n, _c in sorted(pl, key=lambda q: -float(card_l[0][cx.vid(q[1])])):
        anywhere = bool((card(n) or {}).get("anywhere")) or "spell" in roles(n)
        for t in _top_tiles(cx, inp, n, 3, anywhere)[:12]:
            if _valid(env, team, slot, t): return slot, n, t
    return None


# ------------------------------------------------------------------ one battle
def _winner(env):
    a = [env.get_towers_alive(t) for t in (0, 1)]
    if a[0] != a[1]: return 0 if a[0] > a[1] else 1
    hp = [sum(max(0, env.get_tower_hp(t, s)) / max(1, env.get_tower_max_hp(t, s)) for s in (0, 1, 2)) for t in (0, 1)]
    if abs(hp[0] - hp[1]) < 0.02: return None
    return 0 if hp[0] > hp[1] else 1


def battle(cx, decks, pilots, record=True, explore=0.15, max_ticks=1800, seed=None, trace=None, decision_ms=None, replay_atlases=(None, None)):
    """decks: (ids team 0, ids team 1); pilots: each side uses "search", "search-replay", "search-counters", or a policy Ctx.
    -> (samples, winner, stats)"""
    rnd = random.Random(seed)
    env = cx.m.ClashRoyaleEnv(decks[0], decks[1], 3600)
    if seed is not None:
        try: env.seed(int(seed))
        except Exception: pass
    env.reset()
    first = {}
    samples = []
    n_search = n_moves = 0
    t0 = time.perf_counter()
    while env.get_current_tick() < max_ticks:
        acts = [None, None]
        for team in (0, 1):
            decision_start = time.perf_counter() if decision_ms is not None else None
            try:
                pilot = pilots[team]
                uses_search = pilot in ("search", "search-replay", "search-counters")
                inp, hand = inputs(cx if uses_search else pilot, env, team, first)
                if uses_search:
                    if not _playable(cx, env, team, hand): continue
                    cands = candidates(cx, env, team, inp, hand, replay_placements=pilot != "search",
                                       replay_atlas=replay_atlases[team])
                    if not cands: continue
                    res = search(cx, env, team, cands, prioritize_counters=pilot == "search-counters")
                    n_search += 1
                    play_t, card_t, tile_card, tile_t, p = label(cx, res)
                    if record:
                        samples.append((inp, play_t, card_t, tile_card, tile_t))
                    explored = rnd.random() < explore
                    if explored:
                        k = rnd.choices(range(len(res)), weights=p)[0]
                    else:
                        k = max(range(len(res)), key=lambda i: res[i][0])
                    if res[k][1] is not None and (explored or res[k][0] > 0.0):
                        acts[team] = (res[k][1], *eng_point(team, *res[k][3]))
                else:
                    mv = net_move(pilot, env, team, inp, hand)
                    if mv: acts[team] = (mv[0], *eng_point(team, *mv[2]))
                if acts[team]: n_moves += 1
            finally:
                if decision_start is not None:
                    decision_ms[team].append((time.perf_counter() - decision_start) * 1000)
        a0 = acts[0] or (-1, 0.0, 0.0)
        a1 = acts[1] or (-1, 0.0, 0.0)
        # Placement checks use world coordinates. Self-play accepts team 1's
        # local Y and converts it back internally; X stays in world coordinates.
        if trace is not None and any(acts):
            trace.append({"tick": env.get_current_tick(), "plays": [
                None if action is None else {"card": cx.names.get(env.get_hand_for_team(team)[action[0]]),
                                             "world_x": action[1], "world_y": action[2]}
                for team, action in enumerate(acts)],
                "elixir": [round(env.get_elixir_for_team(team), 2) for team in (0, 1)],
                "tower_hp": [[env.get_tower_hp(team, slot) for slot in range(3)] for team in (0, 1)]})
        y1 = env.BOARD_HEIGHT - 1 - a1[2]
        r = env.step_self_play_fast(a0[0], a0[1], a0[2], a1[0], a1[1], y1, DECIDE)
        if r.done: break
    stats = {"ticks": env.get_current_tick(), "searches": n_search, "moves": n_moves,
             "s": round(time.perf_counter() - t0, 1), "towers": [env.get_towers_alive(t) for t in (0, 1)]}
    return samples, _winner(env), stats


def _worker(args):
    """One process: a few battles with search on both sides -> samples (as plain lists)."""
    games, seed, model_path, my_deck, max_ticks = args
    cx = Ctx(model_path)
    rnd = random.Random(seed)
    metas = cx.meta_decks()
    out, stats = [], []
    for g in range(games):
        if rnd.random() < 0.4:                            # the deck against ITSELF: it meets its own plans and
            mname, mdeck = "mirror", list(my_deck)        # finds its own weaknesses (the user's idea, 5.93)
        else:
            mname, mdeck = rnd.choice(metas)
        d = [cx.deck_ids(my_deck), cx.deck_ids(mdeck)]
        if rnd.random() < 0.5: d = d[::-1]
        s, w, st = battle(cx, d, ["search", "search"], seed=seed * 1000 + g, max_ticks=max_ticks)
        out += s
        st["vs"] = mname
        stats.append(st)
    return out, stats


# ------------------------------------------------------------------ learning
def _arrays(samples):
    import numpy as np
    n = len(samples)
    G = np.zeros((n, 11), np.float32); T = np.zeros((n, 24, 8), np.float32); I = np.zeros((n, 24), np.int64)
    H = np.zeros((n, 4), np.int64); P = np.zeros(n, np.float32)
    CI = np.zeros((n, 4), np.int64); CP = np.zeros((n, 4), np.float32)
    TC = np.zeros(n, np.int64); TI = np.zeros((n, 6), np.int64); TP = np.zeros((n, 6), np.float32)
    for k, (inp, play_t, card_t, tile_card, tile_t) in enumerate(samples):
        G[k] = inp["glob"]; T[k] = inp["tok"]; I[k] = inp["tokid"]; H[k] = inp["hand"]; P[k] = play_t
        for j, (c, p) in enumerate(sorted(card_t.items(), key=lambda kv: -kv[1])[:4]): CI[k, j], CP[k, j] = c, p
        TC[k] = tile_card
        for j, (t, p) in enumerate(sorted(tile_t.items(), key=lambda kv: -kv[1])[:6]): TI[k, j], TP[k, j] = t, p
    return dict(G=G, T=T, I=I, H=H, P=P, CI=CI, CP=CP, TC=TC, TI=TI, TP=TP)


def _buffer_add(arr, keep=300_000):
    import numpy as np
    p = HOME / "buffer.npz"
    if p.exists():
        try:
            old = dict(np.load(p))
            arr = {k: np.concatenate([old[k], arr[k]])[-keep:] for k in arr}
        except Exception:
            pass
    HOME.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(HOME / "buffer_tmp.npz", **arr)
    os.replace(HOME / "buffer_tmp.npz", p)
    return arr


def train(arr, start_npz, out_base, epochs=2, lr=1e-4, batch=256, log=print):
    import numpy as np, torch
    from royale import board_net as B
    V = int(max(json.loads((_root() / "assets" / "royale" / "board.json").read_text(encoding="utf-8"))
                ["vocab"].values())) + 1
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    m = B.load(str(start_npz), V).to(dev)
    anchor = {k: v.detach().clone() for k, v in m.state_dict().items()}
    opt = torch.optim.AdamW(m.parameters(), lr=lr, weight_decay=0.0)
    n = len(arr["P"])
    t = {k: torch.from_numpy(v) for k, v in arr.items()}
    m.train()
    for ep in range(epochs):
        perm = torch.randperm(n)
        tot = 0.0
        for i in range(0, n, batch):
            ix = perm[i:i + batch]
            g, tk, ti, h = (t["G"][ix].to(dev), t["T"][ix].to(dev), t["I"][ix].to(dev), t["H"][ix].to(dev))
            cand = t["TC"][ix].to(dev)
            play, card_l, tile_l = m(g, tk, ti, h, cand)
            lp = torch.nn.functional.binary_cross_entropy_with_logits(play, t["P"][ix].to(dev))
            # the card: soft target over the hand (the other cards masked out, as at play time)
            mask = torch.full_like(card_l, -1e9)
            mask.scatter_(1, h, 0.0)
            ls = torch.log_softmax(card_l + mask, 1)
            ci, cp = t["CI"][ix].to(dev), t["CP"][ix].to(dev)
            has = (cp.sum(1) > 0).float()
            lc = -(cp * ls.gather(1, ci)).sum(1)
            lc = (lc * has).sum() / has.sum().clamp(min=1)
            lt_s = torch.log_softmax(tile_l, 1)
            tix, tp = t["TI"][ix].to(dev), t["TP"][ix].to(dev)
            hast = (tp.sum(1) > 0).float()
            ltl = -(tp * lt_s.gather(1, tix)).sum(1)
            ltl = (ltl * hast).sum() / hast.sum().clamp(min=1)
            reg = sum(((p - anchor[k]) ** 2).sum() for k, p in m.named_parameters()) * 1e-4   # stay near the pros
            loss = lp + lc + ltl + reg
            opt.zero_grad(); loss.backward(); opt.step()
            tot += float(loss) * len(ix)
        log(f"  epoch {ep + 1}/{epochs}: loss {tot / max(1, n):.3f} ({n} answers, {dev})")
    m.eval().cpu()
    B.save_weights(m, str(out_base) + ".npz")
    B.export(m, str(out_base) + ".onnx")
    return str(out_base) + ".onnx"


def gate(new_onnx, old_onnx, my_deck, games=20, max_ticks=1800, seed=0):
    """The new brain against the one in use, brain alone, both sides of every deck pair. -> new's score 0..1"""
    cx_new, cx_old = Ctx(new_onnx), Ctx(old_onnx)
    metas = cx_new.meta_decks()
    rnd = random.Random(seed)
    score = 0.0
    for g in range(games // 2):
        _n, md = rnd.choice(metas) if g % 3 else ("mirror", list(my_deck))
        d = [cx_new.deck_ids(my_deck), cx_new.deck_ids(md)]
        for flip in (0, 1):
            pilots = [cx_new, cx_old] if not flip else [cx_old, cx_new]
            _s, w, _st = battle(cx_new, d, pilots, record=False, max_ticks=max_ticks, seed=seed + g)
            if w is None: score += 0.5
            elif w == flip: score += 1.0
    return score / max(1, (games // 2) * 2)


# ------------------------------------------------------------------ the loop
def _progress(**kw):
    p = HOME / "progress.json"
    try: d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): d = {}
    d.update(kw); d["t"] = time.time()
    HOME.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def installed_path(acc):
    from royale import selfplay
    return selfplay.board_path(acc)


def run(my_deck, acc="main", hours=8.0, workers=None, games=None, epochs=2, gate_games=20, max_ticks=1800,
        log=print):
    import multiprocessing as mp
    HOME.mkdir(parents=True, exist_ok=True)
    workers = workers or max(1, min(8, (os.cpu_count() or 2) - 1))
    games = games or workers * 2
    end = time.time() + hours * 3600
    it = int(_progress().get("iteration", 0))
    target = installed_path(acc)
    while time.time() < end and not (HOME / "stop").exists():
        cur = str(target) if target.exists() else str(_root() / "assets" / "royale" / "board.onnx")
        cur_npz = (target.with_suffix(".npz") if target.exists() and target.with_suffix(".npz").exists()
                   else _root() / "assets" / "royale" / "board_weights.npz")
        it += 1
        t0 = time.time()
        log(f"iteration {it}: {games} battles with search ({workers} processes) …")
        jobs = [(max(1, games // workers), random.randrange(10 ** 6), cur, my_deck, max_ticks) for _ in range(workers)]
        samples, stats = [], []
        if workers > 1:
            with mp.get_context("spawn").Pool(workers) as pool:
                for s, st in pool.imap_unordered(_worker, jobs):
                    samples += s; stats += st
        else:
            for j in jobs:
                s, st = _worker(j); samples += s; stats += st
        log(f"  {len(samples)} answers from {len(stats)} battles in {time.time() - t0:.0f} s")
        arr = _buffer_add(_arrays(samples))
        cand = train(arr, cur_npz, HOME / f"candidate", epochs=epochs, log=log)
        sc = gate(cand, cur, my_deck, games=gate_games, max_ticks=max_ticks, seed=it)
        ok = sc >= GATE_WIN
        log(f"  the new brain scored {sc:.0%} against the one in use -> {'IN USE' if ok else 'kept training'}")
        if ok:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(HOME / "candidate.npz", target.with_suffix(".npz"))
            os.replace(HOME / "candidate.onnx", str(target) + ".tmp")
            os.replace(str(target) + ".tmp", target)
        d = _progress(iteration=it, answers=int(len(arr["P"])), last_score=round(sc, 3),
                      accepted=int(_progress().get("accepted", 0)) + (1 if ok else 0),
                      last_battles=stats[-3:], minutes=round((time.time() - t0) / 60, 1))
        log(f"  progress: {d}")


# ------------------------------------------------------------------ started by the bot
def missing():
    import importlib.util
    return [m for m in ("torch", "onnxruntime", "numpy") if importlib.util.find_spec(m) is None]



def _pid():
    return HOME / "exit.pid"


def running():
    try:
        import psutil
        return psutil.pid_exists(int(_pid().read_text()))
    except Exception:
        return False


def start(deck, acc="main", log=None):
    import subprocess
    if running(): return True, "already training"
    HOME.mkdir(parents=True, exist_ok=True)
    try: (HOME / "stop").unlink()
    except OSError: pass
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000010 | 0x00000020                    # its own window, normal priority (6.02)
    py = sys.executable
    if py.lower().endswith("pythonw.exe"): py = py[:-len("pythonw.exe")] + "python.exe"
    p = subprocess.Popen([py, "-u", "-m", "royale.exit_train", "--deck", ",".join(deck), "--acc", str(acc)],
                         cwd=str(_root() / "src"), **kw)
    _pid().write_text(str(p.pid))
    return True, "the AI trains with the engine's answers (Expert Iteration)"


def stop():
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "stop").write_text("1")


if __name__ == "__main__":
    try:                                  # 6.9.14: no broken app-folder onnxruntime inherited from the app
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import ort_gpu
        ort_gpu.sanitize()
    except Exception:
        pass
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True)
    ap.add_argument("--acc", default="main")
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--games", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--gate", type=int, default=20)
    ap.add_argument("--ticks", type=int, default=1800)
    a = ap.parse_args()
    sys.path.insert(0, str(_root() / "src"))

    class _Tee:                                     # what the window shows is also kept in train.log
        def __init__(self, s):
            self.s = s
            HOME.mkdir(parents=True, exist_ok=True)
            self.f = open(HOME / "train.log", "a", encoding="utf-8")
        def write(self, x):
            try: self.s.write(x)
            except Exception: pass
            self.f.write(x); self.f.flush()
        def flush(self):
            try: self.s.flush()
            except Exception: pass
    sys.stdout = _Tee(sys.stdout)
    if os.name == "nt":
        try: __import__("ctypes").windll.kernel32.SetConsoleTitleW("Clash Farmer — الذكاء الاصطناعي بيلعب ضد نفسه ويتعلم")
        except Exception: pass
    print("=" * 70 + "\n  Clash Farmer: the AI plays itself in the battle engine and learns what wins\n" + "=" * 70)
    run(a.deck.split(","), a.acc, a.hours, a.workers or None, a.games or None, a.epochs, a.gate, a.ticks)
