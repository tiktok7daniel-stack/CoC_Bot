"""
Main window: frameless rounded canvas with ambient violet glows, the sidebar, the command header,
the framed content stack (all screens) and the status bar. Wires live data from the Poller into the
header / sidebar / status bar and runs the header actions.
"""
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from . import i18n, icons
from .api import Poller, status_key
from .components.sidebar import Sidebar
from .components.top_command_bar import CommandPalette, StatusBar, TopCommandBar
from .i18n import tr
from .screens.accounts_screen import AccountsScreen
from .screens.attack_screen import AttackScreen
from .screens.base import Ctx
from .screens.bot_settings_screen import BotSettingsScreen
from .screens.builder_base_screen import BuilderBaseScreen
from .screens.dashboard_screen import DashboardScreen
from .screens.logs_diagnostics_screen import LogsScreen
from .screens.setup_wizard_dialog import SetupWizard
from .screens.statistics_screen import StatisticsScreen
from .screens.village_manager_screen import VillageManagerScreen
from .screens.village_screen import VillageScreen
from .store import Store
from .theme import TOKENS
from .widgets.controls import Banner, Toast

EDGE = 7


class Canvas(QWidget):
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        radius = 0 if self.window().isMaximized() else 16
        path.addRoundedRect(r, radius, radius)
        p.fillPath(path, QColor(TOKENS["void"]))
        rtl = self.layoutDirection() == Qt.RightToLeft
        for cx, cy, rad, a in ((r.right() - 140 if rtl else r.left() + 140, r.top() + 40, 420, 56),
                               (r.center().x(), r.top() + 160, 520, 26)):
            g = QRadialGradient(cx, cy, rad)
            g.setColorAt(0, QColor(139, 92, 246, a))
            g.setColorAt(1, QColor(139, 92, 246, 0))
            p.fillPath(path, QBrush(g))
        p.setPen(QPen(QColor(TOKENS["border_solid"]), 1))
        p.drawPath(path)
        p.end()


class ContentFrame(QWidget):
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 16, 16)
        p.fillPath(path, QColor(13, 11, 21, 235))
        p.setPen(QPen(QColor(168, 85, 247, 46), 1))
        p.drawPath(path)
        p.end()


class MainWindow(QMainWindow):
    def __init__(self, api, pipe=None):
        super().__init__()
        self.api, self.pipe = api, pipe
        self.setWindowTitle("CoC Bot")
        self.setWindowIcon(QIcon(icons.pixmap("crest", 64)))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(1200, 760)
        self.resize(1440, 900)
        self.setMouseTracking(True)
        self.store = Store(api)
        self.poller = Poller(api, self.store)
        self.ctx = Ctx(api, self.store, self.poller, self)
        self.version = ""

        canvas = Canvas()
        canvas.setMouseTracking(True)
        self.setCentralWidget(canvas)
        outer = QHBoxLayout(canvas)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)
        self.sidebar = Sidebar()
        self.sidebar.navigate.connect(self.show_screen)
        outer.addWidget(self.sidebar)
        main = QVBoxLayout()
        main.setSpacing(10)
        self.top = TopCommandBar(self)
        self.top.action.connect(self.run_action)
        self.top.account_selected.connect(self.store.switch_account)
        self.top.search_requested.connect(self.open_palette)
        main.addWidget(self.top)
        self.frame = ContentFrame()
        fv = QVBoxLayout(self.frame)
        fv.setContentsMargins(16, 14, 10, 12)
        self.stack = QStackedWidget()
        fv.addWidget(self.stack)
        main.addWidget(self.frame, 1)
        self.status = StatusBar()
        main.addWidget(self.status)
        outer.addLayout(main, 1)

        self.toast = Toast(canvas)
        self.banner = Banner(canvas)
        self.screens = {}
        for cls in (DashboardScreen, AccountsScreen, AttackScreen, BuilderBaseScreen, StatisticsScreen, VillageScreen,
                    VillageManagerScreen, LogsScreen, BotSettingsScreen):
            s = cls(self.ctx)
            self.screens[s.key] = s
            self.stack.addWidget(s)
        self.setup = SetupWizard(self.ctx, self)
        self.palette = CommandPalette(self, self.search_entries)
        self.palette.chosen.connect(self.jump_to)

        self.poller.state.connect(self.on_state)
        self.poller.system.connect(self.on_system)
        self.poller.errors.connect(lambda items: self.sidebar.set_badge("log", sum(1 for e in items if e.get("type") == "error")))
        self.store.accounts_changed.connect(lambda accs: self.top.set_accounts(accs, self.store.account))
        self.store.account_changed.connect(lambda a: (self.top.set_accounts(self.store.APP.get("accounts", []), a), self.poller.refresh_all()))
        self.store.dirty_changed.connect(self.top.dirty.set)
        self.store.saved.connect(self.on_saved)
        self.store.loaded.connect(self.on_loaded)
        api.connect_online(self.on_online)
        i18n.on_lang(self.retitle)
        self.current = "dash"
        self.show_screen("dash")

    # ---------------------------------------------------------------- startup
    def start(self):
        def loaded(ok):
            if not ok:
                QTimer.singleShot(1500, self.start)
                return
            self.apply_language(self.store.APP.get("language", "ar"))
            self.poller.refresh_all()
            if self.store.APP.get("show_setup", True) is not False:
                QTimer.singleShot(400, self.setup.open_wizard)
        self.store.load_all(loaded)

    def on_loaded(self):
        lang = self.store.APP.get("language", "ar")
        if lang != i18n.LANG: self.apply_language(lang)

    def apply_language(self, lang):
        i18n.set_lang(lang)
        QApplication.instance().setLayoutDirection(Qt.RightToLeft if i18n.is_rtl() else Qt.LeftToRight)
        self.retitle()

    def retitle(self):
        s = self.screens.get(self.current)
        if s: self.top.title.setText(tr(s.title_key))

    # ---------------------------------------------------------------- navigation
    def show_screen(self, key, sub=None):
        if key == "setup":
            self.setup.open_wizard()
            return
        s = self.screens.get(key)
        if not s: return
        self.current = key
        self.stack.setCurrentWidget(s)
        self.sidebar.set_active(key)
        self.top.title.setText(tr(s.title_key))
        if sub: s.select_sub(sub)
        s.on_show()

    def search_entries(self):
        out = []
        for s in self.screens.values(): out.extend(s.search_entries())
        return out

    def open_palette(self):
        self.palette.open()

    def jump_to(self, entry):
        self.show_screen(entry["screen"], entry.get("sub"))
        QTimer.singleShot(120, lambda: self.screens[entry["screen"]].flash(entry.get("widget")))

    # ---------------------------------------------------------------- actions
    def run_action(self, a):
        acc = self.store.account
        if a == "save": self.store.save()
        elif a == "discard": self.store.discard()
        elif a == "setup": self.setup.open_wizard()
        elif a == "start": self.account_action(acc, "start")
        elif a == "stop": self.account_action(acc, "stop")
        elif a == "wake": self.account_action(acc, "wake")
        elif a == "pause":
            st = self.poller.account_state()
            paused = bool(st.get("end_time")) and st.get("end_time", 0) > time.time()
            self.account_action(acc, "pause", {"minutes": 0 if paused else 30})

    def account_action(self, acc, action, body=None, after=None):
        def go():
            def done(r):
                if not isinstance(r, dict) or not r.get("ok"):
                    self.toast.show_msg(tr("need_running" if (r or {}).get("error") == "not_running" else "save_err"), "bad")
                else:
                    msg = {"start": "started", "stop": "stopped_t", "wake": "run_now_t", "pause": "paused_t"}.get(action)
                    if action == "pause" and (body or {}).get("minutes") == 0: msg = "resumed"
                    if msg: self.toast.show_msg(tr(msg), "ok")
                self.poller.refresh("state")
                if after: after(r)
            self.api.post(f"/api/account/{acc}/{action}", body or {}, done)
        if action == "start" and self.store.dirty: self.store.save(silent=True, done=lambda ok: go())
        else: go()

    def on_saved(self, ok, msg):
        if not ok: self.toast.show_msg(tr("save_err"), "bad")
        elif msg: self.toast.show_msg(tr(msg) if msg in ("saved",) else msg, "ok" if msg == "saved" else "warn")

    # ---------------------------------------------------------------- live data
    def on_state(self, st):
        self.version = st.get("version", "")
        acc = self.poller.account_state()
        k = status_key(acc)
        self.top.set_state(acc, st.get("current_time"))
        sysd = self.poller.last.get("system") or {}
        emu = {"bluestacks": "BlueStacks", "ldplayer": "LDPlayer", "mumu": "MuMu"}.get(sysd.get("emulator") or self.store.APP.get("emulator"), "—")
        self.sidebar.capsule.set_state(k, tr("st_" + k), emu, self.version)
        self.status.set(k, f"{emu}  •  {sysd.get('adb') or '—'}", self.version, self.api.online)

    def on_system(self, sysd):
        self.on_state(self.poller.last.get("state") or {})

    def on_online(self, online):
        if not online: self.toast.show_msg(tr("conn_lost"), "bad")
        self.on_state(self.poller.last.get("state") or {})

    # ---------------------------------------------------------------- frameless resize
    def _edges(self, pos):
        r = self.rect()
        e = Qt.Edges()
        if pos.x() <= EDGE: e |= Qt.LeftEdge
        if pos.x() >= r.width() - EDGE: e |= Qt.RightEdge
        if pos.y() <= EDGE: e |= Qt.TopEdge
        if pos.y() >= r.height() - EDGE: e |= Qt.BottomEdge
        return e

    def mousePressEvent(self, e):
        edges = self._edges(e.position().toPoint())
        if edges and e.button() == Qt.LeftButton and self.windowHandle() and not self.isMaximized():
            self.windowHandle().startSystemResize(edges)
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        edges = self._edges(e.position().toPoint())
        cursors = {Qt.LeftEdge: Qt.SizeHorCursor, Qt.RightEdge: Qt.SizeHorCursor, Qt.TopEdge: Qt.SizeVerCursor,
                   Qt.BottomEdge: Qt.SizeVerCursor}
        if edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge): self.setCursor(Qt.SizeFDiagCursor)
        elif edges in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge): self.setCursor(Qt.SizeBDiagCursor)
        elif edges in cursors: self.setCursor(cursors[edges])
        else: self.unsetCursor()
        super().mouseMoveEvent(e)

    def closeEvent(self, e):
        if self.store.dirty: self.store.save(silent=True)
        if self.pipe is not None:
            try: self.pipe.send(-1)
            except (OSError, EOFError): pass
        super().closeEvent(e)
