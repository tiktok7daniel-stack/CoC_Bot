"""
Top command header: page title, account switcher (avatar + live uptime), Ctrl+K search, the action
bar (start / stop / pause / run now / setup / save with an unsaved-changes dot) and the window
controls of the frameless window. Also the Ctrl+K command palette and the bottom status bar.
"""
from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from .. import icons
from ..api import fmt_dur, status_key
from ..i18n import on_lang, tr
from ..theme import TOKENS
from ..widgets.controls import IconButton, StatusPill, label, retext


class DirtyDot(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(10, 10)
        self.on = False

    def set(self, v):
        self.on = v
        self.setToolTip(tr("unsaved") if v else tr("all_saved"))
        self.update()

    def paintEvent(self, e):
        if not self.on: return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(TOKENS["warn"]))
        p.drawEllipse(QRectF(1, 1, 8, 8))
        p.end()


class TopCommandBar(QFrame):
    action = Signal(str)          # start / stop / pause / wake / setup / save / discard
    account_selected = Signal(str)
    search_requested = Signal()

    def __init__(self, window):
        super().__init__()
        self.window = window
        self._drag = None
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(10)
        # ---- row 1: title | search | account | window buttons
        r1 = QHBoxLayout()
        r1.setSpacing(12)
        self.title = QLabel("")
        self.title.setProperty("role", "h1")
        r1.addWidget(self.title)
        r1.addStretch(1)
        self.search = QPushButton()
        self.search.setCursor(Qt.PointingHandCursor)
        self.search.setIcon(icons.icon("search", TOKENS["muted"], 16))
        self.search.setMinimumWidth(300)
        self.search.setStyleSheet(f"QPushButton {{ text-align: right; color: {TOKENS['muted']}; border-radius: 11px; padding: 8px 14px; }}")
        retext(self.search, "search_ph")
        self.search.clicked.connect(self.search_requested.emit)
        r1.addWidget(self.search)
        acc = QFrame()
        acc.setStyleSheet(f"QFrame#Acc {{ background: {TOKENS['glass2']}; border: 1px solid {TOKENS['border']}; border-radius: 12px; }}")
        acc.setObjectName("Acc")
        ah = QHBoxLayout(acc)
        ah.setContentsMargins(8, 4, 12, 4)
        ah.setSpacing(10)
        self.avatar = QLabel("M")
        self.avatar.setFixedSize(38, 38)
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #C8102E, stop:1 #FF8A00);"
                                  " border-radius: 10px; font-weight: 800; font-size: 13pt; color: white;")
        ah.addWidget(self.avatar)
        box = QVBoxLayout()
        box.setSpacing(0)
        self.accounts = QComboBox()
        self.accounts.setMinimumWidth(110)
        self.accounts.setStyleSheet("QComboBox { background: transparent; border: 0; font-weight: 800; font-size: 11pt; padding: 0; min-height: 18px; }")
        self.accounts.activated.connect(lambda i: self.account_selected.emit(self.accounts.itemText(i)))
        box.addWidget(self.accounts)
        self.uptime = QLabel("--:--:--")
        self.uptime.setStyleSheet(f"color: {TOKENS['muted']}; font-family: 'JetBrains Mono'; font-size: 8.5pt;")
        box.addWidget(self.uptime)
        ah.addLayout(box)
        r1.addWidget(acc)
        self.win_btns = []
        for name, kind, tip, fn in (("win_min", "win", "frameless_min", lambda: window.showMinimized()),
                                    ("win_max", "win", "frameless_max", self._toggle_max),
                                    ("x", "winclose", "frameless_close", lambda: window.close())):
            b = IconButton(name, kind=kind, size=16, tip_key=tip)
            b.setFixedSize(34, 30)
            b.clicked.connect(fn)
            self.win_btns.append(b)
            r1.addWidget(b)
        v.addLayout(r1)
        # ---- row 2: action bar
        r2 = QHBoxLayout()
        r2.setSpacing(10)
        self.btn_start = IconButton("play", "start_bot", kind="go", size=16)
        self.btn_stop = IconButton("stop", "stop", kind="stop", icon_color="#FCA5A5", size=15)
        self.btn_pause = IconButton("pause", "pause_title", icon_color=TOKENS["warn"], size=15)
        self.btn_wake = IconButton("bolt", "run_now", icon_color=TOKENS["gold"], size=16)
        self.btn_setup = IconButton("plug", "su_title", icon_color="#FFC7A8", size=16)
        for b, a in ((self.btn_start, "start"), (self.btn_stop, "stop"), (self.btn_pause, "pause"),
                     (self.btn_wake, "wake"), (self.btn_setup, "setup")):
            b.setMinimumHeight(40)
            b.setMinimumWidth(130)
            b.clicked.connect(lambda _=False, a=a: self.action.emit(a))
            r2.addWidget(b)
        self.btn_start.setMinimumWidth(170)
        r2.addStretch(1)
        self.state = StatusPill("stopped")
        r2.addWidget(self.state)
        self.discard = IconButton("undo", kind="ghost", size=15, tip_key="discard")
        self.discard.clicked.connect(lambda: self.action.emit("discard"))
        r2.addWidget(self.discard)
        save_box = QWidget()
        sh = QHBoxLayout(save_box)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(4)
        self.btn_save = IconButton("save", "save_settings", kind="primary", size=15)
        self.btn_save.setMinimumHeight(40)
        self.btn_save.clicked.connect(lambda: self.action.emit("save"))
        self.dirty = DirtyDot()
        sh.addWidget(self.btn_save)
        sh.addWidget(self.dirty)
        r2.addWidget(save_box)
        v.addLayout(r2)
        self._started_at = None
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)
        self._clock.start(1000)
        QShortcut(QKeySequence("Ctrl+K"), window, activated=self.search_requested.emit)
        QShortcut(QKeySequence("Ctrl+S"), window, activated=lambda: self.action.emit("save"))

    # ---------------------------------------------------------------- window drag on the header
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.window.windowHandle():
            self.window.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        self._toggle_max()

    def _toggle_max(self):
        if self.window.isMaximized(): self.window.showNormal()
        else: self.window.showMaximized()
        self.win_btns[1].set_icon("win_restore" if self.window.isMaximized() else "win_max")

    # ---------------------------------------------------------------- state
    def set_accounts(self, accounts, current):
        self.accounts.blockSignals(True)
        self.accounts.clear()
        self.accounts.addItems(accounts)
        i = self.accounts.findText(current)
        if i >= 0: self.accounts.setCurrentIndex(i)
        self.accounts.blockSignals(False)
        self.avatar.setText((current or "?")[:1].upper())

    def set_state(self, acc_state, now):
        k = status_key(acc_state)
        self.state.set(k)
        running = bool(acc_state.get("running"))
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_wake.setEnabled(running and k != "running")
        paused = bool(acc_state.get("end_time")) and acc_state.get("end_time", 0) > (now or 0)
        self.btn_pause.setText(tr("resume_now") if paused else tr("pause_title"))
        self.btn_pause.setEnabled(running)
        self._started_at = acc_state.get("started_at") if running else None
        self._now_offset = (now or 0)

    def _tick(self):
        import time
        if self._started_at: self.uptime.setText(fmt_dur(time.time() - self._started_at))
        else: self.uptime.setText("--:--:--")


class CommandPalette(QDialog):
    """Ctrl+K: type to find any setting on any screen, Enter jumps there and highlights it."""
    chosen = Signal(object)

    def __init__(self, parent, entries_fn):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.entries_fn = entries_fn
        self.setModal(True)
        self.resize(640, 460)
        box = QFrame(self)
        box.setObjectName("Pal")
        box.setStyleSheet(f"#Pal {{ background: #121016; border: 1px solid {TOKENS['border_hover']}; border-radius: 16px; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 14, 14, 14)
        self.input = QLineEdit()
        self.input.setProperty("role", "search")
        self.input.setPlaceholderText(tr("search_ph"))
        self.input.addAction(icons.icon("search", TOKENS["muted"], 16), QLineEdit.LeadingPosition)
        self.input.setMinimumHeight(40)
        self.input.textChanged.connect(self.refresh)
        self.input.returnPressed.connect(self.accept_current)
        v.addWidget(self.input)
        self.list = QListWidget()
        self.list.itemActivated.connect(lambda _it: self.accept_current())
        v.addWidget(self.list, 1)
        self.empty = label(key="search_none", role="sub")
        v.addWidget(self.empty)

    def open(self):
        self.input.clear()
        self.refresh("")
        par = self.parentWidget()
        self.move(par.mapToGlobal(QPoint((par.width() - self.width()) // 2, 110)))
        self.show()
        self.input.setFocus()

    def refresh(self, text):
        q = (text or "").strip().lower()
        self.list.clear()
        seen = set()
        for e in self.entries_fn():
            hay = (e["text"] + " " + e["where"]).lower()
            if q and q not in hay: continue
            key = (e["text"], e["where"])
            if key in seen: continue
            seen.add(key)
            it = QListWidgetItem(icons.icon(e.get("icon", "sliders"), "#FFC7A8", 16), f"{e['text']}    —    {e['where']}")
            it.setData(Qt.UserRole, e)
            self.list.addItem(it)
            if self.list.count() >= 60: break
        self.empty.setVisible(self.list.count() == 0)
        if self.list.count(): self.list.setCurrentRow(0)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Down, Qt.Key_Up):
            row = self.list.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
        elif e.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    def accept_current(self):
        it = self.list.currentItem()
        if it:
            self.hide()
            self.chosen.emit(it.data(Qt.UserRole))


class StatusBar(QFrame):
    def __init__(self):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 6, 14, 6)
        h.setSpacing(12)
        self.state = StatusPill("stopped")
        self.state.setStyleSheet("QLabel { background: transparent; border: 0; font-weight: 700; }")
        h.addWidget(self.state)
        h.addWidget(self._sep())
        self.emu = QLabel("—")
        self.emu.setStyleSheet(f"color: {TOKENS['muted']}; font-family: 'JetBrains Mono'; font-size: 8.5pt;")
        h.addWidget(self.emu)
        h.addWidget(self._sep())
        self.conn = QLabel("")
        self.conn.setStyleSheet(f"color: {TOKENS['muted']}; font-size: 8.5pt;")
        h.addWidget(self.conn)
        h.addStretch(1)
        self.ver = QLabel("Clash Farmer")
        self.ver.setStyleSheet(f"color: {TOKENS['muted']}; font-family: 'JetBrains Mono'; font-size: 8.5pt;")
        h.addWidget(self.ver)
        self.setStyleSheet(f"StatusBar {{ background: {TOKENS['glass_solid']}; border: 1px solid {TOKENS['border']}; border-radius: 10px; }}")

    def _sep(self):
        s = QLabel("|")
        s.setStyleSheet(f"color: {TOKENS['dim']};")
        return s

    def set(self, key, emu_text, version, online):
        self.state.set(key)
        self.state.setStyleSheet("QLabel { background: transparent; border: 0; font-weight: 700; }")
        self.emu.setText(emu_text)
        self.conn.setText(tr("conn_ok") if online else tr("conn_lost"))
        self.conn.setStyleSheet(f"color: {TOKENS['muted'] if online else TOKENS['bad']}; font-size: 8.5pt;")
        self.ver.setText(f"Clash Farmer  v{version}" if version else "Clash Farmer")
