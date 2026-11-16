"""
Learning with Claude (settings tab):
 - setup: the GitHub repo the bot sends unknown screens to + the token, automatic sync, test, sync now
 - the three steps (the bot saves -> sends to GitHub -> Claude explains -> the bot knows) with live counts
 - every screen the bot did not understand, with its state: on this computer / sent / learned ✓ + Claude's note
 - the rules Claude has taught so far
"""
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from .. import icons
from ..i18n import tr
from ..theme import TOKENS
from ..widgets.controls import Box, GlassCard, IconButton, StatusPill, bind_line, form_row, label, note, toggle_row

STATE_PILL = {"local": ("info", "ln_st_local"), "sent": ("warn", "ln_st_sent"), "learned": ("learned", "ln_st_learned")}


class ShotRow(Box):
    def __init__(self, panel, it):
        super().__init__(radius=15)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(12)
        self.pic = QLabel()
        self.pic.setFixedSize(160, 90)
        self.pic.setStyleSheet("background: #0B0B10; border-radius: 8px;")
        h.addWidget(self.pic)
        panel.api.get(f"/api/discovered/{panel.store.account}/img/{it['shot']}", self._got, raw=True)
        v = QVBoxLayout()
        v.setSpacing(3)
        top = QHBoxLayout()
        kind, key = STATE_PILL.get(it.get("state"), STATE_PILL["local"])
        top.addWidget(StatusPill(kind, tr(key)))
        top.addWidget(label(time.strftime("%m/%d %H:%M", time.localtime(it.get("t") or 0)), "dim"))
        top.addStretch(1)
        v.addLayout(top)
        words = " · ".join(it.get("words", [])[:8])
        v.addWidget(label(words or "—", "sub", wrap=True))
        if it.get("note"):
            nr = QHBoxLayout()
            nr.setSpacing(6)
            from ..widgets.seal import AnimatedSeal
            nr.addWidget(AnimatedSeal(18, gold=True, autoplay=True), 0, Qt.AlignTop)
            n = label(it["note"], wrap=True)
            n.setStyleSheet("color: #FFD36E;")
            nr.addWidget(n, 1)
            v.addLayout(nr)
        h.addLayout(v, 1)

    def _got(self, data):
        if not data: return
        pm = QPixmap()
        if pm.loadFromData(data): self.pic.setPixmap(pm.scaled(160, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class LearnPanel(QWidget):
    def __init__(self, ctx, secret_field):
        super().__init__()
        self.ctx, self.api, self.store = ctx, ctx.api, ctx.store
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # ---------------- capture mode (you play, the bot photographs every new screen)
        from .capture_panel import CapturePanel
        self.capture = CapturePanel(ctx)
        v.addWidget(self.capture)

        # ---------------- how it works: 4 steps with live numbers
        flow = GlassCard("ln_title", "school", "ln_sub", glow=True)
        steps = QHBoxLayout()
        steps.setSpacing(10)
        self.step_vals = {}
        for i, (ic, key) in enumerate((("camera", "ln_step1"), ("upload", "ln_step2"), ("verified_gold", "ln_step3"), ("verified", "ln_step4"))):
            b = Box(radius=15)
            bl = QVBoxLayout(b)
            bl.setContentsMargins(12, 10, 12, 10)
            bl.setSpacing(4)
            hh = QHBoxLayout()
            num = QLabel(str(i + 1))
            num.setFixedSize(22, 22)
            num.setAlignment(Qt.AlignCenter)
            num.setStyleSheet(f"background: {TOKENS['accent']}; color: {TOKENS['on_accent']}; border-radius: 11px; font-weight: 800;")
            hh.addWidget(num)
            icl = QLabel()
            icl.setPixmap(icons.pixmap(ic, 20 if ic.startswith("verified") else 18, TOKENS["accent"]))
            hh.addWidget(icl)
            hh.addStretch(1)
            val = label("—", "numsm")
            hh.addWidget(val)
            bl.addLayout(hh)
            bl.addWidget(label(key=key, role="sub", wrap=True))
            self.step_vals[i] = val
            steps.addWidget(b, 1)
        flow.add(steps)
        self.state = label("", "sub", wrap=True)
        flow.add(self.state)
        v.addWidget(flow)

        # ---------------- setup
        st = self.store
        setup = GlassCard("ln_setup", "github", "ln_setup_sub")
        repo = QLineEdit()
        repo.setPlaceholderText("tiktok7daniel-stack/ClashFarmer-Learning")
        repo.setLayoutDirection(Qt.LeftToRight)
        repo.setMinimumWidth(320)
        bind_line(st, repo, "learn_repo", "app")
        setup.add(form_row("ln_repo", "ln_repo_sub", repo))
        setup.add(form_row("gh_token", "ln_token_sub", secret_field(st, "github_token", "github_pat_…")))
        setup.add(toggle_row(st, "ln_auto", "learn_auto", "ln_auto_sub", "app"))
        btns = QHBoxLayout()
        t = IconButton("plug", "ln_test", size=14)
        t.clicked.connect(self.test)
        btns.addWidget(t)
        sy = IconButton("refresh", "ln_sync", "primary", size=14)
        sy.clicked.connect(self.sync)
        btns.addWidget(sy)
        btns.addStretch(1)
        setup.add(btns)
        self.test_note = label("", "sub", wrap=True)
        setup.add(self.test_note)
        setup.add(note("ln_private", "shield", TOKENS["warn"]))
        v.addWidget(setup)

        # ---------------- screens + rules
        row = QHBoxLayout()
        row.setSpacing(14)
        sc = GlassCard("ln_screens", "image", "ln_screens_sub")
        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        sc.add(self.list)
        row.addWidget(sc, 3)
        rc = GlassCard("ln_rules", "lightbulb", "ln_rules_sub")
        self.rules = QVBoxLayout()
        self.rules.setSpacing(4)
        rc.add(self.rules)
        row.addWidget(rc, 2)
        v.addLayout(row)

    # ---------------------------------------------------------------- data
    def load(self):
        self.capture.load()
        acc = self.store.account
        if acc: self.api.get(f"/api/learn/{acc}", self.render)

    def _clear(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def render(self, d):
        if not isinstance(d, dict) or "items" not in d: return
        items = d["items"]
        counts = [len(items), sum(1 for i in items if i["state"] in ("sent", "learned")),
                  sum(1 for i in items if i["state"] == "learned"), d.get("rules", 0)]
        for i, n in enumerate(counts): self.step_vals[i].setText(str(n))
        if not d.get("configured"):
            self.state.setText(tr("ln_not_configured"))
            self.state.setStyleSheet(f"color: {TOKENS['warn']};")
        elif d.get("error"):
            err = str(d["error"])
            friendly = tr("ln_err_repo_not_found") if "404" in err else (tr("ln_err_no_write") if "403" in err else
                       (tr("ln_err_bad_token") if "401" in err else err))
            self.state.setText(tr("ln_error") + " " + friendly)
            self.state.setStyleSheet(f"color: {TOKENS['bad']};")
        else:
            last = d.get("last_fetch")
            self.state.setText(tr("ln_ok").format(repo=d.get("repo"), when=time.strftime("%H:%M", time.localtime(last)) if last else "—"))
            self.state.setStyleSheet(f"color: {TOKENS['ok']};")
        self._clear(self.list)
        if not items: self.list.addWidget(label(key="ln_no_screens", role="sub", wrap=True))
        for it in items[:20]: self.list.addWidget(ShotRow(self, it))
        self._clear(self.rules)
        if not d.get("rule_list"): self.rules.addWidget(label(key="ln_no_rules", role="sub", wrap=True))
        for r in d.get("rule_list", []):
            row = QWidget()
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 2, 0, 2)
            rh.setSpacing(8)
            seal = QLabel()
            seal.setPixmap(icons.pixmap("verified_gold", 18))
            rh.addWidget(seal)
            rh.addWidget(label(str(r.get("title") or r.get("id"))), 1)
            self.rules.addWidget(row)

    # ---------------------------------------------------------------- actions
    def test(self):
        if self.store.dirty: self.store.save(silent=True)
        self.test_note.setText(tr("checking"))

        def done(r):
            if not isinstance(r, dict): return
            if r.get("ok"):
                msg = tr("ln_test_ok") + ("" if r.get("private") else "  —  " + tr("ln_public_warn"))
                self.test_note.setStyleSheet(f"color: {TOKENS['ok'] if r.get('private') else TOKENS['warn']};")
            else:
                msg = tr("ln_err_" + str(r.get("error"))) if tr("ln_err_" + str(r.get("error"))) != "ln_err_" + str(r.get("error")) else str(r.get("error"))
                self.test_note.setStyleSheet(f"color: {TOKENS['bad']};")
            self.test_note.setText(msg)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(700, lambda: self.api.post("/api/learn_test", {}, done))

    def sync(self):
        if self.store.dirty: self.store.save(silent=True)
        self.ctx.toast(tr("ln_syncing"), "info")

        def done(r):
            if isinstance(r, dict) and r.get("ok"):
                self.ctx.toast(tr("ln_synced").format(up=r.get("uploaded", 0), rules=r.get("rules", 0)), "ok")
            else:
                self.ctx.toast(tr("ln_sync_fail") + " " + str((r or {}).get("error", "")), "bad")
            self.load()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(700, lambda: self.api.post(f"/api/learn/{self.store.account}/sync", {}, done, timeout=180))
