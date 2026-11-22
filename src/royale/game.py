"""
Clash Royale mode: the bot plays battles by itself on LDPlayer (720x1280 portrait).

  lobby        the yellow Battle button -> a battle (trophy road / Path of Legends: what the Battle button starts)
  battle       ~5 looks a second: eyes (royale.eyes) -> brain (royale.brain) -> two taps (the card, then the tile)
  end          the OK button; the result (win / loss) counted and sent to the phone
  else         popups: close (the red X / OK), once in a while the picture goes to Claude (learning repo)

Nothing here spends gems or buys: only Battle, OK and close buttons are pressed.
"""
import time

PKG = "com.supercell.clashroyale"
ACT = "com.supercell.clashroyale/com.supercell.titan.GameApp"
LOOK_EVERY = 0.08          # seconds between looks in a battle (~10 a second: a look takes ~70 ms)


def _u():
    import utils
    return utils


def frame():
    return _u().Frame_Handler.get_frame(grayscale=False)


def tap(x, y):
    _u().Input_Handler.click(x, y)


def words(fr):
    try:
        return [(b[0].strip().lower(), b) for b in _u().ocr_boxes(fr) if b[5] > 0.4]
    except Exception:
        return []


def find_word(ws, *names, y_min=0.0, y_max=1.0):
    for t, b in ws:
        cy = (b[2] + b[4]) / 2
        if any(t == n or t.startswith(n) for n in names) and y_min <= cy <= y_max:
            return ((b[1] + b[3]) / 2, cy)
    return None


# the game's own tutorial (a new account): the trainer / the king talk in speech bubbles; a tap goes on
TUTORIAL = ("play cards", "defend", "your tower", "towers", "under attack", "trainer", "tap to", "tap anywhere",
            "well done", "great job", "good job", "nice", "awesome", "let's", "lets ", "elixir", "drag", "destroy",
            "crown", "you win", "victory", "hello", "welcome", "chest", "unlock", "collect", "claim", "next",
            "resource card", "your gold", "new card", "card found", "common", "rare", "epic", "tap", "found")
# never pressed, whatever the tutorial / a reward screen says: they spend gems or money
NEVER = ("gem", "buy", "purchase", "speed up", "open now", "open for", "skip", "pass royale", "offer", "shop", "$", "€",
         "subscribe", "upgrade now", "log out", "logout", "exit", "quit")
NAME_WORDS = ("choose a name", "enter name", "your name", "name your", "player name")


def tutorial_point(ws):
    """A tutorial bubble on the screen -> where to tap to go on (the bubble's text), else None."""
    if any(any(n in t for n in NEVER) for t, _ in ws): return None
    hits = []
    for t, b in ws:
        if any(k in t for k in TUTORIAL):
            hits.append(b)
    if not hits: return None
    b = max(hits, key=lambda bb: (bb[3] - bb[1]) * (bb[4] - bb[2]))
    return ((b[1] + b[3]) / 2, (b[2] + b[4]) / 2)


def start_game(logger):
    """Clash Royale open in front (started when it isn't)."""
    dev = _u().ADB_Manager.adbutils_device
    if not dev.shell(f"pidof {PKG}").strip():
        logger.info("Clash Royale: starting the game")
        dev.shell(f"am start -W -n {ACT}")
        time.sleep(12)
    else:
        dev.shell(f"am start -n {ACT}")
        time.sleep(1)


def installed():
    try:
        return PKG in _u().ADB_Manager.adbutils_device.shell(f"pm list packages {PKG}")
    except Exception:
        return False


class RoyaleBot:
    def __init__(self, settings, logger, notify=None):
        from royale.eyes import Eyes
        from royale.brain import Brain
        self.s = settings or {}
        self.log = logger
        _send = notify or (lambda t: None)

        def _notify(text):
            # a phone message goes out on its own thread: Telegram can take up to 11 s, and before 5.71 the
            # battle stood still meanwhile (worst moments of 5-12 s in the user's reports)
            import threading
            threading.Thread(target=lambda: _send(text), daemon=True, name="notify").start()
        self.notify = _notify
        deck = list(self.s.get("deck") or [])
        self.eyes = Eyes(deck)
        self.brain = Brain(deck)
        try:
            from royale.memory import Memory
            self.brain.mem = Memory(_u().INSTANCE_ID)           # learns from every battle it plays
        except Exception:
            logger.debug("Clash Royale: match memory off", exc_info=True)
        self.wins = self.losses = self.battles = 0
        try:                                         # the stronger eyes: fetched / converted once in the background
            from royale import strong_eyes
            strong_eyes.ensure(logger)
        except Exception:
            pass
        try:                                         # and trained on this PC's graphics card, by themselves
            from royale import trainer
            if self.s.get("auto_train", True) and trainer.due():
                logger.info("Clash Royale: training the eyes on this PC in the background (data + graphics card)")
                trainer.start(_u().INSTANCE_ID)
        except Exception:
            logger.debug("Clash Royale: training not started", exc_info=True)
        self.unknown_since = None
        try:                                         # the learned brain loaded now, not in the first decision
            from royale import policy
            if policy.ready():
                ti = policy.info()
                logger.info(f"Clash Royale: learned brain ready (17 M real plays; picks the pro's card "
                            f"{100 * ti.get('card_in_hand', 0):.0f}% of the time)")
            from royale import board as _bb
            if _bb.ready():
                bi = _bb.info()
                logger.info(f"Clash Royale: board brain ready (a Transformer that reads the whole arena; "
                            f"pro's card {100 * bi.get('card_in_hand', 0):.0f}%, tile within 1 "
                            f"{100 * bi.get('tile_within1', 0):.0f}%)")
        except Exception:
            pass
        self._api_start()
        self.account = None
        if self.s.get("manage_account", True):
            try:
                from royale.account import Account
                self.account = Account(_u().INSTANCE_ID, logger, self.notify)
            except Exception:
                logger.debug("Clash Royale: account manager off", exc_info=True)

    # -------------------------------------------------------------- one battle
    def battle(self):
        from royale.eyes import in_battle, tile_xy, card_xy
        log = self.log
        from royale import learn
        # safe play (default): always the best known way, no experiments on your trophies — it still learns from
        # every result; off: 2 settings are tried per battle to find better ones faster
        self.params = learn.choose(_u().INSTANCE_ID, explore=not self.s.get("safe_play", True))
        self.brain.p = dict(learn.DEFAULT, **self.params)
        if not self.s.get("learned_brain", True): self.brain.p["learned"] = False
        # the local AI model decides the moves (on by default); off: the rule brain decides with the models' advice
        # AI mode (on by default since 5.74, the user's choice): the AI model trained on pro games decides, the battle
        # engine simulates its best choices (and the self-play AI's) and keeps the best; the rules only guard it
        self.brain.p["ai"] = bool(self.s.get("ai_play", True)) and self.brain.p.get("learned", True)
        # the AI model alone plays (5.75, on by default): the rule brain never plays a move of its own
        self.brain.p["ai_only"] = self.brain.p["ai"] and bool(self.s.get("ai_only", True))
        if self.brain.p["ai_only"]: log.info("Clash Royale: the AI model plays this battle by itself "
                                             "(the engine compares its own choices, the guards stop sure mistakes)")
        if self.brain.p["ai"]: log.info("Clash Royale: the local AI model plays this battle (the rules only guard it)")
        self.brain.reset()
        # 2v2 (two opponents: their elixir counted as two players, no single-deck hand guess) — known from the Quick
        # Match / 2v2 result screens; Training Camp is always 1v1
        self.brain.p["2v2"] = bool(getattr(self, "_mode_2v2", False)) and not self.s.get("training_camp", False)
        if self.brain.p["2v2"]:
            self.brain.enemy_elixir *= 2.0                         # both start with their own elixir
            log.info("Clash Royale: a 2v2 battle — two opponents counted")
        self._prev_hand = None
        # every unit followed from the battle's first look (6.6): new ids, the side of each, the brain leads its
        # spells on them; in 2v2 a unit of none of our cards can be our partner's (the colour decides)
        try:
            self.eyes.tracker.reset()
            self.eyes.two_v_two = bool(self.brain.p.get("2v2"))
            self.eyes.dual = bool(self.s.get("dual_eyes", False))     # 6.7: one detector unless asked for both
            self.brain.tracker = self.eyes.tracker
        except Exception:
            pass
        try:
            from royale import live_view
            live_view.new_battle()
        except Exception:
            pass
        engine_on = False
        try:
            from royale import engine as _eng
            _eng.new_battle()
        except Exception:
            pass
        if self.s.get("engine_think", True):                 # the battle engine thinks every move through
            from royale import engine
            engine_on = engine.selftest(log)
            if engine_on:
                try:
                    from royale import engine_ai
                    engine_ai.new_battle()
                    if False:
                        import threading
                        def _gate(deck=list(self.brain.deck or self.eyes.deck or [])):
                            self._gate_running = True
                            try:
                                msg = engine_ai.gate_in_background(deck)       # its own process: the battle stays fast
                                if msg:
                                    log.info("Clash Royale AI: " + msg)
                                    try: self.notify("🤖 كلاش رويال: " + msg)
                                    except Exception: pass
                            finally:
                                self._gate_running = False
                        threading.Thread(target=_gate, daemon=True, name="ai-gate").start()
                    w = engine_ai.weights()
                    if w: log.info(f"Clash Royale: the bot's own trained AI proposes moves ({w.name})")
                except Exception:
                    pass
            if not engine_on and not getattr(self, "_engine_told", False):
                self._engine_told = True
                log.info("Clash Royale: the battle engine is not used — " + (engine.status()["why"] or "not available"))
        self._battle_t = time.time()
        if getattr(self, "_api_deck", None) and self.eyes.deck != self._api_deck and \
                not getattr(self, "_expected_deck", None):           # a fresh copy is checked by the hand first
            self.eyes.set_deck(self._api_deck)                   # the exact deck from the official API
            self.brain.deck = list(self._api_deck)
        self.battles += 1
        log.info("Clash Royale: this battle's settings " + ", ".join(f"{k}={v}" for k, v in self.params.items()))
        log.info(f"Clash Royale: battle #{self.battles}")
        out_since, last = None, None
        from royale.abilities import Abilities
        abil, abil_base = Abilities(log), False                       # hero / champion ability buttons
        plays = 0
        look_ms, looks, slow_told = 0.0, 0, False
        self._slot_used = {}                                       # slot -> when it was played (picture lags)
        perf = {"capture": 0.0, "look": 0.0, "decide": 0.0, "engine": 0.0, "tap": 0.0, "loop": 0.0, "n": 0,
                "worst_loop": 0.0}
        full_s, t_prev, b_t0, self._engine_drops = 0.0, time.monotonic(), time.monotonic(), 0
        play_log, slow = [], []
        self._perf = perf
        while _u().running():
            t0 = time.monotonic()
            seen_t = time.time()                                # when the picture was taken (the live screen's
            fr = frame()                                         # tracker makes up the delay from it, 5.97)
            t_cap = time.monotonic()
            if not in_battle(fr):
                out_since = out_since or time.monotonic()
                if time.monotonic() - out_since > 1.0:
                    tp = tutorial_point(words(fr))                     # the tutorial talks over its battle
                    if tp:
                        self._tutorial_battle = True
                        tap(*tp); time.sleep(0.8); out_since = time.monotonic(); continue
                if time.monotonic() - out_since > 4.0: break           # the battle is over
                time.sleep(0.2)
                continue
            out_since = None
            if time.monotonic() - getattr(self, "_flag_t", 0) > 2.0:    # 6.9: the eyes training waits while this is fresh
                self._flag_t = time.monotonic()
                try:
                    from royale.trainer import BATTLE_FLAG
                    BATTLE_FLAG.parent.mkdir(parents=True, exist_ok=True); BATTLE_FLAG.touch()
                except Exception:
                    pass
            try:
                tl = time.monotonic()
                st = self.eyes.look(fr)
                look_ms += (time.monotonic() - tl) * 1000; looks += 1
                perf["capture"] += (t_cap - t0) * 1000
                perf["look"] += (time.monotonic() - tl) * 1000
                if looks == 50 and look_ms / looks > 250 and not slow_told:
                    slow_told = True
                    log.warning(f"Clash Royale: one look takes {look_ms / looks:.0f} ms — the PC is busy (close other "
                                f"programs / the 2nd bot) or the screen comes by ADB (slow)")
            except Exception:
                log.debug("Clash Royale: look failed", exc_info=True)
                time.sleep(0.2)
                continue
            # the deck is learned from coloured (playable) cards only: grey ones get mixed up (Mini P.E.K.K.A
            # was read as Little Prince on the user's screen)
            try: self.brain.see_hand(st["hand"], st.get("hand_look"))
            except Exception: pass
            if self.eyes.learn_deck([h for i, h in enumerate(st["hand"]) if i in st["ready"]]):
                log.info("Clash Royale: my deck = " + ", ".join(self.eyes.deck))
                self.brain.deck = list(self.eyes.deck)
                def _chk():
                    try: self._check_deck()
                    except Exception: log.debug("deck check failed", exc_info=True)
                __import__("threading").Thread(target=_chk, daemon=True, name="deck-check").start()
            if len(self.eyes.deck) == 8 and getattr(self, "_studied", None) != sorted(self.eyes.deck):
                self._studied = sorted(self.eyes.deck)
                deck_now = list(self.eyes.deck)

                def _study():                                  # its own thread: never a pause in the battle
                    try: self._study_deck()
                    except Exception: log.debug("deck study failed", exc_info=True)
                    try: _save_deck(deck_now)
                    except Exception: pass
                __import__("threading").Thread(target=_study, daemon=True, name="deck-study").start()
            # what was just spent: the picture can lag a moment behind a play ("Not enough Elixir!")
            el = st["elixir"]
            t_now = time.monotonic()
            if el >= 9.5: full_s += min(1.0, t_now - t_prev)           # elixir wasted: time spent full
            t_prev = t_now
            spent = getattr(self, "_spent", None)
            if spent and time.monotonic() - spent[1] < 1.5:
                el = min(el, max(0.0, spent[2] - spent[0] + (time.monotonic() - spent[1]) / self.brain.seconds_per_elixir()))
            # sure of the card before it is played: the same card read in that slot on two looks in a row (a
            # card half-seen while the hand moves is never played)
            prev, self._prev_hand = getattr(self, "_prev_hand", None), list(st["hand"])
            ready = [i for i in st["ready"] if i < len(st["hand"]) and
                     prev is not None and i < len(prev) and prev[i] == st["hand"][i] and st["hand"][i] != "blank" and
                     time.monotonic() - self._slot_used.get(i, 0) > 0.8 and
                     (__import__("royale.brain", fromlist=["card"]).card(st["hand"][i]).get("cost", 11) <= el)]
            try:
                t_dec = time.monotonic()
                d = self.brain.decide(st["hand"], ready, el, st["enemies"], st["allies"], st["towers"],
                                      hp=st.get("hp"), spells=st.get("spells"), evo=st.get("evo"))
            except Exception:
                log.warning("Clash Royale: a decision failed — next look", exc_info=True)
                d = None
            try: perf["decide"] += (time.monotonic() - t_dec) * 1000
            except NameError: pass
            t_eng = time.monotonic()
            if engine_on:
                try:
                    d = self._engine_turn(st, d, ready, el)
                except Exception:
                    log.debug("engine turn failed", exc_info=True)
            if self.brain.arch and self.brain.arch != getattr(self, "_arch_logged", None):
                self._arch_logged = self.brain.arch
                log.info(f"Clash Royale: their deck looks like {self.brain.arch} "
                         f"({', '.join(sorted(self.brain.enemy_seen))}) — playing against it")
            if self.brain.predicted and self.brain.predicted != getattr(self, "_pred_logged", None):
                self._pred_logged = set(self.brain.predicted)
                log.info("Clash Royale: their deck probably also has " + ", ".join(sorted(self.brain.predicted)))
            perf["engine"] += (time.monotonic() - t_eng) * 1000
            lp = (time.monotonic() - t0) * 1000
            perf["loop"] += lp; perf["n"] += 1; perf["worst_loop"] = max(perf["worst_loop"], lp)
            if lp > 1500 and len(slow) < 6:                 # where a long moment went (the freezes in the reports)
                try:
                    slow.append({"ms": round(lp), "capture": round((t_cap - t0) * 1000),
                                 "look": round((t_dec - t_cap) * 1000), "decide": round((t_eng - t_dec) * 1000),
                                 "engine": round((time.monotonic() - t_eng) * 1000), "t": round(self.brain.elapsed())})
                except Exception:
                    pass
            st["_perf"] = {k: (round(v / max(1, perf["n"])) if k not in ("n", "worst_loop") else round(v))
                           for k, v in perf.items()}
            try:
                from royale import live_view
                if d: live_view.event("us", d["card"], d["tile"], d.get("why", ""))
                st["_seen_t"] = seen_t
                live_view.battle(_u().INSTANCE_ID, self.brain, st, d, force=bool(d), frame=fr)
            except Exception:
                pass
            now_t = time.monotonic()
            if d:
                # never a card that is in none of the account's real decks (5.89): it can only be a misread — the
                # Goblin Barrel read as Goblin Gang was played as a troop in our half
                try:
                    known = {c for k in self.eyes.known_decks() for c in k}
                except Exception:
                    known = set()
                ed = list(getattr(self.eyes, "deck", []) or [])
                new_deck = len(ed) == 8 and not set(ed) <= known          # a deck of the user's we do not know yet
                if known and not new_deck and d["card"] not in known:
                    if now_t - getattr(self, "_misread_told", 0) > 10:
                        self._misread_told = now_t
                        log.warning(f"Clash Royale: '{d['card']}' is in none of your decks — a misread card, not played")
                    try: self.brain.undo(d)
                    except Exception: pass
                    d = None
            if d and d["card"] in ("goblin_barrel", "miner", "graveyard", "goblin_drill") and d["tile"][1] < 20:
                # the last guard before the tap: these go onto THEIR tower, never into our half
                fixed = self.brain._barrel_tile(tuple(d["tile"]))
                log.warning(f"Clash Royale: {d['card']} was aimed at {d['tile']} ({d['why']}) — sent to their tower "
                            f"{fixed} instead")
                d["tile"], d["why"] = fixed, d["why"] + " | guard: onto their tower"
            if d:
                play_log.append({"t": round(self.brain.elapsed(), 1), "card": d["card"], "tile": list(d["tile"]),
                                 "why": str(d.get("why", ""))[:90], "el": round(float(st["elixir"]), 1)})
                self._spent = (__import__("royale.brain", fromlist=["card"]).card(d["card"]).get("cost", 4),
                               time.monotonic(), el)
                self._slot_used[d["slot"]] = time.monotonic()
                cx, cy = card_xy(d["slot"])
                tx, ty = tile_xy(*d["tile"])
                t_tap = time.monotonic()
                tap(cx, cy)
                time.sleep(0.04)
                tap(tx, ty)
                perf["tap"] += (time.monotonic() - t_tap) * 1000
                plays += 1
                log.info(f"Clash Royale: {d['card']} -> tile {d['tile']} ({d['why']}) — elixir {st['elixir']:.0f}, "
                         f"theirs ~{self.brain.enemy_elixir:.0f}")
            last = st
            if not abil_base:
                abil.reset(fr); abil_base = True                       # the strip above the cards, before any hero
            elif not d:
                try: abil.tick(fr, self.brain, el, tap)
                except Exception: log.debug("ability check failed", exc_info=True)
            if self.s.get("keep_frames", True):
                try:
                    from royale import frames
                    # 6.8: once a battle, the arena before any card is down = a negative picture (skins are nothing)
                    if not getattr(self, "_empty_kept", None) == id(self.brain.plays) and 0.5 < self.brain.elapsed() < 4 \
                            and not self.brain.plays and not self.brain.enemy_hist and not self.brain._stable:
                        if frames.keep(empty=True): self._empty_kept = id(self.brain.plays)
                    frames.keep()
                except Exception:
                    pass
            time.sleep(max(0.0, LOOK_EVERY - (time.monotonic() - t0)))
        try:
            from royale import strong_eyes
            big = f", big model {strong_eyes.speed_ms():.0f} ms in the background" if strong_eyes.speed_ms() else ""
        except Exception:
            big = ""
        src = (getattr(_u().Frame_Handler, "_power", {}) or {}).get("src") or {}
        log.info(f"Clash Royale: battle over — {plays} cards played; one look {look_ms / max(1, looks):.0f} ms"
                 f"{big}; screen by {max(src, key=src.get) if src else '?'}")
        try:                                       # where each moment's time went: the log, and Claude (learning repo)
            n = max(1, perf["n"])
            rep = {k: round(v / n, 1) for k, v in perf.items() if k not in ("n", "worst_loop")}
            rep.update({"moments": perf["n"], "worst_loop_ms": round(perf["worst_loop"]), "plays": plays,
                        "screen_by": (max(src, key=src.get) if src else "?"),
                        "big_model_ms": round(strong_eyes.speed_ms() or 0) if "strong_eyes" in dir() else None,
                        "engine_on": bool(engine_on), "version": __import__("version").VERSION,
                        "seconds": round(time.monotonic() - b_t0), "full_elixir_s": round(full_s),
                        "engine_dropped": getattr(self, "_engine_drops", 0),
                        "ai": bool(self.brain.p.get("ai")), "slow": slow, "plays_list": play_log[-60:]})
            try:
                import ort_gpu
                from royale import strong_eyes as _se
                rep["eyes_gpu"] = ort_gpu.on_gpu()
                rep["eyes_same_moment"] = _se.same_moment()
                rep["one_detector_looks"] = int(getattr(self.eyes, "single_used", 0))
            except Exception:
                pass
            try:
                from royale import engine as _eng
                rep["engine_why"] = _eng.skips()
            except Exception:
                pass
            log.info("Clash Royale: time per moment (ms) — " + ", ".join(f"{k} {v}" for k, v in rep.items()))
            import json as _j, learn_sync
            if learn_sync.configured():
                learn_sync._put(f"inbox/royale_perf/{_u().INSTANCE_ID}_{time.strftime('%Y%m%d_%H%M%S')}.json",
                                _j.dumps(rep, indent=1).encode("utf-8"), "royale perf: one battle")
        except Exception:
            log.debug("perf report failed", exc_info=True)
        return last

    # -------------------------------------------------------------- after the battle
    def results(self, last):
        """The results screen: who won (the WINNER banner over our name = bottom half), then OK."""
        log = self.log
        for _ in range(20):
            if not _u().running(): return
            fr = frame()
            ws = words(fr)
            win = find_word(ws, "winner")
            ok = find_word(ws, "ok", y_min=0.75)
            if not win and not ok:
                tp = tutorial_point(ws)
                if tp:                                   # the tutorial talks in the middle of its battle: go on
                    tap(*tp)
                    time.sleep(1.0)
                    return
            if win or ok:
                if win:
                    won = bool(win[1] > 0.45)                 # a plain bool (numpy's broke the saving)
                    self.wins += won
                    self.losses += not won
                    if self.account:
                        self.account.count("battles"); self.account.count("wins", int(won))
                    self._api_after_battle(won)
                    try:                                    # the learned brain learns from this battle by itself
                        from royale import selfplay
                        if not getattr(self, "_tutorial_battle", False):
                            try: self.brain.score_moves()
                            except Exception: pass
                            selfplay.record(_u().INSTANCE_ID, self.brain.steps, self.brain.tower_log, won,
                                            self.brain.opp_steps)
                            if selfplay.due(_u().INSTANCE_ID):
                                log.info("Clash Royale: the learned brain trains itself on its own battles (background)")
                                selfplay.start(_u().INSTANCE_ID)
                            st = selfplay.read_state(_u().INSTANCE_ID)
                            if st.get("note") and st.get("note") != getattr(self, "_sp_note", None):
                                self._sp_note = st["note"]
                                log.info(f"Clash Royale: self-learning — {st['note']}")
                    except Exception:
                        log.debug("Clash Royale: self-learning record failed", exc_info=True)
                    try:
                        from royale import learn
                        self._was_tutorial = getattr(self, "_tutorial_battle", False)
                        if not getattr(self, "_tutorial_battle", False):     # the tutorial's battles teach nothing
                            learn.record(_u().INSTANCE_ID, getattr(self, "params", {}) or {}, won)
                        self._tutorial_battle = False
                    except Exception:
                        log.debug("Clash Royale: learning failed", exc_info=True)
                    log.info(f"Clash Royale: {'WIN' if won else 'loss'} — {self.wins} won / {self.losses} lost")
                    try:
                        if self.brain.mem and not getattr(self, "_was_tutorial", False):
                            summary = self.brain.mem.end(won, self.brain.enemy_plays, self.brain.arch)
                            log.info("Clash Royale: " + summary.replace("\n", " | "))
                            if self.s.get("notify", True): self.notify(summary)
                    except Exception:
                        log.debug("Clash Royale: match summary failed", exc_info=True)
                    if self.s.get("notify", True):
                        try: self.notify(f"{'🏆 كسبت' if won else '❌ خسرت'} ماتش كلاش رويال — "
                                         f"{self.wins} فوز / {self.losses} خسارة النهارده")
                        except Exception: pass
                if ok:
                    tap(*ok)
                    time.sleep(2.5)
                    return
            time.sleep(0.8)

    # -------------------------------------------------------------- the loop
    def run(self):
        from royale.eyes import in_battle
        log = self.log
        start_game(log)
        max_b = int(self.s.get("max_battles", 0) or 0)
        self._status("now")                                  # the app shows "running", not "starting…"
        try:                                                 # the account's real decks before the first battle
            import learn_sync, threading as _th
            if learn_sync.configured(): _th.Thread(target=learn_sync.fetch_knowledge, daemon=True).start()
        except Exception:
            pass
        try:                                                 # the eyes on the graphics card (once, in the background)
            import ort_gpu
            ort_gpu.install_in_background(log)
            if __import__("os").name == "nt" and not ort_gpu.on_gpu():
                log.warning("Clash Royale: the eyes run on the PROCESSOR now (slow: boxes late / missing) — the "
                            "graphics-card version is being set up in the background; restart the app when it is ready")
        except Exception:
            pass
        try:                                                 # NVIDIA: TensorRT for the eyes (6.6, once, in the background)
            import trt_engine
            trt_engine.install_in_background(log)
        except Exception:
            pass
        self._say("✅ كلاش رويال: البوت شغال ومتوصل باللعبة", "the bot is running and connected to the game", phone=True)
        while _u().running():
            if max_b and self.battles >= max_b:
                log.info(f"Clash Royale: {max_b} battles played — done")
                try: self.notify(f"✅ كلاش رويال: خلصت {self.battles} ماتش — {self.wins} فوز / {self.losses} خسارة")
                except Exception: pass
                return
            try:
                fr = frame()
                self._frame_fails = 0
            except Exception as e:
                # LDPlayer closed / its ADB gone ("device not found"): before, the bot kept failing here and looked
                # like it was running while doing nothing -> the emulator and the game are brought back
                self._frame_fails = getattr(self, "_frame_fails", 0) + 1
                self._recover(e)
                continue
            if in_battle(fr):
                self.unknown_since = None
                last = self.battle()
                try:
                    from royale import engine_ai
                    engine_ai.resume_background()                      # training / version test go on
                    self._gate_after_battle()
                except Exception:
                    pass
                self.results(last)
                try:
                    from royale import live_view
                    live_view.phase(_u().INSTANCE_ID, "result", f"{self.wins} / {self.losses}")
                except Exception:
                    pass
                continue
            ws = words(fr)
            # the lobby's menu (the three lines at the top right) left open: Battle Log / Leaderboards / Training
            # Camp / Settings... -> the same button closes it (stuck picture 20261121_082852)
            if find_word(ws, "leaderboards") and find_word(ws, "battle log", "settings", "tv royale"):
                log.info("Clash Royale: the lobby menu is open — closing it")
                tap(0.91, 0.105)
                time.sleep(1.0)
                continue
            b = find_word(ws, "battle", y_min=0.55, y_max=0.9)
            qm = find_word(ws, "quick match", y_min=0.3, y_max=0.8)          # the 2v2 window left open
            if qm and not in_battle(fr):
                log.info("Clash Royale: 2v2 — Quick Match")
                self._mode_2v2 = True
                tap(*qm)
                time.sleep(2.0)
                continue
            if b and self._cards_study_due():
                self._study_cards()
                continue
            if b and self.s.get("auto_deck", True) and not self.s.get("lock_deck", True) \
                    and not getattr(self, "_deck_checked", False):
                self._deck_checked = True
                self._pick_deck()
                continue
            if b and self.account and self.account.due(self.battles):
                log.info("Clash Royale: looking after the account (cards, clan, rewards)")
                self.account.run()
                continue
            if b and not self._go_ok():
                self.unknown_since = None
                time.sleep(1.0)                              # ready, waiting for the user's Start
                continue
            if b:
                self.unknown_since = None
                self._reward_taps = 0
                log.info("Clash Royale: Battle")
                try:
                    from royale import live_view
                    live_view.phase(_u().INSTANCE_ID, "searching")
                except Exception:
                    pass
                if self.s.get("training_camp", False):
                    # Training Camp only (the user's choice): battles against the game's trainer, no trophies —
                    # the bot practises and learns without risking the account's ladder
                    if not self._start_training_camp():
                        time.sleep(2.0)
                        continue
                else:
                    tap(*b)
                for k in range(60):                          # matchmaking: up to ~1 minute
                    time.sleep(1)
                    fr2 = frame()
                    if in_battle(fr2) or not _u().running(): break
                    if k % 2 == 0:
                        # 2v2 (the user's mode): its window asks Play with Friend / Quick Match -> Quick Match
                        qm = find_word(words(fr2), "quick match", "quick", y_min=0.3, y_max=0.8)
                        if qm:
                            log.info("Clash Royale: 2v2 — Quick Match")
                            self._mode_2v2 = True
                            tap(*qm)
                continue
            # the chat window open over the result screen (a teammate wrote / left the chat): its red X first, it
            # covers the Exit button (the user's picture, 5.87)
            if find_word(ws, "chat", y_max=0.12) and (find_word(ws, "exit", y_min=0.85) or
                                                      find_word(ws, "has left", "has joined", "left the chat")):
                log.info("Clash Royale: the chat is open over the result — closing it")
                try:
                    if not _u().tap_red_x(): tap(0.9, 0.055)
                except Exception:
                    tap(0.9, 0.055)
                time.sleep(1.0)
                continue
            # "Choose your reward" after a battle (2026): the first choice, then its claim / OK
            if find_word(ws, "choose") and find_word(ws, "reward", "rewards"):
                log.info("Clash Royale: a reward to choose after the battle — taking one")
                tap(0.3, 0.5)
                time.sleep(0.8)
                ws2 = words(frame())
                c = find_word(ws2, "claim", "collect", "confirm", "ok", "continue", y_min=0.4)
                if c: tap(*c)
                time.sleep(1.2)
                continue
            # the result screen of a 2v2 (Exit / Play Again / add friend / chat): Exit, then Battle again
            # (the user's order: never Play Again)
            ex = find_word(ws, "exit", y_min=0.85)
            if ex and find_word(ws, "play again", "play", y_min=0.85):
                self._mode_2v2 = True                         # this result screen is 2v2's
                log.info("Clash Royale: battle over — Exit")
                tap(*ex)
                time.sleep(2.0)
                continue
            ok = find_word(ws, "ok", "continue", "tap to continue", "close", y_min=0.5)
            if ok:
                tap(*ok)
                time.sleep(1.5)
                continue
            # "You got:" (a chest's rewards shown) -> a tap anywhere goes on
            if any(t.startswith("you got") for t, _ in ws):
                tap(0.5, 0.85)
                time.sleep(1.0)
                continue
            # another tab of the lobby (Shop / Cards / Clan / Events: the bar at the bottom, no Battle button):
            # back to the Battle tab — never anything on the Shop page (offers cost money)
            if find_word(ws, "shop", "cards", "clan", "events", "social", y_min=0.88) and \
                    not find_word(ws, "battle", y_min=0.55, y_max=0.9):
                from royale.account import TABS, TAB_Y
                log.info("Clash Royale: on another tab of the lobby — back to Battle")
                tap(TABS["battle"], TAB_Y)
                time.sleep(1.2)
                continue
            if any(any(k in t for k in NAME_WORDS) for t, _ in ws):
                if not getattr(self, "_name_told", False):     # typing a name is the user's (once per account)
                    self._name_told = True
                    log.warning("Clash Royale: the game asks for a player name — type it once by hand")
                    try: self.notify("✍️ كلاش رويال بيطلب اسم للاعب — اكتبه مرة بإيدك في LDPlayer والبوت هيكمل")
                    except Exception: pass
                time.sleep(3)
                continue
            tp = tutorial_point(ws)
            if tp:                                          # the tutorial: tap the bubble, the bot plays its battles
                self.unknown_since = None
                self._tutorial_battle = True
                if not getattr(self, "_tut_told", False):
                    self._tut_told = True
                    log.info("Clash Royale: the game's tutorial — going through it (tapping on, playing its battles)")
                tap(*tp)
                time.sleep(1.2)
                continue
            # a chest opening / reward screen: hardly any words (the chest, "?" coins, numbers flying in) -> tapping
            # the middle opens it and shows the next reward, until the game goes back to the lobby
            if len([t for t, _ in ws if len(t) > 1]) <= 3 and not any(any(n in t for n in NEVER) for t, _ in ws):
                self._reward_taps = getattr(self, "_reward_taps", 0) + 1
                if self._reward_taps <= 25:
                    if self._reward_taps == 1:
                        log.info("Clash Royale: a chest / reward screen — tapping it open")
                    tap(0.5, 0.55)
                    time.sleep(0.9)
                    continue
            else:
                self._reward_taps = 0
            try:                                            # a popup with the red X
                if _u().tap_red_x():
                    time.sleep(1.0)
                    continue
            except Exception:
                pass
            self.unknown_since = self.unknown_since or time.monotonic()
            if time.monotonic() - self.unknown_since > 20:
                try:
                    import learn_sync
                    learn_sync.report_stuck(_u().INSTANCE_ID, fr, [w for w, _ in ws], "royale")
                except Exception:
                    pass
                self.unknown_since = time.monotonic() + 600     # once in 10 minutes
                start_game(log)
            time.sleep(1.0)


def _api_names(eyes, keys):
    """API card keys -> the eyes' card names (Mini P.E.K.K.A -> the eyes' minipekka...)."""
    from royale import cr_api
    by = {cr_api.key_of(n): n for n in eyes.by_name}
    return [by[k] for k in keys if k in by]


def _api_start(self):
    """In the background: our exact deck from the official API (known before the first battle), and the meta
    (the decks the best players use now) refreshed once a day."""
    import threading
    from royale import cr_api
    if not cr_api.tag(_u().INSTANCE_ID): return

    def work():
        try:
            md = cr_api.my_deck(_u().INSTANCE_ID)
            lv = {k: (int(l) + 16 - int(m)) for k, l, m, _e in md if l and m}       # the levels shown in the game
            from royale.brain import card as _card, cards_db as _cdb
            _nm = {cr_api.key_of(n): n for n in _cdb()}
            self.brain.evo_cards = {_nm[k]: ((_card(_nm[k]).get("evo") or {}).get("cycles") or 2)
                                    for k, _l, _m, e in md if e and k in _nm}
            if lv:
                self.brain.levels = lv
                self.brain.king_level = round(sum(lv.values()) / len(lv))
                gaps = [b["levels"][1] - b["levels"][0] for b in (self.brain.mem.d.get("api_battles") or [])[-30:]
                        if self.brain.mem and b.get("levels")] if self.brain.mem else []
                gap = (sum(gaps) / len(gaps)) if gaps else 0.0
                self.brain.their_level = round(self.brain.king_level + gap)
                self.log.info(f"Clash Royale API: my levels ~{self.brain.king_level}, opponents usually "
                              f"{'+' if gap >= 0 else ''}{gap:.1f} — the thinking uses the real numbers")
            deck = _api_names(self.eyes, [k for k, *_ in md])
            if len(deck) == 8:
                self._api_deck = deck
                self.log.info("Clash Royale: my deck from the official API = " + ", ".join(deck))
        except Exception as e:
            self.log.info(f"Clash Royale API: {e}")
        try:
            m = cr_api.build_meta()
            if m.get("battles"):
                self.log.info(f"Clash Royale API: the meta now — {m['battles']} battles of the best players, "
                              f"{len(m.get('decks', []))} decks")
        except Exception as e:
            self.log.debug(f"Clash Royale API meta: {e}")
    threading.Thread(target=work, daemon=True, name="cr-api").start()


def _api_after_battle(self, won_seen):
    """A few seconds after the battle the official battle log has it: the opponent's whole deck with levels, the
    crowns and the real result -> the log, the phone, the match memory (and the result is corrected)."""
    import threading
    from royale import cr_api
    if not cr_api.tag(_u().INSTANCE_ID) or getattr(self, "_tutorial_battle", False): return
    t0 = getattr(self, "_battle_t", time.time())

    def work():
        b = None
        for _ in range(6):
            time.sleep(10)
            try:
                b = cr_api.last_battle(_u().INSTANCE_ID, after=t0)
            except Exception:
                b = None
            if b: break
        if not b: return
        deck = ", ".join(f"{k} {lv}" for k, lv in b["their_deck"])
        mine = sum(lv or 0 for _k, lv in b["my_deck"]) / max(1, len(b["my_deck"]))
        theirs = sum(lv or 0 for _k, lv in b["their_deck"]) / max(1, len(b["their_deck"]))
        self.log.info(f"Clash Royale API: {'WIN' if b['won'] else 'loss'} {b['crowns']}-{b['their_crowns']} — "
                      f"their deck: {deck} (levels: mine {mine:.1f}, theirs {theirs:.1f})")
        if b["won"] != bool(won_seen):
            self.log.info("Clash Royale API: the real result differs from what the screen showed — corrected")
            self.wins += 1 if b["won"] else -1
            self.losses += -1 if b["won"] else 1
        try:
            mem = self.brain.mem
            if mem:
                mem.d.setdefault("api_battles", []).append({"t": round(time.time()), "won": b["won"],
                                                            "crowns": [b["crowns"], b["their_crowns"]],
                                                            "their_deck": b["their_deck"], "levels": [mine, theirs]})
                mem.d["api_battles"] = mem.d["api_battles"][-300:]
        except Exception:
            pass
        if self.s.get("notify", True):
            try: self.notify(f"📋 ديك الخصم كامل: {deck}\nمتوسط اللفل: أنا {mine:.1f} — هو {theirs:.1f}")
            except Exception: pass
    threading.Thread(target=work, daemon=True, name="cr-api-battle").start()


def _pick_deck(self):
    """The strongest deck the player owns, from the official API and today's meta -> copied into the game."""
    from royale import cr_api, deck_pick
    acc = _u().INSTANCE_ID
    if not cr_api.tag(acc):
        # no official API: the bot reads the collection from the screen itself (once a week), picks the best deck
        # for these levels from the replays' win rates; the settings' deck when the reading failed
        if not deck_pick.due(acc, every=7 * 86400): return
        if not [c for c in (self.s.get("deck") or []) if c]:
            # the deck in the game is not known yet: one battle first (the bot learns it from its hand), then it is
            # compared with the others — before 5.52.1 a deck was copied in blind on the very first start
            self.log.info("Clash Royale: learning your deck in a battle first, then comparing it with the best others")
            self._pick_after_learn = True
            return
        from royale import collection
        from royale.brain import card, cards_db
        lv = collection.load(acc)
        if not lv:
            self.log.info("Clash Royale: reading the card collection (cards and levels)")
            try: lv = collection.scan(acc, self.log)
            except Exception: self.log.debug("collection scan failed", exc_info=True); lv = {}
        names = {cr_api.key_of(n): n for n in cards_db()}
        cur = [c for c in (self.s.get("deck") or []) if c]
        owned_evo = sorted(set(self.s.get("owned_evo") or []) | set(self.s.get("deck_evo") or []))
        owned_hero = sorted(set(self.s.get("owned_heroes") or []) | set(self.s.get("deck_heroes") or []))
        pick_off = deck_pick.choose_offline(lv, current=cur, evo=owned_evo, heroes=owned_hero) if lv else None
        if pick_off and pick_off.get("keep"):
            deck_pick.mark(acc, {"cards": cur, "why": pick_off["why"]})
            self.log.info(f"Clash Royale: keeping your deck — {pick_off['why']}")
            try: self.notify("🃏 كلاش رويال: ديكك الحالي هو الأحسن ليك (بالتطويرات والهيرو) — مش هغيره\n" + pick_off["why"])
            except Exception: pass
            return
        if not pick_off and cur:
            return                                      # nothing better known: the deck in the game stays
        if pick_off:
            want = [names.get(k, k) for k in pick_off["cards"]]
            self.log.info(f"Clash Royale: the best deck for this account = {', '.join(want)} — {pick_off['why']}")
        else:
            want = [c for c in (self.s.get("wanted_deck") or []) if c]
        if len(want) != 8: return
        want = deck_pick.slot_order(want, owned_evo, owned_hero)       # evolutions / hero into their slots
        ids = [card(c).get("id") for c in want]
        if not all(ids):
            self.log.info("Clash Royale: the wanted deck has a card the bot does not know — not copied")
            return
        pick = {"cards": want, "ids": ids, "why": (pick_off or {}).get("why", "the deck chosen for this account"),
                "current": []}
        self.log.info("Clash Royale: putting in the chosen deck = " + ", ".join(want))
        if deck_pick.apply(acc, pick, self.log, int(self.s.get("deck_slot", 0) or 0)):
            _expect_deck(self, acc, pick, _api_names(self.eyes, [cr_api.key_of(c) for c in want]))
            try: self.notify("🃏 كلاش رويال: حللت حسابك واخترت ديك — " + ", ".join(want) +
                             (f"\n({pick_off['why']})" if pick_off else "") +
                             "\nهتأكد في أول ماتش إنه اتحط فعلاً في اللعبة")
            except Exception: pass
        else:
            try: self.notify("⚠️ كلاش رويال: اخترت ديك " + ", ".join(want) + " بس اللعبة ما فتحتش شباك نسخ الديك — "
                             "الديك ما اتغيرش، وهلعب بالديك اللي عندك وأتعرف عليه من الماتش")
            except Exception: pass
        return
    if not deck_pick.due(acc): return
    owned_hero = sorted(set(self.s.get("owned_heroes") or []) | set(self.s.get("deck_heroes") or []))
    try:
        pick = deck_pick.choose(acc, heroes=owned_hero)
    except Exception as e:
        self.log.info(f"Clash Royale: picking a deck — {e}")
        return
    if not pick:
        self.log.info("Clash Royale: no proven deck you own all 8 cards of — keeping your deck")
        return
    if pick.get("keep") or sorted(pick["cards"]) == sorted(pick.get("current") or []):
        deck_pick.mark(acc, {"cards": pick.get("current") or pick["cards"], "why": pick["why"]})
        self.log.info(f"Clash Royale: keeping your deck — {pick['why']}")
        try: self.notify("🃏 كلاش رويال: ديكك الحالي هو الأحسن ليك (بلفلاتك وتطويراتك والهيرو) — مش هغيره\n" + pick["why"])
        except Exception: pass
        return
    names_of = {cr_api.key_of(n): n for n in __import__("royale.brain", fromlist=["cards_db"]).cards_db()}
    order = deck_pick.slot_order(pick["cards"], pick.get("evo") or [], [cr_api.key_of(h) for h in owned_hero])
    pick["ids"] = [pick["ids"][pick["cards"].index(c)] for c in order]
    pick["cards"] = order
    self.log.info("Clash Royale: the strongest deck you own now = " + ", ".join(pick["cards"]) + f" — {pick['why']}")
    ok = deck_pick.apply(acc, pick, self.log, int(self.s.get("deck_slot", 0) or 0))
    if ok:
        _expect_deck(self, acc, pick, _api_names(self.eyes, pick["cards"]))
        self._api_deck = None
        self._api_start()                                  # the official API then says which deck is really in
        try: self.notify("🃏 كلاش رويال: اخترت أقوى ديك عندك — " + ", ".join(pick["cards"]) + f"\n({pick['why']})"
                         "\nهتأكد في أول ماتش إنه اتحط فعلاً في اللعبة")
        except Exception: pass
    else:
        self.log.info("Clash Royale: the game did not show the copy-deck window — deck not changed")


def _expect_deck(self, acc, pick, names):
    """The copy was tapped: the eyes are NOT told the new deck (before 5.52.1 they were, and when the game had
    not really changed it the bot looked only for cards it did not have and played blind). The deck is learned
    from the first battle's hand as always and compared with this."""
    self._expected_deck = {"acc": acc, "pick": pick, "names": sorted(names)} if len(names) == 8 else None
    self.eyes.set_deck([]); self.eyes.seen_counts = {}
    self.brain.deck = []


def _check_deck(self):
    """The deck seen in battle vs the deck the bot put in -> told; when it is not in, tried again (max 2)."""
    from royale import deck_pick
    exp = getattr(self, "_expected_deck", None)
    if not exp: return
    self._expected_deck = None
    seen = sorted(self.eyes.deck)
    if seen == exp["names"]:
        self.log.info("Clash Royale: the chosen deck is really in the game")
        try: self.notify("✅ كلاش رويال: اتأكدت — الديك الجديد متحط في اللعبة: " + ", ".join(self.eyes.deck))
        except Exception: pass
        return
    self.log.info("Clash Royale: the deck in the game is NOT the chosen one: " + ", ".join(self.eyes.deck))
    deck_pick.forget(exp["acc"])
    self._deck_tries = getattr(self, "_deck_tries", 0) + 1
    if self._deck_tries < 2: self._deck_checked = False         # once more at the next menu
    try: self.notify("⚠️ كلاش رويال: الديك الجديد ما اتحطش في اللعبة — بلعب بالديك اللي فيها: " +
                     ", ".join(self.eyes.deck) + (" — هحاول أحطه تاني" if self._deck_tries < 2 else ""))
    except Exception: pass


def _study_deck(self):
    """The deck is known: studied once (roles, how it attacks, what defends what, its weak spots) -> the brain
    and the phone."""
    from royale import deck_study
    self._studied = sorted(self.eyes.deck)
    try:
        st = deck_study.study(self.eyes.deck, getattr(self.brain, "levels", None),
                              evo=[n for n in self.eyes.deck if n in (self.brain.evo_cards or {})],
                              heroes=getattr(self.brain, "heroes", set()))
    except Exception:
        self.log.debug("deck study failed", exc_info=True)
        return
    if not st: return
    self.s["deck"] = list(self.eyes.deck)
    if getattr(self, "_pick_after_learn", False):            # now the deck is known: compared at the next menu
        self._pick_after_learn = False
        self._deck_checked = False
    self.brain.study = st
    try:                                                 # remembered for the deck choice next time
        import settings
        cfg = settings.load(_u().INSTANCE_ID)
        r = cfg.setdefault("royale", {})
        r["deck_evo"], r["deck_heroes"] = st["evo"], st["heroes"]
        settings.save(_u().INSTANCE_ID, cfg)
        self.s["deck_evo"], self.s["deck_heroes"] = st["evo"], st["heroes"]
    except Exception:
        pass
    self.log.info("Clash Royale: deck studied — " + st["text_ar"].replace("\n", " | "))
    try: self.notify(st["text_ar"])
    except Exception: pass


def _cards_study_due(self):
    """Once a week (royale.scan_cards), or when the app's "Study my cards now" button asked."""
    from royale import card_scan
    if getattr(self, "_cards_studied_at", 0) and time.time() - self._cards_studied_at < 600: return False
    try:
        import settings
        req = float((settings.load(_u().INSTANCE_ID).get("royale") or {}).get("card_scan_request") or 0)
    except Exception:
        req = 0
    if req > getattr(self, "_cards_studied_at", 0) and time.time() - req < 3600: return True
    return bool(self.s.get("scan_cards", True)) and card_scan.due(_u().INSTANCE_ID)


def _study_cards(self):
    from royale import card_scan
    self._cards_studied_at = time.time()
    self.log.info("Clash Royale: studying every card (Info page of each)")
    try:
        n = card_scan.scan(_u().INSTANCE_ID, self.log, self.brain, on_done=self._cards_read)
    except Exception:
        self.log.debug("card study failed", exc_info=True)
        return
    try: self.notify(f"📸 كلاش رويال: صورت صفحات {n} كارت بسرعة — بقراهم وببعتهم للتحليل وأنا بكمل لعب")
    except Exception: pass


def _cards_read(self, pages):
    """The card pictures were read (in the background): what they said goes to the settings, the eyes and the
    deck choice."""
    try: self.eyes.set_deck(self.eyes.deck)                 # the new pictures go into the card reader
    except Exception: pass
    evo = sorted({p["name"] for p in pages.values() if p.get("name") and p["form"] == "evolution"})
    hero = sorted({p["name"] for p in pages.values() if p.get("name") and p["form"] == "hero"})
    deck = []
    for p in pages.values():
        if p.get("in_deck") and p.get("name") and p["name"] not in deck: deck.append(p["name"])
    try:                                    # remembered: the deck in the game now, the evolutions / heroes owned
        import settings
        cfg = settings.load(_u().INSTANCE_ID)
        r = cfg.setdefault("royale", {})
        r["owned_evo"] = sorted(set(r.get("owned_evo") or []) | set(evo))
        r["owned_heroes"] = sorted(set(r.get("owned_heroes") or []) | set(hero))
        if len(deck) == 8: r["deck"] = deck
        settings.save(_u().INSTANCE_ID, cfg)
        self.s.update({"owned_evo": r["owned_evo"], "owned_heroes": r["owned_heroes"]})
        if len(deck) == 8: self.s["deck"] = deck
    except Exception:
        self.log.debug("saving the card study failed", exc_info=True)
    # now everything is known: the deck is chosen right away (and copied in only if clearly better)
    if self.s.get("auto_deck", True) and len(pages) >= 20:
        from royale import deck_pick
        deck_pick.forget(_u().INSTANCE_ID)
        self._deck_checked = False
        self._pick_after_learn = False
    try:
        self.notify(f"✅ كلاش رويال: قريت {len(pages)} كارت من الصور وبعتهم للتحليل"
                    + (f"\nمتطور: {', '.join(evo)}" if evo else "") + (f"\nهيرو: {', '.join(hero)}" if hero else ""))
    except Exception:
        pass


def _say(self, ar, en=None, phone=False):
    """What the bot is doing, in words the user reads (the app's live log; the phone when it matters)."""
    self.log.info(f"Clash Royale: {en or ar}" if en else ar)
    if phone:
        try: self.notify(ar)
        except Exception: pass


def _go_ok(self):
    """Ask before each battle (royale.confirm_battles, off by default): the bot waits in the lobby until the
    app's "Start a battle" button is pressed; one press = one battle. Off: it plays battle after battle."""
    if not self.s.get("confirm_battles", False): return True       # off by default: plays by itself
    try:
        import settings
        go = float((settings.load(_u().INSTANCE_ID).get("royale") or {}).get("go_request") or 0)
    except Exception:
        go = 0
    if go > getattr(self, "_go_used", 0):
        self._go_used = go
        self._waiting_told = False
        self._status("now")
        self._say("▶️ كلاش رويال: دوست ابدأ — داخل ماتش دلوقتي", "Start pressed — going into a battle")
        return True
    if not getattr(self, "_waiting_told", False):
        self._waiting_told = True
        self._status("waiting_start")
        self._say("⏸️ كلاش رويال: جاهز ومستنيك — دوس «ابدأ ماتش» في البرنامج عشان أدخل الماتش",
                  "ready, waiting for the Start button", phone=True)
    return False


def _recover(self, err):
    """The emulator / ADB is gone: LDPlayer started again (when it is closed), ADB reconnected, the game opened."""
    n = self._frame_fails
    if n == 1:
        self._say(f"⚠️ كلاش رويال: الاتصال بـ LDPlayer اتقطع ({type(err).__name__}) — بحاول أرجّعه",
                  f"LDPlayer / ADB lost ({err}) — bringing it back", phone=True)
    try:
        u = _u()
        try:
            if not u.Emulator_Manager.check(): u.Emulator_Manager.start()
        except Exception:
            self.log.debug("emulator start failed", exc_info=True)
        u.ADB_Manager._adbutils_device = None
        if u.ADB_Manager.connect(timeout=60):
            start_game(self.log)
            self._say("✅ كلاش رويال: رجعت اتوصلت باللعبة وبكمّل", "reconnected, going on", phone=n > 1)
            self._frame_fails = 0
            return
    except Exception:
        self.log.debug("recovering the emulator failed", exc_info=True)
    time.sleep(min(60, 5 * n))


def _status(self, st):
    """The app's status line: "now" = running, "waiting_start" = ready, waiting for Start a battle."""
    if getattr(self, "_last_status", None) == st: return
    self._last_status = st
    try: _u().update_status(st)
    except Exception: pass


def _engine_turn(self, st, d, ready, el):
    """The battle engine thinks the move through: plays the best candidate, keeps the brain's, or waits."""
    from royale import engine
    now = time.monotonic()
    enemies = bool(self.brain._stable)
    if not d and not enemies:
        try:
            from royale import engine_ai
            if not engine_ai.weights(): return d                   # nothing to think about without a trained AI
        except Exception:
            return d
    if not d and now - getattr(self, "_engine_t", 0) < 0.4: return d      # defense thinking: ~2 times a second
    self._engine_t = now
    res = engine.think(self.brain, st, st["hand"], [(i, st["hand"][i]) for i in ready], el, d, self.log)
    if not res: return d
    if res[0] == "wait":
        if d:
            self.brain.undo(d)
            self._engine_drops = getattr(self, "_engine_drops", 0) + 1
        if now - getattr(self, "_engine_wait_log", 0) > 5:
            self._engine_wait_log = now
            self.log.info("Clash Royale: " + res[1])
        return None
    _, i, n, tile, why = res
    if d and d["card"] == n and tuple(d["tile"]) == tuple(tile):
        d["why"] = f"{d['why']} | {why}"
        return d
    if d: self.brain.undo(d)
    return self.brain.play_ai(i, n, tile, why, time.monotonic(), engine_ok=True)   # weighed with card_use.penalty


RoyaleBot._engine_turn = _engine_turn
def _start_training_camp(self):
    """Lobby -> the menu (the three lines at the top right) -> Training Camp -> its battle button.
    -> True when a battle is starting."""
    log = self.log
    menu = None
    for _ in range(2):
        ws = words(frame())
        if find_word(ws, "training camp", "training", y_max=0.9): break
        tap(0.93, 0.10)                                       # the menu button (no text on it)
        time.sleep(1.2)
    ws = words(frame())
    tc = find_word(ws, "training camp", "training", y_max=0.9)
    if not tc:
        log.info("Clash Royale: the Training Camp button was not found in the menu — closing it")
        tap(0.5, 0.97)
        return False
    log.info("Clash Royale: Training Camp (a battle against the trainer, no trophies)")
    tap(*tc)
    time.sleep(1.5)
    for _ in range(6):                                        # its own screen: a Battle / Play / Start / OK button
        fr = frame()
        if __import__("royale.eyes", fromlist=["in_battle"]).in_battle(fr): return True
        ws = words(fr)
        if any(any(n in t for n in NEVER) for t, _ in ws): break
        go = find_word(ws, "battle", "play", "start", "fight", "ok", "yes", y_min=0.3)
        if go:
            tap(*go)
            time.sleep(1.5)
            return True
        time.sleep(1.0)
    return True


RoyaleBot._start_training_camp = _start_training_camp
def _gate_after_battle(self):
    """Between battles: a newer trained version is tested against the one in use (its own process, paused while
    a battle runs)."""
    from royale import engine_ai, engine
    import threading
    deck = list(self.brain.deck or self.eyes.deck or [])
    # the self-play AI trains by itself between battles on this deck (paused while a battle runs)
    if self.s.get("ai_self_play", True) and engine.ready() and len(deck) == 8 and not engine_ai.running():
        # Expert Iteration (royale.exit_train): the arena brain learns the engine's best answers on this PC's GPU
        try:
            from royale import exit_train
            if not exit_train.missing() and not exit_train.running():
                ok, msg = exit_train.start(deck, _u().INSTANCE_ID)
                self.log.info("Clash Royale AI: " + msg)
            if exit_train.running(): return
        except Exception:
            self.log.debug("expert iteration start failed", exc_info=True)
        miss = engine_ai.missing()
        if miss:
            if not getattr(self, "_train_missing_told", False):
                self._train_missing_told = True
                self.log.info("Clash Royale AI: self-play training needs " + ", ".join(miss) +
                              " (the app's Royale page installs them) — the AI plays with what it has")
        else:
            try:
                ok, msg = engine_ai.start(deck, self.log)
                self.log.info("Clash Royale AI: self-play training " + ("started — " if ok else "not started — ") + msg)
            except Exception:
                self.log.debug("self-play start failed", exc_info=True)
    if not engine_ai.newest() or getattr(self, "_gate_running", False): return

    def _gate():
        self._gate_running = True
        try:
            msg = engine_ai.gate_in_background(deck)
            if msg:
                self.log.info("Clash Royale AI: " + msg)
                try: self.notify("🤖 كلاش رويال: " + msg)
                except Exception: pass
        finally:
            self._gate_running = False
    threading.Thread(target=_gate, daemon=True, name="ai-gate").start()


RoyaleBot._gate_after_battle = _gate_after_battle
RoyaleBot._status = _status
RoyaleBot._say = _say
RoyaleBot._go_ok = _go_ok
RoyaleBot._recover = _recover
RoyaleBot._cards_study_due = _cards_study_due
RoyaleBot._study_cards = _study_cards
RoyaleBot._cards_read = _cards_read
RoyaleBot._study_deck = _study_deck
RoyaleBot._check_deck = _check_deck
RoyaleBot._pick_deck = _pick_deck
RoyaleBot._api_start = _api_start
RoyaleBot._api_after_battle = _api_after_battle


def _save_deck(deck):
    """The deck seen in battle -> the settings, unless the account's real decks are written down and this is none
    of them (a misread deck saved there confirmed itself, 5.92)."""
    try:
        from royale.eyes import Eyes
        known = Eyes.known_decks()
        if known and not any(sorted(deck) == sorted(k) for k in known): return
    except Exception:
        pass
    import settings
    s = settings.load(_u().INSTANCE_ID)
    r = s.setdefault("royale", {})
    if r.get("deck") != deck:
        r["deck"] = list(deck)
        settings.save(_u().INSTANCE_ID, s)


def run():
    """Entry from the launcher in Clash Royale mode."""
    import settings
    u = _u()
    s = settings.load(u.INSTANCE_ID).get("royale", {}) or {}
    RoyaleBot(s, u.logger, u.send_notification).run()
