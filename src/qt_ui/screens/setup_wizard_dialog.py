"""
Screen 2 - Pre-flight setup wizard: emulator + its folder, display size / DPI with one-click auto
setup for every account, per-account readiness cards (emulator running, connected, size, game open)
with step buttons, add account, start all ready accounts, show-on-start checkbox.
"""
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .. import icons
from ..i18n import on_lang, tr
from ..theme import TOKENS
from ..widgets.controls import Box, Combo, IconButton, NumField, StatusPill, label, retext

EMULATORS = [("ldplayer", "LDPlayer")]


class StepBadge(Box):
    def __init__(self):
        super().__init__(radius=13)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(8)
        self.ic = QLabel()
        h.addWidget(self.ic)
        box = QVBoxLayout()
        box.setSpacing(0)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 700;")
        self.info = QLabel()
        self.info.setProperty("role", "dim")
        box.addWidget(self.title)
        box.addWidget(self.info)
        h.addLayout(box, 1)

    def set(self, ok, title, info=""):
        name, col = ("ok", TOKENS["ok"]) if ok is True else ("bad", TOKENS["bad"]) if ok is False else ("dash_circle", TOKENS["warn"])
        self.ic.setPixmap(icons.pixmap(name, 18, col))
        self.title.setText(title)
        self.info.setText(info or "")
        self.bg = QColor("#10261F" if ok is True else "#2A1218" if ok is False else TOKENS["glass2"])
        self.set_border("rgba(16,185,129,0.5)" if ok is True else "rgba(239,68,68,0.5)" if ok is False else TOKENS["border"])


class AccountCard(Box):
    def __init__(self, wizard, a):
        super().__init__(radius=18)
        self.wizard = wizard
        self.acc = a["id"]
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("users", 18, "#E9D3A6"))
        head.addWidget(ic)
        head.addWidget(label(a["id"], "h2"))
        su = wizard.data
        if su.get("emulator") != "mumu":
            head.addWidget(label(key="su_linked", role="sub"))
            self.link = QComboBox()
            self.link.addItem(tr("su_auto"), "")
            for c in su.get("copies", []): self.link.addItem(c.get("title", ""), str(c.get("index")))
            cur = str((wizard.ctx.store.APP.get("emulator_links", {}) or {}).get(a["id"], ""))
            i = self.link.findData(cur)
            if i >= 0: self.link.setCurrentIndex(i)
            self.link.activated.connect(self._link)
            head.addWidget(self.link)
        head.addWidget(label(key="game_mode", role="sub"))
        self.game = Combo([("coc", "gm_coc"), ("royale", "gm_royale")], 170)   # this account's game
        self.game.set_value(a.get("game_mode", "coc"))
        self.game.activated.connect(self._game)
        head.addWidget(self.game)
        head.addStretch(1)
        head.addWidget(StatusPill("running" if a.get("bot") else "stopped", tr("su_bot_on" if a.get("bot") else "su_bot_off")))
        v.addLayout(head)
        steps = QGridLayout()
        steps.setSpacing(8)
        tgt = a.get("target") or su.get("target") or [1920, 1080, 240]   # this account's game: Royale 720x1280
        self.b_emu, self.b_adb, self.b_res, self.b_game = StepBadge(), StepBadge(), StepBadge(), StepBadge()
        mumu = su.get("emulator") == "mumu"
        self.b_emu.set((a.get("emu_running") or None) if mumu else (bool(a.get("copy")) and bool(a.get("emu_running"))),
                       tr("su_s_emu"), a.get("copy") or tr("su_no_copy"))
        self.b_adb.set(a.get("adb") == "device" and bool(a.get("boot")), tr("su_s_adb"), a.get("address") or "")
        self.b_res.set(None if a.get("res_ok") is None else bool(a.get("res_ok")), f"{tgt[0]}x{tgt[1]} · {tgt[2]} DPI", a.get("resolution") or "")
        self.b_game.set(bool(a.get("game")) if a.get("adb") == "device" else None, tr("su_s_game"))
        for i, b in enumerate((self.b_emu, self.b_adb, self.b_res, self.b_game)): steps.addWidget(b, 0, i)
        v.addLayout(steps)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        ready = wizard.ready(a)
        busy = a.get("progress") and a["progress"] not in ("done", "failed", "failed_link", "failed_adb")
        for ic_name, key, action, enabled, kind in (
                ("wand", "su_b_auto", "auto", not busy, "primary"),
                ("power", "su_b_launch", "launch", not a.get("emu_running") and not mumu, None),
                ("expand", "su_b_res", "fix_res", a.get("res_ok") is False, None),
                ("gamepad", "su_b_game", "open_game", a.get("adb") == "device" and not a.get("game"), None),
                ("play", "su_b_start", "start", not a.get("bot"), "go" if ready else None)):
            b = IconButton(ic_name, key, kind=kind, size=14)
            b.setEnabled(bool(enabled))
            b.clicked.connect(lambda _=False, ac=action: wizard.do(ac, self.acc))
            btns.addWidget(b)
        btns.addStretch(1)
        v.addLayout(btns)
        hint = wizard.hint(a)
        if a.get("progress"):
            p = a["progress"]
            col = TOKENS["bad"] if p.startswith("failed") else TOKENS["ok"] if p == "done" else TOKENS["info"]
            pl = QLabel(tr("su_" + p))
            pl.setStyleSheet(f"color: {col}; font-weight: 600;")
            v.addWidget(pl)
        elif hint and not ready:
            hl = QHBoxLayout()
            bulb = QLabel()
            bulb.setPixmap(icons.pixmap("lightbulb", 16, TOKENS["warn"]))
            hl.addWidget(bulb)
            hl.addWidget(label(tr(hint), "warn", wrap=True), 1)
            v.addLayout(hl)
        if ready: self.set_border("rgba(16,185,129,0.55)")

    def _game(self, _i):
        self.wizard.ctx.api.post(f"/api/account/{self.acc}/game", {"mode": self.game.value()},
                                 lambda r: (self.wizard.ctx.store.load_all(), self.wizard.refresh()))

    def _link(self, _i):
        self.wizard.ctx.api.post("/api/setup/link", {"account": self.acc, "copy": self.link.currentData()},
                                 lambda r: (self.wizard.ctx.store.load_all(), self.wizard.refresh()))


class SetupWizard(QDialog):
    def __init__(self, ctx, parent):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.ctx = ctx
        self.data = {}
        self._busy = False
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.resize(1040, 780)
        frame = Box(bg="#0E0C12", border=TOKENS["border_hover"], radius=18)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        v = QVBoxLayout(frame)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(12)
        head = QHBoxLayout()
        crest = QLabel()
        crest.setPixmap(icons.pixmap("crest", 40))
        head.addWidget(crest)
        tb = QVBoxLayout()
        tb.setSpacing(0)
        tb.addWidget(label(key="su_title", role="h1"))
        tb.addWidget(label(key="su_sub", role="sub", wrap=True))
        head.addLayout(tb, 1)
        x = IconButton("x", kind="winclose", size=16, tip_key="close")
        x.clicked.connect(self.close_wizard)
        head.addWidget(x, 0, Qt.AlignTop)
        v.addLayout(head)
        # emulator + folder
        emu = QHBoxLayout()
        emu.addWidget(label(key="emulator"))
        self.emu = QComboBox()
        for val, text in EMULATORS: self.emu.addItem(text, val)
        self.emu.setFixedWidth(170)
        emu.addWidget(self.emu)
        self.path = QLineEdit()
        self.path.setPlaceholderText("D:\\LDPlayer\\LDPlayer9")
        self.path.setLayoutDirection(Qt.LeftToRight)
        emu.addWidget(self.path, 1)
        save = IconButton("save", "su_save", size=14)
        save.clicked.connect(self.save_emulator)
        emu.addWidget(save)
        ref = IconButton("refresh", "su_refresh", size=14)
        ref.clicked.connect(self.refresh)
        emu.addWidget(ref)
        v.addLayout(emu)
        self.emu.currentIndexChanged.connect(lambda _i: self.path.setVisible(self.emu.currentData() == "ldplayer"))
        # display
        disp = Box(border=TOKENS["purple"], radius=18)
        dv = QVBoxLayout(disp)
        dv.setContentsMargins(14, 10, 14, 10)
        dh = QHBoxLayout()
        di = QLabel()
        di.setPixmap(icons.pixmap("monitor", 18, "#E9D3A6"))
        dh.addWidget(di)
        dh.addWidget(label(key="su_disp", role="h3"))
        dh.addStretch(1)
        self.w, self.h, self.d = NumField(200, 4000, 10, 90), NumField(200, 4000, 10, 90), NumField(60, 700, 10, 80)
        for wdg in (self.w, QLabel("x"), self.h, QLabel("DPI"), self.d): dh.addWidget(wdg)
        reset = IconButton("undo", "su_disp_default", size=14)
        reset.clicked.connect(lambda: (self.w.setValue(1920), self.h.setValue(1080), self.d.setValue(240), self._warn()))
        dh.addWidget(reset)
        auto = IconButton("wand", "su_auto_all", kind="go", size=15)
        auto.clicked.connect(self.auto_all)
        dh.addWidget(auto)
        dv.addLayout(dh)
        self.disp_warn = label(key="su_disp_warn", role="warn", wrap=True)
        dv.addWidget(self.disp_warn)
        for f in (self.w, self.h): f.valueChanged.connect(lambda _v: self._warn())
        v.addWidget(disp)
        self.summary = QLabel()
        self.summary.setStyleSheet(f"background: {TOKENS['glass2']}; border: 1px solid {TOKENS['border']}; border-radius: 12px; padding: 10px 14px; font-weight: 700;")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        # account cards
        self.cards_host = QWidget()
        self.cards = QVBoxLayout(self.cards_host)
        self.cards.setContentsMargins(0, 0, 6, 0)
        self.cards.setSpacing(10)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(self.cards_host)
        sa.setFrameShape(QFrame.NoFrame)
        v.addWidget(sa, 1)
        # add account
        add = QHBoxLayout()
        ai = QLabel()
        ai.setPixmap(icons.pixmap("plus", 16, "#E9D3A6"))
        add.addWidget(ai)
        add.addWidget(label(key="su_add", role="h3"))
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("main2")
        self.new_name.setFixedWidth(180)
        add.addWidget(self.new_name)
        self.new_copy = QComboBox()
        self.new_copy.setFixedWidth(200)
        add.addWidget(self.new_copy)
        addb = IconButton("plus", "su_add_btn", size=14)
        addb.clicked.connect(self.add_account)
        add.addWidget(addb)
        add.addStretch(1)
        v.addLayout(add)
        # footer
        foot = QHBoxLayout()
        self.show_cb = QCheckBox(tr("su_show"))
        on_lang(lambda: self.show_cb.setText(tr("su_show")))
        foot.addWidget(self.show_cb)
        foot.addStretch(1)
        enter = IconButton("chevron_left", "su_enter", kind="primary", size=15)
        enter.clicked.connect(self.close_wizard)
        foot.addWidget(enter)
        start = IconButton("play", "su_start_all", kind="go", size=15)
        start.clicked.connect(self.start_ready)
        foot.addWidget(start)
        v.addLayout(foot)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)

    # ---------------------------------------------------------------- open / close
    def open_wizard(self):
        APP = self.ctx.store.APP
        i = self.emu.findData(APP.get("emulator", "ldplayer"))
        if i >= 0: self.emu.setCurrentIndex(i)
        self.path.setText(APP.get("ldplayer_path", ""))
        self.path.setVisible(self.emu.currentData() == "ldplayer")
        self.w.setValue(int(APP.get("display_w", 1920)))
        self.h.setValue(int(APP.get("display_h", 1080)))
        self.d.setValue(int(APP.get("display_dpi", 240)))
        self.show_cb.setChecked(APP.get("show_setup", True) is not False)
        self._warn()
        par = self.parentWidget()
        self.resize(min(1040, par.width() - 60), min(800, par.height() - 40))
        self.move(par.mapToGlobal(QPoint((par.width() - self.width()) // 2, (par.height() - self.height()) // 2)))
        self.show()
        self.raise_()
        self.refresh()
        self.timer.start(5000)

    def close_wizard(self):
        self.timer.stop()
        show = self.show_cb.isChecked()
        if self.ctx.store.APP.get("show_setup", True) != show:
            self.ctx.store.APP["show_setup"] = show
            self.ctx.store.changed()
            self.ctx.store.save(silent=True)
        self.hide()

    def _warn(self):
        self.disp_warn.setVisible(not (self.w.value() == 1920 and self.h.value() == 1080))

    # ---------------------------------------------------------------- data
    def refresh(self):
        if self._busy: return
        self._busy = True

        def got(d):
            self._busy = False
            if not isinstance(d, dict) or d.get("error"): return
            self.data = d
            self.render()
        self.ctx.api.get("/api/setup/status", got, timeout=60)

    def ready(self, a):
        return bool(a.get("emu_running")) and a.get("adb") == "device" and a.get("res_ok") is not False and bool(a.get("game"))

    def hint(self, a):
        emu = self.data.get("emulator")
        if emu != "mumu" and not a.get("copy"): return "su_h_link"
        if not a.get("emu_running"): return "su_h_launch"
        if a.get("adb") != "device": return "su_h_adb_ld" if emu == "ldplayer" else "su_h_adb"
        if not a.get("boot"): return "su_h_boot"
        if a.get("res_ok") is False: return "su_h_res"
        if not a.get("game"): return "su_h_game"
        return ""

    def render(self):
        d = self.data
        emu_name = dict(EMULATORS).get(d.get("emulator"), d.get("emulator", ""))
        accs = d.get("accounts", [])
        ready = sum(1 for a in accs if self.ready(a))
        if not d.get("found"):
            self.summary.setText(tr("su_not_found").replace("{e}", emu_name))
            self.summary.setStyleSheet(self.summary.styleSheet().replace(TOKENS["border"], "rgba(239,68,68,0.5)"))
        else:
            copies = d.get("copies", [])
            names = "، ".join(c.get("title", "") + (" (on)" if c.get("running") else "") for c in copies)
            self.summary.setText(f"{emu_name}  ·  {tr('su_copies')}: {len(copies)} {('(' + names + ')') if names else ''}"
                                 f"  ·  {tr('su_accounts')}: {len(accs)}  ·  {tr('su_ready')}: {ready}")
        while self.cards.count():
            it = self.cards.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        for a in accs: self.cards.addWidget(AccountCard(self, a))
        self.cards.addStretch(1)
        self.new_copy.clear()
        self.new_copy.addItem(tr("su_auto"), "")
        for c in d.get("copies", []): self.new_copy.addItem(c.get("title", ""), str(c.get("index")))
        self.new_copy.setVisible(bool(d.get("copies")))

    # ---------------------------------------------------------------- actions
    def save_display(self, done):
        APP = self.ctx.store.APP
        APP["display_w"], APP["display_h"], APP["display_dpi"] = self.w.value(), self.h.value(), self.d.value()
        self.ctx.store.changed()
        self.ctx.store.save(silent=True, done=done)

    def save_emulator(self):
        APP = self.ctx.store.APP
        APP["emulator"] = self.emu.currentData()
        APP["ldplayer_path"] = self.path.text().strip()
        self.ctx.store.changed()
        self.ctx.store.save(done=lambda ok: self.refresh())

    def do(self, action, acc):
        if action == "start":
            a = next((x for x in self.data.get("accounts", []) if x["id"] == acc), {})
            if not self.ready(a) and QMessageBox.question(self, "Clash Farmer", tr("su_start_anyway")) != QMessageBox.Yes: return
            self.ctx.window.account_action(acc, "start", after=lambda r: self.refresh())
            return
        if action == "fix_res" and QMessageBox.question(self, "Clash Farmer", tr("su_res_confirm")) != QMessageBox.Yes: return

        def run(_ok=True):
            def done(r):
                ok = isinstance(r, dict) and r.get("ok")
                self.ctx.toast(tr("su_done_" + action) if ok else tr("su_err_" + ((r or {}).get("result") or "x")), "ok" if ok else "bad")
                QTimer.singleShot(1500, self.refresh)
            self.ctx.api.post(f"/api/setup/{action}", {"account": acc}, done, timeout=240)
        if action in ("fix_res", "auto"): self.save_display(run)
        else: run()

    def auto_all(self):
        txt = tr("su_auto_confirm").replace("{s}", f"{self.w.value()}x{self.h.value()} · {self.d.value()} DPI")
        if QMessageBox.question(self, "Clash Farmer", txt) != QMessageBox.Yes: return

        def go(_ok):
            for a in self.data.get("accounts", []):
                self.ctx.api.post("/api/setup/auto", {"account": a["id"]})
            self.ctx.toast(tr("su_auto_started"), "ok")
            QTimer.singleShot(1500, self.refresh)
        self.save_display(go)

    def add_account(self):
        name = self.new_name.text().strip()
        if not name:
            self.ctx.toast(tr("su_need_name"), "bad")
            return
        src = self.ctx.store.account

        def added(r):
            self.new_name.clear()
            if src and src != name: self.ctx.api.post("/api/settings_copy", {"from": src, "to": [name]})
            self.ctx.store.load_all()
            self.refresh()
            self.ctx.toast(tr("copied_from").replace("{a}", src) if src else tr("saved"), "ok")
        self.ctx.api.post("/api/setup/add_account", {"name": name, "copy": self.new_copy.currentData() or ""}, added)

    def start_ready(self):
        ready = [a for a in self.data.get("accounts", []) if self.ready(a) and not a.get("bot")]
        if not ready:
            self.ctx.toast(tr("su_none_ready"), "bad")
            return
        for a in ready: self.ctx.window.account_action(a["id"], "start")
        self.close_wizard()
