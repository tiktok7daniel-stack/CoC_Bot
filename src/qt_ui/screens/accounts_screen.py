"""
Screen 3 - Multi-account manager: start all / stop all, one card per account (status, running time,
start/stop, open its settings, delete), and add an account (instance name instructions).
"""
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from .. import icons
from ..api import fmt_dur, status_key
from ..i18n import on_lang, tr
from ..theme import TOKENS
from ..widgets.controls import Box, GlassCard, IconButton, StatusPill, label, note, toggle_row
from .base import Screen, page


class AccountsScreen(Screen):
    key, title_key, icon_name = "acc", "sub_acc", "id"

    def __init__(self, ctx):
        super().__init__(ctx)
        from PySide6.QtCore import QTimer
        from ..widgets.avatar import profiles
        profiles.changed.connect(lambda _a: QTimer.singleShot(0, self.render))
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

        # ---------------- same play on every account
        sync = GlassCard("sync_title", "layers", "sync_sub", glow=True)
        sync.add(toggle_row(self.store, "sync_on", "sync_settings", "sync_on_sub", "app"))
        crow = QHBoxLayout()
        crow.addWidget(label(key="copy_to_all_lbl"), 1)
        cp = IconButton("copy", "copy_to_all", kind="primary", size=14)
        cp.clicked.connect(self.copy_to_all)
        crow.addWidget(cp)
        sync.add(crow)
        sync.add(note("sync_note", "info"))
        v.addWidget(sync)

        add = GlassCard("add_acc", "plus", "add_acc_sub")
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("alt1")
        self.name.setFixedWidth(240)
        self.name.returnPressed.connect(self.add_account)
        row.addWidget(self.name)
        row.addWidget(label(key="copy_from"))
        self.copy_from = QComboBox()
        self.copy_from.setMinimumWidth(160)
        row.addWidget(self.copy_from)
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
        self.load_follow()

    def render(self):
        cur = self.copy_from.currentData()
        self.copy_from.clear()
        self.copy_from.addItem(tr("copy_none"), "")
        for a in self.store.APP.get("accounts", []): self.copy_from.addItem(a, a)
        i = self.copy_from.findData(cur if cur is not None else self.store.account)
        self.copy_from.setCurrentIndex(i if i >= 0 else min(1, self.copy_from.count() - 1))
        while self.list.count():
            it = self.list.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        st = self.poller.last.get("state") or {}
        now = st.get("current_time") or time.time()
        for acc in self.store.APP.get("accounts", []):
            a = next((x for x in st.get("accounts", []) if x.get("id") == acc), {})
            k = status_key(a)
            row = Box(border=TOKENS["purple"] if acc == self.store.account else TOKENS["border"], radius=18)
            h = QHBoxLayout(row)
            h.setContentsMargins(14, 10, 14, 10)
            h.setSpacing(12)
            from ..widgets.avatar import Avatar, choose_picture, display_name, remove_picture, set_display_name, picture
            av = Avatar(acc, 58)
            av.setCursor(Qt.PointingHandCursor)
            av.setToolTip(tr("pf_change_tip"))
            av.mousePressEvent = lambda e, x=acc: choose_picture(self, x)
            h.addWidget(av)
            box = QVBoxLayout()
            box.setSpacing(3)
            nm = QLineEdit(display_name(self.store, acc))
            nm.setPlaceholderText(tr("pf_name_ph"))
            nm.setMaximumWidth(240)
            nm.setMinimumWidth(160)
            nm.setAlignment(Qt.AlignLeading | Qt.AlignVCenter)
            nm.setStyleSheet("QLineEdit { font-size: 12.5pt; font-weight: 800; background: transparent; border: 1px solid transparent; padding: 2px 6px; }"
                             " QLineEdit:hover { border-color: rgba(255,255,255,0.12); } QLineEdit:focus { border-color: #F5B740; background: #15151C; }")
            nm.editingFinished.connect(lambda x=acc, w=nm: set_display_name(self.store, x, w.text() or x))
            box.addWidget(nm)
            ids = label(f"ID: {acc}", "dim")
            box.addWidget(ids)
            pics = QHBoxLayout()
            pics.setSpacing(4)
            cp = IconButton("image", "pf_change", "ghost", size=13)
            cp.clicked.connect(lambda _=False, x=acc: choose_picture(self, x))
            pics.addWidget(cp)
            if picture(acc) is not None:
                rp = IconButton("x", None, "ghost", icon_color=TOKENS["dim"], tip_key="pf_remove", size=12)
                rp.clicked.connect(lambda _=False, x=acc: remove_picture(x))
                pics.addWidget(rp)
            pics.addStretch(1)
            box.addLayout(pics)
            run = f"{tr('acc_runtime')} {fmt_dur(now - a['started_at'])}" if a.get("running") and a.get("started_at") else tr("not_running")
            box.addWidget(label(run, "dim"))
            # plays like another account (same loadout / recording / army / farm, any change there applies here)
            others = [x for x in self.store.APP.get("accounts", []) if x != acc]
            if others:
                fr = QHBoxLayout()
                fr.setSpacing(6)
                fr.addWidget(label(key="acc_follow", role="dim"))
                fc = QComboBox()
                fc.addItem(tr("acc_follow_own"), "")
                for o in others: fc.addItem(tr("acc_follow_like").replace("{a}", display_name(self.store, o)), o)
                fc.setMinimumWidth(200)
                cur_lead = (self._follow.get(acc) if hasattr(self, "_follow") else None) or ""
                fc.setCurrentIndex(max(0, fc.findData(cur_lead)))
                fc.activated.connect(lambda _i, x=acc, w=fc: self.set_follow(x, w.currentData()))
                fr.addWidget(fc)
                fr.addStretch(1)
                box.addLayout(fr)
            h.addLayout(box, 1)
            h.addWidget(StatusPill(k), 0, Qt.AlignVCenter)
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

    def load_follow(self):
        """Who follows whom (from each account's settings) -> self._follow, then the rows again."""
        self._follow = getattr(self, "_follow", {})
        for acc in self.store.APP.get("accounts", []):
            self.api.get(f"/api/settings/{acc}", lambda r, x=acc: self._got_follow(x, r))

    def _got_follow(self, acc, r):
        lead = (r or {}).get("follow", "") or ""
        if self._follow.get(acc) != lead:
            self._follow[acc] = lead
            self.render()

    def set_follow(self, acc, lead):
        def done(r):
            ok = isinstance(r, dict) and r.get("ok")
            if ok:
                self._follow[acc] = lead or ""
                self.ctx.toast(tr("acc_follow_on").replace("{a}", acc).replace("{b}", lead) if lead else
                               tr("acc_follow_off").replace("{a}", acc), "ok")
                if acc == self.store.account: self.store._load_settings()         # show what it plays now
            else:
                self.ctx.toast(tr("dk_failed"), "bad")
        self.api.post(f"/api/account/{acc}/follow", {"follow": lead or ""}, done)

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
        src = self.copy_from.currentData()
        self.store.changed()

        def saved(ok):
            if src and src != name:   # the new account plays exactly like the chosen one, and keeps following it
                self.api.post("/api/settings_copy", {"from": src, "to": [name]},
                              lambda r: self.set_follow(name, src))
            else:
                self.ctx.toast(tr("added"), "ok")
            self.render()
        self.store.save(done=saved)

    def copy_to_all(self):
        src = self.store.account
        others = [a for a in self.store.APP.get("accounts", []) if a != src]
        if not others:
            self.ctx.toast(tr("copy_no_other"), "bad")
            return
        if QMessageBox.question(self, "Clash Farmer", tr("copy_confirm").replace("{a}", src).replace("{n}", str(len(others)))) != QMessageBox.Yes: return

        def go(_ok=True):
            self.api.post("/api/settings_copy", {"from": src, "to": "all"},
                          lambda r: self.ctx.toast(tr("copy_done").replace("{n}", str(len((r or {}).get("copied", [])))), "ok"))
        if self.store.dirty: self.store.save(silent=True, done=go)
        else: go()

    def remove(self, acc):
        if QMessageBox.question(self, "Clash Farmer", tr("confirm_remove")) != QMessageBox.Yes: return
        st = self.poller.account_state(acc)
        if st.get("running"): self.ctx.window.account_action(acc, "stop")
        accs = [a for a in self.store.APP.get("accounts", []) if a != acc]
        self.store.APP["accounts"] = accs or ["main"]
        if self.store.account == acc: self.store.account = self.store.APP["accounts"][0]
        self.store.changed()
        self.store.save(done=lambda ok: self.store.load_all())
