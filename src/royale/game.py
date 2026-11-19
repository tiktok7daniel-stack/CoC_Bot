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
LOOK_EVERY = 0.2           # seconds between looks in a battle


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

    # -------------------------------------------------------------- one battle
    def battle(self):
        from royale.eyes import in_battle, tile_xy, card_xy
        log = self.log
        from royale import learn
        self.params = learn.choose(_u().INSTANCE_ID)              # this battle's way of playing (learned)
        self.brain.p = dict(learn.DEFAULT, **self.params)
        self.brain.reset()
        self.battles += 1
        log.info("Clash Royale: this battle's settings " + ", ".join(f"{k}={v}" for k, v in self.params.items()))
        log.info(f"Clash Royale: battle #{self.battles}")
        out_since, last = None, None
        plays = 0
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
                st = self.eyes.look(fr)
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
                     (__import__("royale.brain", fromlist=["card"]).card(st["hand"][i]).get("cost", 11) <= el)]
            d = self.brain.decide(st["hand"], ready, el, st["enemies"], st["allies"], st["towers"])
            if self.brain.arch and self.brain.arch != getattr(self, "_arch_logged", None):
                self._arch_logged = self.brain.arch
                log.info(f"Clash Royale: their deck looks like {self.brain.arch} "
                         f"({', '.join(sorted(self.brain.enemy_seen))}) — playing against it")
            if d:
                self._spent = (__import__("royale.brain", fromlist=["card"]).card(d["card"]).get("cost", 4),
                               time.monotonic(), el)
                cx, cy = card_xy(d["slot"])
                tx, ty = tile_xy(*d["tile"])
                tap(cx, cy)
                time.sleep(0.04)
                tap(tx, ty)
                plays += 1
                log.info(f"Clash Royale: {d['card']} -> tile {d['tile']} ({d['why']}) — elixir {st['elixir']:.0f}, "
                         f"theirs ~{self.brain.enemy_elixir:.0f}")
            last = st
            time.sleep(max(0.0, LOOK_EVERY - (time.monotonic() - t0)))
        log.info(f"Clash Royale: battle over — {plays} cards played")
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
                    won = win[1] > 0.45
                    self.wins += won
                    self.losses += not won
                    try:
                        from royale import learn
                        if not getattr(self, "_tutorial_battle", False):     # the tutorial's battles teach nothing
                            learn.record(_u().INSTANCE_ID, getattr(self, "params", {}) or {}, won)
                        self._tutorial_battle = False
                    except Exception:
                        log.debug("Clash Royale: learning failed", exc_info=True)
                    log.info(f"Clash Royale: {'WIN' if won else 'loss'} — {self.wins} won / {self.losses} lost")
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
