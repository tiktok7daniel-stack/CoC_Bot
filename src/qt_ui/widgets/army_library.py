"""
Learned armies: teach the bot an army by preparing it yourself in the game, then one tap to use it.
 - "Learn army": the bot opens the village and watches; you open the army, pick / train it, press Done
 - every learned army shows the picture of its army screen, its steps and the buttons it found by name
 - "Prepare now" makes the bot do it right away; "Use in attacks" ties it to the active loadout so the
   bot prepares it before every attack
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from .. import icons
from ..i18n import tr
from ..theme import TOKENS
from .controls import Box, IconButton, StatusPill, label, note


class ArmyCard(Box):
    def __init__(self, lib, a, in_use):
        super().__init__(radius=14, top=TOKENS["accent"] if in_use else None)
        self.lib, self.a = lib, a
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        self.pic = QLabel()
        self.pic.setFixedHeight(130)
        self.pic.setAlignment(Qt.AlignCenter)
        self.pic.setStyleSheet("background: #0B0B10; border-radius: 10px;")
        self.pic.setText("—")
        v.addWidget(self.pic)
        if a.get("picture"):
            lib.api.get(f"/api/armies/picture/{a['name']}", self._got_pic, raw=True)
        h = QHBoxLayout()
        h.addWidget(label(a["name"], "h3"), 1)
        if in_use: h.addWidget(StatusPill("ok", tr("al_in_use")))
        v.addLayout(h)
        words = ", ".join(w for w in a.get("words", []) if w)
        v.addWidget(label(f"{a.get('steps', 0)} {tr('al_steps')}" + (f"  •  {words}" if words else ""), "dim", wrap=True))
        if a.get("uses"): v.addWidget(label(f"{tr('al_used')} {a['uses']}", "dim"))
        b = QHBoxLayout()
        b.setSpacing(6)
        go = IconButton("bolt", "al_prepare", "primary", size=13)
        go.clicked.connect(lambda: lib.prepare(a["name"]))
        b.addWidget(go, 1)
        use = IconButton("check", None, "ghost", tip_key="al_use", size=15)
        use.clicked.connect(lambda: lib.use(a["name"]))
        b.addWidget(use)
        rm = IconButton("trash", None, "ghost", icon_color=TOKENS["bad"], tip_key="al_delete", size=14)
        rm.clicked.connect(lambda: lib.delete(a["name"]))
        b.addWidget(rm)
        v.addLayout(b)

    def _got_pic(self, data):
        if not data: return
        pm = QPixmap()
        if pm.loadFromData(data):
            self.pic.setPixmap(pm.scaled(self.pic.width() or 260, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class ArmyLibrary(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.api, self.store = ctx, ctx.api, ctx.store
        self.items = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.name = QLineEdit()
        self.name.setPlaceholderText(tr("al_name_ph"))
        self.name.setFixedWidth(220)
        row.addWidget(self.name)
        self.learn_btn = IconButton("eye", "al_learn", "go", size=15)
        self.learn_btn.clicked.connect(self.learn)
        row.addWidget(self.learn_btn)
        self.done_btn = IconButton("check", "al_done", "primary", size=15)
        self.done_btn.clicked.connect(self.done)
        self.done_btn.hide()
        row.addWidget(self.done_btn)
        row.addStretch(1)
        v.addLayout(row)
        self.live = label("", "h3", wrap=True)
        self.live.hide()
        v.addWidget(self.live)
        v.addWidget(note("al_how", "lightbulb"))
        self.grid_w = QWidget()
        self.grid = QGridLayout(self.grid_w)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        v.addWidget(self.grid_w)
        self.empty = label(key="al_empty", role="sub", wrap=True)
        v.addWidget(self.empty)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_status)
        self.store.loaded.connect(self.render)
        self.load()

    # ---------------------------------------------------------------- data
    def load(self):
        self.api.get("/api/armies", lambda r: (setattr(self, "items", r.get("items", [])), self.render()) if isinstance(r, dict) else None)

    def active_plan(self):
        S = self.store.S or {}
        return next((p for p in S.get("plans", []) if p.get("name") and p.get("name") == S.get("active_plan")), None)

    def render(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        plan = self.active_plan() or {}
        for i, a in enumerate(self.items):
            self.grid.addWidget(ArmyCard(self, a, plan.get("army_macro") == a["name"]), i // 3, i % 3)
        for c in range(3): self.grid.setColumnStretch(c, 1)
        self.empty.setVisible(not self.items)

    # ---------------------------------------------------------------- actions
    def learn(self):
        name = self.name.text().strip()
        if not name:
            self.ctx.toast(tr("al_need_name"), "bad")
            return

        def done(r):
            if isinstance(r, dict) and r.get("ok"):
                self.ctx.toast(tr("al_started"), "ok")
                self.timer.start(1500)
            else:
                self.ctx.toast(tr("al_failed_start"), "bad")
        self.api.post(f"/api/armies/learn/{self.store.account}", {"name": name}, done)

    def done(self):
        self.api.post(f"/api/armies/done/{self.store.account}", {}, lambda r: None)
        self.done_btn.setEnabled(False)

    def poll_status(self):
        def got(st):
            if not isinstance(st, dict) or not st.get("text"): return
            t = st["text"]
            col = {"failed": TOKENS["bad"], "saved": TOKENS["ok"], "watching": TOKENS["accent_hi"]}.get(t, TOKENS["info"])
            self.live.setText(tr("al_st_" + t).format(taps=st.get("taps", 0), words=st.get("words", 0), name=st.get("name", "")))
            self.live.setStyleSheet(f"color: {col};")
            self.live.show()
            watching = t == "watching"
            self.done_btn.setVisible(watching)
            self.done_btn.setEnabled(True)
            self.learn_btn.setEnabled(t in ("saved", "failed"))
            if t == "watching" and getattr(self, "_shown", "") != "watching":
                self.ctx.banner(tr("al_banner"), "rec", "eye")
            self._shown = t
            if t in ("saved", "failed"):
                self.timer.stop()
                self.learn_btn.setEnabled(True)
                self.load()
        self.api.get(f"/api/armies/status/{self.store.account}", got)

    def prepare(self, name):
        def done(r):
            ok = isinstance(r, dict) and r.get("ok")
            self.ctx.toast(tr("al_prepare_ok" if ok and r.get("running") else ("al_prepare_idle" if ok else "dk_failed")).format(name=name),
                           "ok" if ok else "bad")
        self.api.post(f"/api/village/{self.store.account}/command", {"cmd": "army", "name": name}, done)

    def use(self, name):
        plan = self.active_plan()
        if plan is None:
            self.ctx.toast(tr("al_need_plan"), "warn")
            return
        plan["army_macro"] = "" if plan.get("army_macro") == name else name
        self.store.changed()
        self.store.save(silent=True)
        self.ctx.toast(tr("al_use_ok" if plan["army_macro"] else "al_use_off").format(name=name, plan=plan.get("name", "")), "ok")
        self.render()

    def delete(self, name):
        if QMessageBox.question(self, "Clash Farmer", tr("al_confirm_delete").format(name=name)) != QMessageBox.Yes: return
        for p in (self.store.S or {}).get("plans", []):
            if p.get("army_macro") == name: p["army_macro"] = ""
        self.store.changed()
        self.api.post("/api/armies/delete", {"name": name}, lambda r: self.load())
