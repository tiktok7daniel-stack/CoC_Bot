"""
The Clash Royale account, looked after by the bot between battles (like a player who also does his chores):

  cards     every card that can be upgraded with GOLD is upgraded (deck cards first). Never gems: any screen that
            says gems / buy / not enough is backed out of
  clan      donates to the clan's requests (free: gold + XP for us) and asks for cards when the request is ready
  rewards   free rewards that wait in the lobby (claim / collect / free) are taken
  mastery   card mastery rewards (Cards tab: a card's Mastery page -> Claim) are collected
  gifts     gifts in the clan chat (sent by a member with the Pass) are claimed
  shop      the shop's FREE daily offer is taken (only a button that says FREE — never one with a price)
  war       Clan War (River Race) battles: the bot plays the day's war battles with the war decks
  report    once a day: battles, wins, upgrades, donations -> the phone

Every step reads the screen (OCR) before it taps and goes back to the Battle tab when anything is unexpected.
Bottom tabs of the game (portrait): Shop | Cards | Battle | Clan | Events.
"""
import json, time
from datetime import date
from pathlib import Path

TAB_Y = 0.955
TABS = {"shop": 0.1, "cards": 0.3, "battle": 0.5, "clan": 0.7, "events": 0.9}
NEVER = ("gem", "buy", "purchase", "not enough", "get more", "speed up", "open now", "offer", "$", "€", "pass royale",
         "subscribe", "log out", "logout", "exit", "quit", "leave", "delete", "magic item", "wild card", "book of")
DIR = Path.home() / ".CoC_Bot" / "learn"


def _g():
    from royale import game
    return game


def _ws():
    g = _g()
    return g.words(g.frame())


def _has(ws, *names):
    return any(any(n in t for n in names) for t, _ in ws)


def _bad(ws):
    return _has(ws, *NEVER)


def _back(log=None):
    """Out of any popup, back on the Battle tab."""
    g = _g()
    for _ in range(3):
        try:
            if not __import__("utils").tap_red_x(): break
        except Exception:
            break
        time.sleep(0.8)
    g.tap(TABS["battle"], TAB_Y)
    time.sleep(1.2)


def _tab(name):
    _g().tap(TABS[name], TAB_Y)
    time.sleep(1.6)
    return _ws()


class Account:
    def __init__(self, acc, log, notify):
        self.acc, self.log, self.notify = acc, log, notify
        self.p = DIR / f"royale_account_{''.join(c for c in str(acc) if c.isalnum() or c in '-_') or 'main'}.json"
        try:
            self.d = json.loads(self.p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.d = {}
        self.last_run = 0.0

    def _save(self):
        try:
            DIR.mkdir(parents=True, exist_ok=True)
            self.p.write_text(json.dumps(self.d, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def count(self, what, n=1):
        day = self.d.setdefault("days", {}).setdefault(date.today().isoformat(), {})
        day[what] = day.get(what, 0) + n
        self._save()

    # -------------------------------------------------------------- when
    def due(self, battles):
        return time.monotonic() - self.last_run > 25 * 60 or (battles and battles % 6 == 0 and
                                                               time.monotonic() - self.last_run > 5 * 60)

    def run(self):
        """One round of chores (a few minutes at most)."""
        self.last_run = time.monotonic()
        steps = [self.rewards, self.upgrade_cards, self.mastery, self.clan, self.shop_free, self.report]
        if self.war_due(): steps.insert(-1, self.war)
        self.war_started = False
        for step in steps:
            try:
                step()
            except Exception:
                self.log.debug(f"Clash Royale account: {step.__name__} failed", exc_info=True)
            if self.war_started:                     # a war battle is starting: the battle loop takes it from here
                return
            _back()

    # -------------------------------------------------------------- cards
    def upgrade_cards(self, max_n=6):
        g = _g()
        ws = _tab("cards")
        if not _has(ws, "collection", "battle deck", "deck", "cards", "found"):
            self.log.info("Clash Royale account: the Cards tab did not open — skipped")
            return
        done = 0
        for _ in range(max_n):
            ws = _ws()
            if _bad(ws): break
            up = [b for t, b in ws if t.startswith("upgrade") and (b[2] + b[4]) / 2 < 0.9]
            if not up: break
            b = up[0]
            g.tap((b[1] + b[3]) / 2, (b[2] + b[4]) / 2 - 0.03)            # the card above its "Upgrade" bar
            time.sleep(1.0)
            ws = _ws()
            btn = g.find_word(ws, "upgrade", y_min=0.3)
            if not btn or _bad(ws):
                _back(); _tab("cards"); continue
            g.tap(*btn)                                                    # the card's Upgrade button
            time.sleep(1.2)
            ws = _ws()
            if _bad(ws):                                                   # not enough gold -> it asks for gems
                self.log.info("Clash Royale account: not enough gold for the next upgrade — stopped")
                break
            conf = g.find_word(ws, "upgrade", "confirm", y_min=0.4)
            if conf:
                g.tap(*conf)                                               # pay with gold
                time.sleep(2.5)
            for _ in range(6):                                             # the level-up show: tap through
                ws = _ws()
                if _bad(ws): break
                nxt = g.find_word(ws, "ok", "continue", "tap to", "close", y_min=0.4)
                if nxt: g.tap(*nxt)
                else: g.tap(0.5, 0.82)
                time.sleep(0.9)
                if _has(ws, "collection", "battle deck"): break
            done += 1
            self.count("upgrades")
            self.log.info(f"Clash Royale account: a card upgraded with gold ({done})")
            _back(); _tab("cards")
        if done:
            try: self.notify(f"⬆️ كلاش رويال: رقّيت {done} كارت بالدهب")
            except Exception: pass

    # -------------------------------------------------------------- clan
    def clan(self, max_donate=8):
        g = _g()
        ws = _tab("clan")
        if _bad(ws) or not _has(ws, "clan", "request", "donate", "chat", "members"):
            return
        given = 0
        for _ in range(max_donate):
            ws = _ws()
            if _bad(ws): break
            d = g.find_word(ws, "donate", y_min=0.1, y_max=0.9)
            if not d: break
            g.tap(*d)
            time.sleep(0.7)
            given += 1
        if given:
            self.count("donations", given)
            self.log.info(f"Clash Royale account: {given} cards donated to the clan")
        self.gifts()
        ws = _ws()
        r = g.find_word(ws, "request", y_min=0.5)
        if r and not _bad(ws):
            g.tap(*r)
            time.sleep(1.2)
            ws = _ws()
            # the card list: the first card offered, then its Request button
            cands = [b for t, b in ws if t.startswith("request") and (b[2] + b[4]) / 2 > 0.3]
            if cands and not _bad(ws):
                b = cands[0]
                g.tap((b[1] + b[3]) / 2, (b[2] + b[4]) / 2)
                time.sleep(1.0)
                self.count("requests")
                self.log.info("Clash Royale account: cards requested from the clan")

    # -------------------------------------------------------------- free rewards
    def _tap_through(self, n=8):
        """A reward show (chest opening, cards flying): tapped through until the screen settles."""
        g = _g()
        for _ in range(n):
            ws = _ws()
            if _bad(ws): return
            nxt = g.find_word(ws, "ok", "continue", "tap to", "close", "collect", y_min=0.35)
            if nxt: g.tap(*nxt)
            elif len([t for t, _ in ws if len(t) > 1]) <= 4: g.tap(0.5, 0.6)
            else: return
            time.sleep(0.9)

    def _claim_loop(self, words, what, y=(0.1, 0.92), most=12, bad=None):
        """Taps buttons that say `words` (claim / collect...) one after the other. -> how many."""
        g = _g()
        bad = bad or _bad
        n = 0
        for _ in range(most):
            ws = _ws()
            if bad(ws): break
            b = g.find_word(ws, *words, y_min=y[0], y_max=y[1])
            if not b: break
            g.tap(*b)
            time.sleep(1.2)
            n += 1
            self._tap_through(5)
        if n:
            self.count(what, n)
        return n

    def rewards(self):
        """Free rewards waiting on the Battle tab (Trophy Road, the Pass's free track, chests ready): claimed."""
        _tab("battle")
        stop = lambda ws: _has(ws, "buy", "purchase", "$", "€", "gems to", "not enough", "open now", "speed up",
                               "subscribe", "leave", "log out", "delete")
        n = self._claim_loop(("claim", "collect", "claim all"), "rewards", bad=stop)
        if n: self.log.info(f"Clash Royale account: {n} free rewards claimed in the lobby")

    def mastery(self):
        """Card Mastery: Cards tab -> the Mastery button / a card's mastery page -> Claim every reward ready."""
        g = _g()
        ws = _tab("cards")
        m = g.find_word(ws, "mastery", "masteries", y_min=0.1, y_max=0.92)
        if not m or _bad(ws):
            return
        g.tap(*m)
        time.sleep(1.5)
        got = 0
        for _ in range(10):                          # every card that has a reward waiting
            ws = _ws()
            if _bad(ws): break
            c = self._claim_loop(("claim", "collect"), "mastery", most=6)
            if not c:
                # a card with a reward waiting is marked: its "claim" / "!" badge opens its page
                r = g.find_word(ws, "reward", "ready", y_min=0.15, y_max=0.92)
                if not r: break
                g.tap(*r)
                time.sleep(1.3)
                if not self._claim_loop(("claim", "collect"), "mastery", most=6): break
                _g().tap(0.5, 0.1)                     # out of the card's page
                time.sleep(0.8)
            got += c
        if got:
            self.log.info(f"Clash Royale account: {got} card mastery rewards collected")

    def gifts(self):
        """The clan chat's gifts (a member with the Pass sends them to everyone): Claim. The gift's text names the
        Pass, so only real spending words stop it here."""
        stop = lambda ws: _has(ws, "buy", "purchase", "$", "€", "gems to", "not enough", "subscribe", "leave",
                               "log out", "delete")
        n = self._claim_loop(("claim", "open gift", "collect"), "gifts", y=(0.12, 0.88), most=10, bad=stop)
        if n: self.log.info(f"Clash Royale account: {n} clan gifts claimed")

    def shop_free(self):
        """The shop's daily FREE offer. Only a button whose own text is "free" is tapped, and the popup after it
        only on its "free" button; anything with a price, buy or purchase is backed out of."""
        g = _g()
        if self.d.get("shop_free") == date.today().isoformat(): return
        ws = _tab("shop")
        if not _has(ws, "shop", "daily", "deals", "free", "offers", "chest"): return
        free = [b for t, b in ws if t.strip(" !.") == "free" and 0.12 < (b[2] + b[4]) / 2 < 0.9]
        if not free:
            self.d["shop_free"] = date.today().isoformat(); self._save()
            return
        b = free[0]
        g.tap((b[1] + b[3]) / 2, (b[2] + b[4]) / 2)
        time.sleep(1.3)
        ws = _ws()
        if _has(ws, "buy", "purchase", "$", "€", "not enough") or any(any(ch.isdigit() for ch in t) and "gem" in t
                                                                     for t, _ in ws):
            self.log.info("Clash Royale account: the shop asked for a price — backed out")
            return
        conf = [b for t, b in ws if t.strip(" !.") in ("free", "claim", "collect")]
        if conf:
            b = conf[0]
            g.tap((b[1] + b[3]) / 2, (b[2] + b[4]) / 2)
            time.sleep(1.5)
        self._tap_through(6)
        self.d["shop_free"] = date.today().isoformat(); self._save()
        self.count("shop_free")
        self.log.info("Clash Royale account: the shop's free daily offer taken")
        try: self.notify("🎁 كلاش رويال: خدت هدية الشوب المجانية بتاعة النهارده")
        except Exception: pass

    # -------------------------------------------------------------- clan war
    def war_due(self):
        day = self.d.get("war_day", {})
        return day.get("d") != date.today().isoformat() or (day.get("n", 0) < 4 and not day.get("none"))

    def war(self):
        """Clan War (River Race): Clan tab -> the war page -> Battle -> the war battle is played by the battle loop
        (royale.game: anything in a battle is played there). At most 4 a day; stops when none is left."""
        g = _g()
        today = date.today().isoformat()
        day = self.d.get("war_day", {})
        if day.get("d") != today: day = {"d": today, "n": 0}
        ws = _tab("clan")
        w = g.find_word(ws, "river race", "clan war", "war", y_min=0.05, y_max=0.9)
        if not w or _bad(ws):
            day["none"] = True; self.d["war_day"] = day; self._save()
            return
        g.tap(*w)
        time.sleep(1.8)
        ws = _ws()
        b = g.find_word(ws, "battle", "duel", "attack", y_min=0.45, y_max=0.95)
        if not b or _bad(ws) or _has(ws, "no battles left", "0/4", "come back"):
            day["none"] = True; self.d["war_day"] = day; self._save()
            return
        g.tap(*b)
        time.sleep(1.8)
        ws = _ws()
        # empty war decks: the game fills one for free ("randomize" / "auto") — the main deck is never touched
        r = g.find_word(ws, "randomize", "random", "auto", y_min=0.3)
        if r and not _bad(ws):
            g.tap(*r); time.sleep(1.0)
            ws = _ws()
        go = g.find_word(ws, "battle", "duel", "start", y_min=0.45)
        if go and not _bad(ws):
            g.tap(*go)
            self.log.info("Clash Royale account: a Clan War battle — the AI plays it")
            day["n"] = day.get("n", 0) + 1
            self.count("war_battles")
        else:
            day["none"] = True
        self.d["war_day"] = day; self._save()
        self.war_started = bool(go)

    # -------------------------------------------------------------- daily report
    def report(self):
        today = date.today().isoformat()
        days = self.d.get("days", {})
        y = [k for k in sorted(days) if k < today]
        if not y or self.d.get("reported") == y[-1]: return
        k = y[-1]
        s = days[k]
        self.d["reported"] = k
        self._save()
        b, w = s.get("battles", 0), s.get("wins", 0)
        txt = (f"📊 تقرير كلاش رويال ({k}) — حساب {self.acc}\n"
               f"ماتشات: {b} — فوز {w} / خسارة {b - w}" + (f" ({100 * w // max(1, b)}%)" if b else "") + "\n"
               f"كروت اترقّت: {s.get('upgrades', 0)} — تبرعات للكلان: {s.get('donations', 0)}\n"
               f"مكافآت: {s.get('rewards', 0)} — ماستري: {s.get('mastery', 0)} — هدايا الكلان: {s.get('gifts', 0)}"
               f" — هدية الشوب: {s.get('shop_free', 0)} — ماتشات الكلان وور: {s.get('war_battles', 0)}")
        self.log.info("Clash Royale account: " + txt.replace("\n", " | "))
        try: self.notify(txt)
        except Exception: pass
