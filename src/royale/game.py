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
        self.notify = notify or (lambda t: None)
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
        self.brain.reset()
        self._battle_t = time.time()
        if getattr(self, "_api_deck", None) and self.eyes.deck != self._api_deck:
            self.eyes.set_deck(self._api_deck)                   # the exact deck from the official API
            self.brain.deck = list(self._api_deck)
        self.battles += 1
        log.info("Clash Royale: this battle's settings " + ", ".join(f"{k}={v}" for k, v in self.params.items()))
        log.info(f"Clash Royale: battle #{self.battles}")
        out_since, last = None, None
        plays = 0
        look_ms, looks, slow_told = 0.0, 0, False
        self._slot_used = {}                                       # slot -> when it was played (picture lags)
        while _u().running():
            t0 = time.monotonic()
            fr = frame()
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
            try:
                tl = time.monotonic()
                st = self.eyes.look(fr)
                look_ms += (time.monotonic() - tl) * 1000; looks += 1
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
            if self.eyes.learn_deck([h for i, h in enumerate(st["hand"]) if i in st["ready"]]):
                log.info("Clash Royale: my deck = " + ", ".join(self.eyes.deck))
                self.brain.deck = list(self.eyes.deck)
                try: _save_deck(self.eyes.deck)
                except Exception: pass
            # what was just spent: the picture can lag a moment behind a play ("Not enough Elixir!")
            el = st["elixir"]
            spent = getattr(self, "_spent", None)
            if spent and time.monotonic() - spent[1] < 1.5:
                el = min(el, max(0.0, spent[2] - spent[0] + (time.monotonic() - spent[1]) / self.brain.seconds_per_elixir()))
            ready = [i for i in st["ready"] if i < len(st["hand"]) and
                     time.monotonic() - self._slot_used.get(i, 0) > 0.8 and
                     (__import__("royale.brain", fromlist=["card"]).card(st["hand"][i]).get("cost", 11) <= el)]
            try:
                d = self.brain.decide(st["hand"], ready, el, st["enemies"], st["allies"], st["towers"],
                                      hp=st.get("hp"), spells=st.get("spells"))
            except Exception:
                log.warning("Clash Royale: a decision failed — next look", exc_info=True)
                d = None
            if self.brain.arch and self.brain.arch != getattr(self, "_arch_logged", None):
                self._arch_logged = self.brain.arch
                log.info(f"Clash Royale: their deck looks like {self.brain.arch} "
                         f"({', '.join(sorted(self.brain.enemy_seen))}) — playing against it")
            if self.brain.predicted and self.brain.predicted != getattr(self, "_pred_logged", None):
                self._pred_logged = set(self.brain.predicted)
                log.info("Clash Royale: their deck probably also has " + ", ".join(sorted(self.brain.predicted)))
            if d:
                self._spent = (__import__("royale.brain", fromlist=["card"]).card(d["card"]).get("cost", 4),
                               time.monotonic(), el)
                self._slot_used[d["slot"]] = time.monotonic()
                cx, cy = card_xy(d["slot"])
                tx, ty = tile_xy(*d["tile"])
                tap(cx, cy)
                time.sleep(0.04)
                tap(tx, ty)
                plays += 1
                log.info(f"Clash Royale: {d['card']} -> tile {d['tile']} ({d['why']}) — elixir {st['elixir']:.0f}, "
                         f"theirs ~{self.brain.enemy_elixir:.0f}")
            last = st
            if self.s.get("keep_frames", True):
                try:
                    from royale import frames
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
        while _u().running():
            if max_b and self.battles >= max_b:
                log.info(f"Clash Royale: {max_b} battles played — done")
                try: self.notify(f"✅ كلاش رويال: خلصت {self.battles} ماتش — {self.wins} فوز / {self.losses} خسارة")
                except Exception: pass
                return
            fr = frame()
            if in_battle(fr):
                self.unknown_since = None
                last = self.battle()
                self.results(last)
                continue
            ws = words(fr)
            b = find_word(ws, "battle", y_min=0.55, y_max=0.9)
            if b and self.s.get("auto_deck", True) and not getattr(self, "_deck_checked", False):
                self._deck_checked = True
                self._pick_deck()
                continue
            if b and self.account and self.account.due(self.battles):
                log.info("Clash Royale: looking after the account (cards, clan, rewards)")
                self.account.run()
                continue
            if b:
                self.unknown_since = None
                self._reward_taps = 0
                log.info("Clash Royale: Battle")
                tap(*b)
                for _ in range(60):                          # matchmaking: up to ~1 minute
                    time.sleep(1)
                    if in_battle(frame()) or not _u().running(): break
                continue
            ok = find_word(ws, "ok", "continue", "tap to continue", "close", y_min=0.5)
            if ok:
                tap(*ok)
                time.sleep(1.5)
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
        from royale import collection
        from royale.brain import card, cards_db
        lv = collection.load(acc)
        if not lv:
            self.log.info("Clash Royale: reading the card collection (cards and levels)")
            try: lv = collection.scan(acc, self.log)
            except Exception: self.log.debug("collection scan failed", exc_info=True); lv = {}
        names = {cr_api.key_of(n): n for n in cards_db()}
        pick_off = deck_pick.choose_offline(lv) if lv else None
        if pick_off:
            want = [names.get(k, k) for k in pick_off["cards"]]
            self.log.info(f"Clash Royale: the best deck for this account = {', '.join(want)} — {pick_off['why']}")
        else:
            want = [c for c in (self.s.get("wanted_deck") or []) if c]
        if len(want) != 8: return
        ids = [card(c).get("id") for c in want]
        if not all(ids):
            self.log.info("Clash Royale: the wanted deck has a card the bot does not know — not copied")
            return
        pick = {"cards": want, "ids": ids, "why": (pick_off or {}).get("why", "the deck chosen for this account"),
                "current": []}
        self.log.info("Clash Royale: putting in the chosen deck = " + ", ".join(want))
        if deck_pick.apply(acc, pick, self.log, int(self.s.get("deck_slot", 0) or 0)):
            names = _api_names(self.eyes, [cr_api.key_of(c) for c in want])
            if len(names) == 8:
                self._api_deck = names
                self.eyes.set_deck(names); self.brain.deck = list(names)
            try: self.notify("🃏 كلاش رويال: حللت حسابك وحطيت أحسن ديك — " + ", ".join(want) +
                             (f"\n({pick_off['why']})" if pick_off else ""))
            except Exception: pass
        return
    if not deck_pick.due(acc): return
    try:
        pick = deck_pick.choose(acc)
    except Exception as e:
        self.log.info(f"Clash Royale: picking a deck — {e}")
        return
    if not pick:
        self.log.info("Clash Royale: no meta deck you own all 8 cards of yet — keeping your deck")
        return
    if sorted(pick["cards"]) == sorted(pick.get("current") or []):
        self.log.info(f"Clash Royale: your deck is already the best pick ({pick['why']})")
        deck_pick._write(acc, pick)
        return
    self.log.info("Clash Royale: the strongest deck you own now = " + ", ".join(pick["cards"]) + f" — {pick['why']}")
    ok = deck_pick.apply(acc, pick, self.log, int(self.s.get("deck_slot", 0) or 0))
    if ok:
        names = _api_names(self.eyes, pick["cards"])
        if len(names) == 8:
            self._api_deck = names
            self.eyes.set_deck(names); self.brain.deck = list(names)
        try: self.notify("🃏 كلاش رويال: اخترت أقوى ديك عندك — " + ", ".join(pick["cards"]) + f"\n({pick['why']})")
        except Exception: pass
    else:
        self.log.info("Clash Royale: the game did not show the copy-deck window — deck not changed")


RoyaleBot._pick_deck = _pick_deck
RoyaleBot._api_start = _api_start
RoyaleBot._api_after_battle = _api_after_battle


def _save_deck(deck):
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
