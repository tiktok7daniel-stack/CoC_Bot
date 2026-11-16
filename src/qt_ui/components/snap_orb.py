"""
Floating camera button — always on top of every window, drag it next to the game.
 - click (or F8 anywhere in Windows): picture of the emulator screen now + sent to Claude right away
 - a white flash + a ring when it takes the picture, the number of pictures on its badge, a green tick when sent
 - right click: a note for the next picture, open the pictures, hide the button
"""
import math, sys

from PySide6.QtCore import QAbstractNativeEventFilter, QPointF, QRectF, Qt, QTimer, QElapsedTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QWidget

from .. import icons
from ..i18n import tr
from ..theme import ui_font

SIZE = 76
HOTKEY_ID = 0xCF08


class _HotkeyFilter(QAbstractNativeEventFilter):
    """Windows: WM_HOTKEY for F8 (registered for the whole system) -> take a picture."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def nativeEventFilter(self, event_type, message):
        try:
            if event_type == b"windows_generic_MSG" or event_type == "windows_generic_MSG":
                import ctypes.wintypes
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0312 and msg.wParam == HOTKEY_ID:
                    QTimer.singleShot(0, self.fn)
                    return True, 0
        except Exception:
            pass
        return False, 0


class SnapOrb(QWidget):
    def __init__(self, win):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.win = win
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(SIZE + 30, SIZE + 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr("so_tip"))
        self.count = 0
        self.next_note = ""
        self.busy = False
        self.sent_ok = False
        self._drag = None
        self._moved = False
        self.flash = QElapsedTimer()
        self.anim = QTimer(self)
        self.anim.timeout.connect(self.update)
        self.hotkey = False
        self._filter = None

    # ---------------------------------------------------------------- show / hotkey
    def toggle(self):
        if self.isVisible(): self.hide_orb()
        else: self.show_orb()

    def show_orb(self):
        if not self.pos().x() and not self.pos().y():
            geo = self.screen().availableGeometry() if self.screen() else None
            if geo: self.move(geo.right() - self.width() - 40, geo.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.register_hotkey()
        self.win.store.APP["show_snap_orb"] = True

    def hide_orb(self):
        self.hide()
        self.unregister_hotkey()
        self.win.store.APP["show_snap_orb"] = False

    def register_hotkey(self):
        if self.hotkey or sys.platform != "win32": return
        try:
            import ctypes
            if ctypes.windll.user32.RegisterHotKey(None, HOTKEY_ID, 0x4000, 0x77):    # MOD_NOREPEAT, VK_F8
                self._filter = _HotkeyFilter(self.snap)
                QApplication.instance().installNativeEventFilter(self._filter)
                self.hotkey = True
        except Exception:
            pass

    def unregister_hotkey(self):
        if not self.hotkey: return
        try:
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
            QApplication.instance().removeNativeEventFilter(self._filter)
        except Exception:
            pass
        self.hotkey = False

    # ---------------------------------------------------------------- the picture
    def snap(self):
        if self.busy: return
        self.busy = True
        self.sent_ok = False
        self.flash.start()
        self.anim.start(16)
        note, self.next_note = self.next_note, ""
        acc = self.win.store.account

        def done(r):
            self.busy = False
            if isinstance(r, dict) and r.get("ok"):
                self.count = r.get("count", self.count + 1)
                self.sent_ok = bool(r.get("sending"))
                self.setToolTip(tr("so_tip") + "\n" + tr("so_last").format(n=self.count))
                screen = self.win.screens.get("learn")
                if screen is not None and screen.isVisible(): screen.panel.capture.poll()
            else:
                err = (r or {}).get("error", "")
                self.win.desktop_notify("Clash Farmer", tr("cp_snap_fail_emu") if err == "no_emulator" else tr("cp_snap_fail") + " " + str(err), "camera")
            self.update()
        self.win.api.post(f"/api/capture/{acc}/snap", {"note": note, "send": True}, done)

    # ---------------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False
        elif e.button() == Qt.RightButton:
            self.menu(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            pos = e.globalPosition().toPoint() - self._drag
            if (pos - self.pos()).manhattanLength() > 4: self._moved = True
            self.move(pos)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag is not None and not self._moved: self.snap()
        self._drag = None

    def menu(self, at):
        m = QMenu()
        m.addAction(tr("so_note"), self.ask_note)
        m.addAction(tr("so_open"), lambda: (self.win.showNormal(), self.win.raise_(), self.win.show_screen("learn")))
        m.addSeparator()
        m.addAction(tr("so_hide"), self.hide_orb)
        m.exec(at)

    def ask_note(self):
        text, ok = QInputDialog.getText(None, "Clash Farmer", tr("cp_note_ph"), text=self.next_note)
        if ok:
            self.next_note = text.strip()
            self.update()

    # ---------------------------------------------------------------- paint
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = SIZE / 2
        k = self.flash.elapsed() / 500.0 if self.flash.isValid() else 1.0
        if k >= 1.0 and not self.busy: self.anim.stop()
        # halo
        halo = QRadialGradient(c, r + 14)
        halo.setColorAt(0.6, QColor(245, 183, 64, 90))
        halo.setColorAt(1, QColor(245, 183, 64, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, r + 14, r + 14)
        # body
        body = QRadialGradient(QPointF(c.x() - r * 0.3, c.y() - r * 0.4), r * 1.4)
        body.setColorAt(0, QColor("#FFE08A"))
        body.setColorAt(0.5, QColor("#F5B740"))
        body.setColorAt(1, QColor("#B9740F"))
        p.setBrush(body)
        p.setPen(QPen(QColor("#5A3A06"), 2))
        p.drawEllipse(c, r, r)
        p.drawPixmap(int(c.x() - 18), int(c.y() - 18), icons.pixmap("camera", 36, "#1A1206"))
        # flash + ring when a picture is taken
        if k < 1.0:
            p.setBrush(QColor(255, 255, 255, int(200 * (1 - k))))
            p.setPen(Qt.NoPen)
            p.drawEllipse(c, r, r)
            ring = r + 14 * k
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, int(220 * (1 - k))), 3))
            p.drawEllipse(c, ring, ring)
        # counter badge
        if self.count:
            b = QRectF(self.width() - 34, 4, 30, 22)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#E5484D"))
            p.drawRoundedRect(b, 11, 11)
            p.setPen(QColor("white"))
            p.setFont(ui_font(9, 800))
            p.drawText(b, Qt.AlignCenter, str(self.count))
        # sent tick / note marker
        if self.sent_ok and not self.busy:
            p.drawPixmap(4, self.height() - 30, icons.pixmap("verified", 24))
        if self.next_note:
            p.drawPixmap(self.width() - 28, self.height() - 28, icons.pixmap("edit", 20, "#FFE7A8"))
        p.end()
