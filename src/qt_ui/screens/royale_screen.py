"""
Clash Royale: the app's own screen for the Clash Royale mode. When an account plays Clash Royale this is the only
game screen the app shows (the Clash of Clans screens are hidden until the account plays Clash of Clans again).

  the game          switch back to Clash of Clans
  today             battles / wins / losses / win rate (from this session's log)
  my deck           the 8 card pictures (found by the bot in the first battle)
  how it plays      stop after N battles, results on Telegram
  setup             what LDPlayer / the game need
  live              what the brain is doing now (its log lines: card -> tile, why, elixir)
"""
import os, re, sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..i18n import on_lang, tr
from ..theme import TOKENS
from ..widgets.controls import GlassCard, combo_row, form_row, label, num_row, toggle_row
from ..widgets.log_view import LogView
from .base import Screen, grid, page

_ROOT = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CARDS_DIR = os.path.join(_ROOT, "assets", "royale", "cards")


class _Stat(QWidget):
    def __init__(self, key, color):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(2)
        self.value = QLabel("0")
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setStyleSheet(f"font-size: 30px; font-weight: 800; color: {color};")
        v.addWidget(self.value)
        cap = label(key=key, role="sub")
        cap.setAlignment(Qt.AlignCenter)
        v.addWidget(cap)


class RoyaleScreen(Screen):
    key, title_key, icon_name = "royale", "royale_screen_title", "bolt"

    def __init__(self, ctx):
        super().__init__(ctx)
        sa, v = page()
        self.root.addWidget(sa)

        # ---------- this account is not a Clash Royale account (yet): say it, one tap fixes it
        from ..widgets.controls import IconButton
        self.not_royale = GlassCard("royale_not_title", "bolt", "royale_not_sub", glow=True)
        fix = IconButton("check", "royale_make", kind="go", size=15)
        fix.clicked.connect(self.make_royale)
        self.not_royale.add(fix)
        v.addWidget(self.not_royale)
        self.store.loaded.connect(self.check_account)
        self.store.account_changed.connect(lambda _a: self.check_account())

        # ---------- the game + today
        w1, g1 = grid(2)
        game = GlassCard("game_title", "layers", "game_sub")
        game.add(combo_row(self.store, "game_mode", "game_mode", [("coc", "gm_coc"), ("royale", "gm_royale")], width=320))
        g1.addWidget(game, 0, 0)
        today = GlassCard("royale_today", "chart", "royale_today_sub", glow=True)
        row = QHBoxLayout()
        self.s_battles = _Stat("royale_battles", TOKENS["text"])
        self.s_wins = _Stat("royale_wins", "#4ade80")
        self.s_losses = _Stat("royale_losses", "#f87171")
        self.s_rate = _Stat("royale_rate", TOKENS.get("gold", "#f5b740"))
        for s in (self.s_battles, self.s_wins, self.s_losses, self.s_rate): row.addWidget(s, 1)
        holder = QWidget()
        holder.setLayout(row)
        today.add(holder)
        g1.addWidget(today, 0, 1)
        v.addWidget(w1)

        # ---------- my deck (the 8 cards)
        deck = GlassCard("royale_deck", "bolt", "royale_deck_sub")
        self.deck_grid = QGridLayout()
        self.deck_grid.setSpacing(10)
        self.deck_slots = []
        for i in range(8):
            box = QVBoxLayout()
            pic = QLabel()
            pic.setFixedSize(84, 100)
            pic.setAlignment(Qt.AlignCenter)
            pic.setStyleSheet(f"background: {TOKENS['glass2']}; border: 1px solid {TOKENS['border']}; border-radius: 12px;")
            name = QLabel("")
            name.setAlignment(Qt.AlignCenter)
            name.setProperty("role", "sub")
            box.addWidget(pic, 0, Qt.AlignHCenter)
            box.addWidget(name)
            cell = QWidget()
            cell.setLayout(box)
            self.deck_grid.addWidget(cell, 0, i)
            self.deck_slots.append((pic, name))
        dw = QWidget()
        dw.setLayout(self.deck_grid)
        deck.add(dw)
        self.deck_note = label("", "dim", wrap=True)
        deck.add(self.deck_note)
        v.addWidget(deck)

        # ---------- how it plays + setup
        w2, g2 = grid(2)
        play = GlassCard("royale_title", "swords", "royale_sub")
        play.add(num_row(self.store, "royale_max", "royale.max_battles", "royale_max_sub", lo=0, hi=10000, width=120))
        play.add(toggle_row(self.store, "royale_notify", "royale.notify", "royale_notify_sub"))
        play.add(toggle_row(self.store, "royale_safe", "royale.safe_play", "royale_safe_sub"))
        play.add(toggle_row(self.store, "royale_ask", "royale.ask_before_battle", "royale_ask_sub"))
        from ..widgets.controls import IconButton as _IBg
        go = _IBg("play", "royale_go", kind="go", size=16)
        go.clicked.connect(self.go_battle)
        play.add(go)
        g2.addWidget(play, 0, 0)
        setup = GlassCard("royale_setup", "sliders", "royale_setup_sub")
        for k in ("royale_need_1", "royale_need_2", "royale_need_3", "royale_need_4"):
            setup.add(label(key=k, role="sub", wrap=True))
        g2.addWidget(setup, 0, 1)
        v.addWidget(w2)

        # ---------- the official Clash Royale API: exact deck, levels, results, the meta
        from PySide6.QtWidgets import QLineEdit
        from ..widgets.controls import bind_line
        from .bot_settings_screen import secret_field
        api = GlassCard("royale_api", "key", "royale_api_sub")
        tg = QLineEdit(); tg.setPlaceholderText("#2PP0JCLQ8"); tg.setLayoutDirection(Qt.LeftToRight); tg.setFixedWidth(200)
        bind_line(self.store, tg, "royale.tag")
        api.add(form_row("royale_tag", None, tg))
        api.add(form_row("royale_api_key", "royale_api_key_sub", secret_field(self.store, "royale_api_key", "eyJ0eXAiOiJKV1Qi…")))
        em = QLineEdit(); em.setLayoutDirection(Qt.LeftToRight); em.setMinimumWidth(260)
        bind_line(self.store, em, "royale_dev_email", "app")
        api.add(form_row("royale_dev_email", "royale_dev_email_sub", em))
        api.add(form_row("royale_dev_pass", None, secret_field(self.store, "royale_dev_password", "••••••••")))
        api.add(toggle_row(self.store, "royale_auto_deck", "royale.auto_deck", "royale_auto_deck_sub"))
        api.add(num_row(self.store, "royale_deck_slot", "royale.deck_slot", "royale_deck_slot_sub", lo=0, hi=10, width=90))
        api.add(toggle_row(self.store, "royale_scan_cards", "royale.scan_cards", "royale_scan_cards_sub"))
        from ..widgets.controls import IconButton as _IB
        sc = _IB("camera", "royale_scan_now", size=14)
        sc.clicked.connect(self.scan_cards_now)
        api.add(sc)
        v.addWidget(api)

        # ---------- training the eyes on this PC
        train = GlassCard("royale_train", "school", "royale_train_sub")
        self.train_state = label("", "sub", wrap=True)
        train.add(self.train_state)
        train.add(toggle_row(self.store, "royale_auto_train", "royale.auto_train", "royale_auto_train_sub"))
        from ..widgets.controls import IconButton
        b = IconButton("play", "royale_train_now", size=14)
        b.clicked.connect(self.train_now)
        train.add(b)
        v.addWidget(train)
        from PySide6.QtCore import QTimer
        self._tt = QTimer(self)
        self._tt.timeout.connect(self.show_training)
        self._tt.start(8000)
        self.show_training()

        # ---------- live: the brain's decisions
        live = GlassCard("royale_live", "terminal", "royale_live_sub")
        self.log = LogView(mini=True)
        self.log.setMinimumHeight(260)
        live.add(self.log)
        v.addWidget(live)

        self.store.bind("s", "royale.deck", self.show_deck)
        self.store.loaded.connect(lambda: self.show_deck(self.store.get("royale.deck", [])))
        self.poller.log.connect(self.on_log)
        self.show_deck(self.store.get("royale.deck", []))
        on_lang(lambda: self.show_deck(self.store.get("royale.deck", [])))

    # -------------------------------------------------------------- the account's game
    def check_account(self):
        games = self.store.APP.get("account_games") or {}
        acc = self.store.account
        self.not_royale.setVisible(bool(acc) and games.get(acc, "coc") != "royale")

    def make_royale(self):
        acc = self.store.account
        def done(r):
            if isinstance(r, dict) and r.get("ok"):
                self.store.APP.setdefault("account_games", {})[acc] = "royale"
                self.ctx.toast(tr("acc_game_set").replace("{a}", acc).replace("{g}", tr("gm_royale")), "ok")
                self.store.load_all(lambda ok: (self.ctx.window.apply_game_mode(force=True), self.check_account()))
        self.api.post(f"/api/account/{acc}/game", {"mode": "royale"}, done)

    def on_show(self):
        self.check_account()

    # -------------------------------------------------------------- training
    def show_training(self):
        try:
            import sys as _s
            _s.path.insert(0, _ROOT + "/src") if (_ROOT + "/src") not in _s.path else None
            from royale import trainer
            st = trainer.read_status()
        except Exception:
            st = {}
        stage = st.get("stage")
        if not stage:
            st = {"stage": "none"}
            stage = "none"
        txt = tr("rt_" + stage) if tr("rt_" + stage) != "rt_" + stage else stage
        if st.get("note"): txt += " — " + str(st["note"])
        if st.get("base_map50") is not None and st.get("new_map50") is not None:
            txt += f"\n{tr('rt_score')}: {st['base_map50']:.2f} → {st['new_map50']:.2f}" + (f" ✅ {tr('rt_used')}" if st.get("used") else "")
        if st.get("error"): txt += "\n⚠ " + str(st["error"])
        try:                                   # the other two brains: the learned network and the own pictures
            from royale import policy, frames
            ti = policy.info()
            if ti:
                txt += f"\n🧠 {tr('rt_policy')}: {100 * ti.get('card_in_hand', 0):.0f}% / {100 * ti.get('play', 0):.0f}%"
            from royale import board as _bb
            bi = _bb.info()
            if bi:
                txt += f"\n🧩 {tr('rt_board')}: {100 * bi.get('card_in_hand', 0):.0f}% / {100 * bi.get('tile_within1', 0):.0f}%"
            txt += f"\n📷 {tr('rt_frames')}: {frames.count()}"
            from royale import selfplay
            sp = selfplay.read_state(self.store.account or "main")
            txt += (f"\n🔁 {tr('rt_self')}: v{sp.get('version', 0)} — {sp.get('battles', 0)} "
                    f"({selfplay.EVERY - (sp.get('battles', 0) - sp.get('trained_at_battles', 0)) % selfplay.EVERY})"
                    + (f" — {sp['note']}" if sp.get("note") else ""))
        except Exception:
            pass
        self.train_state.setText(txt)

    def go_battle(self):
        """One battle: the bot waiting in the lobby goes in."""
        import time as _t
        self.store.set("royale.go_request", _t.time())
        self.store.save(silent=True)          # straight to the bot (it only reads saved settings)
        self.ctx.banner(tr("royale_go_started"), "ok", "play")

    def scan_cards_now(self):
        """The bot opens every card's Info page at the next menu and sends the pictures to be studied."""
        import time as _t
        self.store.set("royale.card_scan_request", _t.time())
        self.store.save(silent=True)          # straight to the bot (it only reads saved settings)
        self.ctx.banner(tr("royale_scan_started"), "ok", "camera")

    def train_now(self):
        try:
            from royale import trainer
            trainer.start(self.store.account or "main")
            self.ctx.banner(tr("rt_started"), "ok", "school")
        except Exception as e:
            self.ctx.banner(str(e), "bad", "x")
        self.show_training()

    # -------------------------------------------------------------- deck
    def show_deck(self, deck):
        deck = list(deck or [])
        for i, (pic, name) in enumerate(self.deck_slots):
            n = deck[i] if i < len(deck) else None
            path = os.path.join(CARDS_DIR, f"{n}.jpg") if n else None
            if path and os.path.exists(path):
                pm = QPixmap(path)
                pic.setPixmap(pm.scaled(80, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                pic.setPixmap(QPixmap())
                pic.setText("?")
            name.setText(n.replace("_", " ").title() if n else "")
        self.deck_note.setText("" if len(deck) == 8 else tr("royale_deck_auto"))

    # -------------------------------------------------------------- live log + today's numbers
    def on_log(self, lines):
        mine = [l for l in (lines or []) if "Clash Royale" in (l if isinstance(l, str) else str(l))]
        self.log.set_lines(mine)
        battles = sum(1 for l in mine if "Clash Royale: battle #" in str(l))
        won = lost = 0
        for l in mine:
            m = re.search(r"(\d+) won / (\d+) lost", str(l))
            if m: won, lost = int(m.group(1)), int(m.group(2))
        self.s_battles.value.setText(str(battles))
        self.s_wins.value.setText(str(won))
        self.s_losses.value.setText(str(lost))
        self.s_rate.value.setText(f"{round(100 * won / (won + lost))}%" if won + lost else "—")
