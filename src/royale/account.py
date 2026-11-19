"""
The Clash Royale account, looked after by the bot between battles (like a player who also does his chores):

  cards     every card that can be upgraded with GOLD is upgraded (deck cards first). Never gems: any screen that
            says gems / buy / not enough is backed out of
  clan      donates to the clan's requests (free: gold + XP for us) and asks for cards when the request is ready
  rewards   free rewards that wait in the lobby (claim / collect / free) are taken
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
        for step in (self.upgrade_cards, self.clan, self.report):
            try:
                step()
            except Exception:
                self.log.debug(f"Clash Royale account: {step.__name__} failed", exc_info=True)
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
               f"كروت اترقّت: {s.get('upgrades', 0)} — تبرعات للكلان: {s.get('donations', 0)}")
        self.log.info("Clash Royale account: " + txt.replace("\n", " | "))
        try: self.notify(txt)
        except Exception: pass
