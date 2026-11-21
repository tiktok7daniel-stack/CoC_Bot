"""
Clash Royale — the simple home page (the first thing the user sees): everything that matters on one screen, nothing
else.

  status     one big line: what the bot is doing now (stopped / in a battle / in the lobby / chores / training)
  start      one big Start / Stop button, and "Battle view" (the window beside the game)
  today      battles, wins, losses, win rate (royale.account's daily counts)
  the AI     who plays (the AI model / the rules), the battle engine, the training on this PC (Expert Iteration:
             round, versions in use, last score) with Train / Stop
  4 choices  AI plays · daily rewards & chores · Training Camp only · results to the phone — saved at once
  advanced   everything else stays on the "Advanced settings" page

Reads the bot's files on this PC every 2 s (no extra work for the bot).
"""
import json, time
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..i18n import on_lang, tr
from ..theme import TOKENS, display_font, ui_font
from ..widgets.controls import GlassCard, IconButton, Toggle, bind_toggle, form_row, label
from .base import Screen, page

LEARN = Path.home() / ".CoC_Bot" / "learn"
EXIT = Path.home() / ".CoC_Bot" / "royale_ai" / "exit" / "progress.json"


def _safe(acc):
    return "".join(c for c in str(acc or "main") if c.isalnum() or c in "-_") or "main"


def _read(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


class _Big(QWidget):
    """A big number with its name under it."""
    def __init__(self, key, col):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.n = QLabel("0")
        self.n.setFont(display_font(30))
        self.n.setAlignment(Qt.AlignCenter)
        self.n.setStyleSheet(f"color: {col}; font-size: 30px; font-weight: 800;")
        v.addWidget(self.n)
        lb = label(key=key)
        lb.setAlignment(Qt.AlignCenter)
        v.addWidget(lb)

    def set(self, t):
        self.n.setText(str(t))


class RoyaleHomeScreen(Screen):
    key, title_key, icon_name = "royale_home", "rh_title", "home"

    def __init__(self, ctx):
        super().__init__(ctx)
        sa, v = page(16)
        self.root.addWidget(sa)

        # ---------- status + the big buttons
        top = GlassCard(None, None, None, glow=True, pad=20)
        h = QHBoxLayout()
        h.setSpacing(16)
        col = QVBoxLayout()
        self.l_status = QLabel("")
        self.l_status.setFont(ui_font(20, 700))
        self.l_status.setWordWrap(True)
        self.l_now = label("", wrap=True)
        self.l_now.setStyleSheet("font-size: 14px;")
        col.addWidget(self.l_status)
        col.addWidget(self.l_now)
        h.addLayout(col, 1)
        self.b_start = IconButton("play", "rh_start", kind="go", size=20)
        self.b_stop = IconButton("stop", "rh_stop", kind="stop", size=18)
        self.b_view = IconButton("eye", "rh_view", size=18)
        for b in (self.b_start, self.b_stop, self.b_view):
            b.setMinimumHeight(54)
            b.setMinimumWidth(170)
            b.setFont(ui_font(12, 600))
        self.b_start.clicked.connect(lambda: self.ctx.window.run_action("start"))
        self.b_stop.clicked.connect(lambda: self.ctx.window.run_action("stop"))
        self.b_view.clicked.connect(self.open_view)
        h.addWidget(self.b_start)
        h.addWidget(self.b_stop)
        h.addWidget(self.b_view)
        top.add(h)
        v.addWidget(top)

        # ---------- today + the AI
        row = QHBoxLayout()
        row.setSpacing(16)
        today = GlassCard("rh_today", "chart")
        g = QHBoxLayout()
        self.n_b = _Big("royale_battles", TOKENS["text"])
        self.n_w = _Big("royale_wins", "#4ade80")
        self.n_l = _Big("royale_losses", "#f87171")
        self.n_r = _Big("royale_rate", TOKENS.get("gold", "#f5b740"))
        for x in (self.n_b, self.n_w, self.n_l, self.n_r): g.addWidget(x, 1)
        today.add(g)
        self.l_chores = label("", wrap=True)
        self.l_chores.setProperty("role", "sub")
        today.add(self.l_chores)
        row.addWidget(today, 1)

        ai = GlassCard("rh_ai", "bolt")
        self.l_ai = label("", wrap=True)
        self.l_ai.setTextFormat(Qt.RichText)
        self.l_ai.setMinimumHeight(78)
        self.l_ai.setAlignment(Qt.AlignTop)
        ai.add(self.l_ai)
        bh = QHBoxLayout()
        self.b_train = IconButton("play", "rh_train", kind="go", size=14)
        self.b_tstop = IconButton("stop", "rh_train_stop", size=14)
        self.b_train.clicked.connect(self.train)
        self.b_tstop.clicked.connect(self.train_stop)
        bh.addWidget(self.b_train)
        bh.addWidget(self.b_tstop)
        bh.addStretch(1)
        ai.add(bh)
        row.addWidget(ai, 1)
        hold = QWidget()
        hold.setLayout(row)
        v.addWidget(hold)

        # ---------- 4 choices (saved at once)
        ch = GlassCard("rh_choices", "sliders", "rh_choices_sub")
        for key, path, sub in (("rh_ai_plays", "royale.ai_play", "rh_ai_plays_sub"),
                               ("rh_chores", "royale.manage_account", "rh_chores_sub"),
                               ("royale_tc", "royale.training_camp", "royale_tc_sub"),
                               ("rh_phone", "royale.notify", "rh_phone_sub")):
            t = bind_toggle(self.store, Toggle(), path)
            t.toggled.connect(lambda _v: QTimer.singleShot(50, lambda: self.store.save(silent=True)))
            ch.add(form_row(key, sub, t))
        adv = IconButton("sliders", "rh_advanced", size=14)
        adv.clicked.connect(lambda: self.ctx.window.show_screen("royale"))
        ah = QHBoxLayout()
        ah.addStretch(1)
        ah.addWidget(adv)
        ch.add(ah)
        v.addWidget(ch)
        v.addStretch(1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        on_lang(self.refresh)

    # -------------------------------------------------------------- actions
    def open_view(self):
        w = self.ctx.window
        s = w.screens.get("royale_ai") or w.screens.get("royale_live")
        if s: s.pop_out()

    def train(self):
        try:
            from royale import exit_train, engine_ai
            miss = engine_ai.missing()
            if miss:
                self.ctx.banner(tr("royale_ai_missing") + ", ".join(miss), "bad", "x"); return
            deck = list(self.store.get("royale.deck", []) or [])
            if len(deck) != 8:
                self.ctx.banner(tr("rh_need_deck"), "bad", "x"); return
            ok, msg = exit_train.start(deck, self.store.account or "main")
            self.ctx.banner(tr("rh_train_started") if ok else msg, "ok" if ok else "bad", "bolt")
        except Exception as e:
            self.ctx.banner(str(e), "bad", "x")
        self.refresh()

    def train_stop(self):
        try:
            from royale import exit_train
            exit_train.stop()
            self.ctx.banner(tr("rh_train_stopping"), "ok", "stop")
        except Exception as e:
            self.ctx.banner(str(e), "bad", "x")

    def on_show(self):
        self.refresh()

    # -------------------------------------------------------------- what the page shows
    def refresh(self):
        if not self.isVisible(): return
        acc = self.store.account or "main"
        st = {}
        try: st = self.ctx.poller.account_state() or {}
        except Exception: pass
        running = bool(st.get("running"))
        live = _read(LEARN / f"royale_live_{_safe(acc)}.json")
        phase = live.get("phase") if live and time.time() - float(live.get("t", 0)) < 15 else None
        if not running:
            self.l_status.setText("⏹  " + tr("rh_stopped"))
            self.l_status.setStyleSheet(f"color: {TOKENS['muted']}; font-size: 24px; font-weight: 800;")
            self.l_now.setText(tr("rh_stopped_sub"))
        else:
            self.l_status.setText("▶  " + tr("rh_running"))
            self.l_status.setStyleSheet("color: #4ade80; font-size: 24px; font-weight: 800;")
            if phase == "battle":
                d = live.get("decision")
                t = live.get("time_s", 0)
                now = f"{tr('rh_in_battle')} — {int(t // 60)}:{int(t % 60):02d} · {tr('rl_elixir')} {live.get('elixir')}"
                if d: now += f"\n▶ {d['card'].replace('_', ' ').title()} — {d.get('why', '')[:90]}"
                self.l_now.setText(now)
            else:
                self.l_now.setText(tr("rl_phase_" + str(phase)) if phase else tr("rh_lobby"))
        self.b_start.setEnabled(not running)
        self.b_stop.setEnabled(running)

        day = _read(LEARN / f"royale_account_{_safe(acc)}.json").get("days", {}).get(date.today().isoformat(), {})
        b, w = int(day.get("battles", 0)), int(day.get("wins", 0))
        self.n_b.set(b); self.n_w.set(w); self.n_l.set(max(0, b - w))
        self.n_r.set(f"{100 * w // b}%" if b else "—")
        extra = [(k, day.get(k, 0)) for k in ("rewards", "mastery", "gifts", "shop_free", "donations", "upgrades",
                                              "war_battles") if day.get(k)]
        self.l_chores.setText(" · ".join(f"{tr('rh_c_' + k)} {n}" for k, n in extra) if extra else tr("rh_no_chores"))

        lines = []
        ai_on = bool(self.store.get("royale.ai_play", True))
        lines.append(f"<b>{tr('rh_who')}:</b> " + (tr("rh_who_ai") if ai_on else tr("rh_who_rules")))
        eng = live.get("engine") or {}
        if eng:
            lines.append(f"<b>{tr('rh_engine')}:</b> " + (tr("rl_engine_on") if eng.get("on") else tr("rl_engine_off")))
        pr = _read(EXIT)
        training = False
        try:
            from royale import exit_train
            training = exit_train.running()
        except Exception:
            pass
        if pr:
            lines.append(f"<b>{tr('rh_training')}:</b> " + (tr("rh_train_on") if training else tr("rh_train_off")) +
                         f" · {tr('rh_round')} {pr.get('iteration', 0)} · {tr('rh_versions')} {pr.get('accepted', 0)}"
                         + (f" · {tr('rh_last')} {int(100 * float(pr.get('last_score', 0)))}%"
                            if pr.get("last_score") is not None else ""))
        else:
            lines.append(f"<b>{tr('rh_training')}:</b> " + (tr("rh_train_on") if training else tr("rh_train_never")))
        self.l_ai.setText("<br>".join(lines))
        self.b_train.setEnabled(not training)
        self.b_tstop.setEnabled(training)
