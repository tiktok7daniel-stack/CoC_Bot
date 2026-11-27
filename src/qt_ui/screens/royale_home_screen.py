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
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..i18n import on_lang, tr
from ..theme import TOKENS, ui_font
from ..icons import icons
from ..widgets import GlassCard, IconButton, KpiTile, StatusPill, Toggle, bind_toggle, form_row, label
from ..widgets import AnimatedToggle, MetricTile
from .base import Screen, page

LEARN = Path.home() / ".CoC_Bot" / "learn"
EXIT = Path.home() / ".CoC_Bot" / "royale_ai" / "exit" / "progress.json"


def _safe(acc):
    return "".join(c for c in str(acc or "main") if c.isalnum() or c in "-_") or "main"


def _read(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def _status_row(title_key, badge_widget):
    """Structured key/badge row inside the AI & Engine summary card."""
    w = QFrame()
    w.setObjectName("AiRow")
    w.setStyleSheet(f"#AiRow {{ background: {TOKENS['glass2']}; border: 1px solid {TOKENS['border_solid']}; border-radius: 12px; }}")
    h = QHBoxLayout(w)
    h.setContentsMargins(12, 8, 12, 8)
    h.setSpacing(10)
    lb = label(key=title_key, role="sub")
    h.addWidget(lb)
    h.addStretch(1)
    h.addWidget(badge_widget)
    return w


class RoyaleHomeScreen(Screen):
    key, title_key, icon_name = "royale_home", "rh_title", "home"

    def __init__(self, ctx):
        super().__init__(ctx)
        sa, v = page(18)
        self.root.addWidget(sa)

        # ---------- hero status + responsive command actions
        top = GlassCard(None, None, None, glow=True, pad=22)
        h = QHBoxLayout()
        h.setSpacing(20)
        col = QVBoxLayout()
        col.setSpacing(6)
        head_row = QHBoxLayout()
        head_row.setSpacing(10)
        self.p_hero = StatusPill("stopped")
        head_row.addWidget(self.p_hero)
        head_row.addStretch(1)
        col.addLayout(head_row)
        self.l_status = QLabel("")
        self.l_status.setFont(ui_font(19, 800))
        self.l_status.setWordWrap(True)
        self.l_now = label("", role="sub", wrap=True)
        self.l_now.setStyleSheet(f"font-size: 10.5pt; color: {TOKENS['muted']};")
        col.addWidget(self.l_status)
        col.addWidget(self.l_now)
        col.addStretch(1)
        h.addLayout(col, 1)

        btns = QVBoxLayout()
        btns.setSpacing(8)
        b_row = QHBoxLayout()
        b_row.setSpacing(8)
        self.b_start = IconButton("play", "rh_start", kind="go", size=18)
        self.b_stop = IconButton("stop", "rh_stop", kind="stop", size=16)
        self.b_view = IconButton("eye", "rh_view", kind="primary", size=16)
        for b in (self.b_start, self.b_stop):
            b.setMinimumHeight(46)
            b.setMinimumWidth(136)
            b.setFont(ui_font(11, 700))
        self.b_view.setMinimumHeight(42)
        self.b_view.setMinimumWidth(280)
        self.b_view.setFont(ui_font(10.5, 700))
        self.b_start.clicked.connect(lambda: self.ctx.window.run_action("start"))
        self.b_stop.clicked.connect(lambda: self.ctx.window.run_action("stop"))
        self.b_view.clicked.connect(self.open_view)
        b_row.addWidget(self.b_start)
        b_row.addWidget(self.b_stop)
        btns.addLayout(b_row)
        btns.addWidget(self.b_view)
        self.b_catalog = IconButton("layers", "rc_title", kind="primary", size=16)
        self.b_catalog.clicked.connect(self.open_catalog)
        btns.addWidget(self.b_catalog)
        h.addLayout(btns)
        top.add(h)
        v.addWidget(top)

        # ---------- today KPIs + structured AI/Engine status
        row = QHBoxLayout()
        row.setSpacing(16)
        today = GlassCard("rh_today", "chart", pad=18)
        g = QHBoxLayout()
        g.setSpacing(10)
        self.n_b = KpiTile("royale_battles", TOKENS["text"])
        self.n_w = KpiTile("royale_wins", TOKENS["ok"])
        self.n_l = KpiTile("royale_losses", TOKENS["bad"])
        self.n_r = KpiTile("royale_rate", TOKENS["crimson"])
        for x in (self.n_b, self.n_w, self.n_l, self.n_r): g.addWidget(x, 1)
        today.add(g)
        self.l_chores = label("", "sub", wrap=True)
        self.l_chores.setStyleSheet(f"padding-top: 6px; color: {TOKENS['dim']}; font-size: 9pt;")
        today.add(self.l_chores)
        row.addWidget(today, 1)

        ai = GlassCard("rh_ai", "bolt", pad=18)
        self.v_who = label("", wrap=True)
        self.v_who.setStyleSheet(f"font-weight: 700; color: {TOKENS['text']};")
        self.v_eng = StatusPill("idle", "—")
        self.v_train = label("", "numsm", wrap=True)
        self.v_train.setStyleSheet(f"color: {TOKENS['crimson_hi']}; font-weight: 700;")
        for r_w in (_status_row("rh_who", self.v_who),
                    _status_row("rh_engine", self.v_eng),
                    _status_row("rh_training", self.v_train)):
            ai.add(r_w)
        bh = QHBoxLayout()
        bh.setSpacing(8)
        bh.setContentsMargins(0, 6, 0, 0)
        self.b_train = IconButton("play", "rh_train", kind="go", size=14)
        self.b_tstop = IconButton("stop", "rh_train_stop", kind="stop", size=14)
        self.b_train.setMinimumHeight(38)
        self.b_tstop.setMinimumHeight(38)
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

        # ---------- choices (saved at once)
        ch = GlassCard("rh_choices", "sliders", "rh_choices_sub")
        for key, path, sub in (("rh_ai_plays", "royale.ai_play", "rh_ai_plays_sub"),
                               ("rh_watch", "royale.watch_only", "rh_watch_sub"),
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
    def open_catalog(self):
        if not self.store.account:
            return
        from .royale_catalog_dialog import RoyaleCatalogDialog
        self.catalog_dialog = RoyaleCatalogDialog(self, self.api, self.store.account)
        self.catalog_dialog.open()

    def open_view(self):
        w = self.ctx.window
        s = w.screens.get("royale_ai")
        if s: s.pop_out()

    def train(self):
        try:
            from royale import exit_train, engine_ai
            miss = exit_train.missing()
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
            self.p_hero.set("stopped", tr("st_stopped"))
            self.l_status.setText(tr("rh_stopped"))
            self.l_status.setStyleSheet(f"color: {TOKENS['text']}; font-size: 19pt; font-weight: 800;")
            self.l_now.setText(tr("rh_stopped_sub"))
        else:
            self.p_hero.set("running", tr("st_running"))
            self.l_status.setText(tr("rh_running"))
            self.l_status.setStyleSheet(f"color: {TOKENS['ok']}; font-size: 19pt; font-weight: 800;")
            if phase == "battle":
                d = live.get("decision")
                t = live.get("time_s", 0)
                now = f"{tr('rh_in_battle')} — {int(t // 60)}:{int(t % 60):02d} · {tr('rl_elixir')} {live.get('elixir')}"
                if d:
                    card_name = d['card'].replace('_', ' ').title()
                    why = d.get('why', '')[:90]
                    dot = icons.img_tag("dot", 12, TOKENS["crimson"])
                    now += f"\n{dot}&nbsp;{card_name} — {why}"
                self.l_now.setText(now)
            else:
                self.l_now.setText(tr("rl_phase_" + str(phase)) if phase else tr("rh_lobby"))
        if running and phase != "battle":
            from royale.catalog_selection import state as catalog_state
            catalog = catalog_state(acc)["status"]
            if catalog.get("state") == "blocked":
                text = tr("rc_" + catalog.get("reason", "copy_failed"))
                self.l_now.setText(text)
        self.b_start.setEnabled(not running)
        self.b_stop.setEnabled(running)

        day = _read(LEARN / f"royale_account_{_safe(acc)}.json").get("days", {}).get(date.today().isoformat(), {})
        b, w = int(day.get("battles", 0)), int(day.get("wins", 0))
        self.n_b.set(b); self.n_w.set(w); self.n_l.set(max(0, b - w))
        self.n_r.set(f"{100 * w // b}%" if b else "—")
        extra = [(k, day.get(k, 0)) for k in ("rewards", "mastery", "gifts", "shop_free", "donations", "upgrades",
                                              "war_battles") if day.get(k)]
        self.l_chores.setText(" · ".join(f"{tr('rh_c_' + k)} {n}" for k, n in extra) if extra else tr("rh_no_chores"))

        ai_on = bool(self.store.get("royale.ai_play", True))
        self.v_who.setText(tr("rh_who_ai") if ai_on else tr("rh_who_rules"))
        eng = live.get("engine") or {}
        if eng:
            self.v_eng.set("ok" if eng.get("on") else "bad", tr("rl_engine_on") if eng.get("on") else tr("rl_engine_off"))
        else:
            self.v_eng.set("idle", tr("rl_engine_off"))
        pr = _read(EXIT)
        training = False
        try:
            from royale import exit_train
            training = exit_train.running()
        except Exception:
            pass
        if pr:
            score_txt = f" · {tr('rh_last')} {int(100 * float(pr.get('last_score', 0)))}%" if pr.get("last_score") is not None else ""
            self.v_train.setText(f"{tr('rh_train_on') if training else tr('rh_train_off')} · "
                                 f"{tr('rh_round')} {pr.get('iteration', 0)} · {tr('rh_versions')} {pr.get('accepted', 0)}{score_txt}")
        else:
            self.v_train.setText(tr("rh_train_on") if training else tr("rh_train_never"))
        self.b_train.setEnabled(not training)
        self.b_tstop.setEnabled(training)
