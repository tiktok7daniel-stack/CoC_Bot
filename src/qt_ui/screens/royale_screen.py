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
        g2.addWidget(play, 0, 0)
        setup = GlassCard("royale_setup", "sliders", "royale_setup_sub")
        for k in ("royale_need_1", "royale_need_2", "royale_need_3", "royale_need_4"):
            setup.add(label(key=k, role="sub", wrap=True))
        g2.addWidget(setup, 0, 1)
        v.addWidget(w2)

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
