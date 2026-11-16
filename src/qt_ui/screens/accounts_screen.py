"""
Screen 3 - Multi-account manager: start all / stop all, one card per account (status, running time,
start/stop, open its settings, delete), and add an account (instance name instructions).
"""
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from .. import icons
from ..api import fmt_dur, status_key
from ..i18n import on_lang, tr
from ..theme import TOKENS
from ..widgets.controls import Box, GlassCard, IconButton, StatusPill, label, note
from .base import Screen, page


class AccountsScreen(Screen):
    key, title_key, icon_name = "acc", "sub_acc", "id"

    def __init__(self, ctx):
        super().__init__(ctx)
        sa, v = page()
        self.root.addWidget(sa)
        card = GlassCard("acc_title", "users", "acc_sub")
        b_all = IconButton("play", "start_all", kind="go", size=14)
        b_all.clicked.connect(lambda: self.all_action("start"))
        card.add_tool(b_all)
        b_none = IconButton("stop", "stop_all", kind="stop", icon_color="#FCA5A5", size=14)
        b_none.clicked.connect(lambda: self.all_action("stop"))
        card.add_tool(b_none)
        self.list_host = QWidget()
        self.list = QVBoxLayout(self.list_host)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(10)
        card.add(self.list_host)
        v.addWidget(card)

        add = GlassCard("add_acc", "plus", "add_acc_sub")
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("alt1")
        self.name.setFixedWidth(240)
        self.name.returnPressed.connect(self.add_account)
        row.addWidget(self.name)
        b = IconButton("plus", "add", kind="primary", size=14)
        b.clicked.connect(self.add_account)
        row.addWidget(b)
        row.addStretch(1)
        add.add(row)
        for k in ("acc_h1", "acc_h2", "acc_h3"):
            add.add(note(k, "info"))
        v.addWidget(add)
        v.addStretch(1)
        self.poller.state.connect(lambda _s: self.render())
        self.store.accounts_changed.connect(lambda _a: self.render())
        on_lang(self.render)

    def on_show(self):
        self.poller.refresh("state")
        self.render()

    def render(self):
        while self.list.count():
            it = self.list.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        st = self.poller.last.get("state") or {}
        now = st.get("current_time") or time.time()
        for acc in self.store.APP.get("accounts", []):
            a = next((x for x in st.get("accounts", []) if x.get("id") == acc), {})
            k = status_key(a)
            row = Box(border=TOKENS["purple"] if acc == self.store.account else TOKENS["border"], radius=14)
            h = QHBoxLayout(row)
            h.setContentsMargins(14, 10, 14, 10)
            h.setSpacing(12)
            av = QLabel(acc[:1].upper())
            av.setFixedSize(44, 44)
            av.setAlignment(Qt.AlignCenter)
            av.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #7C3AED, stop:1 #C026D3); border-radius: 11px;"
                             " font-weight: 800; font-size: 14pt; color: white;")
            h.addWidget(av)
            box = QVBoxLayout()
            box.setSpacing(1)
            box.addWidget(label(acc, "h2"))
            run = f"{tr('acc_runtime')} {fmt_dur(now - a['started_at'])}" if a.get("running") and a.get("started_at") else tr("not_running")
            box.addWidget(label(run, "dim"))
            h.addLayout(box, 1)
            h.addWidget(StatusPill(k))
            if a.get("running"):
                b = IconButton("stop", "stop", kind="stop", icon_color="#FCA5A5", size=14)
                b.clicked.connect(lambda _=False, x=acc: self.ctx.window.account_action(x, "stop"))
            else:
                b = IconButton("play", "start", kind="go", size=14)
                b.clicked.connect(lambda _=False, x=acc: self.ctx.window.account_action(x, "start"))
            h.addWidget(b)
            o = IconButton("sliders", "acc_settings", size=14)
            o.clicked.connect(lambda _=False, x=acc: (self.store.switch_account(x), self.ctx.window.show_screen("dash")))
            h.addWidget(o)
            d = IconButton("trash", kind="ghost", icon_color=TOKENS["bad"], size=15, tip_key="acc_delete")
            d.clicked.connect(lambda _=False, x=acc: self.remove(x))
            h.addWidget(d)
            self.list.addWidget(row)

    def all_action(self, action):
        st = self.poller.last.get("state") or {}
        for acc in self.store.APP.get("accounts", []):
            a = next((x for x in st.get("accounts", []) if x.get("id") == acc), {})
            if (action == "start") != bool(a.get("running")): self.ctx.window.account_action(acc, action)

    def add_account(self):
        name = "".join(c for c in self.name.text().strip() if c.isalnum() or c in "-_")
        if not name:
            self.ctx.toast(tr("su_need_name"), "bad")
            return
        accs = self.store.APP.setdefault("accounts", [])
        if name not in accs: accs.append(name)
        self.name.clear()
        self.store.changed()
        self.store.save(done=lambda ok: (self.ctx.toast(tr("added"), "ok"), self.render()))

    def remove(self, acc):
        if QMessageBox.question(self, "CoC Bot", tr("confirm_remove")) != QMessageBox.Yes: return
        st = self.poller.account_state(acc)
        if st.get("running"): self.ctx.window.account_action(acc, "stop")
        accs = [a for a in self.store.APP.get("accounts", []) if a != acc]
        self.store.APP["accounts"] = accs or ["main"]
        if self.store.account == acc: self.store.account = self.store.APP["accounts"][0]
        self.store.changed()
        self.store.save(done=lambda ok: self.store.load_all())
