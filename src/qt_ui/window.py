"""
Main window: frameless rounded canvas with ambient violet glows, the sidebar, the command header,
the framed content stack (all screens) and the status bar. Wires live data from the Poller into the
header / sidebar / status bar and runs the header actions.
"""
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QHBoxLayout, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

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
from .screens.royale_screen import RoyaleScreen
from .screens.royale_home_screen import RoyaleHomeScreen
from .screens.royale_ai_screen import RoyaleAiScreen
from .screens.royale_training_screen import RoyaleTrainingScreen
from .screens.royale_live_screen import RoyaleLiveScreen
from .screens.logs_diagnostics_screen import LogsScreen
from .screens.setup_wizard_dialog import SetupWizard
from .screens.statistics_screen import StatisticsScreen
from .screens.village_manager_screen import VillageManagerScreen
from .screens.village_screen import VillageScreen
from .screens.upgrade_deck_screen import UpgradeDeckScreen
from .screens.learn_screen import LearnScreen
from .components.mini_hud import MiniHud
from .store import Store
from .theme import TOKENS
from .widgets.controls import Banner, Toast

EDGE = 7


def round_corners_windows(win):
    """Windows 11: ask the desktop compositor for real rounded corners (smooth edges, soft shadow)."""
    import sys
    if sys.platform != "win32": return
    try:
        import ctypes
        pref = ctypes.c_int(2)                         # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(win.winId()), 33, ctypes.byref(pref), ctypes.sizeof(pref))
    except Exception:
        pass


class Canvas(QWidget):
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        radius = 0 if self.window().isMaximized() else 26
        path.addRoundedRect(r, radius, radius)
        p.fillPath(path, QColor(TOKENS["void"]))
        rtl = self.layoutDirection() == Qt.RightToLeft
        # one warm light from the top corner of the sidebar, very soft
        g = QRadialGradient(r.right() - 120 if rtl else r.left() + 120, r.top(), 620)
        g.setColorAt(0, QColor(245, 183, 64, 20))
        g.setColorAt(1, QColor(245, 183, 64, 0))
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
        path.addRoundedRect(r, 22, 22)
        p.fillPath(path, QColor(10, 10, 14, 230))
        p.setPen(QPen(QColor(255, 255, 255, 14), 1))
        p.drawPath(path)
        p.end()


class MainWindow(QMainWindow):
    def __init__(self, api, pipe=None):
        super().__init__()
        self.api, self.pipe = api, pipe
        self.setWindowTitle("Clash Farmer")
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
        for cls in (DashboardScreen, UpgradeDeckScreen, AccountsScreen, AttackScreen, BuilderBaseScreen, StatisticsScreen, VillageScreen,
                    VillageManagerScreen, LearnScreen, LogsScreen, BotSettingsScreen, RoyaleScreen, RoyaleLiveScreen,
                    RoyaleHomeScreen, RoyaleAiScreen, RoyaleTrainingScreen):
            s = cls(self.ctx)
            self.screens[s.key] = s
            self.stack.addWidget(s)
        self.setup = SetupWizard(self.ctx, self)
        self._royale = None
        self.store.loaded.connect(self.apply_game_mode)
        self.store.on_change(self.apply_game_mode)
        self.apply_game_mode()
        self.palette = CommandPalette(self, self.search_entries)
        self.palette.chosen.connect(self.jump_to)

        self.poller.state.connect(self.on_state)
        self.poller.system.connect(self.on_system)
        self.poller.log.connect(self.notify_from_log)
        self._notified = None
        self._seen_lines = None
        self.setup_tray()
        self.hud = MiniHud(self)
        from .components.snap_orb import SnapOrb
        self.snap_orb = SnapOrb(self)
        from .components.today_dialog import TodayPlanner
        self.today = TodayPlanner(self)
        from .components.update_center import UpdateCenter
        self.update_center = UpdateCenter(self, self.top.update_pill)
        self.poller.errors.connect(lambda items: self.sidebar.set_badge("log", sum(1 for e in items if e.get("type") == "error")))
        self.store.accounts_changed.connect(lambda accs: self.sync_accounts())
        self.store.account_changed.connect(lambda a: (self.top.set_accounts(self.accounts_for_ui(), a), self.poller.refresh_all()))
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
            self.api.get("/api/app/resume", self._resume)
            if self.store.APP.get("show_snap_orb", False): self.snap_orb.show_orb()
            if self.store.APP.get("show_hud", False):
                self.hud.place()
                self.hud.show()
            def after_choice():
                self.choose_game(force=False)              # which game? (unless it was remembered)
                if self.store.APP.get("show_setup", True) is not False:
                    QTimer.singleShot(300, self.setup.open_wizard)
            QTimer.singleShot(200, after_choice)
        self.store.load_all(loaded)

    def _resume(self, r):
        """After a restart: start again the bots that were running before it."""
        for acc in (r or {}).get("accounts", []) if isinstance(r, dict) else []:
            self.account_action(acc, "start")
        if isinstance(r, dict) and r.get("accounts"):
            self.banner.show_msg(tr("up_resumed").format(n=len(r["accounts"])), "ok", "refresh")

    def restart_app(self):
        """Close and reopen the whole program (used after an update)."""
        if self.store.dirty: self.store.save_blocking()

        def done(r):
            if isinstance(r, dict) and r.get("ok"):
                QTimer.singleShot(300, self.close)
            else:
                self.toast.show_msg(tr("up_restart_fail"), "bad")
        self.api.post("/api/app/restart", {}, done)

    def on_loaded(self):
        lang = self.store.APP.get("language", "ar")
        if lang != i18n.LANG: self.apply_language(lang)
        QTimer.singleShot(8000, self._offer_gpu)

    def _offer_gpu(self):
        """An NVIDIA card that isn't used yet: say it once (Settings -> Speed & power has the button)."""
        if self.store.APP.get("gpu_offered"): return
        def got(r):
            if isinstance(r, dict) and r.get("card") and not r.get("cuda") and not r.get("pending"):
                self.store.APP["gpu_offered"] = True
                self.banner.show_msg(tr("pw_offer").format(name=r["card"].get("name", "NVIDIA")), "ok", "bolt")
        self.api.get("/api/gpu", got, timeout=150)

    def apply_language(self, lang):
        i18n.set_lang(lang)
        QApplication.instance().setLayoutDirection(Qt.RightToLeft if i18n.is_rtl() else Qt.LeftToRight)
        self.retitle()

    def ui_game(self):
        """The program's face: the game chosen when it opened (else the selected account's game)."""
        g = self.store.APP.get("ui_game") or ""
        return g if g in ("coc", "royale") else (self.store.get("game_mode", "coc") or "coc")

    def accounts_for_ui(self):
        """Only the accounts of the game on screen (all of them when none plays it yet)."""
        accs = list(self.store.APP.get("accounts", []) or [])
        games = self.store.APP.get("account_games") or {}
        g = self.ui_game()
        mine = [a for a in accs if (games.get(a, "coc") or "coc") == g]
        return mine or accs

    def sync_accounts(self):
        """The top bar lists this face's accounts, and the selected account is one of them (never a hidden one:
        the screens, the log and Start would be about another account than the one shown)."""
        accs = self.accounts_for_ui()
        if accs and self.store.account not in accs:
            self.store.switch_account(accs[0])
        self.top.set_accounts(accs, self.store.account)

    def apply_game_mode(self, force=False):
        """Clash Royale face: its own screens only; Clash of Clans face: the usual screens. Accounts follow."""
        royale = self.ui_game() == "royale"
        if royale != self._royale or force:
            self._royale = royale
            self.sidebar.set_mode(royale)
            for b in (self.top.btn_pause, self.top.btn_wake, self.top.btn_setup):
                b.setVisible(not royale)                  # Clash Royale: Start / Stop are enough
            self.sync_accounts()
        cur = getattr(self, "current", None)
        if cur is None: return
        if royale and cur not in ("royale_home", "royale_ai", "royale_training", "royale", "royale_live", "acc", "set"): self.show_screen("royale_home")
        elif not royale and cur in ("royale_home", "royale_ai", "royale_training", "royale", "royale_live"): self.show_screen("dash")

    def choose_game(self, force=True):
        """The game chooser (when the program opens, and from the sidebar's 'change game')."""
        if not force and self.store.APP.get("ui_game") in ("coc", "royale") and self.store.APP.get("ui_game_remember"):
            return False
        from .components.game_chooser import GameChooser
        dlg = GameChooser(self, self.store.APP.get("ui_game_remember", False))

        def picked(k):
            self.store.set("ui_game", k, "app")
            self.store.set("ui_game_remember", bool(dlg.remember.isChecked()), "app")
            self._royale = None
            self.apply_game_mode()
            self.show_screen("royale_home" if k == "royale" else "dash")
            try: self.store.save(silent=True)
            except Exception: pass
        dlg.chosen.connect(picked)
        dlg.adjustSize()
        g = self.geometry()
        dlg.move(g.center().x() - dlg.width() // 2, g.center().y() - dlg.height() // 2)
        dlg.exec()
        return True

    def retitle(self):
        s = self.screens.get(self.current)
        if s: self.top.title.setText(tr(s.title_key))

    # ---------------------------------------------------------------- navigation
    def show_screen(self, key, sub=None):
        if key == "royale_live": key = "royale_ai"           # the old map view: replaced by the live game screen
        if key == "switch_game":
            self.choose_game(force=True)
            return
        if key == "setup":
            self.setup.open_wizard()
            return
        if getattr(self, "_royale", None) and key not in ("royale_home", "royale_ai", "royale_training", "royale", "royale_live", "acc", "set"):
            key = "royale_home"
        elif getattr(self, "_royale", None) is False and key in ("royale_home", "royale_ai", "royale_training", "royale", "royale_live"): key = "dash"
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
        elif a == "wake":
            if self.store.get("game_mode") == "royale":         # Clash Royale: "run now" = start one battle
                self.store.set("royale.go_request", time.time())
                self.store.save(silent=True)
                self.toast.show_msg(tr("royale_go_started"), "ok")
            else:
                self.account_action(acc, "wake")
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
        elif msg: self.toast.show_msg(tr(msg) if msg in ("saved", "follow_note") else msg, "ok" if msg == "saved" else "warn")

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

    # ---------------------------------------------------------------- tray + desktop notifications
    def setup_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable(): return
        self.tray = QSystemTrayIcon(QIcon(icons.pixmap("crest", 64)), self)
        self.tray.setToolTip("Clash Farmer")
        m = QMenu()
        m.addAction(tr("hud_open_main"), lambda: (self.showNormal(), self.raise_(), self.activateWindow()))
        m.addAction(tr("hud_toggle"), self.toggle_hud)
        m.addAction(tr("so_toggle"), lambda: self.snap_orb.toggle())
        m.addSeparator()
        m.addAction(tr("start"), lambda: self.run_action("start"))
        m.addAction(tr("stop"), lambda: self.run_action("stop"))
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.toggle_hud() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self._tray_menu = m

    def toggle_hud(self):
        if self.hud.isVisible(): self.hud.hide()
        else:
            self.hud.place()
            self.hud.show()
        self.store.set("show_hud", self.hud.isVisible(), "app")

    def desktop_notify(self, title, text, icon_name="bell"):
        """Windows toast (tray balloon) + an in-app banner."""
        if self.store.APP.get("desktop_notify", True) and self.tray is not None:
            self.tray.showMessage(title, text, QIcon(icons.pixmap(icon_name, 64, "#F5B740")), 8000)
        self.banner.show_msg(f"{title} — {text}", "ok", icon_name)

    NOTIFY_KEYS = (("Upgrade finished:", "nt_upgrade_done", "builder_hammer"), ("Lab research finished:", "nt_lab_done", "flask"),
                   ("1-tap upgrade done:", "nt_tap_done", "bolt"), ("Auto upgrade started:", "nt_auto_up", "hammer"),
                   ("Batch wall upgrade", "nt_walls", "brick"), ("Stuck on a screen the bot doesn't know", "nt_stuck", "camera"),
                   ("Picture sent to Claude:", "nt_unknown", "camera"))

    def notify_events(self, lines):
        """New log lines -> desktop notifications (first poll only remembers what is already there)."""
        if self._seen_lines is None:
            self._seen_lines = set(lines)
            return
        new = [l for l in lines if l not in self._seen_lines]
        self._seen_lines.update(new)
        if len(self._seen_lines) > 5000: self._seen_lines = set(lines)
        for l in new[-6:]:
            for needle, key, ic in self.NOTIFY_KEYS:
                if needle in l:
                    self.desktop_notify(tr(key), i18n.translate_log(l.split("|")[-1].strip()), ic)
                    break

    def notify_from_log(self, lines):
        self.notify_events(lines)
        """Big notice for the moments the user waits for (walls done, every wall maxed); new lines only."""
        import re
        hits = [l for l in lines if "Walls finished:" in l or "All walls are maxed" in l]
        last = hits[-1] if hits else ""
        if self._notified is None:
            self._notified = last
            return
        if last and last != self._notified:
            self._notified = last
            if "All walls are maxed" in last:
                self.banner.show_msg(tr("walls_maxed_banner"), "ok", "trophy")
            else:
                m = re.search(r"Walls finished: (\d+)", last)
                self.banner.show_msg(i18n.translate_log(f"Walls finished: {m.group(1) if m else '?'} upgraded"), "ok", "brick")
            QApplication.beep()

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

    def showEvent(self, e):
        super().showEvent(e)
        round_corners_windows(self)

    def closeEvent(self, e):
        if self.store.dirty: self.store.save_blocking()
        try:
            self.snap_orb.unregister_hotkey()
            self.snap_orb.close()
            self.hud.close()
            if self.tray is not None: self.tray.hide()
        except RuntimeError: pass
        if self.pipe is not None:
            try: self.pipe.send(-1)
            except (OSError, EOFError): pass
        super().closeEvent(e)
