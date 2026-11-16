"""
Screen 16 - Logs, system diagnostics and error reporter (three sub-tabs):
 log    : live structured log with search, level filter, raw text, copy, clear view
 check  : "check now" runs every system check with an animated step-by-step reveal and fix hints
 errors : error / warning counters, each error with the screenshot of that moment, upload to GitHub,
          save a report zip for the developer, open the screenshots folder, clear the list
"""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from .. import icons
from ..i18n import on_lang, tr, translate_log
from ..theme import TOKENS
from ..widgets.controls import Box, Combo, GlassCard, IconButton, StatusPill, Toggle, label
from ..widgets.log_view import LogView
from .base import Screen


class CheckRow(Box):
    def __init__(self, item):
        super().__init__(radius=12)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(12)
        st = item.get("status")
        name, col = {"ok": ("ok", TOKENS["ok"]), "warn": ("warn", TOKENS["warn"]), "bad": ("bad", TOKENS["bad"])}.get(st, ("info", TOKENS["info"]))
        ic = QLabel()
        ic.setPixmap(icons.pixmap(name, 24, col))
        h.addWidget(ic, 0, Qt.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(2)
        k = item.get("key", "")
        title = tr("sc_" + k)
        info = item.get("info") or ""
        head = QHBoxLayout()
        head.addWidget(label(title if title != "sc_" + k else k, "h3"))
        if info:
            il = label(info, "dim")
            il.setLayoutDirection(Qt.LeftToRight)
            head.addWidget(il)
        head.addStretch(1)
        box.addLayout(head)
        if st != "ok":
            fix = tr("scf_" + k)
            if fix != "scf_" + k:
                fl = QHBoxLayout()
                bulb = QLabel()
                bulb.setPixmap(icons.pixmap("lightbulb", 14, TOKENS["warn"]))
                fl.addWidget(bulb, 0, Qt.AlignTop)
                fl.addWidget(label(fix, "warn", wrap=True), 1)
                box.addLayout(fl)
        h.addLayout(box, 1)
        if st == "bad": self.set_border("rgba(239,68,68,0.5)")
        elif st == "warn": self.set_border("rgba(245,158,11,0.45)")
        else: self.set_border("rgba(16,185,129,0.35)")


class ErrorRow(Box):
    def __init__(self, screen, e):
        super().__init__(radius=12)
        v = QHBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(12)
        err = e.get("type") == "error"
        ic = QLabel()
        ic.setPixmap(icons.pixmap("bad" if err else "warn", 20, TOKENS["bad"] if err else TOKENS["warn"]))
        v.addWidget(ic, 0, Qt.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(2)
        msg = e.get("message", "")
        box.addWidget(label(translate_log(msg), "h3", wrap=True))
        if translate_log(msg) != msg:
            o = label(msg, "dim", wrap=True)
            o.setLayoutDirection(Qt.LeftToRight)
            box.addWidget(o)
        meta = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.get("t", 0)))
        if e.get("phase"): meta += f"  ·  {tr('ph_' + e['phase']) if tr('ph_' + e['phase']) != 'ph_' + e['phase'] else e['phase']}"
        if e.get("where"): meta += f"  ·  {e['where']}"
        box.addWidget(label(meta, "dim"))
        if e.get("detail"):
            d = QLabel(e["detail"][-900:])
            d.setWordWrap(True)
            d.setLayoutDirection(Qt.LeftToRight)
            d.setTextInteractionFlags(Qt.TextSelectableByMouse)
            d.setStyleSheet(f"color: #8F86A8; font-family: 'JetBrains Mono'; font-size: 8pt; background: #07060C; border-radius: 8px; padding: 6px;")
            box.addWidget(d)
        v.addLayout(box, 1)
        if e.get("shot"):
            self.thumb = QLabel()
            self.thumb.setFixedSize(176, 99)
            self.thumb.setStyleSheet("background: #000; border-radius: 8px;")
            self.thumb.setCursor(Qt.PointingHandCursor)
            v.addWidget(self.thumb, 0, Qt.AlignTop)
            self.pm = None
            screen.api.get(f"/api/errors/{screen.store.account}/shot/{e['shot']}", self._shot, raw=True)
            self.thumb.mousePressEvent = lambda ev: screen.show_shot(self.pm)
        self.set_border("rgba(239,68,68,0.45)" if err else "rgba(245,158,11,0.4)")

    def _shot(self, data):
        if not data: return
        pm = QPixmap()
        pm.loadFromData(data)
        if pm.isNull(): return
        self.pm = pm
        self.thumb.setPixmap(pm.scaled(176, 99, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class LogsScreen(Screen):
    key, title_key, icon_name = "log", "sub_log", "scroll"

    def __init__(self, ctx):
        super().__init__(ctx)
        L = self.make_tabs([("log", "bot_log", "terminal"), ("check", "sc_title", "stethoscope"), ("errors", "err_title", "bug")])

        # ---------------- live log
        lc = GlassCard("bot_log", "terminal", "bot_log_sub")
        bar = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setProperty("role", "search")
        self.q.setPlaceholderText(tr("filter_ph"))
        self.q.addAction(icons.icon("search", TOKENS["muted"], 16), QLineEdit.LeadingPosition)
        self.q.textChanged.connect(lambda t: self.view.set_filter(query=t))
        on_lang(lambda: self.q.setPlaceholderText(tr("filter_ph")))
        bar.addWidget(self.q, 1)
        self.level = Combo([("all", "all_levels"), ("info", "lv_info"), ("warn", "lv_warn"), ("err", "lv_err")], 170)
        self.level.currentIndexChanged.connect(lambda _i: self.view.set_filter(level=self.level.value()))
        bar.addWidget(self.level)
        self.raw = Toggle()
        self.raw.toggled.connect(lambda v: self.view.set_filter(raw=v))
        bar.addWidget(label(key="raw", role="sub"))
        bar.addWidget(self.raw)
        cp = IconButton("copy", "copy", size=14)
        cp.clicked.connect(self.copy_log)
        bar.addWidget(cp)
        cl = IconButton("trash", "clear_view", size=14)
        cl.clicked.connect(self.clear_view)
        bar.addWidget(cl)
        lc.add(bar)
        self.view = LogView()
        self.view.setMinimumHeight(520)
        lc.add(self.view, 1)
        L["log"].addWidget(lc, 1)
        self._cut = 0

        # ---------------- system check
        sc = GlassCard("sc_title", "stethoscope", "sc_sub", glow=True)
        self.run_btn = IconButton("play", "check_now", kind="go", size=14)
        self.run_btn.clicked.connect(self.run_check)
        sc.add_tool(self.run_btn)
        self.sc_summary = label("", "h3")
        sc.add(self.sc_summary)
        self.sc_box = QVBoxLayout()
        self.sc_box.setSpacing(8)
        sc.add(self.sc_box)
        L["check"].addWidget(sc)
        L["check"].addStretch(1)

        # ---------------- errors
        ec = GlassCard("err_title", "bug", "err_sub")
        cnt = QHBoxLayout()
        self.n_err = StatusPill("bad", "0")
        self.n_warn = StatusPill("warn", "0")
        cnt.addWidget(self.n_err)
        cnt.addWidget(self.n_warn)
        cnt.addStretch(1)
        for ic, key, fn, kind in (("github", "send_report", self.github, "primary"), ("download", "save_report", self.save_report, None),
                                  ("folder", "open_shots", self.open_folder, None), ("trash", "clear_view", self.clear_errors, None)):
            b = IconButton(ic, key, kind=kind, size=14)
            b.clicked.connect(fn)
            cnt.addWidget(b)
        ec.add(cnt)
        self.err_box = QVBoxLayout()
        self.err_box.setSpacing(8)
        ec.add(self.err_box)
        L["errors"].addWidget(ec)
        L["errors"].addStretch(1)
        self.preview = None

        self.poller.log.connect(self.on_log)
        self.poller.errors.connect(self.render_errors)

    # ---------------------------------------------------------------- log
    def on_show(self):
        self.poller.refresh("log")
        self.poller.refresh("errors")

    def on_log(self, lines):
        if self._cut: lines = lines[self._cut:] if len(lines) > self._cut else []
        self.view.set_lines(lines)

    def clear_view(self):
        last = self.poller.last.get("log", {}).get("lines", [])
        self._cut = len(last)
        self.view.set_lines([])

    def copy_log(self):
        QGuiApplication.clipboard().setText(self.view.plain_text())
        self.ctx.toast(tr("copied"), "ok")

    # ---------------------------------------------------------------- system check
    def run_check(self):
        self.run_btn.setEnabled(False)
        self.run_btn.setText(tr("checking"))
        while self.sc_box.count():
            it = self.sc_box.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        self.sc_summary.setText(tr("checking"))

        def got(r):
            items = (r or {}).get("items", []) if isinstance(r, dict) else []
            self._reveal(items, 0)
        self.api.get(f"/api/syscheck/{self.store.account}", got, timeout=90)

    def _reveal(self, items, i):
        if i < len(items):
            self.sc_box.addWidget(CheckRow(items[i]))
            QTimer.singleShot(110, lambda: self._reveal(items, i + 1))
            return
        bad = sum(1 for x in items if x.get("status") != "ok")
        self.sc_summary.setText(tr("sc_all_ok") if bad == 0 else tr("sc_some").replace("{n}", str(bad)))
        self.run_btn.setEnabled(True)
        self.run_btn.setText(tr("check_now"))

    # ---------------------------------------------------------------- errors
    def render_errors(self, items):
        while self.err_box.count():
            it = self.err_box.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        self.n_err.set("bad", f"{tr('errors_n')}: {sum(1 for e in items if e.get('type') == 'error')}")
        self.n_warn.set("warn", f"{tr('warnings_n')}: {sum(1 for e in items if e.get('type') == 'warning')}")
        if not items:
            self.err_box.addWidget(label(key="no_errors", role="sub"))
            return
        for e in items[:60]: self.err_box.addWidget(ErrorRow(self, e))

    def show_shot(self, pm):
        if pm is None: return
        from PySide6.QtWidgets import QDialog
        d = QDialog(self)
        d.setWindowTitle("CoC Bot")
        v = QVBoxLayout(d)
        lb = QLabel()
        lb.setPixmap(pm.scaled(1280, 720, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        v.addWidget(lb)
        d.exec()

    def github(self):
        def done(r):
            if isinstance(r, dict) and r.get("ok"):
                if r.get("skipped"): self.ctx.toast(tr("no_errors"), "info")
                else: self.ctx.banner(f'{tr("gh_done")}  {r.get("url", "")}', "ok", "github")
            else:
                err = (r or {}).get("error", "") if isinstance(r, dict) else ""
                key = {"no_token": "gh_need_token", "bad_token": "gh_bad_token", "no_permission": "gh_no_perm",
                       "issues_disabled": "gh_issues_off"}.get(err)
                self.ctx.toast(tr(key) if key else (err or tr("save_err")), "bad")
        self.api.post(f"/api/github/report/{self.store.account}", {}, done, timeout=120)

    def save_report(self):
        def done(r):
            if isinstance(r, dict) and r.get("ok"): self.ctx.banner(r.get("path", ""), "ok", "download")
            else: self.ctx.toast((r or {}).get("error", tr("save_err")), "bad")
        self.api.post(f"/api/report/{self.store.account}", {}, done, timeout=60)

    def open_folder(self):
        def done(r):
            if isinstance(r, dict) and not r.get("ok") and r.get("path"):
                QGuiApplication.clipboard().setText(r["path"])
                self.ctx.toast(r["path"], "info")
        self.api.post(f"/api/errors/{self.store.account}/open", {}, done)

    def clear_errors(self):
        self.api.post(f"/api/errors/{self.store.account}/clear", {}, lambda r: self.poller.refresh("errors"))
