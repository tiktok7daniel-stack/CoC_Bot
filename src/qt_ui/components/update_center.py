"""
Updates like a normal desktop app:
 - the program checks GitHub quietly (a few seconds after opening, then every 30 minutes)
 - a new version shows a glowing "New update vX" pill in the top bar (+ a banner once)
 - the update window: current -> new version, "Update now" (downloads only the changed files, settings kept),
   then "Restart now": the program closes and opens again by itself, and the bots that were running start again
 - optional: update automatically in the background and only ask to restart
"""
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import icons
from ..i18n import tr
from ..theme import TOKENS
from ..widgets.controls import IconButton, label
from ..widgets.seal import AnimatedSeal

CHECK_EVERY_MS = 30 * 60 * 1000


class UpdatePill(QPushButton):
    """Gold pill in the top bar with a pulsing dot."""

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("kind", "warn")
        self.setMinimumHeight(40)
        self._on = True
        self._t = QTimer(self)
        self._t.timeout.connect(self._blink)
        self._t.start(700)
        self.hide()

    def set_version(self, v, ready=False):
        self.setIcon(icons.icon("verified_gold" if ready else "download", "#FFD36E", 16))
        self.setText("  " + (tr("up_ready_pill") if ready else tr("up_pill")).format(v=v))
        self.show()

    def _blink(self):
        self._on = not self._on
        self.setStyleSheet("" if self._on else "QPushButton { border-color: rgba(255,211,110,0.9); }")


class UpdateDialog(QDialog):
    updated = Signal(str)

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedWidth(460)
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 22)
        v.setSpacing(12)
        top = QHBoxLayout()
        self.ic = QLabel()
        self.ic.setPixmap(icons.pixmap("download", 30, TOKENS["accent"]))
        top.addWidget(self.ic)
        self.seal = AnimatedSeal(34, gold=True)
        self.seal.hide()
        top.addWidget(self.seal)
        self.title = label("", "h2")
        top.addWidget(self.title, 1)
        v.addLayout(top)
        self.vers = QLabel()
        self.vers.setTextFormat(Qt.RichText)
        self.vers.setAlignment(Qt.AlignCenter)
        self.vers.setStyleSheet("font-size: 15pt; padding: 8px;")
        v.addWidget(self.vers)
        self.note = label("", "sub", wrap=True)
        v.addWidget(self.note)
        self.bar = QLabel()
        self.bar.setFixedHeight(6)
        self.bar.hide()
        v.addWidget(self.bar)
        row = QHBoxLayout()
        self.later = IconButton(None, "up_later", "ghost")
        self.later.clicked.connect(self.reject)
        row.addWidget(self.later)
        row.addStretch(1)
        self.go = IconButton("download", "up_now", "primary", size=16)
        self.go.setMinimumHeight(42)
        self.go.clicked.connect(self.do_update)
        row.addWidget(self.go)
        self.restart = IconButton("refresh", "up_restart", "go", size=16)
        self.restart.setMinimumHeight(42)
        self.restart.clicked.connect(self.do_restart)
        self.restart.hide()
        row.addWidget(self.restart)
        v.addLayout(row)
        self.cur = self.new = ""
        self._dots = QTimer(self)
        self._dots.timeout.connect(self._tick)
        self._n = 0

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 24, 24)
        p.fillPath(path, QColor(14, 14, 19, 250))
        p.setPen(QPen(QColor(245, 183, 64, 120), 1.2))
        p.drawPath(path)
        p.end()

    def open_for(self, cur, new, ready=False):
        self.cur, self.new = cur, new
        self.title.setText(tr("up_title_ready") if ready else tr("up_title"))
        self.vers.setText(f'<span style="color:{TOKENS["dim"]}">v{cur}</span>&nbsp;&nbsp;→&nbsp;&nbsp;'
                          f'<b style="color:{TOKENS["accent_hi"]}">v{new}</b>')
        self.note.setText(tr("up_ready_note") if ready else tr("up_note"))
        self.go.setVisible(not ready)
        self.go.setEnabled(True)
        self.restart.setVisible(ready)
        self.ic.setVisible(not ready)
        self.seal.setVisible(ready)
        if ready: self.seal.finish()
        self.adjustSize()
        par = self.win.geometry()
        self.move(par.center().x() - self.width() // 2, par.center().y() - self.height() // 2)
        self.show()
        self.raise_()

    def _tick(self):
        self._n = (self._n + 1) % 4
        self.note.setText(tr("up_working_note") + " " + "•" * (self._n + 1))

    def do_update(self):
        self.go.setEnabled(False)
        self.later.setEnabled(False)
        self._dots.start(400)

        def done(r):
            self._dots.stop()
            self.later.setEnabled(True)
            if isinstance(r, dict) and r.get("ok"):
                self.title.setText(tr("up_title_ready"))
                self.note.setText(tr("up_ready_note"))
                self.ic.hide()
                self.seal.show()
                self.seal.play()
                self.go.hide()
                self.restart.show()
                self.updated.emit(str(r.get("version") or self.new))
            else:
                self.go.setEnabled(True)
                self.note.setText(tr("upd_err") + "  " + str((r or {}).get("error", "")))
        self.win.api.post("/api/update/apply", {}, done, timeout=600)

    def do_restart(self):
        self.restart.setEnabled(False)
        self.note.setText(tr("up_restarting"))
        self.win.restart_app()


class UpdateCenter:
    """Wires the pill, the dialog and the periodic check into the main window."""

    def __init__(self, win, pill):
        self.win, self.pill = win, pill
        self.dialog = UpdateDialog(win)
        self.dialog.updated.connect(self._ready)
        self.info = {}
        self.ready_version = None
        self._announced = None
        pill.clicked.connect(self.open)
        self.timer = QTimer(win)
        self.timer.timeout.connect(self.check)
        self.timer.start(CHECK_EVERY_MS)
        QTimer.singleShot(8000, self.check)

    def check(self):
        if self.ready_version: return
        self.win.api.get("/api/update/check", self._got, timeout=30)

    def _got(self, r):
        if not isinstance(r, dict) or not r.get("ok") or not r.get("available"): return
        self.info = r
        self.pill.set_version(r.get("latest", "?"))
        self.win.top._apply_compact(force=True)
        if self._announced != r.get("latest"):
            self._announced = r.get("latest")
            self.win.banner.show_msg(tr("up_banner").format(v=r.get("latest", "?")), "info", "download")
            if self.win.store.APP.get("auto_update"):
                self.dialog.open_for(r.get("current", "?"), r.get("latest", "?"))
                self.dialog.do_update()

    def _ready(self, v):
        self.ready_version = v
        self.pill.set_version(v, ready=True)
        self.win.top._apply_compact(force=True)

    def open(self):
        r = self.info
        self.dialog.open_for(r.get("current", "?"), self.ready_version or r.get("latest", "?"), ready=bool(self.ready_version))
